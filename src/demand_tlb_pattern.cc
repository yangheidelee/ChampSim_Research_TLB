/*
 *    Copyright 2023 The ChampSim Contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 */

#include "demand_tlb_pattern.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <utility>

#include <nlohmann/json.hpp>

namespace champsim
{
namespace
{
constexpr std::size_t OUTPUT_BUFFER_LIMIT = 1024 * 1024;

enum class lookup_result : uint8_t {
  UNKNOWN = 0,
  HIT,
  MISS,
};

struct pattern_event {
  uint32_t cpu = 0;
  uint64_t load_tlb_seq = 0;
  uint64_t instr_id = 0;
  uint32_t operand_index = 0;
  uint64_t pc = 0;
  uint64_t dtlb_lookup_cycle = 0;
  uint64_t translation_complete_cycle = 0;
  uint64_t va = 0;
  uint64_t vpn = 0;
  uint64_t virtual_region_2m = 0;
  uint64_t page_offset_in_region = 0;
  uint64_t pa = 0;
  uint64_t ppn = 0;
  uint64_t physical_region_2m = 0;
  uint64_t page_offset_in_physical_region = 0;
  bool physical_address_valid = false;
  lookup_result l1dtlb_result = lookup_result::UNKNOWN;
  bool l1dtlb_merged = false;
  dtlb_merge_detail l1dtlb_merge_detail = dtlb_merge_detail::NONE;
  bool stlb_accessed = false;
  lookup_result stlb_result = lookup_result::UNKNOWN;
  bool stlb_merged = false;
  dtlb_merge_detail stlb_merge_detail = dtlb_merge_detail::NONE;
};

struct core_summary {
  uint64_t created_events = 0;
  uint64_t completed_events = 0;
  uint64_t incomplete_events = 0;
  uint64_t l1dtlb_hits = 0;
  uint64_t l1dtlb_misses = 0;
  uint64_t l1dtlb_merges = 0;
  uint64_t stlb_accesses = 0;
  uint64_t stlb_hits = 0;
  uint64_t stlb_misses = 0;
  uint64_t stlb_merges = 0;
};

struct combined_pattern_event {
  pattern_event translation{};
  uint64_t global_seq = 0;
  uint64_t local_seq = 0;
  uint64_t vberti_prefetch_seq = 0;
  vberti_tlb_pattern_event_type event_type = vberti_tlb_pattern_event_type::DATA_DEMAND;
};

struct combined_core_summary {
  uint64_t demand_events = 0;
  uint64_t completed_demand_events = 0;
  uint64_t incomplete_demand_events = 0;
  uint64_t cross_page_prefetch_events = 0;
  uint64_t completed_cross_page_prefetch_events = 0;
  uint64_t incomplete_cross_page_prefetch_events = 0;
};

bool environment_flag_enabled(const char* name)
{
  const auto* raw = std::getenv(name);
  if (raw == nullptr)
    return false;
  std::string value{raw};
  std::transform(std::begin(value), std::end(value), std::begin(value), [](unsigned char character) {
    return static_cast<char>(std::tolower(character));
  });
  return value == "1" || value == "true" || value == "yes" || value == "on";
}

std::filesystem::path environment_path_or(const char* name, std::filesystem::path fallback)
{
  const auto* raw = std::getenv(name);
  return raw == nullptr || *raw == '\0' ? std::move(fallback) : std::filesystem::path{raw};
}

std::string_view result_name(lookup_result result)
{
  switch (result) {
  case lookup_result::HIT:
    return "HIT";
  case lookup_result::MISS:
    return "MISS";
  case lookup_result::UNKNOWN:
    return "UNKNOWN";
  }
  return "UNKNOWN";
}

std::string_view stlb_result_name(const pattern_event& event)
{
  if (!event.stlb_accessed)
    return "NOT_ACCESSED";
  return result_name(event.stlb_result);
}

std::string_view merge_detail_name(dtlb_merge_detail detail)
{
  switch (detail) {
  case dtlb_merge_detail::NONE:
    return "NONE";
  case dtlb_merge_detail::RQ_MERGE:
    return "RQ_MERGE";
  case dtlb_merge_detail::MSHR_TO_DATA_DEMAND:
    return "MSHR_TO_DATA_DEMAND";
  case dtlb_merge_detail::MSHR_TO_INST_DEMAND:
    return "MSHR_TO_INST_DEMAND";
  case dtlb_merge_detail::MSHR_TO_L1D_PREFETCH:
    return "MSHR_TO_L1D_PREFETCH";
  case dtlb_merge_detail::MSHR_TO_CP_PREFETCH:
    return "MSHR_TO_CP_PREFETCH";
  case dtlb_merge_detail::MSHR_TO_SP_PREFETCH:
    return "MSHR_TO_SP_PREFETCH";
  case dtlb_merge_detail::MSHR_TO_L1I_PREFETCH:
    return "MSHR_TO_L1I_PREFETCH";
  case dtlb_merge_detail::MSHR_TO_OTHER:
    return "MSHR_TO_OTHER";
  case dtlb_merge_detail::PRELOOKUP_COALESCED:
    return "PRELOOKUP_COALESCED";
  }
  return "NONE";
}

std::string_view raster_outcome_name(const pattern_event& event, bool complete)
{
  if (!complete)
    return "Other / incomplete";
  if (event.l1dtlb_merged)
    return "DTLB-side translation merge";
  if (event.stlb_merged)
    return "STLB-side translation merge";
  if (event.l1dtlb_result == lookup_result::HIT)
    return "L1 DTLB hit";
  if (event.l1dtlb_result == lookup_result::MISS && event.stlb_accessed && event.stlb_result == lookup_result::HIT)
    return "L1 miss + STLB hit";
  if (event.l1dtlb_result == lookup_result::MISS && event.stlb_accessed && event.stlb_result == lookup_result::MISS)
    return "STLB miss";
  return "Other / incomplete";
}
} // namespace

class VbertiCrossPageDemandPatternLogger::impl
{
public:
  demand_tlb_pattern_config base_config{};
  bool enabled = false;
  bool roi_active = false;
  std::filesystem::path output_directory{};
  std::vector<uint64_t> next_global_sequence{};
  std::vector<uint64_t> next_demand_sequence{};
  std::vector<uint64_t> next_prefetch_sequence{};
  std::vector<std::map<uint64_t, combined_pattern_event>> pending{};
  std::vector<combined_core_summary> summaries{};
  std::vector<std::ofstream> streams{};
  std::vector<std::string> output_buffers{};

  [[nodiscard]] combined_pattern_event* find(vberti_tlb_pattern_event_ref ref)
  {
    if (!roi_active || ref.cpu >= pending.size())
      return nullptr;
    auto found = pending.at(ref.cpu).find(ref.global_seq);
    return found == pending.at(ref.cpu).end() ? nullptr : &found->second;
  }

  void flush_core(std::size_t cpu)
  {
    if (cpu >= streams.size() || output_buffers.at(cpu).empty())
      return;
    streams.at(cpu) << output_buffers.at(cpu);
    output_buffers.at(cpu).clear();
  }

  void append_line(uint32_t cpu, std::ostringstream& line)
  {
    auto& buffer = output_buffers.at(cpu);
    buffer += line.str();
    if (buffer.size() >= OUTPUT_BUFFER_LIMIT)
      flush_core(cpu);
  }

  void write_event(const combined_pattern_event& combined, bool complete)
  {
    const auto& event = combined.translation;
    const bool is_demand = combined.event_type == vberti_tlb_pattern_event_type::DATA_DEMAND;
    std::ostringstream line;
    line << event.cpu << ',' << combined.global_seq << ',' << (is_demand ? "DATA_DEMAND" : "VBERTI_CP_PREFETCH") << ',';
    if (is_demand)
      line << combined.local_seq << ",,," << event.instr_id << ',' << event.operand_index << ',' << event.pc << ",,,,,";
    else
      line << ',' << combined.local_seq << ',' << combined.vberti_prefetch_seq << ",,," << event.pc << ",,,,,";
    line << event.dtlb_lookup_cycle << ','
         << (complete ? event.translation_complete_cycle : 0) << ',' << event.va << ',' << event.vpn << ',' << event.virtual_region_2m << ','
         << event.page_offset_in_region << ',' << event.pa << ',' << event.ppn << ',' << event.physical_region_2m << ','
         << event.page_offset_in_physical_region << ',' << static_cast<unsigned>(event.physical_address_valid) << ','
         << result_name(event.l1dtlb_result) << ',' << static_cast<unsigned>(event.l1dtlb_merged) << ','
         << merge_detail_name(event.l1dtlb_merge_detail) << ','
         << static_cast<unsigned>(event.stlb_accessed) << ',' << stlb_result_name(event) << ',' << static_cast<unsigned>(event.stlb_merged) << ','
         << merge_detail_name(event.stlb_merge_detail) << ',' << (complete ? "COMPLETE" : "INCOMPLETE") << ','
         << raster_outcome_name(event, complete) << '\n';
    append_line(event.cpu, line);
  }

  void write_metadata() const
  {
    nlohmann::json metadata;
    metadata["page_size"] = base_config.page_size;
    metadata["region_size"] = base_config.region_size;
    metadata["num_cores"] = base_config.num_cores;
    metadata["warmup_instructions"] = base_config.warmup_instructions;
    metadata["simulation_instructions"] = base_config.simulation_instructions;
    metadata["trace_names"] = base_config.trace_names;
    metadata["executable_name"] = base_config.executable_name;
    metadata["environment_switch"] = "DUMP_VBERTI_CROSS_PAGE_DEMAND_PATTERN";
    metadata["environment_switch_enabled"] = enabled;
    metadata["global_seq_semantics"] =
        "per-core accepted L1D-to-DTLB request order shared by real-data demand and vBerti cross-page prefetch";
    metadata["prefetch_result_semantics"] =
        "prefetch rows are actual accepted DTLB requests and carry the same DTLB/STLB/completion tracking as demand rows";
    metadata["csv_columns"] = {
        {"cpu", "core index"},
        {"global_seq", "per-core common order shared by both event types"},
        {"event_type", "DATA_DEMAND or VBERTI_CP_PREFETCH"},
        {"load_tlb_seq", "existing demand-only stream sequence; empty for prefetch"},
        {"cross_page_prefetch_seq", "cross-page DTLB-access sequence; empty for demand"},
        {"vberti_prefetch_seq", "existing vBerti internal prefetch sequence captured at L1D"},
        {"instr_id", "dynamic demand instruction ID; unavailable for prefetch"},
        {"operand_index", "demand source-memory operand; unavailable for prefetch"},
        {"pc", "demand load PC; zero when the prefetch request has no architecturally meaningful load PC"},
        {"prefetch_issue_cycle", "reserved vBerti algorithm issue cycle; currently unavailable"},
        {"prefetch_trigger_instr_id", "reserved trigger instruction ID; currently unavailable"},
        {"prefetch_trigger_pc", "reserved vBerti trigger PC; currently unavailable"},
        {"prefetch_trigger_va", "reserved vBerti trigger VA; currently unavailable"},
        {"dtlb_lookup_cycle", "cycle when L1D successfully issued this request to DTLB"},
        {"translation_complete_cycle", "L1D cycle when translation returned"},
        {"va", "demand virtual byte address or prefetch target virtual byte address"},
        {"vpn", "virtual page number"},
        {"virtual_region_2m", "2 MiB virtual region ID"},
        {"page_offset_in_region", "4 KiB page index inside the 2 MiB region"},
        {"pa", "existing translated physical byte address; zero when unavailable"},
        {"ppn", "existing translated physical page number; zero when unavailable"},
        {"physical_region_2m", "existing 2 MiB physical region ID; zero when unavailable"},
        {"page_offset_in_physical_region", "existing physical page offset; zero when unavailable"},
        {"physical_address_valid", "one only when PA/PPN fields are valid"},
        {"l1dtlb_result", "HIT, MISS, or UNKNOWN for either event type"},
        {"l1dtlb_merged", "existing demand DTLB-side merge marker"},
        {"dtlb_merge_detail", "NONE, RQ_MERGE, MSHR_TO_<translation origin>, or PRELOOKUP_COALESCED"},
        {"stlb_accessed", "existing demand independent STLB lookup marker"},
        {"stlb_result", "HIT, MISS, NOT_ACCESSED, or UNKNOWN for either event type"},
        {"stlb_merged", "existing demand STLB-side merge marker"},
        {"stlb_merge_detail", "NONE, RQ_MERGE, or MSHR_TO_<translation origin>"},
        {"completion_state", "COMPLETE or INCOMPLETE for either event type"},
        {"raster_outcome_category", "native mutually exclusive coarse translation outcome used by the local raster"},
    };
    std::ofstream output{output_directory / "metadata.json"};
    output << metadata.dump(2) << '\n';
  }

  void write_summary() const
  {
    std::ofstream output{output_directory / "logger_summary.txt"};
    for (std::size_t cpu = 0; cpu < summaries.size(); ++cpu) {
      const auto& summary = summaries.at(cpu);
      output << "core " << cpu << '\n';
      output << "demand_events " << summary.demand_events << '\n';
      output << "completed_demand_events " << summary.completed_demand_events << '\n';
      output << "incomplete_demand_events " << summary.incomplete_demand_events << '\n';
      output << "cross_page_prefetch_events " << summary.cross_page_prefetch_events << '\n';
      output << "completed_cross_page_prefetch_events " << summary.completed_cross_page_prefetch_events << '\n';
      output << "incomplete_cross_page_prefetch_events " << summary.incomplete_cross_page_prefetch_events << '\n';
      output << "total_common_events " << next_global_sequence.at(cpu) << '\n';
    }
  }

  void finalize()
  {
    if (!roi_active)
      return;
    for (std::size_t cpu = 0; cpu < pending.size(); ++cpu) {
      for (const auto& [sequence, event] : pending.at(cpu)) {
        (void)sequence;
        write_event(event, false);
        if (event.event_type == vberti_tlb_pattern_event_type::DATA_DEMAND)
          ++summaries.at(cpu).incomplete_demand_events;
        else
          ++summaries.at(cpu).incomplete_cross_page_prefetch_events;
      }
      pending.at(cpu).clear();
      flush_core(cpu);
      streams.at(cpu).close();
    }
    write_summary();
    roi_active = false;
  }
};

VbertiCrossPageDemandPatternLogger::VbertiCrossPageDemandPatternLogger() : pimpl_(std::make_unique<impl>()) {}

VbertiCrossPageDemandPatternLogger::~VbertiCrossPageDemandPatternLogger() { pimpl_->finalize(); }

void VbertiCrossPageDemandPatternLogger::configure(const demand_tlb_pattern_config& base_config)
{
  pimpl_->finalize();
  pimpl_->base_config = base_config;
  pimpl_->enabled = environment_flag_enabled("DUMP_VBERTI_CROSS_PAGE_DEMAND_PATTERN");
  pimpl_->output_directory = environment_path_or("DUMP_VBERTI_CROSS_PAGE_DEMAND_PATTERN_OUTPUT", "vberti_cross_page_demand_pattern");
  if (pimpl_->enabled && (base_config.page_size == 0 || base_config.region_size % base_config.page_size != 0))
    throw std::invalid_argument("vBerti cross-page/demand pattern region size must be divisible by page size");
}

void VbertiCrossPageDemandPatternLogger::begin_phase(bool is_warmup)
{
  if (!pimpl_->enabled || is_warmup)
    return;
  pimpl_->finalize();
  std::filesystem::create_directories(pimpl_->output_directory);
  pimpl_->next_global_sequence.assign(pimpl_->base_config.num_cores, 0);
  pimpl_->next_demand_sequence.assign(pimpl_->base_config.num_cores, 0);
  pimpl_->next_prefetch_sequence.assign(pimpl_->base_config.num_cores, 0);
  pimpl_->pending.assign(pimpl_->base_config.num_cores, {});
  pimpl_->summaries.assign(pimpl_->base_config.num_cores, {});
  pimpl_->streams = std::vector<std::ofstream>(pimpl_->base_config.num_cores);
  pimpl_->output_buffers.assign(pimpl_->base_config.num_cores, {});
  for (std::size_t cpu = 0; cpu < pimpl_->base_config.num_cores; ++cpu) {
    const auto path = pimpl_->output_directory / ("tlb_pattern_core_" + std::to_string(cpu) + ".csv");
    pimpl_->streams.at(cpu).open(path, std::ios::out | std::ios::trunc);
    if (!pimpl_->streams.at(cpu))
      throw std::runtime_error("Unable to open vBerti cross-page/demand pattern output: " + path.string());
    pimpl_->streams.at(cpu)
        << "cpu,global_seq,event_type,load_tlb_seq,cross_page_prefetch_seq,vberti_prefetch_seq,instr_id,operand_index,pc,"
           "prefetch_issue_cycle,prefetch_trigger_instr_id,prefetch_trigger_pc,prefetch_trigger_va,"
           "dtlb_lookup_cycle,translation_complete_cycle,va,vpn,virtual_region_2m,page_offset_in_region,"
           "pa,ppn,physical_region_2m,page_offset_in_physical_region,physical_address_valid,l1dtlb_result,l1dtlb_merged,"
           "dtlb_merge_detail,stlb_accessed,stlb_result,stlb_merged,stlb_merge_detail,completion_state,raster_outcome_category\n";
  }
  pimpl_->write_metadata();
  pimpl_->roi_active = true;
}

void VbertiCrossPageDemandPatternLogger::end_phase(bool is_warmup)
{
  if (!is_warmup)
    pimpl_->finalize();
}

bool VbertiCrossPageDemandPatternLogger::active() const { return pimpl_->enabled && pimpl_->roi_active; }

std::optional<vberti_tlb_pattern_event_ref>
VbertiCrossPageDemandPatternLogger::next_event_ref(uint32_t cpu, vberti_tlb_pattern_event_type event_type) const
{
  if (!active() || cpu >= pimpl_->next_global_sequence.size())
    return std::nullopt;
  if (pimpl_->base_config.max_events_per_core != 0 && pimpl_->next_global_sequence.at(cpu) >= pimpl_->base_config.max_events_per_core)
    return std::nullopt;
  const auto local_seq = event_type == vberti_tlb_pattern_event_type::DATA_DEMAND ? pimpl_->next_demand_sequence.at(cpu)
                                                                                       : pimpl_->next_prefetch_sequence.at(cpu);
  return vberti_tlb_pattern_event_ref{cpu, pimpl_->next_global_sequence.at(cpu), local_seq, event_type};
}

void VbertiCrossPageDemandPatternLogger::create_event(vberti_tlb_pattern_event_ref ref, const vberti_tlb_pattern_event_start& start)
{
  if (!active() || ref.cpu >= pimpl_->pending.size())
    return;
  auto& expected_local = ref.event_type == vberti_tlb_pattern_event_type::DATA_DEMAND ? pimpl_->next_demand_sequence.at(ref.cpu)
                                                                                            : pimpl_->next_prefetch_sequence.at(ref.cpu);
  if (ref.cpu != start.cpu || ref.global_seq != pimpl_->next_global_sequence.at(ref.cpu) || ref.local_seq != expected_local)
    throw std::logic_error("vBerti/demand TLB pattern event was committed out of order");
  combined_pattern_event combined;
  auto& event = combined.translation;
  combined.global_seq = ref.global_seq;
  combined.local_seq = ref.local_seq;
  combined.event_type = ref.event_type;
  combined.vberti_prefetch_seq = start.vberti_prefetch_seq;
  event.cpu = start.cpu;
  event.load_tlb_seq = ref.event_type == vberti_tlb_pattern_event_type::DATA_DEMAND ? ref.local_seq : 0;
  event.instr_id = start.instr_id;
  event.operand_index = start.operand_index;
  event.pc = start.pc;
  event.dtlb_lookup_cycle = start.dtlb_lookup_cycle;
  event.va = start.va;
  event.vpn = start.va / pimpl_->base_config.page_size;
  event.virtual_region_2m = start.va / pimpl_->base_config.region_size;
  event.page_offset_in_region = (start.va % pimpl_->base_config.region_size) / pimpl_->base_config.page_size;
  auto [position, inserted] = pimpl_->pending.at(ref.cpu).emplace(ref.global_seq, combined);
  (void)position;
  if (!inserted)
    throw std::logic_error("Duplicate vBerti/demand TLB pattern event");
  ++pimpl_->next_global_sequence.at(ref.cpu);
  ++expected_local;
  if (ref.event_type == vberti_tlb_pattern_event_type::DATA_DEMAND)
    ++pimpl_->summaries.at(ref.cpu).demand_events;
  else
    ++pimpl_->summaries.at(ref.cpu).cross_page_prefetch_events;
}

void VbertiCrossPageDemandPatternLogger::mark_l1dtlb_rq_merge(const std::vector<vberti_tlb_pattern_event_ref>& refs)
{
  for (const auto ref : refs) {
    auto* combined = pimpl_->find(ref);
    if (combined == nullptr)
      continue;
    combined->translation.l1dtlb_merged = true;
    if (combined->translation.l1dtlb_merge_detail == dtlb_merge_detail::NONE)
      combined->translation.l1dtlb_merge_detail = dtlb_merge_detail::RQ_MERGE;
  }
}

void VbertiCrossPageDemandPatternLogger::mark_l1dtlb_hit(const std::vector<vberti_tlb_pattern_event_ref>& refs, bool merged)
{
  for (const auto ref : refs) {
    auto* combined = pimpl_->find(ref);
    if (combined == nullptr)
      continue;
    if (combined->translation.l1dtlb_result == lookup_result::UNKNOWN)
      combined->translation.l1dtlb_result = lookup_result::HIT;
    combined->translation.l1dtlb_merged |= merged;
    if (merged && combined->translation.l1dtlb_merge_detail == dtlb_merge_detail::NONE)
      combined->translation.l1dtlb_merge_detail = dtlb_merge_detail::RQ_MERGE;
  }
}

void VbertiCrossPageDemandPatternLogger::mark_l1dtlb_miss(const std::vector<vberti_tlb_pattern_event_ref>& refs, bool merged, dtlb_merge_detail detail)
{
  for (const auto ref : refs) {
    auto* combined = pimpl_->find(ref);
    if (combined == nullptr)
      continue;
    if (combined->translation.l1dtlb_result == lookup_result::UNKNOWN)
      combined->translation.l1dtlb_result = lookup_result::MISS;
    combined->translation.l1dtlb_merged |= merged;
    if (merged && combined->translation.l1dtlb_merge_detail == dtlb_merge_detail::NONE)
      combined->translation.l1dtlb_merge_detail = detail == dtlb_merge_detail::NONE ? dtlb_merge_detail::RQ_MERGE : detail;
  }
}

void VbertiCrossPageDemandPatternLogger::mark_stlb_hit(const std::vector<vberti_tlb_pattern_event_ref>& refs)
{
  for (const auto ref : refs) {
    auto* combined = pimpl_->find(ref);
    if (combined == nullptr)
      continue;
    if (!combined->translation.stlb_accessed) {
      combined->translation.stlb_accessed = true;
      combined->translation.stlb_result = lookup_result::HIT;
    }
  }
}

void VbertiCrossPageDemandPatternLogger::mark_stlb_miss(const std::vector<vberti_tlb_pattern_event_ref>& refs, bool merged,
                                                        dtlb_merge_detail detail)
{
  for (const auto ref : refs) {
    auto* combined = pimpl_->find(ref);
    if (combined == nullptr)
      continue;
    if (!combined->translation.stlb_accessed) {
      combined->translation.stlb_accessed = true;
      combined->translation.stlb_result = lookup_result::MISS;
    }
    combined->translation.stlb_merged |= merged;
    if (merged && combined->translation.stlb_merge_detail == dtlb_merge_detail::NONE)
      combined->translation.stlb_merge_detail = detail == dtlb_merge_detail::NONE ? dtlb_merge_detail::MSHR_TO_OTHER : detail;
  }
}

void VbertiCrossPageDemandPatternLogger::mark_stlb_prelookup_merge(const std::vector<vberti_tlb_pattern_event_ref>& refs)
{
  for (const auto ref : refs) {
    auto* combined = pimpl_->find(ref);
    if (combined != nullptr) {
      combined->translation.stlb_merged = true;
      if (combined->translation.stlb_merge_detail == dtlb_merge_detail::NONE)
        combined->translation.stlb_merge_detail = dtlb_merge_detail::RQ_MERGE;
    }
  }
}

void VbertiCrossPageDemandPatternLogger::complete(const std::vector<vberti_tlb_pattern_event_ref>& refs, uint64_t completion_cycle, uint64_t ppn)
{
  for (const auto ref : refs) {
    auto* combined = pimpl_->find(ref);
    if (combined == nullptr)
      continue;
    auto& event = combined->translation;
    if (event.l1dtlb_result == lookup_result::UNKNOWN) {
      event.l1dtlb_result = lookup_result::MISS;
      event.l1dtlb_merged = true;
      if (event.l1dtlb_merge_detail == dtlb_merge_detail::NONE)
        event.l1dtlb_merge_detail = dtlb_merge_detail::PRELOOKUP_COALESCED;
    }
    event.translation_complete_cycle = completion_cycle;
    event.ppn = ppn;
    event.pa = ppn * pimpl_->base_config.page_size + event.va % pimpl_->base_config.page_size;
    event.physical_region_2m = event.pa / pimpl_->base_config.region_size;
    event.page_offset_in_physical_region = (event.pa % pimpl_->base_config.region_size) / pimpl_->base_config.page_size;
    event.physical_address_valid = true;
    pimpl_->write_event(*combined, true);
    if (combined->event_type == vberti_tlb_pattern_event_type::DATA_DEMAND)
      ++pimpl_->summaries.at(ref.cpu).completed_demand_events;
    else
      ++pimpl_->summaries.at(ref.cpu).completed_cross_page_prefetch_events;
    pimpl_->pending.at(ref.cpu).erase(ref.global_seq);
  }
}

VbertiCrossPageDemandPatternLogger& vberti_cross_page_demand_pattern_logger()
{
  static VbertiCrossPageDemandPatternLogger logger;
  return logger;
}

void append_vberti_tlb_pattern_refs(std::vector<vberti_tlb_pattern_event_ref>& destination,
                                    const std::vector<vberti_tlb_pattern_event_ref>& source)
{
  for (const auto ref : source) {
    if (std::find(std::begin(destination), std::end(destination), ref) == std::end(destination))
      destination.push_back(ref);
  }
}

class DemandTlbPatternLogger::impl
{
public:
  demand_tlb_pattern_config config{};
  bool roi_active = false;
  std::filesystem::path output_directory{};
  std::vector<uint64_t> next_sequence{};
  std::vector<std::map<uint64_t, pattern_event>> pending{};
  std::vector<core_summary> summaries{};
  std::vector<std::ofstream> streams{};
  std::vector<std::string> output_buffers{};

  [[nodiscard]] pattern_event* find(demand_tlb_pattern_event_ref ref)
  {
    if (!roi_active || ref.cpu >= pending.size())
      return nullptr;
    auto found = pending.at(ref.cpu).find(ref.load_tlb_seq);
    return found == pending.at(ref.cpu).end() ? nullptr : &found->second;
  }

  void flush_core(std::size_t cpu)
  {
    if (cpu >= streams.size() || output_buffers.at(cpu).empty())
      return;
    streams.at(cpu) << output_buffers.at(cpu);
    output_buffers.at(cpu).clear();
  }

  void write_event(const pattern_event& event, bool complete)
  {
    auto& buffer = output_buffers.at(event.cpu);
    std::ostringstream line;
    line << event.cpu << ',' << event.load_tlb_seq << ',' << event.instr_id << ',' << event.operand_index << ',' << event.pc << ','
         << event.dtlb_lookup_cycle << ',' << (complete ? event.translation_complete_cycle : 0) << ',' << event.va << ',' << event.vpn << ','
         << event.virtual_region_2m << ',' << event.page_offset_in_region << ',' << event.pa << ',' << event.ppn << ','
         << event.physical_region_2m << ',' << event.page_offset_in_physical_region << ','
         << static_cast<unsigned>(event.physical_address_valid) << ',' << result_name(event.l1dtlb_result) << ','
         << static_cast<unsigned>(event.l1dtlb_merged) << ',' << merge_detail_name(event.l1dtlb_merge_detail) << ','
         << static_cast<unsigned>(event.stlb_accessed) << ',' << stlb_result_name(event) << ','
         << static_cast<unsigned>(event.stlb_merged) << ',' << merge_detail_name(event.stlb_merge_detail) << ','
         << (complete ? "COMPLETE" : "INCOMPLETE") << ',' << raster_outcome_name(event, complete) << '\n';
    buffer += line.str();
    if (buffer.size() >= OUTPUT_BUFFER_LIMIT)
      flush_core(event.cpu);
  }

  void write_metadata() const
  {
    nlohmann::json metadata;
    metadata["page_size"] = config.page_size;
    metadata["region_size"] = config.region_size;
    metadata["num_cores"] = config.num_cores;
    metadata["warmup_instructions"] = config.warmup_instructions;
    metadata["simulation_instructions"] = config.simulation_instructions;
    metadata["trace_names"] = config.trace_names;
    metadata["executable_name"] = config.executable_name;
    metadata["pattern_switch_enabled"] = config.enabled;
    metadata["max_events_per_core"] = config.max_events_per_core;
    metadata["csv_columns"] = {
        {"cpu", "core index"},
        {"load_tlb_seq", "per-core order of accepted demand-load L1 DTLB requests"},
        {"instr_id", "dynamic architectural instruction ID"},
        {"operand_index", "source-memory operand index within the dynamic instruction"},
        {"pc", "static load instruction address"},
        {"dtlb_lookup_cycle", "L1D cycle when the L1 DTLB input accepted the request"},
        {"translation_complete_cycle", "L1D cycle when translation returned; zero for incomplete events"},
        {"va", "virtual byte address"},
        {"vpn", "virtual page number"},
        {"virtual_region_2m", "2 MiB virtual region ID"},
        {"page_offset_in_region", "page index inside the 2 MiB region"},
        {"pa", "translated physical byte address; zero when physical_address_valid is zero"},
        {"ppn", "translated physical page number; zero when physical_address_valid is zero"},
        {"physical_region_2m", "2 MiB physical region ID; zero when physical_address_valid is zero"},
        {"page_offset_in_physical_region", "physical page index inside the 2 MiB physical region; zero when physical_address_valid is zero"},
        {"physical_address_valid", "one when the translation returned and PA/PPN fields are valid"},
        {"l1dtlb_result", "HIT, MISS, or UNKNOWN"},
        {"l1dtlb_merged", "request coalesced before an independent lower-level lookup"},
        {"dtlb_merge_detail", "NONE, RQ_MERGE, MSHR_TO_<translation origin>, or PRELOOKUP_COALESCED"},
        {"stlb_accessed", "request performed an independent STLB tag lookup"},
        {"stlb_result", "HIT, MISS, NOT_ACCESSED, or UNKNOWN"},
        {"stlb_merged", "request merged before STLB lookup or into an STLB MSHR"},
        {"stlb_merge_detail", "NONE, RQ_MERGE, or MSHR_TO_<translation origin>"},
        {"completion_state", "COMPLETE or INCOMPLETE"},
        {"raster_outcome_category", "native mutually exclusive coarse translation outcome used by the local raster"},
    };

    std::ofstream output{output_directory / "metadata.json"};
    output << metadata.dump(2) << '\n';
  }

  void write_summary() const
  {
    std::ofstream output{output_directory / "logger_summary.txt"};
    for (std::size_t cpu = 0; cpu < summaries.size(); ++cpu) {
      const auto& summary = summaries.at(cpu);
      output << "core " << cpu << '\n';
      output << "created_events " << summary.created_events << '\n';
      output << "completed_events " << summary.completed_events << '\n';
      output << "incomplete_events " << summary.incomplete_events << '\n';
      output << "l1dtlb_hits " << summary.l1dtlb_hits << '\n';
      output << "l1dtlb_misses " << summary.l1dtlb_misses << '\n';
      output << "l1dtlb_merges " << summary.l1dtlb_merges << '\n';
      output << "stlb_accesses " << summary.stlb_accesses << '\n';
      output << "stlb_hits " << summary.stlb_hits << '\n';
      output << "stlb_misses " << summary.stlb_misses << '\n';
      output << "stlb_merges " << summary.stlb_merges << '\n';
    }
  }

  void finalize()
  {
    if (!roi_active)
      return;

    for (std::size_t cpu = 0; cpu < pending.size(); ++cpu) {
      for (const auto& [sequence, event] : pending.at(cpu)) {
        (void)sequence;
        write_event(event, false);
        ++summaries.at(cpu).incomplete_events;
      }
      pending.at(cpu).clear();
      flush_core(cpu);
      streams.at(cpu).close();
    }
    write_summary();
    roi_active = false;
  }
};

DemandTlbPatternLogger::DemandTlbPatternLogger() : pimpl_(std::make_unique<impl>()) {}

DemandTlbPatternLogger::~DemandTlbPatternLogger() { pimpl_->finalize(); }

void DemandTlbPatternLogger::configure(demand_tlb_pattern_config config)
{
  pimpl_->finalize();
  pimpl_->config = std::move(config);
  vberti_cross_page_demand_pattern_logger().configure(pimpl_->config);
  if (pimpl_->config.enabled && (pimpl_->config.page_size == 0 || pimpl_->config.region_size % pimpl_->config.page_size != 0))
    throw std::invalid_argument("Demand TLB pattern region size must be divisible by page size");
}

void DemandTlbPatternLogger::begin_phase(bool is_warmup)
{
  vberti_cross_page_demand_pattern_logger().begin_phase(is_warmup);
  if (!pimpl_->config.enabled || is_warmup)
    return;

  pimpl_->finalize();
  pimpl_->output_directory = pimpl_->config.output_directory;
  std::filesystem::create_directories(pimpl_->output_directory);
  pimpl_->next_sequence.assign(pimpl_->config.num_cores, 0);
  pimpl_->pending.assign(pimpl_->config.num_cores, {});
  pimpl_->summaries.assign(pimpl_->config.num_cores, {});
  pimpl_->streams = std::vector<std::ofstream>(pimpl_->config.num_cores);
  pimpl_->output_buffers.assign(pimpl_->config.num_cores, {});

  for (std::size_t cpu = 0; cpu < pimpl_->config.num_cores; ++cpu) {
    const auto path = pimpl_->output_directory / ("demand_tlb_pattern_core_" + std::to_string(cpu) + ".csv");
    pimpl_->streams.at(cpu).open(path, std::ios::out | std::ios::trunc);
    if (!pimpl_->streams.at(cpu))
      throw std::runtime_error("Unable to open demand TLB pattern output: " + path.string());
    pimpl_->streams.at(cpu)
        << "cpu,load_tlb_seq,instr_id,operand_index,pc,dtlb_lookup_cycle,translation_complete_cycle,va,vpn,virtual_region_2m,"
           "page_offset_in_region,pa,ppn,physical_region_2m,page_offset_in_physical_region,physical_address_valid,"
           "l1dtlb_result,l1dtlb_merged,dtlb_merge_detail,stlb_accessed,stlb_result,stlb_merged,stlb_merge_detail,completion_state,"
           "raster_outcome_category\n";
  }

  pimpl_->write_metadata();
  pimpl_->roi_active = true;
}

void DemandTlbPatternLogger::end_phase(bool is_warmup)
{
  if (!is_warmup)
    pimpl_->finalize();
  vberti_cross_page_demand_pattern_logger().end_phase(is_warmup);
}

bool DemandTlbPatternLogger::active() const { return pimpl_->config.enabled && pimpl_->roi_active; }

std::optional<demand_tlb_pattern_event_ref> DemandTlbPatternLogger::next_event_ref(uint32_t cpu) const
{
  if (!active() || cpu >= pimpl_->next_sequence.size())
    return std::nullopt;
  const auto next = pimpl_->next_sequence.at(cpu);
  if (pimpl_->config.max_events_per_core != 0 && next >= pimpl_->config.max_events_per_core)
    return std::nullopt;
  return demand_tlb_pattern_event_ref{cpu, next};
}

void DemandTlbPatternLogger::create_event(demand_tlb_pattern_event_ref ref, const demand_tlb_pattern_event_start& start)
{
  if (!active())
    return;
  if (ref.cpu != start.cpu || ref.cpu >= pimpl_->pending.size() || ref.load_tlb_seq != pimpl_->next_sequence.at(ref.cpu))
    throw std::logic_error("Demand TLB pattern event was committed out of order");

  pattern_event event;
  event.cpu = start.cpu;
  event.load_tlb_seq = ref.load_tlb_seq;
  event.instr_id = start.instr_id;
  event.operand_index = start.operand_index;
  event.pc = start.pc;
  event.dtlb_lookup_cycle = start.dtlb_lookup_cycle;
  event.va = start.va;
  event.vpn = start.va / pimpl_->config.page_size;
  event.virtual_region_2m = start.va / pimpl_->config.region_size;
  event.page_offset_in_region = (start.va % pimpl_->config.region_size) / pimpl_->config.page_size;

  auto [position, inserted] = pimpl_->pending.at(ref.cpu).emplace(ref.load_tlb_seq, event);
  (void)position;
  if (!inserted)
    throw std::logic_error("Duplicate demand TLB pattern event");
  ++pimpl_->next_sequence.at(ref.cpu);
  ++pimpl_->summaries.at(ref.cpu).created_events;
}

void DemandTlbPatternLogger::mark_l1dtlb_rq_merge(const std::vector<demand_tlb_pattern_event_ref>& refs)
{
  for (const auto ref : refs) {
    auto* event = pimpl_->find(ref);
    if (event == nullptr)
      continue;
    if (!event->l1dtlb_merged) {
      event->l1dtlb_merged = true;
      ++pimpl_->summaries.at(ref.cpu).l1dtlb_merges;
    }
    if (event->l1dtlb_merge_detail == dtlb_merge_detail::NONE)
      event->l1dtlb_merge_detail = dtlb_merge_detail::RQ_MERGE;
  }
}

void DemandTlbPatternLogger::mark_l1dtlb_hit(const std::vector<demand_tlb_pattern_event_ref>& refs, bool merged)
{
  for (const auto ref : refs) {
    auto* event = pimpl_->find(ref);
    if (event == nullptr)
      continue;
    if (event->l1dtlb_result == lookup_result::UNKNOWN) {
      event->l1dtlb_result = lookup_result::HIT;
      ++pimpl_->summaries.at(ref.cpu).l1dtlb_hits;
    }
    if (merged && !event->l1dtlb_merged) {
      event->l1dtlb_merged = true;
      ++pimpl_->summaries.at(ref.cpu).l1dtlb_merges;
    }
    if (merged && event->l1dtlb_merge_detail == dtlb_merge_detail::NONE)
      event->l1dtlb_merge_detail = dtlb_merge_detail::RQ_MERGE;
  }
}

void DemandTlbPatternLogger::mark_l1dtlb_miss(const std::vector<demand_tlb_pattern_event_ref>& refs, bool merged, dtlb_merge_detail detail)
{
  for (const auto ref : refs) {
    auto* event = pimpl_->find(ref);
    if (event == nullptr)
      continue;
    if (event->l1dtlb_result == lookup_result::UNKNOWN) {
      event->l1dtlb_result = lookup_result::MISS;
      ++pimpl_->summaries.at(ref.cpu).l1dtlb_misses;
    }
    if (merged && !event->l1dtlb_merged) {
      event->l1dtlb_merged = true;
      ++pimpl_->summaries.at(ref.cpu).l1dtlb_merges;
    }
    if (merged && event->l1dtlb_merge_detail == dtlb_merge_detail::NONE)
      event->l1dtlb_merge_detail = detail == dtlb_merge_detail::NONE ? dtlb_merge_detail::RQ_MERGE : detail;
  }
}

void DemandTlbPatternLogger::mark_stlb_hit(const std::vector<demand_tlb_pattern_event_ref>& refs)
{
  for (const auto ref : refs) {
    auto* event = pimpl_->find(ref);
    if (event == nullptr || event->stlb_accessed)
      continue;
    event->stlb_accessed = true;
    event->stlb_result = lookup_result::HIT;
    ++pimpl_->summaries.at(ref.cpu).stlb_accesses;
    ++pimpl_->summaries.at(ref.cpu).stlb_hits;
  }
}

void DemandTlbPatternLogger::mark_stlb_miss(const std::vector<demand_tlb_pattern_event_ref>& refs, bool merged, dtlb_merge_detail detail)
{
  for (const auto ref : refs) {
    auto* event = pimpl_->find(ref);
    if (event == nullptr)
      continue;
    if (!event->stlb_accessed) {
      event->stlb_accessed = true;
      event->stlb_result = lookup_result::MISS;
      ++pimpl_->summaries.at(ref.cpu).stlb_accesses;
      ++pimpl_->summaries.at(ref.cpu).stlb_misses;
    }
    if (merged && !event->stlb_merged) {
      event->stlb_merged = true;
      ++pimpl_->summaries.at(ref.cpu).stlb_merges;
    }
    if (merged && event->stlb_merge_detail == dtlb_merge_detail::NONE)
      event->stlb_merge_detail = detail == dtlb_merge_detail::NONE ? dtlb_merge_detail::MSHR_TO_OTHER : detail;
  }
}

void DemandTlbPatternLogger::mark_stlb_prelookup_merge(const std::vector<demand_tlb_pattern_event_ref>& refs)
{
  for (const auto ref : refs) {
    auto* event = pimpl_->find(ref);
    if (event == nullptr || event->stlb_merged)
      continue;
    event->stlb_merged = true;
    event->stlb_merge_detail = dtlb_merge_detail::RQ_MERGE;
    ++pimpl_->summaries.at(ref.cpu).stlb_merges;
  }
}

void DemandTlbPatternLogger::complete(const std::vector<demand_tlb_pattern_event_ref>& refs, uint64_t completion_cycle, uint64_t ppn)
{
  for (const auto ref : refs) {
    auto* event = pimpl_->find(ref);
    if (event == nullptr)
      continue;
    // L1D can consume an older same-VPN translation response before this
    // accepted request reaches its own DTLB tag lookup. Treat that event as a
    // pre-lookup L1 DTLB merge, matching the simulator's effective behavior.
    if (event->l1dtlb_result == lookup_result::UNKNOWN) {
      event->l1dtlb_result = lookup_result::MISS;
      ++pimpl_->summaries.at(ref.cpu).l1dtlb_misses;
      if (!event->l1dtlb_merged) {
        event->l1dtlb_merged = true;
        ++pimpl_->summaries.at(ref.cpu).l1dtlb_merges;
      }
      if (event->l1dtlb_merge_detail == dtlb_merge_detail::NONE)
        event->l1dtlb_merge_detail = dtlb_merge_detail::PRELOOKUP_COALESCED;
    }
    event->translation_complete_cycle = completion_cycle;
    event->ppn = ppn;
    event->pa = ppn * pimpl_->config.page_size + event->va % pimpl_->config.page_size;
    event->physical_region_2m = event->pa / pimpl_->config.region_size;
    event->page_offset_in_physical_region = (event->pa % pimpl_->config.region_size) / pimpl_->config.page_size;
    event->physical_address_valid = true;
    pimpl_->write_event(*event, true);
    ++pimpl_->summaries.at(ref.cpu).completed_events;
    pimpl_->pending.at(ref.cpu).erase(ref.load_tlb_seq);
  }
}

DemandTlbPatternLogger& demand_tlb_pattern_logger()
{
  static DemandTlbPatternLogger logger;
  return logger;
}

void append_demand_tlb_pattern_refs(std::vector<demand_tlb_pattern_event_ref>& destination,
                                    const std::vector<demand_tlb_pattern_event_ref>& source)
{
  for (const auto ref : source) {
    if (std::find(std::begin(destination), std::end(destination), ref) == std::end(destination))
      destination.push_back(ref);
  }
}
} // namespace champsim
