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

#include <algorithm>
#include <utility>
#include <nlohmann/json.hpp>

#include "stats_printer.h"

void to_json(nlohmann::json& j, const O3_CPU::stats_type& stats)
{
  constexpr std::array types{branch_type::BRANCH_DIRECT_JUMP, branch_type::BRANCH_INDIRECT,      branch_type::BRANCH_CONDITIONAL,
                             branch_type::BRANCH_DIRECT_CALL, branch_type::BRANCH_INDIRECT_CALL, branch_type::BRANCH_RETURN};

  auto total_mispredictions = std::ceil(
      std::accumulate(std::begin(types), std::end(types), 0LL, [btm = stats.branch_type_misses](auto acc, auto next) { return acc + btm.value_or(next, 0); }));

  std::map<std::string, std::size_t> mpki{};
  for (auto type : types) {
    mpki.emplace(branch_type_names.at(champsim::to_underlying(type)), stats.branch_type_misses.value_or(type, 0));
  }

  j = nlohmann::json{{"instructions", stats.instrs()},
                     {"cycles", stats.cycles()},
                     {"Avg ROB occupancy at mispredict", std::ceil(stats.total_rob_occupancy_at_branch_mispredict) / std::ceil(total_mispredictions)},
                     {"mispredict", mpki}};
}

void to_json(nlohmann::json& j, const CACHE::stats_type& stats)
{
  using hits_value_type = typename decltype(stats.hits)::value_type;
  using misses_value_type = typename decltype(stats.misses)::value_type;
  using mshr_merge_value_type = typename decltype(stats.mshr_merge)::value_type;
  using mshr_return_value_type = typename decltype(stats.mshr_return)::value_type;

  std::map<std::string, nlohmann::json> statsmap;
  statsmap.emplace("prefetch requested", stats.pf_requested);
  statsmap.emplace("prefetch issued", stats.pf_issued);
  statsmap.emplace("useful prefetch", stats.pf_useful);
  statsmap.emplace("useless prefetch", stats.pf_useless);
  statsmap.emplace("too-early prefetch", stats.pf_too_early);
  statsmap.emplace("prefetch pollution evict", stats.pf_pollution_evict);
  statsmap.emplace("prefetch pollution demand", stats.pf_pollution_demand);
  statsmap.emplace("STLB prefetch requested", stats.stlb_prefetch_requested);
  statsmap.emplace("STLB prefetch issued", stats.stlb_prefetch_issued);
  statsmap.emplace("STLB prefetch lookups", stats.stlb_prefetch_lookups);
  statsmap.emplace("STLB prefetch hit", stats.stlb_prefetch_hit);
  statsmap.emplace("STLB prefetch miss", stats.stlb_prefetch_miss);
  statsmap.emplace("STLB prefetch MSHR merge", stats.stlb_prefetch_mshr_merge);
  statsmap.emplace("STLB prefetch fill", stats.stlb_prefetch_fill);
  statsmap.emplace("STLB prefetch useful", stats.stlb_prefetch_useful);
  statsmap.emplace("STLB prefetch useless", stats.stlb_prefetch_useless);
  statsmap.emplace("STLB prefetch late", stats.stlb_prefetch_late);
  statsmap.emplace("STLB prefetch too early", stats.stlb_prefetch_too_early);
  statsmap.emplace("STLB prefetch pollution evict", stats.stlb_prefetch_pollution_evict);
  statsmap.emplace("STLB prefetch pollution demand", stats.stlb_prefetch_pollution_demand);
  statsmap.emplace("vBerti prefetch requested", stats.vberti_prefetch_requested);
  statsmap.emplace("vBerti cross-page requested", stats.vberti_cross_page_requested);
  statsmap.emplace("vBerti prefetch issued", stats.vberti_prefetch_issued);
  statsmap.emplace("vBerti cross-page issued", stats.vberti_cross_page_issued);
  if (stats.cross_page_pf_translation_only_requested > 0 || stats.cross_page_pf_translation_only_issued > 0
      || stats.cross_page_pf_translation_only_dropped > 0) {
    statsmap.emplace("cross-page prefetch translation-only requested", stats.cross_page_pf_translation_only_requested);
    statsmap.emplace("cross-page prefetch translation-only issued", stats.cross_page_pf_translation_only_issued);
    statsmap.emplace("cross-page prefetch translation-only dropped", stats.cross_page_pf_translation_only_dropped);
  }
  statsmap.emplace("cross-page prefetch PQ-full drop", stats.cp_pf_pqfull_drop);
  statsmap.emplace("cross-page prefetch PQ-full TLB rescue enqueued", stats.cp_pf_pqfull_tlb_rescue_enqueued);
  statsmap.emplace("cross-page prefetch PQ-full TLB rescue issued", stats.cp_pf_pqfull_tlb_rescue_issued);
  statsmap.emplace("cross-page prefetch PQ-full TLB rescue translated", stats.cp_pf_pqfull_tlb_rescue_translated);
  statsmap.emplace("TLB cross-page prefetch issued", stats.tlb_cross_prefetch_issued);
  statsmap.emplace("TLB cross-page prefetch useful", stats.tlb_cross_prefetch_useful);
  statsmap.emplace("TLB cross-page prefetch useless", stats.tlb_cross_prefetch_useless);
  statsmap.emplace("TLB cross-page prefetch late", stats.tlb_cross_prefetch_late);
  statsmap.emplace("TLB cross-page prefetch too early", stats.tlb_cross_prefetch_too_early);
  statsmap.emplace("TLB cross-page prefetch pollution evict", stats.tlb_cross_prefetch_pollution_evict);
  statsmap.emplace("TLB cross-page prefetch pollution demand", stats.tlb_cross_prefetch_pollution_demand);
  statsmap.emplace("TLB-system cross-page prefetch issued", stats.tlb_system_cross_prefetch_issued);
  statsmap.emplace("TLB-system cross-page prefetch useful", stats.tlb_system_cross_prefetch_useful);
  statsmap.emplace("TLB-system cross-page prefetch useless", stats.tlb_system_cross_prefetch_useless);
  statsmap.emplace("TLB-system cross-page prefetch late", stats.tlb_system_cross_prefetch_late);
  statsmap.emplace("TLB-system cross-page prefetch too early", stats.tlb_system_cross_prefetch_too_early);
  statsmap.emplace("STLB CP-PB raw demand miss", stats.stlb_cp_pb_raw_demand_miss);
  statsmap.emplace("STLB CP-PB insert", stats.stlb_cp_pb_insert);
  statsmap.emplace("STLB CP-PB demand hit", stats.stlb_cp_pb_demand_hit);
  statsmap.emplace("STLB CP-PB demand miss", stats.stlb_cp_pb_demand_miss);
  if (stats.stlb_prefetch_buffer_insert > 0 || stats.stlb_prefetch_buffer_eviction > 0 || stats.stlb_prefetch_buffer_lookup > 0
      || stats.stlb_prefetch_buffer_hit > 0 || stats.stlb_prefetch_buffer_miss > 0) {
    statsmap.emplace("STLB prefetch buffer insert", stats.stlb_prefetch_buffer_insert);
    statsmap.emplace("STLB prefetch buffer eviction", stats.stlb_prefetch_buffer_eviction);
    statsmap.emplace("STLB prefetch buffer lookup", stats.stlb_prefetch_buffer_lookup);
    statsmap.emplace("STLB prefetch buffer hit", stats.stlb_prefetch_buffer_hit);
    statsmap.emplace("STLB prefetch buffer miss", stats.stlb_prefetch_buffer_miss);
  }

  uint64_t total_downstream_demands = stats.mshr_return.total();
  for (std::size_t cpu = 0; cpu < NUM_CPUS; ++cpu)
    total_downstream_demands -= stats.mshr_return.value_or(std::pair{access_type::PREFETCH, cpu}, mshr_return_value_type{});

  statsmap.emplace("miss latency", std::ceil(stats.total_miss_latency_cycles) / std::ceil(total_downstream_demands));
  for (const auto type : {access_type::LOAD, access_type::RFO, access_type::PREFETCH, access_type::WRITE, access_type::TRANSLATION}) {
    std::vector<hits_value_type> hits;
    std::vector<misses_value_type> misses;
    std::vector<mshr_merge_value_type> mshr_merges;

    for (std::size_t cpu = 0; cpu < NUM_CPUS; ++cpu) {
      hits.push_back(stats.hits.value_or(std::pair{type, cpu}, hits_value_type{}));
      misses.push_back(stats.misses.value_or(std::pair{type, cpu}, misses_value_type{}));
      mshr_merges.push_back(stats.mshr_merge.value_or(std::pair{type, cpu}, mshr_merge_value_type{}));
    }

    statsmap.emplace(access_type_names.at(champsim::to_underlying(type)), nlohmann::json{{"hit", hits}, {"miss", misses}, {"mshr_merge", mshr_merges}});
  }

  j = statsmap;
}

void to_json(nlohmann::json& j, const DRAM_CHANNEL::stats_type stats)
{
  j = nlohmann::json{{"RQ ROW_BUFFER_HIT", stats.RQ_ROW_BUFFER_HIT},
                     {"RQ ROW_BUFFER_MISS", stats.RQ_ROW_BUFFER_MISS},
                     {"WQ ROW_BUFFER_HIT", stats.WQ_ROW_BUFFER_HIT},
                     {"WQ ROW_BUFFER_MISS", stats.WQ_ROW_BUFFER_MISS},
                     {"DRAM RQ read data demand", stats.rq_read_data_demand},
                     {"DRAM RQ read inst demand", stats.rq_read_inst_demand},
                     {"DRAM RQ read cache inst prefetch", stats.rq_read_cache_inst_prefetch},
                     {"DRAM RQ read cache data prefetch", stats.rq_read_cache_data_prefetch},
                     {"DRAM RQ read STLB data demand", stats.rq_read_stlb_data_demand},
                     {"DRAM RQ read STLB inst demand", stats.rq_read_stlb_inst_demand},
                     {"DRAM RQ read STLB L1I prefetch", stats.rq_read_stlb_l1i_pref},
                     {"DRAM RQ read STLB L1D prefetch", stats.rq_read_stlb_l1d_pref},
                     {"DRAM RQ read unclassified", stats.rq_read_unclassified},
                     {"DRAM RQ read total observed", stats.rq_read_total_observed},
                     {"AVG DBUS CONGESTED CYCLE", (std::ceil(stats.dbus_cycle_congested) / std::ceil(stats.dbus_count_congested))},
                     {"REFRESHES ISSUED", stats.refresh_cycles}};
}

void to_json(nlohmann::json& j, const PageTableWalker::stats_type stats)
{
  j = nlohmann::json{{"STLB miss total", stats.stlb_miss_total},
                     {"STLB miss touch DRAM", stats.stlb_miss_touch_dram},
                     {"STLB miss no DRAM touch", stats.stlb_miss_no_dram_touch}};
}

namespace champsim
{
void to_json(nlohmann::json& j, const champsim::phase_stats stats)
{
  std::map<std::string, nlohmann::json> roi_stats;
  roi_stats.emplace("cores", stats.roi_cpu_stats);
  roi_stats.emplace("DRAM", stats.roi_dram_stats);
  roi_stats.emplace("PTW", stats.roi_ptw_stats);
  for (auto x : stats.roi_cache_stats) {
    roi_stats.emplace(x.name, x);
  }

  std::map<std::string, nlohmann::json> sim_stats;
  sim_stats.emplace("cores", stats.sim_cpu_stats);
  sim_stats.emplace("DRAM", stats.sim_dram_stats);
  sim_stats.emplace("PTW", stats.sim_ptw_stats);
  for (auto x : stats.sim_cache_stats) {
    sim_stats.emplace(x.name, x);
  }

  std::map<std::string, nlohmann::json> statsmap{{"name", stats.name}, {"traces", stats.trace_names}};
  statsmap.emplace("roi", roi_stats);
  statsmap.emplace("sim", sim_stats);
  j = statsmap;
}
} // namespace champsim

void champsim::json_printer::print(std::vector<phase_stats>& stats) { stream << nlohmann::json::array_t{std::begin(stats), std::end(stats)}; }
