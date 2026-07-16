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

#ifndef CACHE_H
#define CACHE_H

#ifdef CHAMPSIM_MODULE
#define SET_ASIDE_CHAMPSIM_MODULE
#undef CHAMPSIM_MODULE
#endif

#include <array>
#include <cstddef> // for size_t
#include <cstdint> // for uint64_t, uint32_t, uint8_t
#include <cstdlib>
#include <cxxabi.h>
#include <deque>
#include <iterator> // for size
#include <limits>   // for numeric_limits
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <type_traits>
#include <typeinfo>
#include <vector>

#include "address.h"
#include "bandwidth.h"
#include "block.h"
#include "cache_builder.h"
#include "cache_stats.h"
#include "champsim.h"
#include "channel.h"
#include "chrono.h"
#include "modules.h"
#include "operable.h"
#include "util/to_underlying.h" // for to_underlying
#include "waitable.h"

class CACHE : public champsim::operable
{
  enum [[deprecated(
      "Prefetchers may not specify arbitrary fill levels. Use CACHE::prefetch_line(pf_addr, fill_this_level, prefetch_metadata) instead.")]] FILL_LEVEL {
    FILL_L1 = 1,
    FILL_L2 = 2,
    FILL_LLC = 4,
    FILL_DRC = 8,
    FILL_DRAM = 16
  };

  using channel_type = champsim::channel;
  using request_type = typename channel_type::request_type;
  using response_type = typename channel_type::response_type;

  struct tag_lookup_type {
    champsim::address address;
    champsim::address v_address;
    champsim::address data;
    champsim::address ip;
    uint64_t instr_id;

    uint32_t pf_metadata;
    uint32_t cpu;
    uint32_t demand_tlb_operand_index = std::numeric_limits<uint32_t>::max();
    champsim::demand_tlb_pattern_stage demand_tlb_stage = champsim::demand_tlb_pattern_stage::NONE;
    std::vector<champsim::demand_tlb_pattern_event_ref> demand_tlb_events{};
    std::vector<champsim::demand_tlb_pattern_event_ref> demand_tlb_coalesced_events{};
    champsim::vberti_tlb_pattern_stage vberti_tlb_stage = champsim::vberti_tlb_pattern_stage::NONE;
    std::vector<champsim::vberti_tlb_pattern_event_ref> vberti_tlb_events{};
    std::vector<champsim::vberti_tlb_pattern_event_ref> vberti_tlb_coalesced_events{};

    access_type type;
    translation_origin translation_source = translation_origin::OTHER;
    bool prefetch_from_this;
    bool skip_fill;
    bool is_translated;
    bool translate_issued = false;
    bool is_instr = false;
    bool has_l1d_prefetch_seq = false;
    bool translation_only_rescue = false;
    uint64_t l1d_prefetch_seq = 0;
    bool vberti_end_to_end_tracked = false;
    uint32_t vberti_end_to_end_cpu = std::numeric_limits<uint32_t>::max();
    uint64_t vberti_end_to_end_id = 0;

    bool tlb_ptw_prefetch_tracked = false;
    bool tlb_ptw_real_demand_waiting = false;
    uint32_t tlb_ptw_prefetch_cpu = std::numeric_limits<uint32_t>::max();
    uint64_t tlb_ptw_prefetch_id = 0;

    bool stlb_prefetch_tracked = false;
    bool stlb_prefetch_used = false;

    uint8_t asid[2] = {std::numeric_limits<uint8_t>::max(), std::numeric_limits<uint8_t>::max()};

    champsim::chrono::clock::time_point event_cycle = champsim::chrono::clock::time_point::max();

    std::vector<uint64_t> instr_depend_on_me{};
    std::vector<std::shared_ptr<bool>> ptw_dram_touched_flags{};
    std::vector<std::deque<response_type>*> to_return{};

    explicit tag_lookup_type(request_type req) : tag_lookup_type(req, false, false) {}
    tag_lookup_type(const request_type& req, bool local_pref, bool skip);
  };

public:
  struct mshr_type {
    champsim::address address;
    champsim::address v_address;
    champsim::address ip;
    uint64_t instr_id;

    struct returned_value {
      champsim::address data;
      uint32_t pf_metadata;
    };
    champsim::waitable<returned_value> data_promise{};
    uint32_t cpu;

    access_type type;
    translation_origin translation_source = translation_origin::OTHER;
    bool prefetch_from_this;
    bool is_instr = false;
    bool vberti_end_to_end_tracked = false;
    uint32_t vberti_end_to_end_cpu = std::numeric_limits<uint32_t>::max();
    uint64_t vberti_end_to_end_id = 0;

    bool tlb_ptw_prefetch_tracked = false;
    bool tlb_ptw_real_demand_waiting = false;
    uint32_t tlb_ptw_prefetch_cpu = std::numeric_limits<uint32_t>::max();
    uint64_t tlb_ptw_prefetch_id = 0;

    bool stlb_prefetch_tracked = false;
    bool stlb_prefetch_used = false;

    uint8_t asid[2] = {std::numeric_limits<uint8_t>::max(), std::numeric_limits<uint8_t>::max()};

    champsim::chrono::clock::time_point time_enqueued;

    std::vector<uint64_t> instr_depend_on_me{};
    std::vector<std::shared_ptr<bool>> ptw_dram_touched_flags{};
    std::vector<std::deque<response_type>*> to_return{};

    mshr_type(const tag_lookup_type& req, champsim::chrono::clock::time_point _time_enqueued);
    static mshr_type merge(mshr_type predecessor, mshr_type successor);
  };

private:
  struct tlb_prefetch_key {
    uint32_t cpu = 0;
    uint64_t vpn = 0;
    uint8_t asid0 = std::numeric_limits<uint8_t>::max();
    uint8_t asid1 = std::numeric_limits<uint8_t>::max();

    bool operator<(const tlb_prefetch_key& other) const
    {
      return std::tie(cpu, vpn, asid0, asid1) < std::tie(other.cpu, other.vpn, other.asid0, other.asid1);
    }

    bool operator==(const tlb_prefetch_key& other) const
    {
      return cpu == other.cpu && vpn == other.vpn && asid0 == other.asid0 && asid1 == other.asid1;
    }
  };

  struct stlb_cp_pb_entry {
    champsim::address address{};
    champsim::address v_address{};
    champsim::address data{};
    uint32_t pf_metadata = 0;
    uint32_t cpu = 0;
    uint8_t asid[2] = {std::numeric_limits<uint8_t>::max(), std::numeric_limits<uint8_t>::max()};
    bool tlb_ptw_prefetch_tracked = false;
    uint32_t tlb_ptw_prefetch_cpu = std::numeric_limits<uint32_t>::max();
    uint64_t tlb_ptw_prefetch_id = 0;
  };

  struct stlb_prefetch_buffer_entry {
    champsim::address address{};
    champsim::address v_address{};
    champsim::address data{};
    uint32_t pf_metadata = 0;
    uint32_t cpu = 0;
    uint8_t asid[2] = {std::numeric_limits<uint8_t>::max(), std::numeric_limits<uint8_t>::max()};
    uint64_t generation = 0;
    bool stats_tracked = false;
  };

  struct stlb_prefetch_buffer_lookup {
    tag_lookup_type packet;
    std::optional<stlb_prefetch_buffer_entry> result{};
    champsim::chrono::clock::time_point ready_at = champsim::chrono::clock::time_point::max();
  };

  struct prefetch_too_early_key {
    uint32_t cpu = 0;
    uint64_t line = 0;

    bool operator<(const prefetch_too_early_key& other) const { return std::tie(cpu, line) < std::tie(other.cpu, other.line); }
  };

  struct prefetch_pollution_key {
    uint32_t cpu = 0;
    uint64_t line = 0;

    bool operator<(const prefetch_pollution_key& other) const { return std::tie(cpu, line) < std::tie(other.cpu, other.line); }
  };

  bool try_hit(const tag_lookup_type& handle_pkt);
  bool handle_fill(const mshr_type& fill_mshr);
  bool handle_miss(const tag_lookup_type& handle_pkt);
  bool handle_write(const tag_lookup_type& handle_pkt);
  void operate_stlb_prefetcher(const tag_lookup_type& handle_pkt, bool hit, bool useful_prefetch, bool prefetch_buffer_hit = false);
  void fill_stlb_prefetcher(const mshr_type& fill_mshr, long set, long way, champsim::address evicted_v_address);
  void finish_packet(const response_type& packet);
  void finish_translation(const response_type& packet);
  void finish_pqfull_tlb_rescue_translation(const response_type& packet);

  [[nodiscard]] bool should_drop_l1d_cross_page_translation_only(const tag_lookup_type& handle_pkt) const;
  std::size_t drop_translated_l1d_cross_page_translation_only(std::deque<tag_lookup_type>& queue);

  void issue_translation(tag_lookup_type& q_entry) const;
  [[nodiscard]] bool pqfull_tlb_rescue_can_issue() const;
  long issue_pqfull_tlb_rescue();
  [[nodiscard]] translation_origin classify_translation_origin(const tag_lookup_type& q_entry) const;
  [[nodiscard]] bool is_dtlb() const;
  [[nodiscard]] bool is_stlb() const;
  [[nodiscard]] bool is_tlb() const;
  [[nodiscard]] std::size_t too_early_shadow_size() const;
  [[nodiscard]] prefetch_too_early_key make_prefetch_too_early_key(uint32_t pkt_cpu, champsim::address address) const;
  [[nodiscard]] prefetch_pollution_key make_prefetch_pollution_key(uint32_t pkt_cpu, champsim::address address) const;
  [[nodiscard]] tlb_prefetch_key make_tlb_prefetch_key(const tag_lookup_type& pkt) const;
  [[nodiscard]] tlb_prefetch_key make_tlb_prefetch_key(uint32_t pkt_cpu, champsim::address v_address, const uint8_t asid[2]) const;
  void remember_prefetch_too_early_candidate(const champsim::cache_block& victim, uint32_t victim_cpu);
  bool consume_prefetch_too_early_candidate(const tag_lookup_type& handle_pkt);
  void discard_prefetch_too_early_candidate(const tag_lookup_type& handle_pkt);
  void remember_prefetch_pollution_candidate(const champsim::cache_block& victim, uint32_t victim_cpu);
  std::pair<bool, bool> consume_prefetch_pollution_candidate(const tag_lookup_type& handle_pkt);
  void discard_prefetch_pollution_candidate(const tag_lookup_type& handle_pkt);
  void remember_tlb_cross_prefetch_too_early_candidate(const champsim::cache_block& victim, uint32_t victim_cpu);
  bool consume_tlb_cross_prefetch_too_early_candidate(const tag_lookup_type& handle_pkt);
  void discard_tlb_cross_prefetch_too_early_candidate(const tag_lookup_type& handle_pkt);
  void remember_tlb_cross_prefetch_pollution_candidate(const champsim::cache_block& victim, uint32_t victim_cpu);
  std::pair<bool, bool> consume_tlb_cross_prefetch_pollution_candidate(const tag_lookup_type& handle_pkt);
  void discard_tlb_cross_prefetch_pollution_candidate(const tag_lookup_type& handle_pkt);
  void remember_stlb_prefetch_too_early_candidate(const champsim::cache_block& victim, uint32_t victim_cpu);
  bool consume_stlb_prefetch_too_early_candidate(const tag_lookup_type& handle_pkt);
  void discard_stlb_prefetch_too_early_candidate(const tag_lookup_type& handle_pkt);
  void remember_stlb_prefetch_pollution_candidate(const champsim::cache_block& victim, uint32_t victim_cpu);
  std::pair<bool, bool> consume_stlb_prefetch_pollution_candidate(const tag_lookup_type& handle_pkt);
  void discard_stlb_prefetch_pollution_candidate(const tag_lookup_type& handle_pkt);
  void record_tlb_origin_hit(const tag_lookup_type& handle_pkt);
  void record_tlb_origin_miss(const tag_lookup_type& handle_pkt);
  bool record_tlb_cross_prefetch_fill(const mshr_type& fill_mshr);
  void record_tlb_cross_prefetch_eviction(const champsim::cache_block& victim, uint32_t cpu);
  void record_tlb_cross_prefetch_hit(const tag_lookup_type& handle_pkt, champsim::cache_block& way);
  void record_tlb_cross_prefetch_miss(const tag_lookup_type& handle_pkt, bool new_mshr);
  void record_tlb_ptw_system_fill(const mshr_type& fill_mshr, champsim::cache_block& way);
  void record_tlb_ptw_system_eviction(const champsim::cache_block& victim);
  void record_tlb_ptw_system_hit(const tag_lookup_type& handle_pkt, const champsim::cache_block& way);
  void finalize_tlb_cross_prefetch_stats();
  [[nodiscard]] bool should_redirect_stlb_cp_pb_fill(const mshr_type& fill_mshr) const;
  void insert_stlb_cp_pb(const mshr_type& fill_mshr);
  bool try_stlb_cp_pb_demand_hit(const tag_lookup_type& handle_pkt);
  void fill_stlb_from_cp_pb(const tag_lookup_type& handle_pkt, const stlb_cp_pb_entry& entry);
  [[nodiscard]] bool stlb_prefetch_buffer_enabled() const;
  [[nodiscard]] bool should_redirect_stlb_prefetch_buffer_fill(const mshr_type& fill_mshr) const;
  void insert_stlb_prefetch_buffer(const mshr_type& fill_mshr);
  bool start_stlb_prefetch_buffer_lookup(const tag_lookup_type& handle_pkt);
  long complete_stlb_prefetch_buffer_lookups();
  void complete_stlb_prefetch_buffer_hit(const tag_lookup_type& handle_pkt, const stlb_prefetch_buffer_entry& entry);
  void fill_stlb_from_prefetch_buffer(const tag_lookup_type& handle_pkt, const stlb_prefetch_buffer_entry& entry);

public:
  using BLOCK = champsim::cache_block;

private:
  static BLOCK fill_block(mshr_type mshr, uint32_t metadata);
  using set_type = std::vector<BLOCK>;

  std::pair<set_type::iterator, set_type::iterator> get_set_span(champsim::address address);
  [[nodiscard]] std::pair<set_type::const_iterator, set_type::const_iterator> get_set_span(champsim::address address) const;
  [[nodiscard]] long get_set_index(champsim::address address) const;

  template <typename T>
  bool should_activate_prefetcher(const T& pkt) const;

  template <typename T>
  static std::string module_type_name();

  template <bool>
  auto initiate_tag_check(champsim::channel* ul = nullptr);

  template <typename T>
  champsim::address module_address(const T& element) const;

  template <typename T>
  bool module_is_instr(const T& element) const;

  auto matches_address(champsim::address address) const;
  std::pair<mshr_type, request_type> mshr_and_forward_packet(const tag_lookup_type& handle_pkt);

  std::deque<tag_lookup_type> internal_PQ{};
  std::deque<tag_lookup_type> inflight_tag_check{};
  std::deque<tag_lookup_type> translation_stash{};
  std::deque<tag_lookup_type> pqfull_tlb_rescue_queue{};
  std::deque<tag_lookup_type> pqfull_tlb_rescue_inflight{};
  uint64_t vberti_prefetch_seq_counter = 0;
  uint64_t vberti_end_to_end_id_counter = 0;
  bool vberti_end_to_end_roi_started = false;
  std::map<tlb_prefetch_key, uint64_t> tlb_cross_prefetch_pending{};
  std::deque<prefetch_too_early_key> prefetch_too_early_fifo{};
  std::map<prefetch_too_early_key, uint64_t> prefetch_too_early_shadow{};
  std::deque<std::tuple<prefetch_pollution_key, bool, uint64_t>> prefetch_pollution_fifo{};
  std::map<prefetch_pollution_key, std::pair<uint64_t, bool>> prefetch_pollution_shadow{};
  uint64_t prefetch_pollution_next_id = 0;
  std::deque<tlb_prefetch_key> tlb_cross_prefetch_too_early_fifo{};
  std::map<tlb_prefetch_key, uint64_t> tlb_cross_prefetch_too_early_shadow{};
  std::deque<std::tuple<tlb_prefetch_key, bool, uint64_t>> tlb_cross_prefetch_pollution_fifo{};
  std::map<tlb_prefetch_key, std::pair<uint64_t, bool>> tlb_cross_prefetch_pollution_shadow{};
  uint64_t tlb_cross_prefetch_pollution_next_id = 0;
  std::deque<tlb_prefetch_key> stlb_prefetch_too_early_fifo{};
  std::map<tlb_prefetch_key, uint64_t> stlb_prefetch_too_early_shadow{};
  std::deque<std::tuple<tlb_prefetch_key, bool, uint64_t>> stlb_prefetch_pollution_fifo{};
  std::map<tlb_prefetch_key, std::pair<uint64_t, bool>> stlb_prefetch_pollution_shadow{};
  uint64_t stlb_prefetch_pollution_next_id = 0;
  uint8_t current_prefetch_asid[2] = {std::numeric_limits<uint8_t>::max(), std::numeric_limits<uint8_t>::max()};
  std::map<tlb_prefetch_key, stlb_cp_pb_entry> stlb_cp_pb{};
  std::deque<stlb_prefetch_buffer_entry> stlb_prefetch_buffer{};
  std::deque<stlb_prefetch_buffer_lookup> stlb_prefetch_buffer_lookups{};
  uint64_t stlb_prefetch_buffer_next_generation = 0;

public:
  std::vector<channel_type*> upper_levels;
  channel_type* lower_level;
  channel_type* lower_translate;

  uint32_t cpu = 0;
  std::string NAME;
  uint32_t NUM_SET, NUM_WAY, MSHR_SIZE;
  std::size_t PQ_SIZE;
  champsim::chrono::clock::duration HIT_LATENCY;
  champsim::chrono::clock::duration FILL_LATENCY;
  champsim::data::bits OFFSET_BITS;
  set_type block{static_cast<typename set_type::size_type>(NUM_SET * NUM_WAY)};
  champsim::bandwidth::maximum_type MAX_TAG, MAX_FILL;
  bool prefetch_as_load;
  bool match_offset_bits;
  bool virtual_prefetch;
  champsim::stlb_prefetch_destination STLB_PREFETCH_DESTINATION;
  std::size_t STLB_PREFETCH_BUFFER_SIZE;
  champsim::chrono::clock::duration STLB_PREFETCH_BUFFER_LATENCY;
  std::vector<access_type> pref_activate_mask;

  using stats_type = cache_stats;

  stats_type sim_stats, roi_stats;

  std::deque<mshr_type> MSHR;
  std::deque<mshr_type> inflight_writes;

  long operate() final;
  void initialize() final;
  void begin_phase() final;
  void end_phase(unsigned cpu) final;

  [[deprecated]] std::size_t get_occupancy(uint8_t queue_type, champsim::address address) const;
  [[deprecated]] std::size_t get_size(uint8_t queue_type, champsim::address address) const;

  // NOLINTBEGIN
  [[deprecated("get_occupancy() returns 0 for every input except 0 (MSHR). Use get_mshr_occupancy() instead.")]] std::size_t
  get_occupancy(uint8_t queue_type, uint64_t address) const;
  [[deprecated("get_size() returns 0 for every input except 0 (MSHR). Use get_mshr_size() instead.")]] std::size_t get_size(uint8_t queue_type,
                                                                                                                            uint64_t address) const;
  // NOLINTEND

  [[nodiscard]] std::size_t get_mshr_occupancy() const;
  [[nodiscard]] std::size_t get_mshr_size() const;
  [[nodiscard]] double get_mshr_occupancy_ratio() const;

  [[nodiscard]] std::vector<std::size_t> get_rq_occupancy() const;
  [[nodiscard]] std::vector<std::size_t> get_rq_size() const;
  [[nodiscard]] std::vector<double> get_rq_occupancy_ratio() const;

  [[nodiscard]] std::vector<std::size_t> get_wq_occupancy() const;
  [[nodiscard]] std::vector<std::size_t> get_wq_size() const;
  [[nodiscard]] std::vector<double> get_wq_occupancy_ratio() const;

  [[nodiscard]] std::vector<std::size_t> get_pq_occupancy() const;
  [[nodiscard]] std::vector<std::size_t> get_pq_size() const;
  [[nodiscard]] std::vector<double> get_pq_occupancy_ratio() const;

  [[deprecated("Use get_set_index() instead.")]] [[nodiscard]] uint64_t get_set(uint64_t address) const;
  [[deprecated("This function should not be used to access the blocks directly.")]] [[nodiscard]] uint64_t get_way(uint64_t address, uint64_t set) const;

  long invalidate_entry(champsim::address inval_addr);
  void record_l1d_prefetch_candidate(uint32_t prefetch_metadata);
  bool prefetch_line(champsim::address pf_addr, bool fill_this_level, uint32_t prefetch_metadata);
  bool prefetch_translation(champsim::address virtual_address, uint32_t prefetch_metadata = 0);
  [[nodiscard]] std::vector<std::string> prefetcher_names() const;
  [[nodiscard]] std::vector<std::string> replacement_names() const;

  [[deprecated]] bool prefetch_line(uint64_t pf_addr, bool fill_this_level, uint32_t prefetch_metadata);

  [[deprecated("Use CACHE::prefetch_line(pf_addr, fill_this_level, prefetch_metadata) instead.")]] bool
  prefetch_line(uint64_t ip, uint64_t base_addr, uint64_t pf_addr, bool fill_this_level, uint32_t prefetch_metadata);

  void print_deadlock() final;

#include "module_decl.inc"

  struct prefetcher_module_concept {
    virtual ~prefetcher_module_concept() = default;

    virtual void bind(CACHE* cache) = 0;

    virtual void impl_prefetcher_initialize() = 0;
    virtual uint32_t impl_prefetcher_cache_operate(champsim::address addr, champsim::address ip, bool cache_hit, bool useful_prefetch, access_type type,
                                                   uint32_t metadata_in) = 0;
    virtual uint32_t impl_prefetcher_cache_fill(champsim::address addr, long set, long way, bool prefetch, champsim::address evicted_addr,
                                                uint32_t metadata_in) = 0;
    virtual void impl_stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context) = 0;
    virtual void impl_stlb_prefetcher_fill(const champsim::modules::stlb_prefetcher_fill_context& context) = 0;
    virtual void impl_prefetcher_cycle_operate() = 0;
    virtual void impl_prefetcher_final_stats() = 0;
    virtual void impl_prefetcher_branch_operate(champsim::address ip, uint8_t branch_type, champsim::address branch_target) = 0;
    virtual std::vector<std::string> module_names() const = 0;
  };

  struct replacement_module_concept {
    virtual ~replacement_module_concept() = default;

    virtual void bind(CACHE* cache) = 0;

    virtual void impl_initialize_replacement() = 0;
    virtual long impl_find_victim(uint32_t triggering_cpu, uint64_t instr_id, long set, const BLOCK* current_set, champsim::address ip,
                                  champsim::address full_addr, access_type type) = 0;
    virtual void impl_update_replacement_state(uint32_t triggering_cpu, long set, long way, champsim::address full_addr, champsim::address ip,
                                               champsim::address victim_addr, access_type type, bool hit) = 0;
    virtual void impl_replacement_cache_fill(uint32_t triggering_cpu, long set, long way, champsim::address full_addr, champsim::address ip,
                                             champsim::address victim_addr, access_type type) = 0;
    virtual void impl_replacement_final_stats() = 0;
    virtual std::vector<std::string> module_names() const = 0;
  };

  template <typename... Ps>
  struct prefetcher_module_model final : prefetcher_module_concept {
    std::tuple<Ps...> intern_;
    explicit prefetcher_module_model(CACHE* cache) : intern_(Ps{cache}...) { (void)cache; /* silence -Wunused-but-set-parameter when sizeof...(Ps) == 0 */ }
    void bind(CACHE* cache)
    {
      std::apply([cache = cache](auto&... p) { (..., p.bind(cache)); }, intern_);
    }

    void impl_prefetcher_initialize() final;
    [[nodiscard]] uint32_t impl_prefetcher_cache_operate(champsim::address addr, champsim::address ip, bool cache_hit, bool useful_prefetch, access_type type,
                                                         uint32_t metadata_in) final;
    [[nodiscard]] uint32_t impl_prefetcher_cache_fill(champsim::address addr, long set, long way, bool prefetch, champsim::address evicted_addr,
                                                      uint32_t metadata_in) final;
    void impl_stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context) final;
    void impl_stlb_prefetcher_fill(const champsim::modules::stlb_prefetcher_fill_context& context) final;
    void impl_prefetcher_cycle_operate() final;
    void impl_prefetcher_final_stats() final;
    void impl_prefetcher_branch_operate(champsim::address ip, uint8_t branch_type, champsim::address branch_target) final;
    [[nodiscard]] std::vector<std::string> module_names() const final { return {module_type_name<Ps>()...}; }
  };

  template <typename... Rs>
  struct replacement_module_model final : replacement_module_concept {
    // Assert that at least one has an update state
    // static_assert(std::disjunction<champsim::is_detected<has_update_state, Rs>...>::value, "At least one replacement policy must update its state");

    std::tuple<Rs...> intern_;
    explicit replacement_module_model(CACHE* cache) : intern_(Rs{cache}...) { (void)cache; /* silence -Wunused-but-set-parameter when sizeof...(Rs) == 0 */ }
    void bind(CACHE* cache)
    {
      std::apply([cache = cache](auto&... r) { (..., r.bind(cache)); }, intern_);
    }

    void impl_initialize_replacement() final;
    [[nodiscard]] long impl_find_victim(uint32_t triggering_cpu, uint64_t instr_id, long set, const BLOCK* current_set, champsim::address ip,
                                        champsim::address full_addr, access_type type) final;
    void impl_update_replacement_state(uint32_t triggering_cpu, long set, long way, champsim::address full_addr, champsim::address ip,
                                       champsim::address victim_addr, access_type type, bool hit) final;
    void impl_replacement_cache_fill(uint32_t triggering_cpu, long set, long way, champsim::address full_addr, champsim::address ip,
                                     champsim::address victim_addr, access_type type) final;
    void impl_replacement_final_stats() final;
    [[nodiscard]] std::vector<std::string> module_names() const final { return {module_type_name<Rs>()...}; }
  };

  std::unique_ptr<prefetcher_module_concept> pref_module_pimpl;
  std::unique_ptr<replacement_module_concept> repl_module_pimpl;

  // NOLINTBEGIN(readability-make-member-function-const): legacy modules use non-const hooks
  void impl_prefetcher_initialize() const;
  [[nodiscard]] uint32_t impl_prefetcher_cache_operate(champsim::address addr, champsim::address ip, bool cache_hit, bool useful_prefetch, access_type type,
                                                       uint32_t metadata_in) const;
  [[nodiscard]] uint32_t impl_prefetcher_cache_fill(champsim::address addr, long set, long way, bool prefetch, champsim::address evicted_addr,
                                                    uint32_t metadata_in) const;
  void impl_stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context) const;
  void impl_stlb_prefetcher_fill(const champsim::modules::stlb_prefetcher_fill_context& context) const;
  void impl_prefetcher_cycle_operate() const;
  void impl_prefetcher_final_stats() const;
  void impl_prefetcher_branch_operate(champsim::address ip, uint8_t branch_type, champsim::address branch_target) const;

  void impl_initialize_replacement() const;
  [[nodiscard]] long impl_find_victim(uint32_t triggering_cpu, uint64_t instr_id, long set, const BLOCK* current_set, champsim::address ip,
                                      champsim::address full_addr, access_type type) const;
  void impl_update_replacement_state(uint32_t triggering_cpu, long set, long way, champsim::address full_addr, champsim::address ip,
                                     champsim::address victim_addr, access_type type, bool hit) const;
  void impl_replacement_cache_fill(uint32_t triggering_cpu, long set, long way, champsim::address full_addr, champsim::address ip,
                                   champsim::address victim_addr, access_type type) const;
  void impl_replacement_final_stats() const;
  // NOLINTEND(readability-make-member-function-const)

  template <typename... Ps, typename... Rs>
  explicit CACHE(champsim::cache_builder<champsim::cache_builder_module_type_holder<Ps...>, champsim::cache_builder_module_type_holder<Rs...>> b)
      : champsim::operable(b.m_clock_period), upper_levels(b.m_uls), lower_level(b.m_ll), lower_translate(b.m_lt), NAME(b.m_name), NUM_SET(b.get_num_sets()),
        NUM_WAY(b.get_num_ways()), MSHR_SIZE(b.get_num_mshrs()), PQ_SIZE(b.m_pq_size), HIT_LATENCY(b.get_hit_latency() * b.m_clock_period),
        FILL_LATENCY(b.get_fill_latency() * b.m_clock_period), OFFSET_BITS(b.m_offset_bits), MAX_TAG(b.get_tag_bandwidth()), MAX_FILL(b.get_fill_bandwidth()),
        prefetch_as_load(b.m_pref_load), match_offset_bits(b.m_wq_full_addr), virtual_prefetch(b.m_va_pref),
        STLB_PREFETCH_DESTINATION(b.m_stlb_prefetch_destination), STLB_PREFETCH_BUFFER_SIZE(b.m_stlb_prefetch_buffer_size),
        STLB_PREFETCH_BUFFER_LATENCY(b.m_stlb_prefetch_buffer_latency * b.m_clock_period), pref_activate_mask(b.m_pref_act_mask),
        pref_module_pimpl(std::make_unique<prefetcher_module_model<Ps...>>(this)), repl_module_pimpl(std::make_unique<replacement_module_model<Rs...>>(this))
  {
    if (STLB_PREFETCH_DESTINATION == champsim::stlb_prefetch_destination::PREFETCH_BUFFER && !is_stlb())
      throw std::invalid_argument("The STLB prefetch buffer can only be configured on an STLB cache");
    if (STLB_PREFETCH_DESTINATION == champsim::stlb_prefetch_destination::PREFETCH_BUFFER && STLB_PREFETCH_BUFFER_SIZE == 0)
      throw std::invalid_argument("The STLB prefetch buffer must contain at least one entry");
  }

  CACHE(const CACHE&) = delete;
  CACHE(CACHE&&);
  CACHE& operator=(const CACHE&) = delete;
  CACHE& operator=(CACHE&&);
};

template <typename T>
std::string CACHE::module_type_name()
{
  int status = 0;
  auto deleter = [](char* ptr) { std::free(ptr); };
  std::unique_ptr<char, decltype(deleter)> demangled{abi::__cxa_demangle(typeid(T).name(), nullptr, nullptr, &status), deleter};
  std::string name = status == 0 && demangled ? demangled.get() : typeid(T).name();
  auto pos = name.rfind("::");
  if (pos != std::string::npos)
    name = name.substr(pos + 2);
  return name;
}

inline std::vector<std::string> CACHE::prefetcher_names() const { return pref_module_pimpl->module_names(); }

inline std::vector<std::string> CACHE::replacement_names() const { return repl_module_pimpl->module_names(); }

template <typename... Ps>
void CACHE::prefetcher_module_model<Ps...>::impl_prefetcher_initialize()
{
  [[maybe_unused]] auto process_one = [&](auto& p) {
    using namespace champsim::modules;
    if constexpr (prefetcher::has_initialize<decltype(p)>)
      p.prefetcher_initialize();
    if constexpr (stlb_prefetcher::has_initialize<decltype(p)>)
      p.stlb_prefetcher_initialize();
  };

  std::apply([&](auto&... p) { (..., process_one(p)); }, intern_);
}

template <typename... Ps>
uint32_t CACHE::prefetcher_module_model<Ps...>::impl_prefetcher_cache_operate(champsim::address addr, champsim::address ip, bool cache_hit,
                                                                              bool useful_prefetch, access_type type, uint32_t metadata_in)
{
  using return_type = uint32_t;
  [[maybe_unused]] auto process_one = [&](auto& p) {
    using namespace champsim::modules;
    /* Strong addresses */
    if constexpr (prefetcher::has_cache_operate<decltype(p), champsim::address, champsim::address, bool, bool, access_type, uint32_t>)
      return return_type{p.prefetcher_cache_operate(addr, ip, cache_hit, useful_prefetch, type, metadata_in)};

    /* Strong addresses, raw integer access type */
    if constexpr (prefetcher::has_cache_operate<decltype(p), champsim::address, champsim::address, bool, bool, std::underlying_type_t<access_type>, uint32_t>)
      return return_type{p.prefetcher_cache_operate(addr, ip, cache_hit, useful_prefetch, champsim::to_underlying(type), metadata_in)};

    /* Raw integer addresses, no useful_prefetch parameter, raw integer access type */
    if constexpr (prefetcher::has_cache_operate<decltype(p), uint64_t, uint64_t, bool, std::underlying_type_t<access_type>, uint32_t>)
      return return_type{p.prefetcher_cache_operate(addr.to<uint64_t>(), ip.to<uint64_t>(), cache_hit, champsim::to_underlying(type), metadata_in)};

    return return_type{};
  };

  return std::apply([&](auto&... p) { return (return_type{} ^ ... ^ process_one(p)); }, intern_);
}

template <typename... Ps>
uint32_t CACHE::prefetcher_module_model<Ps...>::impl_prefetcher_cache_fill(champsim::address addr, long set, long way, bool prefetch,
                                                                           champsim::address evicted_addr, uint32_t metadata_in)
{
  using return_type = uint32_t;
  [[maybe_unused]] auto process_one = [&](auto& p) {
    using namespace champsim::modules;
    if constexpr (prefetcher::has_cache_fill<decltype(p), champsim::address, long, long, bool, champsim::address, uint32_t>)
      return return_type{p.prefetcher_cache_fill(addr, set, way, prefetch, evicted_addr, metadata_in)};
    if constexpr (prefetcher::has_cache_fill<decltype(p), uint64_t, long, long, bool, uint64_t, uint32_t>)
      return return_type{p.prefetcher_cache_fill(addr.to<uint64_t>(), set, way, prefetch, evicted_addr.to<uint64_t>(), metadata_in)};
    return return_type{};
  };

  return std::apply([&](auto&... p) { return (return_type{} ^ ... ^ process_one(p)); }, intern_);
}

template <typename... Ps>
void CACHE::prefetcher_module_model<Ps...>::impl_stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context)
{
  [[maybe_unused]] auto process_one = [&](auto& p) {
    using namespace champsim::modules;
    if constexpr (stlb_prefetcher::has_operate<decltype(p), const stlb_prefetcher_context&>)
      p.stlb_prefetcher_operate(context);
  };

  std::apply([&](auto&... p) { (..., process_one(p)); }, intern_);
}

template <typename... Ps>
void CACHE::prefetcher_module_model<Ps...>::impl_stlb_prefetcher_fill(const champsim::modules::stlb_prefetcher_fill_context& context)
{
  [[maybe_unused]] auto process_one = [&](auto& p) {
    using namespace champsim::modules;
    if constexpr (stlb_prefetcher::has_fill<decltype(p), const stlb_prefetcher_fill_context&>)
      p.stlb_prefetcher_fill(context);
  };

  std::apply([&](auto&... p) { (..., process_one(p)); }, intern_);
}

template <typename... Ps>
void CACHE::prefetcher_module_model<Ps...>::impl_prefetcher_cycle_operate()
{
  [[maybe_unused]] auto process_one = [&](auto& p) {
    using namespace champsim::modules;
    if constexpr (prefetcher::has_cycle_operate<decltype(p)>)
      p.prefetcher_cycle_operate();
    if constexpr (stlb_prefetcher::has_cycle_operate<decltype(p)>)
      p.stlb_prefetcher_cycle_operate();
  };

  std::apply([&](auto&... p) { (..., process_one(p)); }, intern_);
}

template <typename... Ps>
void CACHE::prefetcher_module_model<Ps...>::impl_prefetcher_final_stats()
{
  [[maybe_unused]] auto process_one = [&](auto& p) {
    using namespace champsim::modules;
    if constexpr (prefetcher::has_final_stats<decltype(p)>)
      p.prefetcher_final_stats();
    if constexpr (stlb_prefetcher::has_final_stats<decltype(p)>)
      p.stlb_prefetcher_final_stats();
  };

  std::apply([&](auto&... p) { (..., process_one(p)); }, intern_);
}

template <typename... Ps>
void CACHE::prefetcher_module_model<Ps...>::impl_prefetcher_branch_operate(champsim::address ip, uint8_t branch_type, champsim::address branch_target)
{
  [[maybe_unused]] auto process_one = [&](auto& p) {
    using namespace champsim::modules;
    if constexpr (prefetcher::has_branch_operate<decltype(p), champsim::address, uint8_t, champsim::address>)
      p.prefetcher_branch_operate(ip, branch_type, branch_target);
    if constexpr (prefetcher::has_branch_operate<decltype(p), uint64_t, uint8_t, uint64_t>)
      p.prefetcher_branch_operate(ip.to<uint64_t>(), branch_type, branch_target.to<uint64_t>());
  };

  std::apply([&](auto&... p) { (..., process_one(p)); }, intern_);
}

template <typename... Rs>
void CACHE::replacement_module_model<Rs...>::impl_initialize_replacement()
{
  [[maybe_unused]] auto process_one = [&](auto& r) {
    using namespace champsim::modules;
    if constexpr (replacement::has_initialize<decltype(r)>)
      r.initialize_replacement();
  };

  std::apply([&](auto&... r) { (..., process_one(r)); }, intern_);
}

template <typename... Rs>
long CACHE::replacement_module_model<Rs...>::impl_find_victim(uint32_t triggering_cpu, uint64_t instr_id, long set, const BLOCK* current_set,
                                                              champsim::address ip, champsim::address full_addr, access_type type)
{
  using return_type = long;
  [[maybe_unused]] auto process_one = [&](auto& r) {
    using namespace champsim::modules;

    /* Strong addresses */
    if constexpr (replacement::has_find_victim<decltype(r), uint32_t, uint64_t, long, const BLOCK*, champsim::address, champsim::address, access_type>)
      return return_type{r.find_victim(triggering_cpu, instr_id, set, current_set, ip, full_addr, type)};

    /* Raw integer addresses */
    if constexpr (replacement::has_find_victim<decltype(r), uint32_t, uint64_t, long, const BLOCK*, champsim::address, champsim::address,
                                               std::underlying_type_t<access_type>>)
      return return_type{r.find_victim(triggering_cpu, instr_id, set, current_set, ip, full_addr, champsim::to_underlying(type))};

    /* Raw integer addresses, raw integer access type */
    if constexpr (replacement::has_find_victim<decltype(r), uint32_t, uint64_t, long, const BLOCK*, uint64_t, uint64_t, std::underlying_type_t<access_type>>)
      return return_type{r.find_victim(triggering_cpu, instr_id, set, current_set, ip.to<uint64_t>(), full_addr.to<uint64_t>(), champsim::to_underlying(type))};

    return return_type{};
  };

  if constexpr (sizeof...(Rs) > 0) {
    return std::apply([&](auto&... r) { return (..., process_one(r)); }, intern_);
  }
  return return_type{};
}

template <typename... Rs>
void CACHE::replacement_module_model<Rs...>::impl_update_replacement_state(uint32_t triggering_cpu, long set, long way, champsim::address full_addr,
                                                                           champsim::address ip, champsim::address victim_addr, access_type type, bool hit)
{
  [[maybe_unused]] auto process_one = [&](auto& r) {
    using namespace champsim::modules;

    if (hit || replacement::has_cache_fill<decltype(r), uint32_t, long, long, champsim::address, champsim::address, champsim::address, access_type>) {
      auto new_victim_addr = hit ? champsim::address{} : victim_addr;

      /* Strong addresses */
      if constexpr (replacement::has_update_state<decltype(r), uint32_t, long, long, champsim::address, champsim::address, access_type, bool>)
        r.update_replacement_state(triggering_cpu, set, way, full_addr, ip, type, hit);

      /* Strong addresses */
      else if constexpr (replacement::has_update_state<decltype(r), uint32_t, long, long, champsim::address, champsim::address, champsim::address, access_type,
                                                       bool>)
        r.update_replacement_state(triggering_cpu, set, way, full_addr, ip, new_victim_addr, type, hit);

      /* Raw integer access type */
      else if constexpr (replacement::has_update_state<decltype(r), uint32_t, long, long, champsim::address, champsim::address, champsim::address,
                                                       std::underlying_type_t<access_type>, bool>)
        r.update_replacement_state(triggering_cpu, set, way, full_addr, ip, new_victim_addr, champsim::to_underlying(type), hit);

      /* Raw integer addresses, raw integer access type */
      else if constexpr (replacement::has_update_state<decltype(r), uint32_t, long, long, uint64_t, uint64_t, uint64_t, std::underlying_type_t<access_type>,
                                                       bool>)
        r.update_replacement_state(triggering_cpu, set, way, full_addr.to<uint64_t>(), ip.to<uint64_t>(), new_victim_addr.to<uint64_t>(),
                                   champsim::to_underlying(type), hit);
    }
  };

  std::apply([&](auto&... r) { (..., process_one(r)); }, intern_);
}

template <typename... Rs>
void CACHE::replacement_module_model<Rs...>::impl_replacement_cache_fill(uint32_t triggering_cpu, long set, long way, champsim::address full_addr,
                                                                         champsim::address ip, champsim::address victim_addr, access_type type)
{
  [[maybe_unused]] auto process_one = [&](auto& r) {
    using namespace champsim::modules;

    /* Strong addresses */
    if constexpr (replacement::has_cache_fill<decltype(r), uint32_t, long, long, champsim::address, champsim::address, champsim::address, access_type>)
      r.replacement_cache_fill(triggering_cpu, set, way, full_addr, ip, victim_addr, type);

    else
      impl_update_replacement_state(triggering_cpu, set, way, full_addr, ip, victim_addr, type, false);
  };

  std::apply([&](auto&... r) { (..., process_one(r)); }, intern_);
}

template <typename... Rs>
void CACHE::replacement_module_model<Rs...>::impl_replacement_final_stats()
{
  [[maybe_unused]] auto process_one = [&](auto& r) {
    using namespace champsim::modules;
    if constexpr (replacement::has_final_stats<decltype(r)>)
      r.replacement_final_stats();
  };

  std::apply([&](auto&... r) { (..., process_one(r)); }, intern_);
}

#ifdef SET_ASIDE_CHAMPSIM_MODULE
#undef SET_ASIDE_CHAMPSIM_MODULE
#define CHAMPSIM_MODULE
#endif

#endif
