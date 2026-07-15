/*
 *    Copyright 2023 The ChampSim Contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include "cache.h"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <iomanip>
#include <limits>
#include <numeric>
#include <fmt/core.h>

#include "bandwidth.h"
#include "champsim.h"
#include "chrono.h"
#include "deadlock.h"
#include "instruction.h"
#include "tlb_prefetch_metadata.h"
#include "tlb_ptw_system_stats.h"
#include "util/algorithm.h"
#include "util/bits.h"
#include "util/span.h"
#include "vberti_end_to_end.h"
#include "vpn_pattern_tracker.h"

namespace champsim
{
bool enable_stlb_cp_pb = false;
bool ordered_pqfull_tlb_rescue = false;
bool l1d_cross_page_pf_translation_only = false;
}

namespace
{
constexpr std::size_t PQFULL_TLB_RESCUE_QUEUE_SIZE = 16;

void append_ptw_dram_touched_flags(std::vector<std::shared_ptr<bool>>& destination, const std::vector<std::shared_ptr<bool>>& source)
{
  for (const auto& flag : source) {
    const auto found = std::find_if(std::begin(destination), std::end(destination), [&flag](const auto& existing) { return existing.get() == flag.get(); });
    if (found == std::end(destination))
      destination.push_back(flag);
  }
}

bool is_demand_origin(translation_origin origin)
{
  return origin == translation_origin::DEMAND_DATA || origin == translation_origin::DEMAND_INSTRUCTION;
}

bool is_data_demand_origin(translation_origin origin) { return origin == translation_origin::DEMAND_DATA; }

bool is_l1d_cross_page_prefetch_origin(translation_origin origin) { return origin == translation_origin::L1D_PREFETCH_CROSS_PAGE; }

champsim::dtlb_merge_detail classify_tlb_mshr_merge_target(translation_origin origin)
{
  switch (origin) {
  case translation_origin::DEMAND_DATA:
    return champsim::dtlb_merge_detail::MSHR_TO_DATA_DEMAND;
  case translation_origin::DEMAND_INSTRUCTION:
    return champsim::dtlb_merge_detail::MSHR_TO_INST_DEMAND;
  case translation_origin::L1D_PREFETCH:
    return champsim::dtlb_merge_detail::MSHR_TO_L1D_PREFETCH;
  case translation_origin::L1D_PREFETCH_CROSS_PAGE:
    return champsim::dtlb_merge_detail::MSHR_TO_CP_PREFETCH;
  case translation_origin::L1D_PREFETCH_SAME_PAGE:
    return champsim::dtlb_merge_detail::MSHR_TO_SP_PREFETCH;
  case translation_origin::L1I_PREFETCH:
    return champsim::dtlb_merge_detail::MSHR_TO_L1I_PREFETCH;
  case translation_origin::OTHER:
  case translation_origin::NUM_TYPES:
  default:
    return champsim::dtlb_merge_detail::MSHR_TO_OTHER;
  }
}

bool is_cache_demand_type(access_type type) { return type == access_type::LOAD || type == access_type::RFO; }

bool is_l1d_name(std::string_view name) { return name.size() >= 4 && name.compare(name.size() - 4, 4, "_L1D") == 0; }

template <typename Key>
void remember_shadow_candidate(std::deque<Key>& fifo, std::map<Key, uint64_t>& shadow, const Key& key, std::size_t limit)
{
  fifo.push_back(key);
  ++shadow[key];

  while (std::size(fifo) > limit) {
    const auto old = fifo.front();
    fifo.pop_front();
    auto found = shadow.find(old);
    if (found == std::end(shadow))
      continue;
    if (found->second <= 1) {
      shadow.erase(found);
    } else {
      --found->second;
    }
  }
}

template <typename Key>
bool erase_shadow_candidate(std::map<Key, uint64_t>& shadow, const Key& key)
{
  const auto found = shadow.find(key);
  if (found == std::end(shadow))
    return false;

  shadow.erase(found);
  return true;
}

template <typename Key>
void remember_pollution_candidate(std::deque<std::tuple<Key, bool, uint64_t>>& fifo, std::map<Key, std::pair<uint64_t, bool>>& shadow, uint64_t& next_id,
                                  const Key& key, bool demand_victim, std::size_t limit)
{
  const auto id = next_id++;
  fifo.emplace_back(key, demand_victim, id);
  shadow[key] = {id, demand_victim};

  while (std::size(fifo) > limit) {
    const auto [old_key, old_demand_victim, old_id] = fifo.front();
    (void)old_demand_victim;
    fifo.pop_front();

    auto found = shadow.find(old_key);
    if (found == std::end(shadow))
      continue;

    if (found->second.first == old_id)
      shadow.erase(found);
  }
}

template <typename Key>
std::pair<bool, bool> consume_pollution_candidate(std::map<Key, std::pair<uint64_t, bool>>& shadow, const Key& key)
{
  auto found = shadow.find(key);
  if (found == std::end(shadow))
    return {false, false};

  const auto demand_victim = found->second.second;
  shadow.erase(found);

  return {true, demand_victim};
}

template <typename Key>
void discard_pollution_candidate(std::map<Key, std::pair<uint64_t, bool>>& shadow, const Key& key)
{
  shadow.erase(key);
}

struct tlb_system_key {
  uint32_t cpu = 0;
  uint64_t vpn = 0;
  uint8_t asid0 = std::numeric_limits<uint8_t>::max();
  uint8_t asid1 = std::numeric_limits<uint8_t>::max();

  bool operator<(const tlb_system_key& other) const
  {
    return std::tie(cpu, vpn, asid0, asid1) < std::tie(other.cpu, other.vpn, other.asid0, other.asid1);
  }
};

struct tlb_system_entry {
  uint64_t pending = 0;
  uint64_t active = 0;
  bool used = false;
};

std::map<tlb_system_key, tlb_system_entry> tlb_system_cross_prefetch_state;
std::deque<tlb_system_key> tlb_system_cross_prefetch_too_early_fifo;
std::map<tlb_system_key, uint64_t> tlb_system_cross_prefetch_too_early_shadow;
bool tlb_system_cross_prefetch_finalized = false;

tlb_system_key make_tlb_system_key(uint32_t cpu, champsim::address vaddr, const uint8_t asid[2])
{
  return {cpu, champsim::page_number{vaddr}.to<uint64_t>(), asid[0], asid[1]};
}

void reset_tlb_system_cross_prefetch_state()
{
  tlb_system_cross_prefetch_state.clear();
  tlb_system_cross_prefetch_too_early_fifo.clear();
  tlb_system_cross_prefetch_too_early_shadow.clear();
  tlb_system_cross_prefetch_finalized = false;
}

void mark_tlb_system_pending(const tlb_system_key& key) { ++tlb_system_cross_prefetch_state[key].pending; }

void mark_tlb_system_active(const tlb_system_key& key)
{
  auto& entry = tlb_system_cross_prefetch_state[key];
  if (entry.pending > 0)
    --entry.pending;
  ++entry.active;
}

bool mark_tlb_system_useful(const tlb_system_key& key)
{
  auto found = tlb_system_cross_prefetch_state.find(key);
  if (found == std::end(tlb_system_cross_prefetch_state) || found->second.used)
    return false;

  found->second.used = true;
  found->second.pending = 0;
  return true;
}

bool mark_tlb_system_late(const tlb_system_key& key)
{
  auto found = tlb_system_cross_prefetch_state.find(key);
  if (found == std::end(tlb_system_cross_prefetch_state) || found->second.pending == 0 || found->second.used)
    return false;

  found->second.used = true;
  found->second.pending = 0;
  return true;
}

bool mark_tlb_system_eviction(const tlb_system_key& key, std::size_t shadow_limit)
{
  auto found = tlb_system_cross_prefetch_state.find(key);
  if (found == std::end(tlb_system_cross_prefetch_state))
    return false;

  if (found->second.active > 0)
    --found->second.active;

  const bool useless = found->second.active == 0 && found->second.pending == 0 && !found->second.used;
  if (useless)
    remember_shadow_candidate(tlb_system_cross_prefetch_too_early_fifo, tlb_system_cross_prefetch_too_early_shadow, key, shadow_limit);
  if (found->second.active == 0 && found->second.pending == 0)
    tlb_system_cross_prefetch_state.erase(found);

  return useless;
}

bool consume_tlb_system_too_early(const tlb_system_key& key) { return erase_shadow_candidate(tlb_system_cross_prefetch_too_early_shadow, key); }

void discard_tlb_system_too_early(const tlb_system_key& key)
{
  erase_shadow_candidate(tlb_system_cross_prefetch_too_early_shadow, key);
}

uint64_t finalize_tlb_system_cross_prefetch_state()
{
  if (tlb_system_cross_prefetch_finalized)
    return 0;

  uint64_t useless = 0;
  for (const auto& [key, entry] : tlb_system_cross_prefetch_state) {
    (void)key;
    if (!entry.used && (entry.pending > 0 || entry.active > 0))
      ++useless;
  }
  tlb_system_cross_prefetch_state.clear();
  tlb_system_cross_prefetch_finalized = true;
  return useless;
}
} // namespace

CACHE::CACHE(CACHE&& other)
    : operable(other),

      pqfull_tlb_rescue_queue(std::move(other.pqfull_tlb_rescue_queue)), pqfull_tlb_rescue_inflight(std::move(other.pqfull_tlb_rescue_inflight)),
      vberti_prefetch_seq_counter(other.vberti_prefetch_seq_counter), vberti_end_to_end_id_counter(other.vberti_end_to_end_id_counter),
      vberti_end_to_end_roi_started(other.vberti_end_to_end_roi_started),
      stlb_cp_pb(std::move(other.stlb_cp_pb)),

      upper_levels(std::move(other.upper_levels)), lower_level(std::move(other.lower_level)), lower_translate(std::move(other.lower_translate)),

      cpu(other.cpu), NAME(std::move(other.NAME)), NUM_SET(other.NUM_SET), NUM_WAY(other.NUM_WAY), MSHR_SIZE(other.MSHR_SIZE), PQ_SIZE(other.PQ_SIZE),
      HIT_LATENCY(other.HIT_LATENCY), FILL_LATENCY(other.FILL_LATENCY), OFFSET_BITS(other.OFFSET_BITS), block(std::move(other.block)), MAX_TAG(other.MAX_TAG),
      MAX_FILL(other.MAX_FILL), prefetch_as_load(other.prefetch_as_load), match_offset_bits(other.match_offset_bits), virtual_prefetch(other.virtual_prefetch),
      pref_activate_mask(std::move(other.pref_activate_mask)),

      sim_stats(std::move(other.sim_stats)), roi_stats(std::move(other.roi_stats)),

      pref_module_pimpl(std::move(other.pref_module_pimpl)), repl_module_pimpl(std::move(other.repl_module_pimpl))
{
  pref_module_pimpl->bind(this);
  repl_module_pimpl->bind(this);
}

auto CACHE::operator=(CACHE&& other) -> CACHE&
{
  this->clock_period = other.clock_period;
  this->current_time = other.current_time;
  this->warmup = other.warmup;

  this->upper_levels = std::move(other.upper_levels);
  this->lower_level = std::move(other.lower_level);
  this->lower_translate = std::move(other.lower_translate);

  this->cpu = other.cpu;
  this->NAME = std::move(other.NAME);
  this->NUM_SET = other.NUM_SET;
  this->NUM_WAY = other.NUM_WAY;
  ;
  this->MSHR_SIZE = other.MSHR_SIZE;
  ;
  this->PQ_SIZE = other.PQ_SIZE;
  this->HIT_LATENCY = other.HIT_LATENCY;
  this->FILL_LATENCY = other.FILL_LATENCY;
  this->OFFSET_BITS = other.OFFSET_BITS;
  ;
  this->block = std::move(other.block);
  this->MAX_TAG = other.MAX_TAG;
  this->MAX_FILL = other.MAX_FILL;
  this->prefetch_as_load = other.prefetch_as_load;
  this->match_offset_bits = other.match_offset_bits;
  this->virtual_prefetch = other.virtual_prefetch;
  this->pref_activate_mask = std::move(other.pref_activate_mask);
  this->pqfull_tlb_rescue_queue = std::move(other.pqfull_tlb_rescue_queue);
  this->pqfull_tlb_rescue_inflight = std::move(other.pqfull_tlb_rescue_inflight);
  this->vberti_prefetch_seq_counter = other.vberti_prefetch_seq_counter;
  this->vberti_end_to_end_id_counter = other.vberti_end_to_end_id_counter;
  this->vberti_end_to_end_roi_started = other.vberti_end_to_end_roi_started;
  this->stlb_cp_pb = std::move(other.stlb_cp_pb);

  this->sim_stats = std::move(other.sim_stats);
  this->roi_stats = std::move(other.roi_stats);

  this->pref_module_pimpl = std::move(other.pref_module_pimpl);
  this->repl_module_pimpl = std::move(other.repl_module_pimpl);

  pref_module_pimpl->bind(this);
  repl_module_pimpl->bind(this);

  return *this;
}

CACHE::tag_lookup_type::tag_lookup_type(const request_type& req, bool local_pref, bool skip)
    : address(req.address), v_address(req.v_address), data(req.data), ip(req.ip), instr_id(req.instr_id), pf_metadata(req.pf_metadata), cpu(req.cpu),
      demand_tlb_operand_index(req.demand_tlb_operand_index), demand_tlb_stage(req.demand_tlb_stage), demand_tlb_events(req.demand_tlb_events),
      demand_tlb_coalesced_events(req.demand_tlb_coalesced_events),
      vberti_tlb_stage(req.vberti_tlb_stage), vberti_tlb_events(req.vberti_tlb_events),
      vberti_tlb_coalesced_events(req.vberti_tlb_coalesced_events),
      type(req.type), translation_source(req.translation_source), prefetch_from_this(local_pref), skip_fill(skip), is_translated(req.is_translated), is_instr(req.is_instr),
      vberti_end_to_end_tracked(req.vberti_end_to_end_tracked), vberti_end_to_end_cpu(req.vberti_end_to_end_cpu),
      vberti_end_to_end_id(req.vberti_end_to_end_id),
      tlb_ptw_prefetch_tracked(req.tlb_ptw_prefetch_tracked), tlb_ptw_real_demand_waiting(req.tlb_ptw_real_demand_waiting),
      tlb_ptw_prefetch_cpu(req.tlb_ptw_prefetch_cpu), tlb_ptw_prefetch_id(req.tlb_ptw_prefetch_id),
      instr_depend_on_me(req.instr_depend_on_me), ptw_dram_touched_flags(req.ptw_dram_touched_flags)
{
}

CACHE::mshr_type::mshr_type(const tag_lookup_type& req, champsim::chrono::clock::time_point _time_enqueued)
    : address(req.address), v_address(req.v_address), ip(req.ip), instr_id(req.instr_id), cpu(req.cpu), type(req.type),
      translation_source(req.translation_source), prefetch_from_this(req.prefetch_from_this), is_instr(req.is_instr),
      vberti_end_to_end_tracked(req.vberti_end_to_end_tracked), vberti_end_to_end_cpu(req.vberti_end_to_end_cpu),
      vberti_end_to_end_id(req.vberti_end_to_end_id), tlb_ptw_prefetch_tracked(req.tlb_ptw_prefetch_tracked),
      tlb_ptw_real_demand_waiting(req.tlb_ptw_real_demand_waiting), tlb_ptw_prefetch_cpu(req.tlb_ptw_prefetch_cpu),
      tlb_ptw_prefetch_id(req.tlb_ptw_prefetch_id), time_enqueued(_time_enqueued),
      instr_depend_on_me(req.instr_depend_on_me), ptw_dram_touched_flags(req.ptw_dram_touched_flags), to_return(req.to_return)
{
}

CACHE::mshr_type CACHE::mshr_type::merge(mshr_type predecessor, mshr_type successor)
{
  std::vector<uint64_t> merged_instr{};
  std::vector<std::deque<response_type>*> merged_return{};

  std::set_union(std::begin(predecessor.instr_depend_on_me), std::end(predecessor.instr_depend_on_me), std::begin(successor.instr_depend_on_me),
                 std::end(successor.instr_depend_on_me), std::back_inserter(merged_instr));
  std::set_union(std::begin(predecessor.to_return), std::end(predecessor.to_return), std::begin(successor.to_return), std::end(successor.to_return),
                 std::back_inserter(merged_return));

  mshr_type retval{(successor.type == access_type::PREFETCH) ? predecessor : successor};

  // set the time enqueued to the predecessor unless its a demand into prefetch, in which case we use the successor
  retval.time_enqueued =
      ((successor.type != access_type::PREFETCH && predecessor.type == access_type::PREFETCH)) ? successor.time_enqueued : predecessor.time_enqueued;
  retval.instr_depend_on_me = merged_instr;
  retval.to_return = merged_return;
  retval.data_promise = predecessor.data_promise;
  retval.vberti_end_to_end_tracked = predecessor.vberti_end_to_end_tracked;
  retval.vberti_end_to_end_cpu = predecessor.vberti_end_to_end_cpu;
  retval.vberti_end_to_end_id = predecessor.vberti_end_to_end_id;
  const auto& ptw_provenance = predecessor.tlb_ptw_prefetch_tracked ? predecessor : successor;
  retval.tlb_ptw_prefetch_tracked = ptw_provenance.tlb_ptw_prefetch_tracked;
  retval.tlb_ptw_prefetch_cpu = ptw_provenance.tlb_ptw_prefetch_cpu;
  retval.tlb_ptw_prefetch_id = ptw_provenance.tlb_ptw_prefetch_id;
  retval.tlb_ptw_real_demand_waiting = predecessor.tlb_ptw_real_demand_waiting || successor.tlb_ptw_real_demand_waiting;
  retval.ptw_dram_touched_flags = predecessor.ptw_dram_touched_flags;
  append_ptw_dram_touched_flags(retval.ptw_dram_touched_flags, successor.ptw_dram_touched_flags);

  if (is_demand_origin(predecessor.translation_source) || is_demand_origin(successor.translation_source))
    retval.translation_source = is_demand_origin(successor.translation_source) ? successor.translation_source : predecessor.translation_source;

  if constexpr (champsim::debug_print) {
    if (successor.type == access_type::PREFETCH) {
      fmt::print("[MSHR] {} address {} type: {} into address {} type: {}\n", __func__, successor.address,
                 access_type_names.at(champsim::to_underlying(successor.type)), predecessor.address,
                 access_type_names.at(champsim::to_underlying(successor.type)));
    } else {
      fmt::print("[MSHR] {} address {} type: {} into address {} type: {}\n", __func__, predecessor.address,
                 access_type_names.at(champsim::to_underlying(predecessor.type)), successor.address,
                 access_type_names.at(champsim::to_underlying(successor.type)));
    }
  }

  return retval;
}

auto CACHE::fill_block(mshr_type mshr, uint32_t metadata) -> BLOCK
{
  CACHE::BLOCK to_fill;
  to_fill.valid = true;
  to_fill.prefetch = mshr.prefetch_from_this;
  to_fill.dirty = (mshr.type == access_type::WRITE);
  to_fill.address = mshr.address;
  to_fill.v_address = mshr.v_address;
  to_fill.data = mshr.data_promise->data;
  to_fill.pf_metadata = metadata;
  to_fill.cpu = mshr.cpu;
  to_fill.asid[0] = mshr.asid[0];
  to_fill.asid[1] = mshr.asid[1];
  to_fill.vberti_end_to_end_tracked = mshr.vberti_end_to_end_tracked;
  to_fill.vberti_end_to_end_cpu = mshr.vberti_end_to_end_cpu;
  to_fill.vberti_end_to_end_id = mshr.vberti_end_to_end_id;
  to_fill.tlb_ptw_prefetch_tracked = mshr.tlb_ptw_prefetch_tracked;
  to_fill.tlb_ptw_prefetch_cpu = mshr.tlb_ptw_prefetch_cpu;
  to_fill.tlb_ptw_prefetch_id = mshr.tlb_ptw_prefetch_id;
  to_fill.translation_source = mshr.translation_source;
  to_fill.tlb_cross_prefetch = false;
  to_fill.tlb_cross_prefetch_used = false;

  return to_fill;
}

auto CACHE::matches_address(champsim::address addr) const
{
  return [match = addr.slice_upper(OFFSET_BITS), shamt = OFFSET_BITS](const auto& entry) {
    return entry.address.slice_upper(shamt) == match;
  };
}

template <typename T>
champsim::address CACHE::module_address(const T& element) const
{
  auto address = virtual_prefetch ? element.v_address : element.address;
  return champsim::address{address.slice_upper(match_offset_bits ? champsim::data::bits{} : OFFSET_BITS)};
}

template <typename T>
bool CACHE::module_is_instr(const T& element) const
{
  return element.is_instr;
}

bool CACHE::handle_fill(const mshr_type& fill_mshr)
{
  cpu = fill_mshr.cpu;

  if (should_redirect_stlb_cp_pb_fill(fill_mshr)) {
    insert_stlb_cp_pb(fill_mshr);

    if (fill_mshr.type != access_type::PREFETCH)
      sim_stats.total_miss_latency_cycles += (current_time - (fill_mshr.time_enqueued + clock_period)) / clock_period;
    sim_stats.mshr_return.increment(std::pair{fill_mshr.type, fill_mshr.cpu});

    response_type response{fill_mshr.address, fill_mshr.v_address, fill_mshr.data_promise->data, fill_mshr.data_promise->pf_metadata,
                           fill_mshr.instr_depend_on_me};
    response.tlb_ptw_prefetch_tracked = fill_mshr.tlb_ptw_prefetch_tracked;
    response.tlb_ptw_prefetch_cpu = fill_mshr.tlb_ptw_prefetch_cpu;
    response.tlb_ptw_prefetch_id = fill_mshr.tlb_ptw_prefetch_id;
    for (auto* ret : fill_mshr.to_return) {
      ret->push_back(response);
    }

    return true;
  }

  // find victim
  auto [set_begin, set_end] = get_set_span(fill_mshr.address);
  auto way = std::find_if_not(set_begin, set_end, [](auto x) { return x.valid; });
  if (way == set_end) {
    way = std::next(set_begin, impl_find_victim(fill_mshr.cpu, fill_mshr.instr_id, get_set_index(fill_mshr.address), &*set_begin, fill_mshr.ip,
                                                fill_mshr.address, fill_mshr.type));
  }
  assert(set_begin <= way);
  assert(way <= set_end);
  assert(way != set_end || fill_mshr.type != access_type::WRITE); // Writes may not bypass
  const auto way_idx = std::distance(set_begin, way);             // cast protected by earlier assertion

  if constexpr (champsim::debug_print) {
    fmt::print("[{}] {} instr_id: {} address: {} v_address: {} set: {} way: {} type: {} prefetch_metadata: {} cycle_enqueued: {} cycle: {}\n", NAME, __func__,
               fill_mshr.instr_id, fill_mshr.address, fill_mshr.v_address, get_set_index(fill_mshr.address), way_idx,
               access_type_names.at(champsim::to_underlying(fill_mshr.type)), fill_mshr.data_promise->pf_metadata,
               (fill_mshr.time_enqueued.time_since_epoch()) / clock_period, (current_time.time_since_epoch()) / clock_period);
  }

  if (way != set_end && way->valid && way->dirty) {
    request_type writeback_packet;

    writeback_packet.cpu = fill_mshr.cpu;
    writeback_packet.address = way->address;
    writeback_packet.data = way->data;
    writeback_packet.instr_id = fill_mshr.instr_id;
    writeback_packet.ip = champsim::address{};
    writeback_packet.type = access_type::WRITE;
    writeback_packet.pf_metadata = way->pf_metadata;
    writeback_packet.response_requested = false;

    if constexpr (champsim::debug_print) {
      fmt::print("[{}] {} evict address: {} v_address: {} prefetch_metadata: {}\n", NAME, __func__, writeback_packet.address, writeback_packet.v_address,
                 fill_mshr.data_promise->pf_metadata);
    }

    auto success = lower_level->add_wq(writeback_packet);
    if (!success) {
      return false;
    }
  }

  champsim::address evicting_address{};
  if (way != set_end && way->valid) {
    evicting_address = module_address(*way);
  }

  if (way != set_end) {
    discard_pollution_candidate(prefetch_pollution_shadow, make_prefetch_pollution_key(fill_mshr.cpu, fill_mshr.address));
    if (is_tlb()) {
      discard_pollution_candidate(tlb_cross_prefetch_pollution_shadow, make_tlb_prefetch_key(fill_mshr.cpu, fill_mshr.v_address, fill_mshr.asid));
    }

    if (way->valid && fill_mshr.type == access_type::PREFETCH) {
      remember_prefetch_pollution_candidate(*way, way->cpu);
    }
    if (way->valid && is_tlb() && is_l1d_cross_page_prefetch_origin(fill_mshr.translation_source)) {
      remember_tlb_cross_prefetch_pollution_candidate(*way, way->cpu);
    }
    if (way->valid && way->prefetch) {
      remember_prefetch_too_early_candidate(*way, way->cpu);
      ++sim_stats.pf_useless;
    }
    if (way->valid) {
      record_tlb_ptw_system_eviction(*way);
      record_tlb_cross_prefetch_eviction(*way, way->cpu);
    }

    if (fill_mshr.type == access_type::PREFETCH) {
      ++sim_stats.pf_fill;
    }
  }

  uint32_t metadata_thru = fill_mshr.data_promise->pf_metadata;
  if (!module_is_instr(fill_mshr)) { // limiting only for data line fills
    metadata_thru = impl_prefetcher_cache_fill(module_address(fill_mshr), get_set_index(fill_mshr.address), way_idx, (fill_mshr.type == access_type::PREFETCH),
                                               evicting_address, fill_mshr.data_promise->pf_metadata);
  }
  impl_replacement_cache_fill(fill_mshr.cpu, get_set_index(fill_mshr.address), way_idx, module_address(fill_mshr), fill_mshr.ip, evicting_address,
                              fill_mshr.type);

  if (way != set_end) {
    *way = fill_block(fill_mshr, metadata_thru);
    if (is_tlb())
      sim_stats.tlb_origin_fills.increment(std::pair{fill_mshr.translation_source, fill_mshr.cpu});
    way->tlb_cross_prefetch = record_tlb_cross_prefetch_fill(fill_mshr);
    record_tlb_ptw_system_fill(fill_mshr, *way);
  }

  // COLLECT STATS
  if (fill_mshr.type != access_type::PREFETCH)
    sim_stats.total_miss_latency_cycles += (current_time - (fill_mshr.time_enqueued + clock_period)) / clock_period;
  sim_stats.mshr_return.increment(std::pair{fill_mshr.type, fill_mshr.cpu});

  response_type response{fill_mshr.address, fill_mshr.v_address, fill_mshr.data_promise->data, metadata_thru, fill_mshr.instr_depend_on_me};
  response.tlb_ptw_prefetch_tracked = fill_mshr.tlb_ptw_prefetch_tracked;
  response.tlb_ptw_prefetch_cpu = fill_mshr.tlb_ptw_prefetch_cpu;
  response.tlb_ptw_prefetch_id = fill_mshr.tlb_ptw_prefetch_id;
  for (auto* ret : fill_mshr.to_return) {
    ret->push_back(response);
  }

  return true;
}

bool CACHE::try_hit(const tag_lookup_type& handle_pkt)
{
  cpu = handle_pkt.cpu;

  // access cache
  auto [set_begin, set_end] = get_set_span(handle_pkt.address);
  auto way = std::find_if(set_begin, set_end, [matcher = matches_address(handle_pkt.address)](const auto& x) { return x.valid && matcher(x); });
  const auto hit = (way != set_end);
  const auto useful_prefetch = (hit && way->prefetch && !handle_pkt.prefetch_from_this);

  if constexpr (champsim::debug_print) {
    fmt::print("[{}] {} instr_id: {} address: {} v_address: {} data: {} set: {} way: {} ({}) type: {} cycle: {}\n", NAME, __func__, handle_pkt.instr_id,
               handle_pkt.address, handle_pkt.v_address, handle_pkt.data, get_set_index(handle_pkt.address), std::distance(set_begin, way),
               hit ? "HIT" : "MISS", access_type_names.at(champsim::to_underlying(handle_pkt.type)), current_time.time_since_epoch() / clock_period);
  }

  auto metadata_thru = handle_pkt.pf_metadata;
  if (should_activate_prefetcher(handle_pkt) && !module_is_instr(handle_pkt)) { // limiting only to data line hits
    metadata_thru = impl_prefetcher_cache_operate(module_address(handle_pkt), handle_pkt.ip, hit, useful_prefetch, handle_pkt.type, metadata_thru);
  }

  // update replacement policy
  const auto way_idx = std::distance(set_begin, way);
  impl_update_replacement_state(handle_pkt.cpu, get_set_index(handle_pkt.address), way_idx, module_address(handle_pkt), handle_pkt.ip, {}, handle_pkt.type,
                                hit);

  if (hit) {
    if (is_dtlb()) {
      champsim::demand_tlb_pattern_logger().mark_l1dtlb_hit(handle_pkt.demand_tlb_events, false);
      champsim::demand_tlb_pattern_logger().mark_l1dtlb_hit(handle_pkt.demand_tlb_coalesced_events, true);
      champsim::vberti_cross_page_demand_pattern_logger().mark_l1dtlb_hit(handle_pkt.vberti_tlb_events, false);
      champsim::vberti_cross_page_demand_pattern_logger().mark_l1dtlb_hit(handle_pkt.vberti_tlb_coalesced_events, true);
    } else if (is_stlb()) {
      champsim::demand_tlb_pattern_logger().mark_stlb_hit(handle_pkt.demand_tlb_events);
      champsim::vberti_cross_page_demand_pattern_logger().mark_stlb_hit(handle_pkt.vberti_tlb_events);
    }

    if (handle_pkt.vberti_end_to_end_tracked)
      champsim::vberti_end_to_end::cancel(handle_pkt.vberti_end_to_end_cpu, handle_pkt.vberti_end_to_end_id);
    if (!handle_pkt.is_instr && is_cache_demand_type(handle_pkt.type) && way->vberti_end_to_end_tracked)
      champsim::vberti_end_to_end::mark_useful(way->vberti_end_to_end_cpu, way->vberti_end_to_end_id, false);

    sim_stats.hits.increment(std::pair{handle_pkt.type, handle_pkt.cpu});
    discard_prefetch_too_early_candidate(handle_pkt);
    discard_prefetch_pollution_candidate(handle_pkt);
    record_tlb_ptw_system_hit(handle_pkt, *way);
    record_tlb_cross_prefetch_hit(handle_pkt, *way);
    record_tlb_origin_hit(handle_pkt);

    response_type response{handle_pkt.address, handle_pkt.v_address, way->data, metadata_thru, handle_pkt.instr_depend_on_me};
    response.tlb_ptw_prefetch_tracked = way->tlb_ptw_prefetch_tracked;
    response.tlb_ptw_prefetch_cpu = way->tlb_ptw_prefetch_cpu;
    response.tlb_ptw_prefetch_id = way->tlb_ptw_prefetch_id;
    for (auto* ret : handle_pkt.to_return) {
      ret->push_back(response);
    }

    way->dirty |= (handle_pkt.type == access_type::WRITE);

    // update prefetch stats and reset prefetch bit
    if (useful_prefetch) {
      ++sim_stats.pf_useful;
      way->prefetch = false;
    }
  }

  return hit;
}

auto CACHE::mshr_and_forward_packet(const tag_lookup_type& handle_pkt) -> std::pair<mshr_type, request_type>
{
  mshr_type to_allocate{handle_pkt, current_time};

  request_type fwd_pkt;

  fwd_pkt.asid[0] = handle_pkt.asid[0];
  fwd_pkt.asid[1] = handle_pkt.asid[1];
  fwd_pkt.type = (handle_pkt.type == access_type::WRITE) ? access_type::RFO : handle_pkt.type;
  fwd_pkt.translation_source = handle_pkt.translation_source;
  fwd_pkt.pf_metadata = handle_pkt.pf_metadata;
  fwd_pkt.cpu = handle_pkt.cpu;
  fwd_pkt.demand_tlb_operand_index = handle_pkt.demand_tlb_operand_index;
  fwd_pkt.vberti_end_to_end_tracked = handle_pkt.vberti_end_to_end_tracked;
  fwd_pkt.vberti_end_to_end_cpu = handle_pkt.vberti_end_to_end_cpu;
  fwd_pkt.vberti_end_to_end_id = handle_pkt.vberti_end_to_end_id;
  fwd_pkt.tlb_ptw_prefetch_tracked = handle_pkt.tlb_ptw_prefetch_tracked;
  fwd_pkt.tlb_ptw_real_demand_waiting = handle_pkt.tlb_ptw_real_demand_waiting;
  fwd_pkt.tlb_ptw_prefetch_cpu = handle_pkt.tlb_ptw_prefetch_cpu;
  fwd_pkt.tlb_ptw_prefetch_id = handle_pkt.tlb_ptw_prefetch_id;

  fwd_pkt.address = handle_pkt.address;
  fwd_pkt.v_address = handle_pkt.v_address;
  fwd_pkt.data = handle_pkt.data;
  fwd_pkt.instr_id = handle_pkt.instr_id;
  fwd_pkt.ip = handle_pkt.ip;
  fwd_pkt.is_instr = handle_pkt.is_instr;

  fwd_pkt.instr_depend_on_me = handle_pkt.instr_depend_on_me;
  fwd_pkt.ptw_dram_touched_flags = handle_pkt.ptw_dram_touched_flags;
  fwd_pkt.count_ptw_dram_touch = is_stlb() && !warmup;
  fwd_pkt.response_requested = (!handle_pkt.prefetch_from_this || !handle_pkt.skip_fill);

  if (is_dtlb() && !handle_pkt.demand_tlb_events.empty()) {
    fwd_pkt.demand_tlb_stage = champsim::demand_tlb_pattern_stage::STLB;
    fwd_pkt.demand_tlb_events = handle_pkt.demand_tlb_events;
  }
  if (is_dtlb() && !handle_pkt.vberti_tlb_events.empty()) {
    fwd_pkt.vberti_tlb_stage = champsim::vberti_tlb_pattern_stage::STLB;
    fwd_pkt.vberti_tlb_events = handle_pkt.vberti_tlb_events;
  }

  return std::pair{std::move(to_allocate), std::move(fwd_pkt)};
}

bool CACHE::handle_miss(const tag_lookup_type& handle_pkt)
{
  if constexpr (champsim::debug_print) {
    fmt::print("[{}] {} instr_id: {} address: {} v_address: {} type: {} local_prefetch: {} cycle: {}\n", NAME, __func__, handle_pkt.instr_id,
               handle_pkt.address, handle_pkt.v_address, access_type_names.at(champsim::to_underlying(handle_pkt.type)), handle_pkt.prefetch_from_this,
               current_time.time_since_epoch() / clock_period);
  }

  mshr_type to_allocate{handle_pkt, current_time};

  cpu = handle_pkt.cpu;

  if (try_stlb_cp_pb_demand_hit(handle_pkt)) {
    if (is_stlb()) {
      champsim::demand_tlb_pattern_logger().mark_stlb_miss(handle_pkt.demand_tlb_events, false);
      champsim::vberti_cross_page_demand_pattern_logger().mark_stlb_miss(handle_pkt.vberti_tlb_events, false);
    }
    return true;
  }

  auto mshr_pkt = mshr_and_forward_packet(handle_pkt);

  // check mshr
  auto mshr_entry = std::find_if(std::begin(MSHR), std::end(MSHR), matches_address(handle_pkt.address));
  bool mshr_full = (MSHR.size() == MSHR_SIZE);
  bool new_mshr = false;
  bool merged_into_mshr = false;
  auto tlb_mshr_merge_detail = champsim::dtlb_merge_detail::NONE;

  if (mshr_entry != MSHR.end()) // miss already inflight
  {
    merged_into_mshr = true;
    if (is_tlb())
      tlb_mshr_merge_detail = classify_tlb_mshr_merge_target(mshr_entry->translation_source);
    if (mshr_entry->vberti_end_to_end_tracked && !handle_pkt.is_instr && is_cache_demand_type(handle_pkt.type))
      champsim::vberti_end_to_end::mark_useful(mshr_entry->vberti_end_to_end_cpu, mshr_entry->vberti_end_to_end_id, true);
    if (handle_pkt.vberti_end_to_end_tracked)
      champsim::vberti_end_to_end::cancel(handle_pkt.vberti_end_to_end_cpu, handle_pkt.vberti_end_to_end_id);

    if (is_tlb() && is_demand_origin(handle_pkt.translation_source) && !mshr_entry->tlb_ptw_real_demand_waiting) {
      if (mshr_entry->tlb_ptw_prefetch_tracked) {
        champsim::tlb_ptw_system::note_demand_for_id(mshr_entry->tlb_ptw_prefetch_cpu, mshr_entry->tlb_ptw_prefetch_id);
      } else if (is_dtlb() && is_l1d_cross_page_prefetch_origin(mshr_entry->translation_source)) {
        const champsim::tlb_ptw_system::key translation{handle_pkt.cpu, champsim::page_number{handle_pkt.v_address}.to<uint64_t>(), handle_pkt.asid[0],
                                                         handle_pkt.asid[1]};
        champsim::tlb_ptw_system::note_demand_for_key(translation);
      }
      mshr_entry->tlb_ptw_real_demand_waiting = true;
    }

    if (mshr_entry->type == access_type::PREFETCH && handle_pkt.type != access_type::PREFETCH) {
      // Mark the prefetch as useful
      if (mshr_entry->prefetch_from_this) {
        ++sim_stats.pf_useful;
        ++sim_stats.pf_late;
      }
    }

    // COLLECT STATS
    sim_stats.mshr_merge.increment(std::pair{to_allocate.type, to_allocate.cpu});
    if (is_tlb())
      sim_stats.tlb_origin_mshr_merge.increment(std::pair{handle_pkt.translation_source, handle_pkt.cpu});

    *mshr_entry = mshr_type::merge(*mshr_entry, to_allocate);
  } else {
    if (mshr_full) { // not enough MSHR resource
      return false;  // TODO should we allow prefetches anyway if they will not be filled to this level?
    }

    if (is_stlb() && is_l1d_cross_page_prefetch_origin(handle_pkt.translation_source)) {
      const auto ptw_id = champsim::tlb_ptw_system::reserve_prefetch_ptw_id(handle_pkt.cpu);
      mshr_pkt.first.tlb_ptw_prefetch_tracked = true;
      mshr_pkt.first.tlb_ptw_prefetch_cpu = handle_pkt.cpu;
      mshr_pkt.first.tlb_ptw_prefetch_id = ptw_id;
      mshr_pkt.second.tlb_ptw_prefetch_tracked = true;
      mshr_pkt.second.tlb_ptw_prefetch_cpu = handle_pkt.cpu;
      mshr_pkt.second.tlb_ptw_prefetch_id = ptw_id;
    }

    const bool send_to_rq = (prefetch_as_load || handle_pkt.type != access_type::PREFETCH);
    bool success = send_to_rq ? lower_level->add_rq(mshr_pkt.second) : lower_level->add_pq(mshr_pkt.second);

    if (!success) {
      return false;
    }

    // Allocate an MSHR
    if (mshr_pkt.second.response_requested) {
      MSHR.emplace_back(std::move(mshr_pkt.first));
      new_mshr = true;
    }
  }

  if (is_dtlb()) {
    champsim::demand_tlb_pattern_logger().mark_l1dtlb_miss(handle_pkt.demand_tlb_events, merged_into_mshr, tlb_mshr_merge_detail);
    champsim::demand_tlb_pattern_logger().mark_l1dtlb_miss(handle_pkt.demand_tlb_coalesced_events, true, champsim::dtlb_merge_detail::RQ_MERGE);
    champsim::vberti_cross_page_demand_pattern_logger().mark_l1dtlb_miss(handle_pkt.vberti_tlb_events, merged_into_mshr,
                                                                        tlb_mshr_merge_detail);
    champsim::vberti_cross_page_demand_pattern_logger().mark_l1dtlb_miss(handle_pkt.vberti_tlb_coalesced_events, true,
                                                                        champsim::dtlb_merge_detail::RQ_MERGE);
  } else if (is_stlb()) {
    champsim::demand_tlb_pattern_logger().mark_stlb_miss(handle_pkt.demand_tlb_events, merged_into_mshr, tlb_mshr_merge_detail);
    champsim::vberti_cross_page_demand_pattern_logger().mark_stlb_miss(handle_pkt.vberti_tlb_events, merged_into_mshr,
                                                                      tlb_mshr_merge_detail);
  }

  sim_stats.misses.increment(std::pair{handle_pkt.type, handle_pkt.cpu});
  if (consume_prefetch_too_early_candidate(handle_pkt))
    ++sim_stats.pf_too_early;
  const auto [polluted_by_prefetch, polluted_victim_was_demand] = consume_prefetch_pollution_candidate(handle_pkt);
  if (polluted_by_prefetch)
    ++sim_stats.pf_pollution_evict;
  if (polluted_victim_was_demand)
    ++sim_stats.pf_pollution_demand;
  record_tlb_cross_prefetch_miss(handle_pkt, new_mshr);
  record_tlb_origin_miss(handle_pkt);
  if (is_stlb() && is_data_demand_origin(handle_pkt.translation_source)) {
    ++sim_stats.stlb_cp_pb_raw_demand_miss;
    ++sim_stats.stlb_cp_pb_demand_miss;
  }
  champsim::instrumentation::record_stlb_vpn_miss(NAME, warmup, current_time, clock_period, handle_pkt.ip, handle_pkt.v_address, handle_pkt.instr_id,
                                                  handle_pkt.cpu, handle_pkt.type, handle_pkt.translation_source, handle_pkt.prefetch_from_this,
                                                  handle_pkt.is_instr);

  return true;
}

bool CACHE::handle_write(const tag_lookup_type& handle_pkt)
{
  if constexpr (champsim::debug_print) {
    fmt::print("[{}] {} instr_id: {} address: {} v_address: {} type: {} local_prefetch: {} cycle: {}\n", NAME, __func__, handle_pkt.instr_id,
               handle_pkt.address, handle_pkt.v_address, access_type_names.at(champsim::to_underlying(handle_pkt.type)), handle_pkt.prefetch_from_this,
               current_time.time_since_epoch() / clock_period);
  }

  mshr_type to_allocate{handle_pkt, current_time};
  to_allocate.data_promise.ready_at(current_time + (warmup ? champsim::chrono::clock::duration{} : FILL_LATENCY));
  inflight_writes.push_back(to_allocate);

  sim_stats.misses.increment(std::pair{handle_pkt.type, handle_pkt.cpu});
  record_tlb_cross_prefetch_miss(handle_pkt, false);
  record_tlb_origin_miss(handle_pkt);
  champsim::instrumentation::record_stlb_vpn_miss(NAME, warmup, current_time, clock_period, handle_pkt.ip, handle_pkt.v_address, handle_pkt.instr_id,
                                                  handle_pkt.cpu, handle_pkt.type, handle_pkt.translation_source, handle_pkt.prefetch_from_this,
                                                  handle_pkt.is_instr);

  return true;
}

template <bool UpdateRequest>
auto CACHE::initiate_tag_check(champsim::channel* ul)
{
  return [time = current_time + (warmup ? champsim::chrono::clock::duration{} : HIT_LATENCY), ul](const auto& entry) {
    CACHE::tag_lookup_type retval{entry};
    retval.event_cycle = time;

    if constexpr (UpdateRequest) {
      if (entry.response_requested) {
        retval.to_return = {&ul->returned};
      }
    } else {
      (void)ul; // supress warning about ul being unused
    }

    if constexpr (champsim::debug_print) {
      fmt::print("[TAG] initiate_tag_check instr_id: {} address: {} v_address: {} type: {} response_requested: {}\n", retval.instr_id, retval.address,
                 retval.v_address, access_type_names.at(champsim::to_underlying(retval.type)), !std::empty(retval.to_return));
    }

    return retval;
  };
}

long CACHE::operate()
{
  long progress{0};

  auto is_ready = [time = current_time](const auto& entry) {
    return entry.event_cycle <= time;
  };
  auto is_translated = [](const auto& entry) {
    return entry.is_translated;
  };

  for (auto* ul : upper_levels) {
    ul->check_collision();
  }

  // Finish returns
  std::for_each(std::cbegin(lower_level->returned), std::cend(lower_level->returned), [this](const auto& pkt) { this->finish_packet(pkt); });
  progress += std::distance(std::cbegin(lower_level->returned), std::cend(lower_level->returned));
  lower_level->returned.clear();

  // Finish translations
  if (lower_translate != nullptr) {
    std::for_each(std::cbegin(lower_translate->returned), std::cend(lower_translate->returned), [this](const auto& pkt) {
      this->finish_translation(pkt);
      this->finish_pqfull_tlb_rescue_translation(pkt);
    });
    progress += std::distance(std::cbegin(lower_translate->returned), std::cend(lower_translate->returned));
    lower_translate->returned.clear();
  }

  // Translation-only packets use the normal L1D PQ and DTLB/STLB/PTW path.
  // Remove them only after translation has completed, before any data tag
  // lookup or lower-cache request can be generated.
  progress += drop_translated_l1d_cross_page_translation_only(translation_stash);
  progress += drop_translated_l1d_cross_page_translation_only(inflight_tag_check);

  // Perform fills
  champsim::bandwidth fill_bw{MAX_FILL};
  for (auto q : {std::ref(MSHR), std::ref(inflight_writes)}) {
    auto [fill_begin, fill_end] = champsim::get_span_p(std::cbegin(q.get()), std::cend(q.get()), fill_bw,
                                                       [time = current_time](const auto& x) { return x.data_promise.is_ready_at(time); });
    auto complete_end = std::find_if_not(fill_begin, fill_end, [this](const auto& x) { return this->handle_fill(x); });
    fill_bw.consume(std::distance(fill_begin, complete_end));
    q.get().erase(fill_begin, complete_end);
  }

  // Initiate tag checks
  const champsim::bandwidth::maximum_type bandwidth_from_tag_checks{champsim::to_underlying(MAX_TAG) * (long)(HIT_LATENCY / clock_period)
                                                                    - (long)std::size(inflight_tag_check)};
  champsim::bandwidth initiate_tag_bw{std::clamp(bandwidth_from_tag_checks, champsim::bandwidth::maximum_type{0}, MAX_TAG)};
  auto can_translate = [avail = (std::size(translation_stash) < static_cast<std::size_t>(MSHR_SIZE))](const auto& entry) {
    return avail || entry.is_translated;
  };
  auto stash_bandwidth_consumed =
      champsim::transform_while_n(translation_stash, std::back_inserter(inflight_tag_check), initiate_tag_bw, is_translated, initiate_tag_check<false>());
  initiate_tag_bw.consume(stash_bandwidth_consumed);
  std::vector<long long> channels_bandwidth_consumed{};

  if (std::size(upper_levels) > 1) {
    std::rotate(upper_levels.begin(), upper_levels.begin() + 1, upper_levels.end());
  }

  // upper levels get an equal portion of the remaining bandwidth
  champsim::bandwidth::maximum_type per_upper_bandwidth =
      std::size(upper_levels) >= 1
          ? (champsim::bandwidth::maximum_type)std::max((size_t)initiate_tag_bw.amount_remaining() / std::size(upper_levels), size_t{1})
          : champsim::bandwidth::maximum_type{};

  for (auto* ul : upper_levels) {
    for (auto q : {std::ref(ul->WQ), std::ref(ul->RQ), std::ref(ul->PQ)}) {
      // this needs to be in this loop, we need to ensure that for cases where bandwidth doesn't divide nicely across upstreams,
      // we don't accidentally consume more bandwidth than expected
      champsim::bandwidth per_upper_tag_bw{std::min(per_upper_bandwidth, champsim::bandwidth::maximum_type{initiate_tag_bw.amount_remaining()})};
      auto bandwidth_consumed =
          champsim::transform_while_n(q.get(), std::back_inserter(inflight_tag_check), per_upper_tag_bw, can_translate, initiate_tag_check<true>(ul));
      channels_bandwidth_consumed.push_back(bandwidth_consumed);
      initiate_tag_bw.consume(bandwidth_consumed);
    }
  }

  auto pq_bandwidth_consumed =
      champsim::transform_while_n(internal_PQ, std::back_inserter(inflight_tag_check), initiate_tag_bw, can_translate, initiate_tag_check<false>());
  initiate_tag_bw.consume(pq_bandwidth_consumed);

  // Issue translations
  std::for_each(std::begin(inflight_tag_check), std::end(inflight_tag_check), [this](auto& x) { this->issue_translation(x); });
  std::for_each(std::begin(translation_stash), std::end(translation_stash), [this](auto& x) { this->issue_translation(x); });
  progress += issue_pqfull_tlb_rescue();

  // Find entries that would be ready except that they have not finished translation, move them to the stash
  auto [last_not_missed, stash_end] = champsim::extract_if(std::begin(inflight_tag_check), std::end(inflight_tag_check), std::back_inserter(translation_stash),
                                                           [is_ready, is_translated](const auto& x) { return is_ready(x) && !is_translated(x); });
  progress += std::distance(last_not_missed, std::end(inflight_tag_check));
  inflight_tag_check.erase(last_not_missed, std::end(inflight_tag_check));

  // Perform tag checks
  auto do_handle_miss = [this](const auto& pkt) {
    if (pkt.type == access_type::WRITE && !this->match_offset_bits) {
      return this->handle_write(pkt); // Treat writes (that is, writebacks) like fills
    }
    return this->handle_miss(pkt); // Treat writes (that is, stores) like reads
  };
  champsim::bandwidth tag_check_bw{MAX_TAG};
  auto [tag_check_ready_begin, tag_check_ready_end] =
      champsim::get_span_p(std::begin(inflight_tag_check), std::end(inflight_tag_check), tag_check_bw,
                           [is_ready, is_translated](const auto& pkt) { return is_ready(pkt) && is_translated(pkt); });
  for (auto it = tag_check_ready_begin; it != tag_check_ready_end; ++it) {
    champsim::instrumentation::record_l1d_vpn_access(NAME, warmup, current_time, clock_period, it->ip, it->v_address, it->instr_id, it->cpu, it->type,
                                                     it->prefetch_from_this, it->is_instr);
    champsim::instrumentation::record_dtlb_vpn_access(NAME, warmup, current_time, clock_period, it->ip, it->v_address, it->instr_id, it->cpu, it->type,
                                                      it->translation_source, it->prefetch_from_this, it->is_instr);
    champsim::instrumentation::record_stlb_vpn_access(NAME, warmup, current_time, clock_period, it->ip, it->v_address, it->instr_id, it->cpu, it->type,
                                                      it->translation_source, it->prefetch_from_this, it->is_instr);
  }
  auto hits_end = std::stable_partition(tag_check_ready_begin, tag_check_ready_end, [this](const auto& pkt) { return this->try_hit(pkt); });
  auto finish_tag_check_end = std::stable_partition(hits_end, tag_check_ready_end, do_handle_miss);
  tag_check_bw.consume(std::distance(tag_check_ready_begin, finish_tag_check_end));
  inflight_tag_check.erase(tag_check_ready_begin, finish_tag_check_end);

  impl_prefetcher_cycle_operate();

  if constexpr (champsim::debug_print) {
    fmt::print("[{}] {} cycle completed: {} tags checked: {} remaining: {} stash consumed: {} remaining: {} channel consumed: {} pq consumed {} unused consume "
               "bw {}\n",
               NAME, __func__, current_time.time_since_epoch() / clock_period, tag_check_bw.amount_consumed(), std::size(inflight_tag_check),
               stash_bandwidth_consumed, std::size(translation_stash), channels_bandwidth_consumed, pq_bandwidth_consumed, initiate_tag_bw.amount_remaining());
  }

  return progress + fill_bw.amount_consumed() + initiate_tag_bw.amount_consumed() + tag_check_bw.amount_consumed();
}

// LCOV_EXCL_START exclude deprecated function
uint64_t CACHE::get_set(uint64_t address) const { return static_cast<uint64_t>(get_set_index(champsim::address{address})); }
// LCOV_EXCL_STOP

long CACHE::get_set_index(champsim::address address) const { return address.slice(champsim::dynamic_extent{OFFSET_BITS, champsim::lg2(NUM_SET)}).to<long>(); }

template <typename It>
std::pair<It, It> get_span(It anchor, typename std::iterator_traits<It>::difference_type set_idx, typename std::iterator_traits<It>::difference_type num_way)
{
  auto begin = std::next(anchor, set_idx * num_way);
  return {std::move(begin), std::next(begin, num_way)};
}

auto CACHE::get_set_span(champsim::address address) -> std::pair<set_type::iterator, set_type::iterator>
{
  const auto set_idx = get_set_index(address);
  assert(set_idx < NUM_SET);
  return get_span(std::begin(block), static_cast<set_type::difference_type>(set_idx), NUM_WAY); // safe cast because of prior assert
}

auto CACHE::get_set_span(champsim::address address) const -> std::pair<set_type::const_iterator, set_type::const_iterator>
{
  const auto set_idx = get_set_index(address);
  assert(set_idx < NUM_SET);
  return get_span(std::cbegin(block), static_cast<set_type::difference_type>(set_idx), NUM_WAY); // safe cast because of prior assert
}

// LCOV_EXCL_START exclude deprecated function
uint64_t CACHE::get_way(uint64_t address, uint64_t /*unused set index*/) const
{
  champsim::address intern_addr{address};
  auto [begin, end] = get_set_span(intern_addr);
  return static_cast<uint64_t>(std::distance(begin, std::find_if(begin, end, matches_address(champsim::address{address}))));
}
// LCOV_EXCL_STOP

long CACHE::invalidate_entry(champsim::address inval_addr)
{
  auto [begin, end] = get_set_span(inval_addr);
  auto inv_way = std::find_if(begin, end, matches_address(inval_addr));

  if (inv_way != end) {
    inv_way->valid = false;
  }

  return std::distance(begin, inv_way);
}

void CACHE::record_l1d_prefetch_candidate(uint32_t prefetch_metadata)
{
  if (!is_l1d_pref_meta(prefetch_metadata))
    return;

  ++sim_stats.vberti_prefetch_requested;
  if (is_l1d_pref_cross(prefetch_metadata))
    ++sim_stats.vberti_cross_page_requested;
}

bool CACHE::prefetch_line(champsim::address pf_addr, bool fill_this_level, uint32_t prefetch_metadata)
{
  ++sim_stats.pf_requested;

  const auto is_vberti_prefetch = is_l1d_pref_meta(prefetch_metadata);
  const auto is_cross_page_prefetch = is_vberti_prefetch && is_l1d_pref_cross(prefetch_metadata);
  const auto is_l1d_vberti_prefetch =
      is_vberti_prefetch && NAME.size() >= 4 && NAME.compare(NAME.size() - 4, 4, "_L1D") == 0;
  const auto prefetch_seq = is_vberti_prefetch ? vberti_prefetch_seq_counter++ : 0;
  const auto is_translation_only_prefetch = champsim::l1d_cross_page_pf_translation_only && is_l1d_vberti_prefetch
                                            && is_l1d_pref_translation_only(prefetch_metadata);

  if (is_translation_only_prefetch)
    ++sim_stats.cross_page_pf_translation_only_requested;

  auto make_prefetch_packet = [this, pf_addr, prefetch_metadata]() {
    request_type pf_packet;
    pf_packet.type = access_type::PREFETCH;
    pf_packet.pf_metadata = prefetch_metadata;
    pf_packet.cpu = cpu;
    pf_packet.address = pf_addr;
    pf_packet.v_address = virtual_prefetch ? pf_addr : champsim::address{};
    pf_packet.is_translated = !virtual_prefetch;
    pf_packet.is_instr = NAME.size() >= 4 && NAME.compare(NAME.size() - 4, 4, "_L1I") == 0;
    if (pf_packet.is_instr) {
      pf_packet.translation_source = translation_origin::L1I_PREFETCH;
    } else if (NAME.size() >= 4 && NAME.compare(NAME.size() - 4, 4, "_L1D") == 0) {
      pf_packet.translation_source = translation_origin::L1D_PREFETCH;
    }
    return pf_packet;
  };

  if (std::size(internal_PQ) >= PQ_SIZE) {
    if (is_cross_page_prefetch) {
      ++sim_stats.cp_pf_pqfull_drop;
      if (champsim::ordered_pqfull_tlb_rescue && lower_translate != nullptr && virtual_prefetch
          && std::size(pqfull_tlb_rescue_queue) < PQFULL_TLB_RESCUE_QUEUE_SIZE) {
        auto pf_packet = make_prefetch_packet();
        tag_lookup_type rescue_entry{pf_packet, true, !fill_this_level};
        rescue_entry.has_l1d_prefetch_seq = true;
        rescue_entry.l1d_prefetch_seq = prefetch_seq;
        rescue_entry.translation_only_rescue = true;
        pqfull_tlb_rescue_queue.push_back(rescue_entry);
        ++sim_stats.cp_pf_pqfull_tlb_rescue_enqueued;
      }
    }
    return false;
  }

  auto pf_packet = make_prefetch_packet();
  internal_PQ.emplace_back(pf_packet, true, !fill_this_level);
  if (is_vberti_prefetch) {
    internal_PQ.back().has_l1d_prefetch_seq = true;
    internal_PQ.back().l1d_prefetch_seq = prefetch_seq;
    if (!warmup && is_l1d_vberti_prefetch && !is_translation_only_prefetch) {
      if (!vberti_end_to_end_roi_started) {
        champsim::vberti_end_to_end::reset(cpu);
        vberti_end_to_end_id_counter = 0;
        vberti_end_to_end_roi_started = true;
      }
      internal_PQ.back().vberti_end_to_end_tracked = true;
      internal_PQ.back().vberti_end_to_end_cpu = cpu;
      internal_PQ.back().vberti_end_to_end_id = vberti_end_to_end_id_counter++;
      champsim::vberti_end_to_end::issue(cpu, internal_PQ.back().vberti_end_to_end_id);
    }
  }
  ++sim_stats.pf_issued;
  if (is_vberti_prefetch) {
    ++sim_stats.vberti_prefetch_issued;
    if (is_cross_page_prefetch)
      ++sim_stats.vberti_cross_page_issued;
  }
  if (is_translation_only_prefetch)
    ++sim_stats.cross_page_pf_translation_only_issued;

  return true;
}

bool CACHE::should_drop_l1d_cross_page_translation_only(const tag_lookup_type& handle_pkt) const
{
  return champsim::l1d_cross_page_pf_translation_only && is_l1d_name(NAME) && handle_pkt.type == access_type::PREFETCH
         && handle_pkt.prefetch_from_this && handle_pkt.is_translated && is_l1d_pref_cross(handle_pkt.pf_metadata)
         && is_l1d_pref_translation_only(handle_pkt.pf_metadata);
}

std::size_t CACHE::drop_translated_l1d_cross_page_translation_only(std::deque<tag_lookup_type>& queue)
{
  if (!champsim::l1d_cross_page_pf_translation_only || !is_l1d_name(NAME))
    return 0;

  const auto drop_begin = std::remove_if(std::begin(queue), std::end(queue),
                                         [this](const auto& pkt) { return should_drop_l1d_cross_page_translation_only(pkt); });
  const auto dropped = static_cast<std::size_t>(std::distance(drop_begin, std::end(queue)));
  queue.erase(drop_begin, std::end(queue));
  sim_stats.cross_page_pf_translation_only_dropped += dropped;
  return dropped;
}

// LCOV_EXCL_START exclude deprecated function
bool CACHE::prefetch_line(uint64_t pf_addr, bool fill_this_level, uint32_t prefetch_metadata)
{
  return prefetch_line(champsim::address{pf_addr}, fill_this_level, prefetch_metadata);
}

bool CACHE::prefetch_line(uint64_t /*deprecated*/, uint64_t /*deprecated*/, uint64_t pf_addr, bool fill_this_level, uint32_t prefetch_metadata)
{
  return prefetch_line(champsim::address{pf_addr}, fill_this_level, prefetch_metadata);
}
// LCOV_EXCL_STOP

void CACHE::finish_packet(const response_type& packet)
{
  // check MSHR information
  auto mshr_entry = std::find_if(std::begin(MSHR), std::end(MSHR), matches_address(packet.address));
  auto first_unreturned = std::find_if(MSHR.begin(), MSHR.end(), [](auto x) { return x.data_promise.has_unknown_readiness(); });

  // sanity check
  if (mshr_entry == MSHR.end()) {
    fmt::print(stderr, "[{}_MSHR] {} cannot find a matching entry! address: {} v_address: {}\n", NAME, __func__, packet.address, packet.v_address);
    assert(0);
  }

  if (mshr_entry->tlb_ptw_real_demand_waiting && packet.tlb_ptw_prefetch_tracked)
    champsim::tlb_ptw_system::note_demand_for_id(packet.tlb_ptw_prefetch_cpu, packet.tlb_ptw_prefetch_id);
  if (is_dtlb()) {
    const champsim::tlb_ptw_system::key translation{mshr_entry->cpu, champsim::page_number{mshr_entry->v_address}.to<uint64_t>(), mshr_entry->asid[0],
                                                     mshr_entry->asid[1]};
    champsim::tlb_ptw_system::clear_waiting_for_key(translation);
  }
  mshr_entry->tlb_ptw_prefetch_tracked = packet.tlb_ptw_prefetch_tracked;
  mshr_entry->tlb_ptw_prefetch_cpu = packet.tlb_ptw_prefetch_cpu;
  mshr_entry->tlb_ptw_prefetch_id = packet.tlb_ptw_prefetch_id;

  // MSHR holds the most updated information about this request
  mshr_type::returned_value finished_value{packet.data, packet.pf_metadata};
  mshr_entry->data_promise = champsim::waitable{finished_value, current_time + (warmup ? champsim::chrono::clock::duration{} : FILL_LATENCY)};
  if constexpr (champsim::debug_print) {
    fmt::print("[{}_MSHR] finish_packet instr_id: {} address: {} data: {} type: {} current: {}\n", this->NAME, mshr_entry->instr_id, mshr_entry->address,
               mshr_entry->data_promise->data, access_type_names.at(champsim::to_underlying(mshr_entry->type)), current_time.time_since_epoch() / clock_period);
  }

  // Order this entry after previously-returned entries, but before non-returned
  // entries
  std::iter_swap(mshr_entry, first_unreturned);
}

void CACHE::finish_translation(const response_type& packet)
{
  auto matches_vpage = [page_num = champsim::page_number{packet.v_address}](const auto& entry) {
    return (champsim::page_number{entry.v_address} == page_num) && !entry.is_translated;
  };
  auto mark_translated = [p_page = champsim::page_number{packet.data}, this](auto& entry) {
    [[maybe_unused]] auto old_address = entry.address;
    if (is_l1d_name(NAME)) {
      const auto completion_cycle = static_cast<uint64_t>(current_time.time_since_epoch() / clock_period);
      const auto ppn = p_page.to<uint64_t>();
      champsim::demand_tlb_pattern_logger().complete(entry.demand_tlb_events, completion_cycle, ppn);
      champsim::demand_tlb_pattern_logger().complete(entry.demand_tlb_coalesced_events, completion_cycle, ppn);
      champsim::vberti_cross_page_demand_pattern_logger().complete(entry.vberti_tlb_events, completion_cycle, ppn);
      champsim::vberti_cross_page_demand_pattern_logger().complete(entry.vberti_tlb_coalesced_events, completion_cycle, ppn);
    }
    entry.address = champsim::address{champsim::splice(p_page, champsim::page_offset{entry.v_address})}; // translated address
    entry.is_translated = true;                                                                          // This entry is now translated

    if constexpr (champsim::debug_print) {
      fmt::print("[{}_TRANSLATE] finish_translation old: {} paddr: {} vaddr: {} type: {} cycle: {}\n", this->NAME, old_address, entry.address, entry.v_address,
                 access_type_names.at(champsim::to_underlying(entry.type)), this->current_time.time_since_epoch() / this->clock_period);
    }
  };

  // Restart stashed translations
  auto finish_begin = std::find_if_not(std::begin(translation_stash), std::end(translation_stash), [](const auto& x) { return x.is_translated; });
  auto finish_end = std::stable_partition(finish_begin, std::end(translation_stash), matches_vpage);
  std::for_each(finish_begin, finish_end, mark_translated);

  // Find all packets that match the page of the returned packet
  for (auto& entry : inflight_tag_check) {
    if (matches_vpage(entry)) {
      mark_translated(entry);
    }
  }
}

void CACHE::finish_pqfull_tlb_rescue_translation(const response_type& packet)
{
  auto matches_vpage = [page_num = champsim::page_number{packet.v_address}](const auto& entry) {
    return (champsim::page_number{entry.v_address} == page_num) && !entry.is_translated;
  };

  auto translated_begin = std::stable_partition(std::begin(pqfull_tlb_rescue_inflight), std::end(pqfull_tlb_rescue_inflight), matches_vpage);
  const auto translated = std::distance(std::begin(pqfull_tlb_rescue_inflight), translated_begin);
  sim_stats.cp_pf_pqfull_tlb_rescue_translated += static_cast<uint64_t>(translated);
  pqfull_tlb_rescue_inflight.erase(std::begin(pqfull_tlb_rescue_inflight), translated_begin);
}

void CACHE::issue_translation(tag_lookup_type& q_entry) const
{
  if (!q_entry.translate_issued && !q_entry.is_translated) {
    request_type fwd_pkt;
    fwd_pkt.asid[0] = q_entry.asid[0];
    fwd_pkt.asid[1] = q_entry.asid[1];
    fwd_pkt.type = access_type::LOAD;
    fwd_pkt.translation_source = classify_translation_origin(q_entry);
    fwd_pkt.cpu = q_entry.cpu;

    fwd_pkt.address = q_entry.address;
    fwd_pkt.v_address = q_entry.v_address;
    fwd_pkt.data = q_entry.data;
    fwd_pkt.pf_metadata = q_entry.pf_metadata;
    fwd_pkt.instr_id = q_entry.instr_id;
    fwd_pkt.ip = q_entry.ip;
    fwd_pkt.is_instr = q_entry.is_instr;
    fwd_pkt.demand_tlb_operand_index = q_entry.demand_tlb_operand_index;

    fwd_pkt.instr_depend_on_me = q_entry.instr_depend_on_me;
    fwd_pkt.is_translated = true;

    std::optional<champsim::demand_tlb_pattern_event_ref> new_pattern_event;
    const bool is_demand_data_load = is_l1d_name(NAME) && q_entry.type == access_type::LOAD && !q_entry.is_instr && !q_entry.prefetch_from_this;
    const bool is_cross_page_vberti_prefetch =
        is_l1d_name(NAME) && q_entry.type == access_type::PREFETCH && q_entry.prefetch_from_this
        && is_l1d_cross_page_prefetch_origin(fwd_pkt.translation_source);
    if (is_demand_data_load && !warmup && q_entry.demand_tlb_events.empty()) {
      new_pattern_event = champsim::demand_tlb_pattern_logger().next_event_ref(q_entry.cpu);
      if (new_pattern_event.has_value()) {
        fwd_pkt.demand_tlb_stage = champsim::demand_tlb_pattern_stage::L1_DTLB;
        fwd_pkt.demand_tlb_events = {*new_pattern_event};
      }
    }

    std::optional<champsim::vberti_tlb_pattern_event_ref> new_vberti_pattern_event;
    if (!warmup && q_entry.vberti_tlb_events.empty() && (is_demand_data_load || is_cross_page_vberti_prefetch)) {
      const auto event_type = is_demand_data_load ? champsim::vberti_tlb_pattern_event_type::DATA_DEMAND
                                                  : champsim::vberti_tlb_pattern_event_type::VBERTI_CP_PREFETCH;
      new_vberti_pattern_event = champsim::vberti_cross_page_demand_pattern_logger().next_event_ref(q_entry.cpu, event_type);
      if (new_vberti_pattern_event.has_value()) {
        fwd_pkt.vberti_tlb_stage = champsim::vberti_tlb_pattern_stage::L1_DTLB;
        fwd_pkt.vberti_tlb_events = {*new_vberti_pattern_event};
      }
    }

    q_entry.translate_issued = lower_translate->add_rq(fwd_pkt);
    if (q_entry.translate_issued && new_pattern_event.has_value()) {
      q_entry.demand_tlb_stage = champsim::demand_tlb_pattern_stage::L1_DTLB;
      q_entry.demand_tlb_events = {*new_pattern_event};
      champsim::demand_tlb_pattern_event_start start;
      start.cpu = q_entry.cpu;
      start.instr_id = q_entry.instr_id;
      start.operand_index = q_entry.demand_tlb_operand_index;
      start.pc = q_entry.ip.to<uint64_t>();
      start.va = q_entry.v_address.to<uint64_t>();
      start.dtlb_lookup_cycle = static_cast<uint64_t>(current_time.time_since_epoch() / clock_period);
      champsim::demand_tlb_pattern_logger().create_event(*new_pattern_event, start);
    }
    if (q_entry.translate_issued && new_vberti_pattern_event.has_value()) {
      q_entry.vberti_tlb_stage = champsim::vberti_tlb_pattern_stage::L1_DTLB;
      q_entry.vberti_tlb_events = {*new_vberti_pattern_event};
      champsim::vberti_tlb_pattern_event_start start;
      start.cpu = q_entry.cpu;
      start.instr_id = q_entry.instr_id;
      start.operand_index = q_entry.demand_tlb_operand_index;
      start.pc = q_entry.ip.to<uint64_t>();
      start.va = q_entry.v_address.to<uint64_t>();
      start.dtlb_lookup_cycle = static_cast<uint64_t>(current_time.time_since_epoch() / clock_period);
      start.vberti_prefetch_seq = q_entry.has_l1d_prefetch_seq ? q_entry.l1d_prefetch_seq : 0;
      champsim::vberti_cross_page_demand_pattern_logger().create_event(*new_vberti_pattern_event, start);
    }
    if constexpr (champsim::debug_print) {
      if (q_entry.translate_issued) {
        fmt::print("[TRANSLATE] do_issue_translation instr_id: {} paddr: {} vaddr: {} type: {}\n", q_entry.instr_id, q_entry.address, q_entry.v_address,
                   access_type_names.at(champsim::to_underlying(q_entry.type)));
      }
    }
  }
}

bool CACHE::pqfull_tlb_rescue_can_issue() const
{
  if (!champsim::ordered_pqfull_tlb_rescue || lower_translate == nullptr || std::empty(pqfull_tlb_rescue_queue))
    return false;

  if (std::empty(internal_PQ))
    return true;

  auto oldest_pq_seq = std::numeric_limits<uint64_t>::max();
  bool found_seq = false;
  for (const auto& entry : internal_PQ) {
    if (entry.has_l1d_prefetch_seq) {
      oldest_pq_seq = std::min(oldest_pq_seq, entry.l1d_prefetch_seq);
      found_seq = true;
    } else {
      return false;
    }
  }

  return found_seq && pqfull_tlb_rescue_queue.front().l1d_prefetch_seq < oldest_pq_seq;
}

long CACHE::issue_pqfull_tlb_rescue()
{
  if (!pqfull_tlb_rescue_can_issue())
    return 0;

  auto entry = pqfull_tlb_rescue_queue.front();
  issue_translation(entry);
  if (!entry.translate_issued)
    return 0;

  pqfull_tlb_rescue_queue.pop_front();
  pqfull_tlb_rescue_inflight.push_back(entry);
  ++sim_stats.cp_pf_pqfull_tlb_rescue_issued;
  return 1;
}

translation_origin CACHE::classify_translation_origin(const tag_lookup_type& q_entry) const
{
  if (q_entry.type == access_type::PREFETCH && q_entry.prefetch_from_this) {
    if (NAME.size() >= 4 && NAME.compare(NAME.size() - 4, 4, "_L1D") == 0) {
      if (is_l1d_pref_meta(q_entry.pf_metadata))
        return is_l1d_pref_cross(q_entry.pf_metadata) ? translation_origin::L1D_PREFETCH_CROSS_PAGE : translation_origin::L1D_PREFETCH_SAME_PAGE;
      return translation_origin::L1D_PREFETCH;
    }
    if (NAME.size() >= 4 && NAME.compare(NAME.size() - 4, 4, "_L1I") == 0)
      return translation_origin::L1I_PREFETCH;
    return translation_origin::OTHER;
  }

  if (q_entry.type == access_type::PREFETCH)
    return q_entry.translation_source;

  return q_entry.is_instr ? translation_origin::DEMAND_INSTRUCTION : translation_origin::DEMAND_DATA;
}

bool CACHE::is_dtlb() const { return NAME.size() >= 5 && NAME.compare(NAME.size() - 5, 5, "_DTLB") == 0; }

bool CACHE::is_stlb() const { return NAME.size() >= 5 && NAME.compare(NAME.size() - 5, 5, "_STLB") == 0; }

bool CACHE::is_tlb() const { return is_dtlb() || is_stlb(); }

bool CACHE::should_redirect_stlb_cp_pb_fill(const mshr_type& fill_mshr) const
{
  return champsim::enable_stlb_cp_pb && is_stlb() && is_l1d_cross_page_prefetch_origin(fill_mshr.translation_source);
}

void CACHE::insert_stlb_cp_pb(const mshr_type& fill_mshr)
{
  const auto key = make_tlb_prefetch_key(fill_mshr.cpu, fill_mshr.v_address, fill_mshr.asid);
  stlb_cp_pb[key] = stlb_cp_pb_entry{fill_mshr.address, fill_mshr.v_address, fill_mshr.data_promise->data, fill_mshr.data_promise->pf_metadata,
                                     fill_mshr.cpu, {fill_mshr.asid[0], fill_mshr.asid[1]}, fill_mshr.tlb_ptw_prefetch_tracked,
                                     fill_mshr.tlb_ptw_prefetch_cpu, fill_mshr.tlb_ptw_prefetch_id};
  ++sim_stats.stlb_cp_pb_insert;
}

void CACHE::fill_stlb_from_cp_pb(const tag_lookup_type& handle_pkt, const stlb_cp_pb_entry& entry)
{
  auto [set_begin, set_end] = get_set_span(handle_pkt.address);
  auto way = std::find_if_not(set_begin, set_end, [](auto x) { return x.valid; });
  if (way == set_end) {
    way = std::next(set_begin, impl_find_victim(handle_pkt.cpu, handle_pkt.instr_id, get_set_index(handle_pkt.address), &*set_begin, handle_pkt.ip,
                                                handle_pkt.address, handle_pkt.type));
  }

  assert(set_begin <= way);
  assert(way < set_end);
  const auto way_idx = std::distance(set_begin, way);

  discard_pollution_candidate(prefetch_pollution_shadow, make_prefetch_pollution_key(handle_pkt.cpu, handle_pkt.address));
  discard_pollution_candidate(tlb_cross_prefetch_pollution_shadow, make_tlb_prefetch_key(handle_pkt));

  champsim::address evicting_address{};
  if (way->valid) {
    evicting_address = module_address(*way);

    if (way->prefetch) {
      remember_prefetch_too_early_candidate(*way, way->cpu);
      ++sim_stats.pf_useless;
    }
    record_tlb_ptw_system_eviction(*way);
    record_tlb_cross_prefetch_eviction(*way, way->cpu);
  }

  mshr_type fill_mshr{handle_pkt, current_time};
  fill_mshr.data_promise = champsim::waitable{mshr_type::returned_value{entry.data, handle_pkt.pf_metadata}, current_time};
  fill_mshr.tlb_ptw_prefetch_tracked = entry.tlb_ptw_prefetch_tracked;
  fill_mshr.tlb_ptw_prefetch_cpu = entry.tlb_ptw_prefetch_cpu;
  fill_mshr.tlb_ptw_prefetch_id = entry.tlb_ptw_prefetch_id;

  uint32_t metadata_thru = handle_pkt.pf_metadata;
  if (!module_is_instr(fill_mshr)) {
    metadata_thru = impl_prefetcher_cache_fill(module_address(fill_mshr), get_set_index(fill_mshr.address), way_idx, false, evicting_address,
                                               handle_pkt.pf_metadata);
  }
  impl_replacement_cache_fill(fill_mshr.cpu, get_set_index(fill_mshr.address), way_idx, module_address(fill_mshr), fill_mshr.ip, evicting_address,
                              fill_mshr.type);

  *way = fill_block(fill_mshr, metadata_thru);
  sim_stats.tlb_origin_fills.increment(std::pair{fill_mshr.translation_source, fill_mshr.cpu});
  record_tlb_ptw_system_fill(fill_mshr, *way);
  if (entry.tlb_ptw_prefetch_tracked)
    champsim::tlb_ptw_system::mark_useful(entry.tlb_ptw_prefetch_cpu, entry.tlb_ptw_prefetch_id, false);
}

bool CACHE::try_stlb_cp_pb_demand_hit(const tag_lookup_type& handle_pkt)
{
  if (!champsim::enable_stlb_cp_pb || !is_stlb() || !is_data_demand_origin(handle_pkt.translation_source))
    return false;

  auto found = stlb_cp_pb.find(make_tlb_prefetch_key(handle_pkt));
  if (found == std::end(stlb_cp_pb))
    return false;

  const auto entry = found->second;
  stlb_cp_pb.erase(found);

  ++sim_stats.stlb_cp_pb_raw_demand_miss;
  ++sim_stats.stlb_cp_pb_demand_hit;

  sim_stats.misses.increment(std::pair{handle_pkt.type, handle_pkt.cpu});
  if (consume_prefetch_too_early_candidate(handle_pkt))
    ++sim_stats.pf_too_early;
  const auto [polluted_by_prefetch, polluted_victim_was_demand] = consume_prefetch_pollution_candidate(handle_pkt);
  if (polluted_by_prefetch)
    ++sim_stats.pf_pollution_evict;
  if (polluted_victim_was_demand)
    ++sim_stats.pf_pollution_demand;
  record_tlb_cross_prefetch_miss(handle_pkt, false);
  record_tlb_origin_miss(handle_pkt);
  champsim::instrumentation::record_stlb_vpn_miss(NAME, warmup, current_time, clock_period, handle_pkt.ip, handle_pkt.v_address, handle_pkt.instr_id,
                                                  handle_pkt.cpu, handle_pkt.type, handle_pkt.translation_source, handle_pkt.prefetch_from_this,
                                                  handle_pkt.is_instr);

  fill_stlb_from_cp_pb(handle_pkt, entry);

  response_type response{handle_pkt.address, handle_pkt.v_address, entry.data, handle_pkt.pf_metadata, handle_pkt.instr_depend_on_me};
  response.tlb_ptw_prefetch_tracked = entry.tlb_ptw_prefetch_tracked;
  response.tlb_ptw_prefetch_cpu = entry.tlb_ptw_prefetch_cpu;
  response.tlb_ptw_prefetch_id = entry.tlb_ptw_prefetch_id;
  for (auto* ret : handle_pkt.to_return) {
    ret->push_back(response);
  }

  return true;
}

std::size_t CACHE::too_early_shadow_size() const
{
  return static_cast<std::size_t>(NUM_SET) * static_cast<std::size_t>(NUM_WAY);
}

CACHE::prefetch_too_early_key CACHE::make_prefetch_too_early_key(uint32_t pkt_cpu, champsim::address address) const
{
  return {pkt_cpu, address.slice_upper(OFFSET_BITS).to<uint64_t>()};
}

CACHE::prefetch_pollution_key CACHE::make_prefetch_pollution_key(uint32_t pkt_cpu, champsim::address address) const
{
  return {pkt_cpu, address.slice_upper(OFFSET_BITS).to<uint64_t>()};
}

CACHE::tlb_prefetch_key CACHE::make_tlb_prefetch_key(const tag_lookup_type& pkt) const
{
  return make_tlb_prefetch_key(pkt.cpu, pkt.v_address, pkt.asid);
}

CACHE::tlb_prefetch_key CACHE::make_tlb_prefetch_key(uint32_t pkt_cpu, champsim::address v_address, const uint8_t asid[2]) const
{
  return {pkt_cpu, champsim::page_number{v_address}.to<uint64_t>(), asid[0], asid[1]};
}

void CACHE::remember_prefetch_too_early_candidate(const BLOCK& victim, uint32_t victim_cpu)
{
  remember_shadow_candidate(prefetch_too_early_fifo, prefetch_too_early_shadow, make_prefetch_too_early_key(victim_cpu, victim.address),
                            too_early_shadow_size());
}

bool CACHE::consume_prefetch_too_early_candidate(const tag_lookup_type& handle_pkt)
{
  if (!is_cache_demand_type(handle_pkt.type))
    return false;

  return erase_shadow_candidate(prefetch_too_early_shadow, make_prefetch_too_early_key(handle_pkt.cpu, handle_pkt.address));
}

void CACHE::discard_prefetch_too_early_candidate(const tag_lookup_type& handle_pkt)
{
  if (!is_cache_demand_type(handle_pkt.type))
    return;

  erase_shadow_candidate(prefetch_too_early_shadow, make_prefetch_too_early_key(handle_pkt.cpu, handle_pkt.address));
}

void CACHE::remember_prefetch_pollution_candidate(const BLOCK& victim, uint32_t victim_cpu)
{
  remember_pollution_candidate(prefetch_pollution_fifo, prefetch_pollution_shadow, prefetch_pollution_next_id,
                               make_prefetch_pollution_key(victim_cpu, victim.address), !victim.prefetch, too_early_shadow_size());
}

std::pair<bool, bool> CACHE::consume_prefetch_pollution_candidate(const tag_lookup_type& handle_pkt)
{
  if (!is_cache_demand_type(handle_pkt.type))
    return {false, false};

  return consume_pollution_candidate(prefetch_pollution_shadow, make_prefetch_pollution_key(handle_pkt.cpu, handle_pkt.address));
}

void CACHE::discard_prefetch_pollution_candidate(const tag_lookup_type& handle_pkt)
{
  if (!is_cache_demand_type(handle_pkt.type))
    return;

  discard_pollution_candidate(prefetch_pollution_shadow, make_prefetch_pollution_key(handle_pkt.cpu, handle_pkt.address));
}

void CACHE::remember_tlb_cross_prefetch_too_early_candidate(const BLOCK& victim, uint32_t victim_cpu)
{
  remember_shadow_candidate(tlb_cross_prefetch_too_early_fifo, tlb_cross_prefetch_too_early_shadow,
                            make_tlb_prefetch_key(victim_cpu, victim.v_address, victim.asid), too_early_shadow_size());
}

bool CACHE::consume_tlb_cross_prefetch_too_early_candidate(const tag_lookup_type& handle_pkt)
{
  if (!is_tlb() || !is_demand_origin(handle_pkt.translation_source))
    return false;

  return erase_shadow_candidate(tlb_cross_prefetch_too_early_shadow, make_tlb_prefetch_key(handle_pkt));
}

void CACHE::discard_tlb_cross_prefetch_too_early_candidate(const tag_lookup_type& handle_pkt)
{
  if (!is_tlb() || !is_demand_origin(handle_pkt.translation_source))
    return;

  erase_shadow_candidate(tlb_cross_prefetch_too_early_shadow, make_tlb_prefetch_key(handle_pkt));
}

void CACHE::remember_tlb_cross_prefetch_pollution_candidate(const BLOCK& victim, uint32_t victim_cpu)
{
  remember_pollution_candidate(tlb_cross_prefetch_pollution_fifo, tlb_cross_prefetch_pollution_shadow, tlb_cross_prefetch_pollution_next_id,
                               make_tlb_prefetch_key(victim_cpu, victim.v_address, victim.asid), is_demand_origin(victim.translation_source),
                               too_early_shadow_size());
}

std::pair<bool, bool> CACHE::consume_tlb_cross_prefetch_pollution_candidate(const tag_lookup_type& handle_pkt)
{
  if (!is_tlb() || !is_demand_origin(handle_pkt.translation_source))
    return {false, false};

  return consume_pollution_candidate(tlb_cross_prefetch_pollution_shadow, make_tlb_prefetch_key(handle_pkt));
}

void CACHE::discard_tlb_cross_prefetch_pollution_candidate(const tag_lookup_type& handle_pkt)
{
  if (!is_tlb() || !is_demand_origin(handle_pkt.translation_source))
    return;

  discard_pollution_candidate(tlb_cross_prefetch_pollution_shadow, make_tlb_prefetch_key(handle_pkt));
}

void CACHE::record_tlb_origin_hit(const tag_lookup_type& handle_pkt)
{
  discard_tlb_cross_prefetch_too_early_candidate(handle_pkt);
  discard_tlb_cross_prefetch_pollution_candidate(handle_pkt);
  if (is_dtlb() && is_demand_origin(handle_pkt.translation_source))
    discard_tlb_system_too_early(make_tlb_system_key(handle_pkt.cpu, handle_pkt.v_address, handle_pkt.asid));

  if (is_dtlb())
    sim_stats.dtlb_origin_hits.increment(std::pair{handle_pkt.translation_source, handle_pkt.cpu});
  if (is_stlb())
    sim_stats.stlb_origin_hits.increment(std::pair{handle_pkt.translation_source, handle_pkt.cpu});

  if (is_tlb() && is_l1d_cross_page_prefetch_origin(handle_pkt.translation_source))
    ++sim_stats.tlb_cross_prefetch_issued;
  if (is_dtlb() && is_l1d_cross_page_prefetch_origin(handle_pkt.translation_source))
    ++sim_stats.tlb_system_cross_prefetch_issued;
}

void CACHE::record_tlb_origin_miss(const tag_lookup_type& handle_pkt)
{
  if (is_dtlb())
    sim_stats.dtlb_origin_misses.increment(std::pair{handle_pkt.translation_source, handle_pkt.cpu});
  if (is_stlb())
    sim_stats.stlb_origin_misses.increment(std::pair{handle_pkt.translation_source, handle_pkt.cpu});

  if (is_tlb() && is_l1d_cross_page_prefetch_origin(handle_pkt.translation_source))
    ++sim_stats.tlb_cross_prefetch_issued;
  if (is_dtlb() && is_l1d_cross_page_prefetch_origin(handle_pkt.translation_source))
    ++sim_stats.tlb_system_cross_prefetch_issued;
}

bool CACHE::record_tlb_cross_prefetch_fill(const mshr_type& fill_mshr)
{
  if (!is_tlb() || !is_l1d_cross_page_prefetch_origin(fill_mshr.translation_source))
    return false;

  const auto key = make_tlb_system_key(fill_mshr.cpu, fill_mshr.v_address, fill_mshr.asid);
  auto local_key = tlb_prefetch_key{fill_mshr.cpu, champsim::page_number{fill_mshr.v_address}.to<uint64_t>(), fill_mshr.asid[0], fill_mshr.asid[1]};
  auto found = tlb_cross_prefetch_pending.find(local_key);
  if (found == std::end(tlb_cross_prefetch_pending) || found->second == 0)
    return false;

  --found->second;
  if (found->second == 0)
    tlb_cross_prefetch_pending.erase(found);

  if (is_dtlb())
    mark_tlb_system_active(key);
  return true;
}

void CACHE::record_tlb_cross_prefetch_eviction(const BLOCK& victim, uint32_t victim_cpu)
{
  if (!is_tlb() || !victim.tlb_cross_prefetch || victim.tlb_cross_prefetch_used)
    return;

  remember_tlb_cross_prefetch_too_early_candidate(victim, victim_cpu);
  ++sim_stats.tlb_cross_prefetch_useless;
  if (mark_tlb_system_eviction(make_tlb_system_key(victim_cpu, victim.v_address, victim.asid), too_early_shadow_size()))
    ++sim_stats.tlb_system_cross_prefetch_useless;
}

void CACHE::record_tlb_cross_prefetch_hit(const tag_lookup_type& handle_pkt, BLOCK& way)
{
  if (!is_tlb() || !is_demand_origin(handle_pkt.translation_source) || !way.tlb_cross_prefetch || way.tlb_cross_prefetch_used)
    return;

  way.tlb_cross_prefetch_used = true;
  ++sim_stats.tlb_cross_prefetch_useful;
  if (mark_tlb_system_useful(make_tlb_system_key(handle_pkt.cpu, handle_pkt.v_address, handle_pkt.asid)))
    ++sim_stats.tlb_system_cross_prefetch_useful;
}

void CACHE::record_tlb_ptw_system_fill(const mshr_type& fill_mshr, BLOCK& way)
{
  if (!is_tlb() || !fill_mshr.tlb_ptw_prefetch_tracked) {
    way.tlb_ptw_prefetch_tracked = false;
    return;
  }

  const auto level = is_dtlb() ? champsim::tlb_ptw_system::residency_level::dtlb : champsim::tlb_ptw_system::residency_level::stlb;
  const bool tracked = champsim::tlb_ptw_system::mark_fill(fill_mshr.tlb_ptw_prefetch_cpu, fill_mshr.tlb_ptw_prefetch_id, level);
  way.tlb_ptw_prefetch_tracked = tracked;
  if (tracked) {
    way.tlb_ptw_prefetch_cpu = fill_mshr.tlb_ptw_prefetch_cpu;
    way.tlb_ptw_prefetch_id = fill_mshr.tlb_ptw_prefetch_id;
  }
}

void CACHE::record_tlb_ptw_system_eviction(const BLOCK& victim)
{
  if (!is_tlb() || !victim.tlb_ptw_prefetch_tracked)
    return;

  const auto level = is_dtlb() ? champsim::tlb_ptw_system::residency_level::dtlb : champsim::tlb_ptw_system::residency_level::stlb;
  champsim::tlb_ptw_system::mark_eviction(victim.tlb_ptw_prefetch_cpu, victim.tlb_ptw_prefetch_id, level);
}

void CACHE::record_tlb_ptw_system_hit(const tag_lookup_type& handle_pkt, const BLOCK& way)
{
  if (!is_tlb() || !is_demand_origin(handle_pkt.translation_source) || !way.tlb_ptw_prefetch_tracked)
    return;

  champsim::tlb_ptw_system::mark_useful(way.tlb_ptw_prefetch_cpu, way.tlb_ptw_prefetch_id, false);
}

void CACHE::record_tlb_cross_prefetch_miss(const tag_lookup_type& handle_pkt, bool new_mshr)
{
  if (!is_tlb())
    return;

  const auto local_key = make_tlb_prefetch_key(handle_pkt);
  const auto system_key = make_tlb_system_key(handle_pkt.cpu, handle_pkt.v_address, handle_pkt.asid);
  if (is_demand_origin(handle_pkt.translation_source)) {
    bool counted_late = false;
    auto pending = tlb_cross_prefetch_pending.find(local_key);
    if (pending != std::end(tlb_cross_prefetch_pending) && pending->second > 0) {
      ++sim_stats.tlb_cross_prefetch_useful;
      ++sim_stats.tlb_cross_prefetch_late;
      counted_late = true;
      pending->second = 0;
      tlb_cross_prefetch_pending.erase(pending);
    }
    if (!counted_late && consume_tlb_cross_prefetch_too_early_candidate(handle_pkt))
      ++sim_stats.tlb_cross_prefetch_too_early;

    const auto [polluted_by_cross_prefetch, polluted_victim_was_demand] = consume_tlb_cross_prefetch_pollution_candidate(handle_pkt);
    if (polluted_by_cross_prefetch)
      ++sim_stats.tlb_cross_prefetch_pollution_evict;
    if (polluted_victim_was_demand)
      ++sim_stats.tlb_cross_prefetch_pollution_demand;

    bool counted_system_late = false;
    if (is_dtlb() && mark_tlb_system_late(system_key)) {
      ++sim_stats.tlb_system_cross_prefetch_useful;
      ++sim_stats.tlb_system_cross_prefetch_late;
      counted_system_late = true;
    }
    if (is_dtlb() && !counted_system_late && consume_tlb_system_too_early(system_key))
      ++sim_stats.tlb_system_cross_prefetch_too_early;
    return;
  }

  if (is_l1d_cross_page_prefetch_origin(handle_pkt.translation_source) && new_mshr) {
    ++tlb_cross_prefetch_pending[local_key];
    if (is_dtlb())
      mark_tlb_system_pending(system_key);
  }
}

void CACHE::finalize_tlb_cross_prefetch_stats()
{
  if (!is_tlb())
    return;

  sim_stats.tlb_cross_prefetch_useless += std::accumulate(std::begin(tlb_cross_prefetch_pending), std::end(tlb_cross_prefetch_pending), uint64_t{0},
                                                          [](uint64_t acc, const auto& entry) { return acc + entry.second; });
  tlb_cross_prefetch_pending.clear();
  tlb_cross_prefetch_too_early_fifo.clear();
  tlb_cross_prefetch_too_early_shadow.clear();

  for (const auto& way : block)
    if (way.valid && way.tlb_cross_prefetch && !way.tlb_cross_prefetch_used)
      ++sim_stats.tlb_cross_prefetch_useless;

  if (!tlb_system_cross_prefetch_finalized)
    sim_stats.tlb_system_cross_prefetch_useless += finalize_tlb_system_cross_prefetch_state();
}

std::size_t CACHE::get_mshr_occupancy() const { return std::size(MSHR); }

std::vector<std::size_t> CACHE::get_rq_occupancy() const
{
  std::vector<std::size_t> retval;
  std::transform(std::begin(upper_levels), std::end(upper_levels), std::back_inserter(retval), [](auto ulptr) { return ulptr->rq_occupancy(); });
  return retval;
}

std::vector<std::size_t> CACHE::get_wq_occupancy() const
{
  std::vector<std::size_t> retval;
  std::transform(std::begin(upper_levels), std::end(upper_levels), std::back_inserter(retval), [](auto ulptr) { return ulptr->wq_occupancy(); });
  return retval;
}

std::vector<std::size_t> CACHE::get_pq_occupancy() const
{
  std::vector<std::size_t> retval;
  std::transform(std::begin(upper_levels), std::end(upper_levels), std::back_inserter(retval), [](auto ulptr) { return ulptr->pq_occupancy(); });
  retval.push_back(std::size(internal_PQ));
  return retval;
}

// LCOV_EXCL_START exclude deprecated function
std::size_t CACHE::get_occupancy(uint8_t queue_type, uint64_t /*deprecated*/) const
{
  if (queue_type == 0) {
    return get_mshr_occupancy();
  }
  return 0;
}

std::size_t CACHE::get_occupancy(uint8_t queue_type, champsim::address /*deprecated*/) const
{
  if (queue_type == 0) {
    return get_mshr_occupancy();
  }
  return 0;
}
// LCOV_EXCL_STOP

std::size_t CACHE::get_mshr_size() const { return MSHR_SIZE; }
std::vector<std::size_t> CACHE::get_rq_size() const
{
  std::vector<std::size_t> retval;
  std::transform(std::begin(upper_levels), std::end(upper_levels), std::back_inserter(retval), [](auto ulptr) { return ulptr->rq_size(); });
  return retval;
}

std::vector<std::size_t> CACHE::get_wq_size() const
{
  std::vector<std::size_t> retval;
  std::transform(std::begin(upper_levels), std::end(upper_levels), std::back_inserter(retval), [](auto ulptr) { return ulptr->wq_size(); });
  return retval;
}

std::vector<std::size_t> CACHE::get_pq_size() const
{
  std::vector<std::size_t> retval;
  std::transform(std::begin(upper_levels), std::end(upper_levels), std::back_inserter(retval), [](auto ulptr) { return ulptr->pq_size(); });
  retval.push_back(PQ_SIZE);
  return retval;
}

// LCOV_EXCL_START exclude deprecated function
std::size_t CACHE::get_size(uint8_t queue_type, champsim::address /*deprecated*/) const
{
  if (queue_type == 0) {
    return get_mshr_size();
  }
  return 0;
}

std::size_t CACHE::get_size(uint8_t queue_type, uint64_t /*deprecated*/) const
{
  if (queue_type == 0) {
    return get_mshr_size();
  }
  return 0;
}
// LCOV_EXCL_STOP

namespace
{
double occupancy_ratio(std::size_t occ, std::size_t sz) { return std::ceil(occ) / std::ceil(sz); }

std::vector<double> occupancy_ratio_vec(std::vector<std::size_t> occ, std::vector<std::size_t> sz)
{
  std::vector<double> retval;
  std::transform(std::begin(occ), std::end(occ), std::begin(sz), std::back_inserter(retval), occupancy_ratio);
  return retval;
}
} // namespace

double CACHE::get_mshr_occupancy_ratio() const { return ::occupancy_ratio(get_mshr_occupancy(), get_mshr_size()); }

std::vector<double> CACHE::get_rq_occupancy_ratio() const { return ::occupancy_ratio_vec(get_rq_occupancy(), get_rq_size()); }

std::vector<double> CACHE::get_wq_occupancy_ratio() const { return ::occupancy_ratio_vec(get_wq_occupancy(), get_wq_size()); }

std::vector<double> CACHE::get_pq_occupancy_ratio() const { return ::occupancy_ratio_vec(get_pq_occupancy(), get_pq_size()); }

void CACHE::impl_prefetcher_initialize() const { pref_module_pimpl->impl_prefetcher_initialize(); }

uint32_t CACHE::impl_prefetcher_cache_operate(champsim::address addr, champsim::address ip, bool cache_hit, bool useful_prefetch, access_type type,
                                              uint32_t metadata_in) const
{
  return pref_module_pimpl->impl_prefetcher_cache_operate(addr, ip, cache_hit, useful_prefetch, type, metadata_in);
}

uint32_t CACHE::impl_prefetcher_cache_fill(champsim::address addr, long set, long way, bool prefetch, champsim::address evicted_addr,
                                           uint32_t metadata_in) const
{
  return pref_module_pimpl->impl_prefetcher_cache_fill(addr, set, way, prefetch, evicted_addr, metadata_in);
}

void CACHE::impl_prefetcher_cycle_operate() const { pref_module_pimpl->impl_prefetcher_cycle_operate(); }

void CACHE::impl_prefetcher_final_stats() const { pref_module_pimpl->impl_prefetcher_final_stats(); }

void CACHE::impl_prefetcher_branch_operate(champsim::address ip, uint8_t branch_type, champsim::address branch_target) const
{
  pref_module_pimpl->impl_prefetcher_branch_operate(ip, branch_type, branch_target);
}

void CACHE::impl_initialize_replacement() const { repl_module_pimpl->impl_initialize_replacement(); }

long CACHE::impl_find_victim(uint32_t triggering_cpu, uint64_t instr_id, long set, const BLOCK* current_set, champsim::address ip, champsim::address full_addr,
                             access_type type) const
{
  return repl_module_pimpl->impl_find_victim(triggering_cpu, instr_id, set, current_set, ip, full_addr, type);
}

void CACHE::impl_update_replacement_state(uint32_t triggering_cpu, long set, long way, champsim::address full_addr, champsim::address ip,
                                          champsim::address victim_addr, access_type type, bool hit) const
{
  repl_module_pimpl->impl_update_replacement_state(triggering_cpu, set, way, full_addr, ip, victim_addr, type, hit);
}

void CACHE::impl_replacement_cache_fill(uint32_t triggering_cpu, long set, long way, champsim::address full_addr, champsim::address ip,
                                        champsim::address victim_addr, access_type type) const
{
  repl_module_pimpl->impl_replacement_cache_fill(triggering_cpu, set, way, full_addr, ip, victim_addr, type);
}

void CACHE::impl_replacement_final_stats() const { repl_module_pimpl->impl_replacement_final_stats(); }

void CACHE::initialize()
{
  impl_prefetcher_initialize();
  impl_initialize_replacement();
}

void CACHE::begin_phase()
{
  if (is_tlb()) {
    if (is_stlb())
      champsim::tlb_ptw_system::reset(cpu);
    tlb_cross_prefetch_pending.clear();
    tlb_cross_prefetch_too_early_fifo.clear();
    tlb_cross_prefetch_too_early_shadow.clear();
    tlb_cross_prefetch_pollution_fifo.clear();
    tlb_cross_prefetch_pollution_shadow.clear();
    tlb_cross_prefetch_pollution_next_id = 0;
    stlb_cp_pb.clear();
    reset_tlb_system_cross_prefetch_state();
    for (auto& way : block) {
      way.tlb_cross_prefetch = false;
      way.tlb_cross_prefetch_used = false;
      way.tlb_ptw_prefetch_tracked = false;
    }
  }
  prefetch_too_early_fifo.clear();
  prefetch_too_early_shadow.clear();
  prefetch_pollution_fifo.clear();
  prefetch_pollution_shadow.clear();
  prefetch_pollution_next_id = 0;
  pqfull_tlb_rescue_queue.clear();
  pqfull_tlb_rescue_inflight.clear();
  vberti_end_to_end_roi_started = false;

  stats_type new_roi_stats;
  stats_type new_sim_stats;

  new_roi_stats.name = NAME;
  new_sim_stats.name = NAME;

  roi_stats = new_roi_stats;
  sim_stats = new_sim_stats;

  for (auto* ul : upper_levels) {
    channel_type::stats_type ul_new_roi_stats;
    channel_type::stats_type ul_new_sim_stats;
    ul->roi_stats = ul_new_roi_stats;
    ul->sim_stats = ul_new_sim_stats;
  }
}

void CACHE::end_phase(unsigned finished_cpu)
{
  finished_cpu = finished_cpu;
  finalize_tlb_cross_prefetch_stats();
  roi_stats.total_miss_latency_cycles = sim_stats.total_miss_latency_cycles;

  roi_stats.hits = sim_stats.hits;
  roi_stats.misses = sim_stats.misses;
  roi_stats.mshr_merge = sim_stats.mshr_merge;
  roi_stats.mshr_return = sim_stats.mshr_return;
  roi_stats.stlb_origin_hits = sim_stats.stlb_origin_hits;
  roi_stats.stlb_origin_misses = sim_stats.stlb_origin_misses;
  roi_stats.dtlb_origin_hits = sim_stats.dtlb_origin_hits;
  roi_stats.dtlb_origin_misses = sim_stats.dtlb_origin_misses;
  roi_stats.tlb_origin_mshr_merge = sim_stats.tlb_origin_mshr_merge;
  roi_stats.tlb_origin_fills = sim_stats.tlb_origin_fills;

  roi_stats.pf_requested = sim_stats.pf_requested;
  roi_stats.pf_issued = sim_stats.pf_issued;
  roi_stats.pf_useful = sim_stats.pf_useful;
  roi_stats.pf_useless = sim_stats.pf_useless;
  roi_stats.pf_late = sim_stats.pf_late;
  roi_stats.pf_fill = sim_stats.pf_fill;
  roi_stats.pf_too_early = sim_stats.pf_too_early;
  roi_stats.pf_pollution_evict = sim_stats.pf_pollution_evict;
  roi_stats.pf_pollution_demand = sim_stats.pf_pollution_demand;
  roi_stats.vberti_prefetch_requested = sim_stats.vberti_prefetch_requested;
  roi_stats.vberti_cross_page_requested = sim_stats.vberti_cross_page_requested;
  roi_stats.vberti_prefetch_issued = sim_stats.vberti_prefetch_issued;
  roi_stats.vberti_cross_page_issued = sim_stats.vberti_cross_page_issued;
  roi_stats.cross_page_pf_translation_only_requested = sim_stats.cross_page_pf_translation_only_requested;
  roi_stats.cross_page_pf_translation_only_issued = sim_stats.cross_page_pf_translation_only_issued;
  roi_stats.cross_page_pf_translation_only_dropped = sim_stats.cross_page_pf_translation_only_dropped;
  roi_stats.cp_pf_pqfull_drop = sim_stats.cp_pf_pqfull_drop;
  roi_stats.cp_pf_pqfull_tlb_rescue_enqueued = sim_stats.cp_pf_pqfull_tlb_rescue_enqueued;
  roi_stats.cp_pf_pqfull_tlb_rescue_issued = sim_stats.cp_pf_pqfull_tlb_rescue_issued;
  roi_stats.cp_pf_pqfull_tlb_rescue_translated = sim_stats.cp_pf_pqfull_tlb_rescue_translated;
  roi_stats.tlb_cross_prefetch_issued = sim_stats.tlb_cross_prefetch_issued;
  roi_stats.tlb_cross_prefetch_useful = sim_stats.tlb_cross_prefetch_useful;
  roi_stats.tlb_cross_prefetch_useless = sim_stats.tlb_cross_prefetch_useless;
  roi_stats.tlb_cross_prefetch_late = sim_stats.tlb_cross_prefetch_late;
  roi_stats.tlb_cross_prefetch_too_early = sim_stats.tlb_cross_prefetch_too_early;
  roi_stats.tlb_cross_prefetch_pollution_evict = sim_stats.tlb_cross_prefetch_pollution_evict;
  roi_stats.tlb_cross_prefetch_pollution_demand = sim_stats.tlb_cross_prefetch_pollution_demand;
  roi_stats.tlb_system_cross_prefetch_issued = sim_stats.tlb_system_cross_prefetch_issued;
  roi_stats.tlb_system_cross_prefetch_useful = sim_stats.tlb_system_cross_prefetch_useful;
  roi_stats.tlb_system_cross_prefetch_useless = sim_stats.tlb_system_cross_prefetch_useless;
  roi_stats.tlb_system_cross_prefetch_late = sim_stats.tlb_system_cross_prefetch_late;
  roi_stats.tlb_system_cross_prefetch_too_early = sim_stats.tlb_system_cross_prefetch_too_early;
  roi_stats.stlb_cp_pb_raw_demand_miss = sim_stats.stlb_cp_pb_raw_demand_miss;
  roi_stats.stlb_cp_pb_insert = sim_stats.stlb_cp_pb_insert;
  roi_stats.stlb_cp_pb_demand_hit = sim_stats.stlb_cp_pb_demand_hit;
  roi_stats.stlb_cp_pb_demand_miss = sim_stats.stlb_cp_pb_demand_miss;

  for (auto* ul : upper_levels) {
    ul->roi_stats.RQ_ACCESS = ul->sim_stats.RQ_ACCESS;
    ul->roi_stats.RQ_MERGED = ul->sim_stats.RQ_MERGED;
    ul->roi_stats.RQ_FULL = ul->sim_stats.RQ_FULL;
    ul->roi_stats.RQ_TO_CACHE = ul->sim_stats.RQ_TO_CACHE;

    ul->roi_stats.PQ_ACCESS = ul->sim_stats.PQ_ACCESS;
    ul->roi_stats.PQ_MERGED = ul->sim_stats.PQ_MERGED;
    ul->roi_stats.PQ_FULL = ul->sim_stats.PQ_FULL;
    ul->roi_stats.PQ_TO_CACHE = ul->sim_stats.PQ_TO_CACHE;

    ul->roi_stats.WQ_ACCESS = ul->sim_stats.WQ_ACCESS;
    ul->roi_stats.WQ_MERGED = ul->sim_stats.WQ_MERGED;
    ul->roi_stats.WQ_FULL = ul->sim_stats.WQ_FULL;
    ul->roi_stats.WQ_TO_CACHE = ul->sim_stats.WQ_TO_CACHE;
    ul->roi_stats.WQ_FORWARD = ul->sim_stats.WQ_FORWARD;
  }
}

template <typename T>
bool CACHE::should_activate_prefetcher(const T& pkt) const
{
  return !pkt.prefetch_from_this && std::count(std::begin(pref_activate_mask), std::end(pref_activate_mask), pkt.type) > 0;
}

// LCOV_EXCL_START Exclude the following function from LCOV
void CACHE::print_deadlock()
{
  std::string_view mshr_write{"instr_id: {} address: {} v_addr: {} type: {} ready: {}"};
  auto mshr_pack = [time = current_time](const auto& entry) {
    return std::tuple{entry.instr_id, entry.address, entry.v_address, access_type_names.at(champsim::to_underlying(entry.type)),
                      entry.data_promise.is_ready_at(time)};
  };

  std::string_view tag_check_write{"instr_id: {} address: {} v_addr: {} is_translated: {} translate_issued: {} event_cycle: {}"};
  auto tag_check_pack = [period = clock_period](const auto& entry) {
    return std::tuple{entry.instr_id,      entry.address,          entry.v_address,
                      entry.is_translated, entry.translate_issued, entry.event_cycle.time_since_epoch() / period};
  };

  champsim::range_print_deadlock(MSHR, NAME + "_MSHR", mshr_write, mshr_pack);
  champsim::range_print_deadlock(inflight_tag_check, NAME + "_tags", tag_check_write, tag_check_pack);
  champsim::range_print_deadlock(translation_stash, NAME + "_translation", tag_check_write, tag_check_pack);

  std::string_view q_writer{"instr_id: {} address: {} v_addr: {} type: {} translated: {}"};
  auto q_entry_pack = [](const auto& entry) {
    return std::tuple{entry.instr_id, entry.address, entry.v_address, access_type_names.at(champsim::to_underlying(entry.type)), entry.is_translated};
  };

  for (auto* ul : upper_levels) {
    champsim::range_print_deadlock(ul->RQ, NAME + "_RQ", q_writer, q_entry_pack);
    champsim::range_print_deadlock(ul->WQ, NAME + "_WQ", q_writer, q_entry_pack);
    champsim::range_print_deadlock(ul->PQ, NAME + "_PQ", q_writer, q_entry_pack);
  }
}
// LCOV_EXCL_STOP
