/*
 *    Copyright 2023 The ChampSim Contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 */

#ifndef DEMAND_TLB_PATTERN_H
#define DEMAND_TLB_PATTERN_H

#include <cstdint>
#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace champsim
{
enum class demand_tlb_pattern_stage : uint8_t {
  NONE = 0,
  L1_DTLB,
  STLB,
};

// Mutually exclusive observation-only explanation of a DTLB/STLB-side
// translation merge. MSHR values describe the origin stored in the existing
// level-local MSHR immediately before the new request is merged into it.
enum class dtlb_merge_detail : uint8_t {
  NONE = 0,
  RQ_MERGE,
  MSHR_TO_DATA_DEMAND,
  MSHR_TO_INST_DEMAND,
  MSHR_TO_L1D_PREFETCH,
  MSHR_TO_CP_PREFETCH,
  MSHR_TO_SP_PREFETCH,
  MSHR_TO_L1I_PREFETCH,
  MSHR_TO_OTHER,
  PRELOOKUP_COALESCED,
};

struct demand_tlb_pattern_event_ref {
  uint32_t cpu = std::numeric_limits<uint32_t>::max();
  uint64_t load_tlb_seq = 0;

  friend bool operator==(const demand_tlb_pattern_event_ref& lhs, const demand_tlb_pattern_event_ref& rhs)
  {
    return lhs.cpu == rhs.cpu && lhs.load_tlb_seq == rhs.load_tlb_seq;
  }
};

struct demand_tlb_pattern_config {
  bool enabled = false;
  std::string output_directory = "demand_tlb_pattern";
  uint64_t max_events_per_core = 0;
  uint64_t page_size = 4096;
  uint64_t region_size = 2 * 1024 * 1024;
  std::size_t num_cores = 0;
  uint64_t warmup_instructions = 0;
  uint64_t simulation_instructions = 0;
  std::vector<std::string> trace_names{};
  std::string executable_name{};
};

struct demand_tlb_pattern_event_start {
  uint32_t cpu = 0;
  uint64_t instr_id = 0;
  uint32_t operand_index = 0;
  uint64_t pc = 0;
  uint64_t va = 0;
  uint64_t dtlb_lookup_cycle = 0;
};

// Optional, observation-only stream used to place real data-demand TLB
// requests and actual vBerti cross-page DTLB requests on one per-core event
// axis.  It deliberately owns no simulator resources and never participates
// in queueing, matching, replacement, or statistics.
enum class vberti_tlb_pattern_event_type : uint8_t {
  DATA_DEMAND = 0,
  VBERTI_CP_PREFETCH,
};

enum class vberti_tlb_pattern_stage : uint8_t {
  NONE = 0,
  L1_DTLB,
  STLB,
};

struct vberti_tlb_pattern_event_ref {
  uint32_t cpu = 0;
  uint64_t global_seq = 0;
  uint64_t local_seq = 0;
  vberti_tlb_pattern_event_type event_type = vberti_tlb_pattern_event_type::DATA_DEMAND;

  friend bool operator==(const vberti_tlb_pattern_event_ref& lhs, const vberti_tlb_pattern_event_ref& rhs)
  {
    return lhs.cpu == rhs.cpu && lhs.global_seq == rhs.global_seq && lhs.local_seq == rhs.local_seq && lhs.event_type == rhs.event_type;
  }
};

struct vberti_tlb_pattern_event_start {
  uint32_t cpu = 0;
  uint64_t instr_id = 0;
  uint32_t operand_index = std::numeric_limits<uint32_t>::max();
  uint64_t pc = 0;
  uint64_t va = 0;
  uint64_t dtlb_lookup_cycle = 0;
  uint64_t vberti_prefetch_seq = 0;
};

class VbertiCrossPageDemandPatternLogger
{
  class impl;
  std::unique_ptr<impl> pimpl_;

public:
  VbertiCrossPageDemandPatternLogger();
  ~VbertiCrossPageDemandPatternLogger();
  VbertiCrossPageDemandPatternLogger(const VbertiCrossPageDemandPatternLogger&) = delete;
  VbertiCrossPageDemandPatternLogger& operator=(const VbertiCrossPageDemandPatternLogger&) = delete;

  void configure(const demand_tlb_pattern_config& base_config);
  void begin_phase(bool is_warmup);
  void end_phase(bool is_warmup);

  [[nodiscard]] bool active() const;
  [[nodiscard]] std::optional<vberti_tlb_pattern_event_ref> next_event_ref(uint32_t cpu, vberti_tlb_pattern_event_type event_type) const;
  void create_event(vberti_tlb_pattern_event_ref ref, const vberti_tlb_pattern_event_start& start);
  void mark_l1dtlb_rq_merge(const std::vector<vberti_tlb_pattern_event_ref>& refs);
  void mark_l1dtlb_hit(const std::vector<vberti_tlb_pattern_event_ref>& refs, bool merged);
  void mark_l1dtlb_miss(const std::vector<vberti_tlb_pattern_event_ref>& refs, bool merged, dtlb_merge_detail detail = dtlb_merge_detail::NONE);
  void mark_stlb_hit(const std::vector<vberti_tlb_pattern_event_ref>& refs);
  void mark_stlb_miss(const std::vector<vberti_tlb_pattern_event_ref>& refs, bool merged,
                      dtlb_merge_detail detail = dtlb_merge_detail::NONE);
  void mark_stlb_prelookup_merge(const std::vector<vberti_tlb_pattern_event_ref>& refs);
  void complete(const std::vector<vberti_tlb_pattern_event_ref>& refs, uint64_t completion_cycle, uint64_t ppn);
};

class DemandTlbPatternLogger
{
  class impl;
  std::unique_ptr<impl> pimpl_;

public:
  DemandTlbPatternLogger();
  ~DemandTlbPatternLogger();
  DemandTlbPatternLogger(const DemandTlbPatternLogger&) = delete;
  DemandTlbPatternLogger& operator=(const DemandTlbPatternLogger&) = delete;

  void configure(demand_tlb_pattern_config config);
  void begin_phase(bool is_warmup);
  void end_phase(bool is_warmup);

  [[nodiscard]] bool active() const;
  [[nodiscard]] std::optional<demand_tlb_pattern_event_ref> next_event_ref(uint32_t cpu) const;
  void create_event(demand_tlb_pattern_event_ref ref, const demand_tlb_pattern_event_start& start);

  void mark_l1dtlb_rq_merge(const std::vector<demand_tlb_pattern_event_ref>& refs);
  void mark_l1dtlb_hit(const std::vector<demand_tlb_pattern_event_ref>& refs, bool merged);
  void mark_l1dtlb_miss(const std::vector<demand_tlb_pattern_event_ref>& refs, bool merged, dtlb_merge_detail detail = dtlb_merge_detail::NONE);
  void mark_stlb_hit(const std::vector<demand_tlb_pattern_event_ref>& refs);
  void mark_stlb_miss(const std::vector<demand_tlb_pattern_event_ref>& refs, bool merged,
                      dtlb_merge_detail detail = dtlb_merge_detail::NONE);
  void mark_stlb_prelookup_merge(const std::vector<demand_tlb_pattern_event_ref>& refs);
  void complete(const std::vector<demand_tlb_pattern_event_ref>& refs, uint64_t completion_cycle, uint64_t ppn);
};

DemandTlbPatternLogger& demand_tlb_pattern_logger();
VbertiCrossPageDemandPatternLogger& vberti_cross_page_demand_pattern_logger();
void append_vberti_tlb_pattern_refs(std::vector<vberti_tlb_pattern_event_ref>& destination,
                                    const std::vector<vberti_tlb_pattern_event_ref>& source);
void append_demand_tlb_pattern_refs(std::vector<demand_tlb_pattern_event_ref>& destination,
                                    const std::vector<demand_tlb_pattern_event_ref>& source);
} // namespace champsim

#endif
