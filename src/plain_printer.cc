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

#include <cctype>
#include <cmath>
#include <map>
#include <numeric>
#include <ratio>
#include <set>
#include <string_view> // for string_view
#include <utility>
#include <vector>
#include <fmt/chrono.h>
#include <fmt/core.h>
#include <fmt/ostream.h>

#include "stats_printer.h"
#include "tlb_ptw_system_stats.h"

namespace
{
template <typename N, typename D>
auto print_ratio(N num, D denom)
{
  if (denom > 0) {
    return fmt::format("{:.4g}", std::ceil(num) / std::ceil(denom));
  }
  return std::string{"-"};
}

template <typename N, typename D>
double ratio_or_zero(N num, D denom)
{
  if (denom > 0)
    return static_cast<double>(num) / static_cast<double>(denom);
  return 0.0;
}

std::string join_or_no(const std::vector<std::string>& names)
{
  if (names.empty())
    return "no";
  return fmt::format("{}", fmt::join(names, ","));
}

std::string normalize_cache_name(std::string name)
{
  auto pos = name.find('_');
  if (pos != std::string::npos)
    return name.substr(pos + 1);
  return name;
}

std::string cache_label(std::size_t cpu, const std::string& cache_name)
{
  return fmt::format("Core_{}_{}", cpu, normalize_cache_name(cache_name));
}

std::string config_label(const std::string& cache_name)
{
  std::string label = cache_name;
  if (label.rfind("cpu", 0) == 0) {
    const auto suffix_pos = label.find('_');
    if (suffix_pos != std::string::npos)
      label = fmt::format("Core_{}_{}", label.substr(3, suffix_pos - 3), label.substr(suffix_pos + 1));
  }
  std::transform(std::begin(label), std::end(label), std::begin(label), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return label;
}

std::vector<std::size_t> cache_cpus(const CACHE::stats_type& stats)
{
  std::vector<std::size_t> cpus;
  auto stat_keys = {stats.hits.get_keys(), stats.misses.get_keys(), stats.mshr_merge.get_keys(), stats.mshr_return.get_keys()};
  for (auto keys : stat_keys) {
    std::transform(std::begin(keys), std::end(keys), std::back_inserter(cpus), [](auto val) { return val.second; });
  }
  std::sort(std::begin(cpus), std::end(cpus));
  auto uniq_end = std::unique(std::begin(cpus), std::end(cpus));
  cpus.erase(uniq_end, std::end(cpus));
  return cpus;
}

template <typename Counter>
auto counter_value(const Counter& counter, access_type type, std::size_t cpu)
{
  return counter.value_or(std::pair{type, cpu}, typename Counter::value_type{});
}

uint64_t access_count(const CACHE::stats_type& stats, access_type type, std::size_t cpu)
{
  return counter_value(stats.hits, type, cpu) + counter_value(stats.misses, type, cpu);
}

uint64_t hit_count(const CACHE::stats_type& stats, access_type type, std::size_t cpu) { return counter_value(stats.hits, type, cpu); }

uint64_t miss_count(const CACHE::stats_type& stats, access_type type, std::size_t cpu) { return counter_value(stats.misses, type, cpu); }

template <typename Counter>
auto origin_counter_value(const Counter& counter, translation_origin origin, std::size_t cpu)
{
  return counter.value_or(std::pair{origin, cpu}, typename Counter::value_type{});
}

template <typename Counter>
uint64_t origin_access_count(const Counter& hits, const Counter& misses, translation_origin origin, std::size_t cpu)
{
  return origin_counter_value(hits, origin, cpu) + origin_counter_value(misses, origin, cpu);
}

template <typename Counter>
uint64_t demand_origin_count(const Counter& counter, std::size_t cpu)
{
  return origin_counter_value(counter, translation_origin::DEMAND_DATA, cpu) + origin_counter_value(counter, translation_origin::DEMAND_INSTRUCTION, cpu);
}

template <typename Counter>
uint64_t l1d_prefetch_origin_count(const Counter& counter, std::size_t cpu)
{
  return origin_counter_value(counter, translation_origin::L1D_PREFETCH, cpu)
         + origin_counter_value(counter, translation_origin::L1D_PREFETCH_SAME_PAGE, cpu)
         + origin_counter_value(counter, translation_origin::L1D_PREFETCH_CROSS_PAGE, cpu);
}

std::vector<std::string> format_stlb_miss_cause_block(const CACHE::stats_type& stats, std::size_t cpu)
{
  std::vector<std::string> lines;
  lines.emplace_back("");
  lines.emplace_back("======STLB miss causes ========");

  const std::array detailed_origins{translation_origin::DEMAND_DATA,      translation_origin::DEMAND_INSTRUCTION,       translation_origin::L1D_PREFETCH,
                                    translation_origin::L1D_PREFETCH_SAME_PAGE, translation_origin::L1D_PREFETCH_CROSS_PAGE, translation_origin::L1I_PREFETCH,
                                    translation_origin::OTHER};
  const std::array detailed_names{"Demand_Data", "Demand_Instruction", "L1D_Prefetch", "L1D_Prefetch_Same_Page",
                                  "L1D_Prefetch_Cross_Page", "L1I_Prefetch", "Other"};

  const auto label = cache_label(cpu, stats.name);
  const auto stlb_total_access = access_count(stats, access_type::LOAD, cpu) + access_count(stats, access_type::RFO, cpu)
                                 + access_count(stats, access_type::PREFETCH, cpu) + access_count(stats, access_type::WRITE, cpu);
  lines.push_back(fmt::format("{}_miss_cause_breakdown", label));

  for (std::size_t idx = 0; idx < std::size(detailed_origins); ++idx) {
    const auto origin = detailed_origins.at(idx);
    const auto misses = origin == translation_origin::L1D_PREFETCH ? l1d_prefetch_origin_count(stats.stlb_origin_misses, cpu)
                                                                   : origin_counter_value(stats.stlb_origin_misses, origin, cpu);
    lines.push_back(fmt::format("{}_cause_{}_miss {}", label, detailed_names.at(idx), misses));
    lines.push_back(fmt::format("{}_cause_{}_miss_rate {:.6g}", label, detailed_names.at(idx), ratio_or_zero(misses, stlb_total_access)));
  }

  const auto demand_misses = demand_origin_count(stats.stlb_origin_misses, cpu);
  const auto l1d_prefetch_misses = l1d_prefetch_origin_count(stats.stlb_origin_misses, cpu);
  const auto other_misses = origin_counter_value(stats.stlb_origin_misses, translation_origin::L1I_PREFETCH, cpu)
                            + origin_counter_value(stats.stlb_origin_misses, translation_origin::OTHER, cpu);

  lines.push_back(fmt::format("{}_Demand_miss {}", label, demand_misses));
  lines.push_back(fmt::format("{}_Demand_miss_rate {:.6g}", label, ratio_or_zero(demand_misses, stlb_total_access)));
  lines.push_back(fmt::format("{}_L1D_Prefetch_miss {}", label, l1d_prefetch_misses));
  lines.push_back(fmt::format("{}_L1D_Prefetch_miss_rate {:.6g}", label, ratio_or_zero(l1d_prefetch_misses, stlb_total_access)));
  lines.push_back(fmt::format("{}_Other_miss {}", label, other_misses));
  lines.push_back(fmt::format("{}_Other_miss_rate {:.6g}", label, ratio_or_zero(other_misses, stlb_total_access)));

  return lines;
}

std::vector<std::string> format_dram_rq_read_traffic(const std::vector<DRAM_CHANNEL::stats_type>& dram_stats, uint64_t roi_instructions)
{
  std::vector<std::string> lines;

  uint64_t data_demand_read = 0;
  uint64_t inst_demand_read = 0;
  uint64_t cache_inst_prefetch = 0;
  uint64_t cache_data_prefetch = 0;
  uint64_t stlb_data_demand = 0;
  uint64_t stlb_inst_demand = 0;
  uint64_t stlb_l1i_pref = 0;
  uint64_t stlb_l1d_pref = 0;
  uint64_t unclassified_read = 0;
  uint64_t dram_rq_read_total_observed = 0;

  for (const auto& stats : dram_stats) {
    data_demand_read += stats.rq_read_data_demand;
    inst_demand_read += stats.rq_read_inst_demand;
    cache_inst_prefetch += stats.rq_read_cache_inst_prefetch;
    cache_data_prefetch += stats.rq_read_cache_data_prefetch;
    stlb_data_demand += stats.rq_read_stlb_data_demand;
    stlb_inst_demand += stats.rq_read_stlb_inst_demand;
    stlb_l1i_pref += stats.rq_read_stlb_l1i_pref;
    stlb_l1d_pref += stats.rq_read_stlb_l1d_pref;
    unclassified_read += stats.rq_read_unclassified;
    dram_rq_read_total_observed += stats.rq_read_total_observed;
  }

  const auto total_classified_read = data_demand_read + inst_demand_read + cache_inst_prefetch + cache_data_prefetch + stlb_data_demand + stlb_inst_demand
                                     + stlb_l1i_pref + stlb_l1d_pref;
  const auto cache_demand = data_demand_read + inst_demand_read;
  const auto cache_prefetch = cache_inst_prefetch + cache_data_prefetch;
  const auto stlb_demand = stlb_data_demand + stlb_inst_demand;
  const auto stlb_prefetch = stlb_l1i_pref + stlb_l1d_pref;
  const auto total_read_with_other = total_classified_read + unclassified_read;
  const auto classified_plus_unclassified_check = total_read_with_other;

  auto append_count_share = [&lines, total_classified_read](std::string_view key, uint64_t count) {
    lines.push_back(fmt::format("{}.count = {}", key, count));
    lines.push_back(fmt::format("{}.share = {:.2f}%", key, 100.0 * ratio_or_zero(count, total_classified_read)));
    lines.emplace_back("");
  };

  lines.emplace_back("");
  lines.emplace_back("====== DRAM_RQ_TRAFFIC ========");
  lines.emplace_back("DRAM_RQ_READ_TRAFFIC_BREAKDOWN:");
  append_count_share("data_demand_read", data_demand_read);
  append_count_share("inst_demand_read", inst_demand_read);
  append_count_share("cache_inst_prefetch", cache_inst_prefetch);
  append_count_share("cache_data_prefetch", cache_data_prefetch);
  append_count_share("stlb_data_demand", stlb_data_demand);
  append_count_share("stlb_inst_demand", stlb_inst_demand);
  append_count_share("stlb_l1i_pref", stlb_l1i_pref);
  append_count_share("stlb_l1d_pref", stlb_l1d_pref);

  lines.emplace_back("DRAM_RQ_READ_TRAFFIC_SUMMARY:");
  append_count_share("cache_demand", cache_demand);
  append_count_share("cache_prefetch", cache_prefetch);
  append_count_share("stlb_demand", stlb_demand);
  append_count_share("stlb_prefetch", stlb_prefetch);

  lines.emplace_back("DRAM_RQ_READ_TRAFFIC_DEBUG:");
  lines.push_back(fmt::format("total_classified_read.count = {}", total_classified_read));
  lines.push_back(fmt::format("unclassified_read.count = {}", unclassified_read));
  lines.push_back(fmt::format("total_read_with_other.count = {}", total_read_with_other));
  lines.emplace_back("");
  lines.push_back(fmt::format("classified_plus_unclassified_check.count = {}", classified_plus_unclassified_check));
  lines.push_back(fmt::format("dram_rq_read_total_observed.count = {}", dram_rq_read_total_observed));
  lines.push_back(fmt::format("dram_rq_read_total_observed.per_1K_instructions = {:.6g}",
                              ratio_or_zero(dram_rq_read_total_observed * 1000.0, roi_instructions)));

  return lines;
}

std::vector<std::string> format_stlb_miss_ptw_dram_touch(const std::vector<PageTableWalker::stats_type>& ptw_stats)
{
  std::vector<std::string> lines;
  uint64_t stlb_miss_total = 0;
  uint64_t stlb_miss_touch_dram = 0;
  uint64_t stlb_miss_no_dram_touch = 0;

  for (const auto& stats : ptw_stats) {
    stlb_miss_total += stats.stlb_miss_total;
    stlb_miss_touch_dram += stats.stlb_miss_touch_dram;
    stlb_miss_no_dram_touch += stats.stlb_miss_no_dram_touch;
  }

  const auto stlb_miss_touch_plus_no_touch = stlb_miss_touch_dram + stlb_miss_no_dram_touch;

  lines.emplace_back("");
  lines.emplace_back("STLB_MISS_PTW_DRAM_TOUCH_BREAKDOWN:");
  lines.push_back(fmt::format("stlb_miss_total.count = {}", stlb_miss_total));
  lines.emplace_back("");
  lines.push_back(fmt::format("stlb_miss_touch_dram.count = {}", stlb_miss_touch_dram));
  lines.push_back(fmt::format("stlb_miss_touch_dram.share = {:.2f}%", 100.0 * ratio_or_zero(stlb_miss_touch_dram, stlb_miss_total)));
  lines.emplace_back("");
  lines.push_back(fmt::format("stlb_miss_no_dram_touch.count = {}", stlb_miss_no_dram_touch));
  lines.push_back(fmt::format("stlb_miss_no_dram_touch.share = {:.2f}%", 100.0 * ratio_or_zero(stlb_miss_no_dram_touch, stlb_miss_total)));

  lines.emplace_back("");
  lines.emplace_back("STLB_MISS_PTW_DRAM_TOUCH_DEBUG:");
  lines.push_back(fmt::format("stlb_miss_touch_plus_no_touch.count = {}", stlb_miss_touch_plus_no_touch));
  lines.push_back(fmt::format("stlb_miss_total_check.count = {}", stlb_miss_total));

  return lines;
}

std::vector<std::string> format_cache_metric_block(const CACHE::stats_type& stats, std::size_t cpu, long long instrs)
{
  std::vector<std::string> lines;
  const auto label = cache_label(cpu, stats.name);
  const auto is_stlb_stats = stats.name.size() >= 5 && stats.name.compare(stats.name.size() - 5, 5, "_STLB") == 0;
  const std::array types{access_type::LOAD, access_type::RFO, access_type::PREFETCH, access_type::WRITE};
  const std::array names{"load", "rfo", "prefetch", "writeback"};

  uint64_t total_access = 0;
  uint64_t total_hit = 0;
  uint64_t total_miss = 0;
  for (auto type : types) {
    total_access += access_count(stats, type, cpu);
    total_hit += hit_count(stats, type, cpu);
    total_miss += miss_count(stats, type, cpu);
  }

  lines.push_back(fmt::format("{}_total_access {}", label, total_access));
  lines.push_back(fmt::format("{}_total_hit {}", label, total_hit));
  lines.push_back(fmt::format("{}_total_miss {}", label, total_miss));
  lines.push_back(fmt::format("{}_total_MPKI {:.6g}", label, ratio_or_zero(total_miss * 1000.0, instrs)));
  lines.push_back(fmt::format("{}_total_miss_rate {:.6g}", label, ratio_or_zero(total_miss, total_access)));

  const auto demand_access = access_count(stats, access_type::LOAD, cpu) + access_count(stats, access_type::RFO, cpu);
  const auto demand_hit = hit_count(stats, access_type::LOAD, cpu) + hit_count(stats, access_type::RFO, cpu);
  const auto demand_miss = miss_count(stats, access_type::LOAD, cpu) + miss_count(stats, access_type::RFO, cpu);
  lines.push_back(fmt::format("{}_demand_access {}", label, demand_access));
  lines.push_back(fmt::format("{}_demand_hit {}", label, demand_hit));
  lines.push_back(fmt::format("{}_demand_miss {}", label, demand_miss));
  lines.push_back(fmt::format("{}_demand_MPKI {:.6g}", label, ratio_or_zero(demand_miss * 1000.0, instrs)));
  lines.push_back(fmt::format("{}_demand_miss_rate {:.6g}", label, ratio_or_zero(demand_miss, demand_access)));

  for (std::size_t idx = 0; idx < std::size(types); ++idx) {
    auto type = types.at(idx);
    auto name = names.at(idx);
    auto accesses = access_count(stats, type, cpu);
    auto hits = hit_count(stats, type, cpu);
    auto misses = miss_count(stats, type, cpu);
    // When an STLB-local predictor is active, keep the established prefetch
    // labels but report only its requests. Other translation-prefetch origins
    // retain the legacy aggregate values when the local predictor is disabled.
    if (is_stlb_stats && type == access_type::PREFETCH && stats.stlb_prefetch_requested > 0) {
      accesses = stats.stlb_prefetch_lookups;
      hits = stats.stlb_prefetch_hit;
      misses = stats.stlb_prefetch_miss;
    }
    lines.push_back(fmt::format("{}_{}_access {}", label, name, accesses));
    lines.push_back(fmt::format("{}_{}_hit {}", label, name, hits));
    lines.push_back(fmt::format("{}_{}_miss {}", label, name, misses));
    lines.push_back(fmt::format("{}_{}_MPKI {:.6g}", label, name, ratio_or_zero(misses * 1000.0, instrs)));
    lines.push_back(fmt::format("{}_{}_miss_rate {:.6g}", label, name, ratio_or_zero(misses, accesses)));
  }

  const auto pf_requested = is_stlb_stats ? stats.stlb_prefetch_requested : stats.pf_requested;
  const auto pf_issued = is_stlb_stats ? stats.stlb_prefetch_issued : stats.pf_issued;
  const auto pf_useful = is_stlb_stats ? stats.stlb_prefetch_useful : stats.pf_useful;
  const auto pf_useless = is_stlb_stats ? stats.stlb_prefetch_useless : stats.pf_useless;
  const auto pf_late = is_stlb_stats ? stats.stlb_prefetch_late : stats.pf_late;
  const auto pf_fill = is_stlb_stats ? stats.stlb_prefetch_fill : stats.pf_fill;
  const auto pf_too_early = is_stlb_stats ? stats.stlb_prefetch_too_early : stats.pf_too_early;
  const auto pf_pollution_evict = is_stlb_stats ? stats.stlb_prefetch_pollution_evict : stats.pf_pollution_evict;
  const auto pf_pollution_demand = is_stlb_stats ? stats.stlb_prefetch_pollution_demand : stats.pf_pollution_demand;
  lines.push_back(fmt::format("{}_prefetch_requested {}", label, pf_requested));
  lines.push_back(fmt::format("{}_prefetch_issued {}", label, pf_issued));
  lines.push_back(fmt::format("{}_prefetch_useful {}", label, pf_useful));
  lines.push_back(fmt::format("{}_prefetch_useless {}", label, pf_useless));
  lines.push_back(fmt::format("{}_prefetch_late {}", label, pf_late));
  lines.push_back(fmt::format("{}_prefetch_fill {}", label, pf_fill));
  lines.push_back(fmt::format("{}_prefetch_too_early {}", label, pf_too_early));
  lines.push_back(fmt::format("{}_prefetch_too_early_among_fill {:.6g}", label, ratio_or_zero(pf_too_early, pf_fill)));
  lines.push_back(fmt::format("{}_prefetch_too_early_among_useless {:.6g}", label, ratio_or_zero(pf_too_early, pf_useless)));
  lines.push_back(fmt::format("{}_prefetch_pollution_evict {}", label, pf_pollution_evict));
  lines.push_back(fmt::format("{}_prefetch_pollution_demand {}", label, pf_pollution_demand));
  if (stats.cross_page_pf_translation_only_requested > 0 || stats.cross_page_pf_translation_only_issued > 0
      || stats.cross_page_pf_translation_only_dropped > 0) {
    lines.push_back(fmt::format("{}_cross_page_pf_translation_only_requested {}", label, stats.cross_page_pf_translation_only_requested));
    lines.push_back(fmt::format("{}_cross_page_pf_translation_only_issued {}", label, stats.cross_page_pf_translation_only_issued));
    lines.push_back(fmt::format("{}_cross_page_pf_translation_only_dropped {}", label, stats.cross_page_pf_translation_only_dropped));
  }
  lines.push_back(fmt::format("{}_prefetch_pollution_among_prefetch_fill {:.6g}", label, ratio_or_zero(pf_pollution_evict, pf_fill)));
  lines.push_back(fmt::format("{}_prefetch_accuracy {:.6g}", label, ratio_or_zero(pf_useful, pf_issued)));
  if (stats.name.size() >= 4 && stats.name.compare(stats.name.size() - 4, 4, "_L1D") == 0)
    lines.push_back(fmt::format("{}_prefetch_accuracy_berti_artifact {:.6g}", label,
                                ratio_or_zero(stats.pf_useful, stats.pf_useful + stats.pf_useless)));
  const auto coverage_demand_miss = is_stlb_stats ? demand_origin_count(stats.stlb_origin_misses, cpu) : demand_miss;
  lines.push_back(fmt::format("{}_prefetch_coverage {:.6g}", label, ratio_or_zero(pf_useful, pf_useful + coverage_demand_miss)));

  if (is_stlb_stats && stats.stlb_prefetch_requested > 0) {
    const auto dropped = pf_requested >= pf_issued ? pf_requested - pf_issued : 0;
    const auto timely = pf_useful >= pf_late ? pf_useful - pf_late : 0;
    lines.push_back(fmt::format("{}_pq_drop_rate {:.6g}", label, ratio_or_zero(dropped, pf_requested)));
    lines.push_back(fmt::format("{}_prefetch_lookups {}", label, stats.stlb_prefetch_lookups));
    lines.push_back(fmt::format("{}_prefetch_mshr_merge {}", label, stats.stlb_prefetch_mshr_merge));
    lines.push_back(fmt::format("{}_prefetch_mpki {:.6g}", label, ratio_or_zero(stats.stlb_prefetch_lookups * 1000.0, instrs)));
    lines.push_back(fmt::format("{}_timely_coverage {:.6g}", label, ratio_or_zero(timely, pf_useful + coverage_demand_miss)));
    lines.push_back(fmt::format("{}_timely_accuracy {:.6g}", label, ratio_or_zero(timely, pf_issued)));
    lines.push_back(fmt::format("{}_fill_accuracy {:.6g}", label, ratio_or_zero(timely + pf_late, pf_fill)));
  }

  return lines;
}

struct tlb_origin_counts {
  uint64_t demand_access = 0;
  uint64_t demand_hit = 0;
  uint64_t demand_miss = 0;
  uint64_t demand_mshr_merge = 0;
  uint64_t demand_fill = 0;
  uint64_t same_access = 0;
  uint64_t same_hit = 0;
  uint64_t same_miss = 0;
  uint64_t same_mshr_merge = 0;
  uint64_t same_fill = 0;
  uint64_t cross_access = 0;
  uint64_t cross_hit = 0;
  uint64_t cross_miss = 0;
  uint64_t cross_mshr_merge = 0;
  uint64_t cross_fill = 0;
};

tlb_origin_counts get_dtlb_origin_counts(const CACHE::stats_type& stats, std::size_t cpu)
{
  const auto demand_hit = demand_origin_count(stats.dtlb_origin_hits, cpu);
  const auto demand_miss = demand_origin_count(stats.dtlb_origin_misses, cpu);
  const auto same_hit = static_cast<uint64_t>(origin_counter_value(stats.dtlb_origin_hits, translation_origin::L1D_PREFETCH_SAME_PAGE, cpu));
  const auto same_miss = static_cast<uint64_t>(origin_counter_value(stats.dtlb_origin_misses, translation_origin::L1D_PREFETCH_SAME_PAGE, cpu));
  const auto cross_hit = static_cast<uint64_t>(origin_counter_value(stats.dtlb_origin_hits, translation_origin::L1D_PREFETCH_CROSS_PAGE, cpu));
  const auto cross_miss = static_cast<uint64_t>(origin_counter_value(stats.dtlb_origin_misses, translation_origin::L1D_PREFETCH_CROSS_PAGE, cpu));
  const auto same_merge =
      static_cast<uint64_t>(origin_counter_value(stats.tlb_origin_mshr_merge, translation_origin::L1D_PREFETCH_SAME_PAGE, cpu));
  const auto cross_merge =
      static_cast<uint64_t>(origin_counter_value(stats.tlb_origin_mshr_merge, translation_origin::L1D_PREFETCH_CROSS_PAGE, cpu));

  return {
      demand_hit + demand_miss,
      demand_hit,
      demand_miss,
      demand_origin_count(stats.tlb_origin_mshr_merge, cpu),
      demand_origin_count(stats.tlb_origin_fills, cpu),
      same_hit + same_miss,
      same_hit,
      same_miss,
      same_merge,
      static_cast<uint64_t>(origin_counter_value(stats.tlb_origin_fills, translation_origin::L1D_PREFETCH_SAME_PAGE, cpu)),
      cross_hit + cross_miss,
      cross_hit,
      cross_miss,
      cross_merge,
      static_cast<uint64_t>(origin_counter_value(stats.tlb_origin_fills, translation_origin::L1D_PREFETCH_CROSS_PAGE, cpu)),
  };
}

tlb_origin_counts get_stlb_origin_counts(const CACHE::stats_type& stats, std::size_t cpu)
{
  const auto demand_hit = demand_origin_count(stats.stlb_origin_hits, cpu);
  const auto demand_miss = demand_origin_count(stats.stlb_origin_misses, cpu);
  const auto same_hit = static_cast<uint64_t>(origin_counter_value(stats.stlb_origin_hits, translation_origin::L1D_PREFETCH_SAME_PAGE, cpu));
  const auto same_miss = static_cast<uint64_t>(origin_counter_value(stats.stlb_origin_misses, translation_origin::L1D_PREFETCH_SAME_PAGE, cpu));
  const auto cross_hit = static_cast<uint64_t>(origin_counter_value(stats.stlb_origin_hits, translation_origin::L1D_PREFETCH_CROSS_PAGE, cpu));
  const auto cross_miss = static_cast<uint64_t>(origin_counter_value(stats.stlb_origin_misses, translation_origin::L1D_PREFETCH_CROSS_PAGE, cpu));
  const auto same_merge =
      static_cast<uint64_t>(origin_counter_value(stats.tlb_origin_mshr_merge, translation_origin::L1D_PREFETCH_SAME_PAGE, cpu));
  const auto cross_merge =
      static_cast<uint64_t>(origin_counter_value(stats.tlb_origin_mshr_merge, translation_origin::L1D_PREFETCH_CROSS_PAGE, cpu));

  return {
      demand_hit + demand_miss,
      demand_hit,
      demand_miss,
      demand_origin_count(stats.tlb_origin_mshr_merge, cpu),
      demand_origin_count(stats.tlb_origin_fills, cpu),
      same_hit + same_miss,
      same_hit,
      same_miss,
      same_merge,
      static_cast<uint64_t>(origin_counter_value(stats.tlb_origin_fills, translation_origin::L1D_PREFETCH_SAME_PAGE, cpu)),
      cross_hit + cross_miss,
      cross_hit,
      cross_miss,
      cross_merge,
      static_cast<uint64_t>(origin_counter_value(stats.tlb_origin_fills, translation_origin::L1D_PREFETCH_CROSS_PAGE, cpu)),
  };
}

void append_tlb_quality_metrics(std::vector<std::string>& lines, std::string_view label, const tlb_origin_counts& counts, uint64_t instrs, uint64_t issued,
                                uint64_t useful, uint64_t useless, uint64_t late, uint64_t too_early)
{
  lines.push_back(fmt::format("{}_demand_miss_rate {:.6g}", label, ratio_or_zero(counts.demand_miss, counts.demand_access)));
  lines.push_back(fmt::format("{}_demand_mpki {:.6g}", label, ratio_or_zero(counts.demand_miss * 1000.0, instrs)));
  lines.push_back(fmt::format("{}_same_page_prefetch_miss_rate {:.6g}", label, ratio_or_zero(counts.same_miss, counts.same_access)));
  lines.push_back(fmt::format("{}_same_page_prefetch_mpki {:.6g}", label, ratio_or_zero(counts.same_miss * 1000.0, instrs)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_miss_rate {:.6g}", label, ratio_or_zero(counts.cross_miss, counts.cross_access)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_mpki {:.6g}", label, ratio_or_zero(counts.cross_miss * 1000.0, instrs)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_issued {}", label, issued));
  lines.push_back(fmt::format("{}_cross_page_prefetch_lookups {}", label, counts.cross_access));
  lines.push_back(fmt::format("{}_cross_page_prefetch_useful {}", label, useful));
  lines.push_back(fmt::format("{}_cross_page_prefetch_useless {}", label, useless));
  lines.push_back(fmt::format("{}_cross_page_prefetch_late {}", label, late));
  lines.push_back(fmt::format("{}_cross_page_prefetch_too_early {}", label, too_early));
  lines.push_back(fmt::format("{}_cross_page_prefetch_too_early_among_fill {:.6g}", label, ratio_or_zero(too_early, counts.cross_fill)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_too_early_among_useless {:.6g}", label, ratio_or_zero(too_early, useless)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_accuracy {:.6g}", label, ratio_or_zero(useful, issued)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_coverage {:.6g}", label, ratio_or_zero(useful, useful + counts.demand_miss)));
}

void append_tlb_prefetch_quality_metrics(std::vector<std::string>& lines, std::string_view label, const tlb_origin_counts& counts, uint64_t instrs,
                                         uint64_t issued, uint64_t useful, uint64_t useless, uint64_t late, uint64_t too_early, uint64_t pollution_evict,
                                         uint64_t pollution_demand)
{
  lines.push_back(fmt::format("{}_same_page_prefetch_miss_rate {:.6g}", label, ratio_or_zero(counts.same_miss, counts.same_access)));
  lines.push_back(fmt::format("{}_same_page_prefetch_mpki {:.6g}", label, ratio_or_zero(counts.same_miss * 1000.0, instrs)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_miss_rate {:.6g}", label, ratio_or_zero(counts.cross_miss, counts.cross_access)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_mpki {:.6g}", label, ratio_or_zero(counts.cross_miss * 1000.0, instrs)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_issued {}", label, issued));
  lines.push_back(fmt::format("{}_cross_page_prefetch_lookups {}", label, counts.cross_access));
  lines.push_back(fmt::format("{}_cross_page_prefetch_useful {}", label, useful));
  lines.push_back(fmt::format("{}_cross_page_prefetch_useless {}", label, useless));
  lines.push_back(fmt::format("{}_cross_page_prefetch_late {}", label, late));
  lines.push_back(fmt::format("{}_cross_page_prefetch_too_early {}", label, too_early));
  lines.push_back(fmt::format("{}_cross_page_prefetch_too_early_among_fill {:.6g}", label, ratio_or_zero(too_early, counts.cross_fill)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_too_early_among_useless {:.6g}", label, ratio_or_zero(too_early, useless)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_pollution_evict {}", label, pollution_evict));
  lines.push_back(fmt::format("{}_cross_page_prefetch_pollution_demand {}", label, pollution_demand));
  lines.push_back(fmt::format("{}_cross_page_prefetch_pollution_among_prefetch_fill {:.6g}", label, ratio_or_zero(pollution_evict, counts.cross_fill)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_accuracy {:.6g}", label, ratio_or_zero(useful, issued)));
  lines.push_back(fmt::format("{}_cross_page_prefetch_coverage {:.6g}", label, ratio_or_zero(useful, useful + counts.demand_miss)));
}

void append_tlb_vberti_detail_metrics(std::vector<std::string>& lines, std::string_view level_name, std::string_view label,
                                      const tlb_origin_counts& counts, uint64_t instrs, uint64_t issued, uint64_t useful, uint64_t useless,
                                      uint64_t late, uint64_t too_early, uint64_t pollution_evict, uint64_t pollution_demand)
{
  const auto vberti_prefetch_access = counts.same_access + counts.cross_access;
  const auto vberti_prefetch_hit = counts.same_hit + counts.cross_hit;
  const auto vberti_prefetch_miss = counts.same_miss + counts.cross_miss;
  const auto vberti_prefetch_mshr_merge = counts.same_mshr_merge + counts.cross_mshr_merge;
  const auto vberti_prefetch_fill = counts.same_fill + counts.cross_fill;

  lines.push_back(fmt::format("{}_demand_access {}", label, counts.demand_access));
  lines.push_back(fmt::format("{}_demand_hit {}", label, counts.demand_hit));
  lines.push_back(fmt::format("{}_demand_miss {}", label, counts.demand_miss));
  lines.push_back(fmt::format("{}_demand_mshr_merge {}", label, counts.demand_mshr_merge));
  lines.push_back(fmt::format("{}_demand_fill {}", label, counts.demand_fill));
  lines.push_back(fmt::format("{}_demand_miss_rate {:.6g}", label, ratio_or_zero(counts.demand_miss, counts.demand_access)));
  lines.push_back(fmt::format("{}_demand_mpki {:.6g}", label, ratio_or_zero(counts.demand_miss * 1000.0, instrs)));
  lines.push_back(fmt::format("{}_vberti_prefetch_access {}", label, vberti_prefetch_access));
  lines.push_back(fmt::format("{}_vberti_prefetch_hit {}", label, vberti_prefetch_hit));
  lines.push_back(fmt::format("{}_vberti_prefetch_miss {}", label, vberti_prefetch_miss));
  lines.push_back(fmt::format("{}_vberti_prefetch_mshr_merge {}", label, vberti_prefetch_mshr_merge));
  lines.push_back(fmt::format("{}_vberti_prefetch_fill {}", label, vberti_prefetch_fill));
  lines.push_back(fmt::format("{}_vberti_prefetch_miss_rate {:.6g}", label, ratio_or_zero(vberti_prefetch_miss, vberti_prefetch_access)));
  lines.push_back(fmt::format("{}_vberti_prefetch_mpki {:.6g}", label, ratio_or_zero(vberti_prefetch_miss * 1000.0, instrs)));

  lines.emplace_back("");
  lines.push_back(fmt::format("=== {}_vBerti Same/Cross-page Prefetch Stats ===", level_name));
  lines.push_back(fmt::format("{}_vberti_same_page_prefetch {}", label, counts.same_access));
  lines.push_back(fmt::format("{}_vberti_same_page_prefetch_hit {}", label, counts.same_hit));
  lines.push_back(fmt::format("{}_vberti_same_page_prefetch_miss {}", label, counts.same_miss));
  lines.push_back(fmt::format("{}_vberti_same_page_prefetch_mshr_merge {}", label, counts.same_mshr_merge));
  lines.push_back(fmt::format("{}_vberti_same_page_prefetch_fill {}", label, counts.same_fill));
  lines.push_back(fmt::format("{}_vberti_same_page_prefetch_miss_rate {:.6g}", label, ratio_or_zero(counts.same_miss, counts.same_access)));
  lines.push_back(fmt::format("{}_vberti_same_page_prefetch_mpki {:.6g}", label, ratio_or_zero(counts.same_miss * 1000.0, instrs)));
  lines.push_back(fmt::format("{}_vberti_cross_page_prefetch {}", label, counts.cross_access));
  lines.push_back(fmt::format("{}_vberti_cross_page_prefetch_hit {}", label, counts.cross_hit));
  lines.push_back(fmt::format("{}_vberti_cross_page_prefetch_miss {}", label, counts.cross_miss));
  lines.push_back(fmt::format("{}_vberti_cross_page_prefetch_mshr_merge {}", label, counts.cross_mshr_merge));
  lines.push_back(fmt::format("{}_vberti_cross_page_prefetch_fill {}", label, counts.cross_fill));
  lines.push_back(fmt::format("{}_vberti_cross_page_prefetch_miss_rate {:.6g}", label, ratio_or_zero(counts.cross_miss, counts.cross_access)));
  lines.push_back(fmt::format("{}_vberti_cross_page_prefetch_mpki {:.6g}", label, ratio_or_zero(counts.cross_miss * 1000.0, instrs)));
  append_tlb_prefetch_quality_metrics(lines, label, counts, instrs, issued, useful, useless, late, too_early, pollution_evict, pollution_demand);
}

void append_stlb_cp_pb_metrics(std::vector<std::string>& lines, std::string_view label, const CACHE::stats_type& stats, uint64_t instrs)
{
  lines.emplace_back("");
  lines.emplace_back("========= STLB Cross-page Prefetch Buffer Stats =========");
  lines.push_back(fmt::format("{}_STLB_raw_demand_miss {}", label, stats.stlb_cp_pb_raw_demand_miss));
  lines.push_back(fmt::format("{}_CP_PB_insert {}", label, stats.stlb_cp_pb_insert));
  lines.push_back(fmt::format("{}_CP_PB_demand_hit {}", label, stats.stlb_cp_pb_demand_hit));
  lines.push_back(fmt::format("{}_STLB_PB_demand_miss {}", label, stats.stlb_cp_pb_demand_miss));
  lines.push_back(fmt::format("{}_CP_PB_coverage {:.6g}", label, ratio_or_zero(stats.stlb_cp_pb_demand_hit, stats.stlb_cp_pb_raw_demand_miss)));
  lines.push_back(fmt::format("{}_STLB_raw_demand_mpki {:.6g}", label, ratio_or_zero(stats.stlb_cp_pb_raw_demand_miss * 1000.0, instrs)));
  lines.push_back(fmt::format("{}_STLB_PB_demand_mpki {:.6g}", label, ratio_or_zero(stats.stlb_cp_pb_demand_miss * 1000.0, instrs)));
  lines.push_back(fmt::format("{}_CP_PB_demand_hit_mpki {:.6g}", label, ratio_or_zero(stats.stlb_cp_pb_demand_hit * 1000.0, instrs)));
}

void append_stlb_prefetch_buffer_metrics(std::vector<std::string>& lines, std::string_view label, const CACHE::stats_type& stats)
{
  const auto activity = stats.stlb_prefetch_buffer_insert + stats.stlb_prefetch_buffer_eviction + stats.stlb_prefetch_buffer_lookup
      + stats.stlb_prefetch_buffer_hit + stats.stlb_prefetch_buffer_miss;
  if (activity == 0)
    return;

  lines.emplace_back("");
  lines.emplace_back("========= STLB-local Prefetch Buffer Stats =========");
  lines.push_back(fmt::format("{}_STLB_prefetch_buffer_insert {}", label, stats.stlb_prefetch_buffer_insert));
  lines.push_back(fmt::format("{}_STLB_prefetch_buffer_eviction {}", label, stats.stlb_prefetch_buffer_eviction));
  lines.push_back(fmt::format("{}_STLB_prefetch_buffer_lookup {}", label, stats.stlb_prefetch_buffer_lookup));
  lines.push_back(fmt::format("{}_STLB_prefetch_buffer_hit {}", label, stats.stlb_prefetch_buffer_hit));
  lines.push_back(fmt::format("{}_STLB_prefetch_buffer_miss {}", label, stats.stlb_prefetch_buffer_miss));
  lines.push_back(fmt::format("{}_STLB_prefetch_buffer_hit_rate {:.6g}", label,
                              ratio_or_zero(stats.stlb_prefetch_buffer_hit, stats.stlb_prefetch_buffer_lookup)));
}

std::vector<std::string> format_vberti_tlb_cross_page_flow_stats(const std::map<std::string, CACHE::stats_type>& cache_stats_by_name,
                                                                 const std::vector<O3_CPU::stats_type>& cpu_stats)
{
  std::vector<std::string> lines;
  lines.emplace_back("");
  lines.emplace_back("========== vBerti-TLB Cross-page Flow Stats ==========");

  for (std::size_t cpu_idx = 0; cpu_idx < std::size(cpu_stats); ++cpu_idx) {
    const auto instrs = static_cast<uint64_t>(cpu_stats.at(cpu_idx).instrs());
    const auto l1d = cache_stats_by_name.find(fmt::format("cpu{}_L1D", cpu_idx));
    const auto dtlb = cache_stats_by_name.find(fmt::format("cpu{}_DTLB", cpu_idx));
    const auto stlb = cache_stats_by_name.find(fmt::format("cpu{}_STLB", cpu_idx));
    if (l1d == std::end(cache_stats_by_name) || dtlb == std::end(cache_stats_by_name) || stlb == std::end(cache_stats_by_name))
      continue;

    const auto requested = l1d->second.vberti_prefetch_requested;
    const auto cross_requested = l1d->second.vberti_cross_page_requested;
    const auto issued = l1d->second.vberti_prefetch_issued;
    const auto cross_issued = l1d->second.vberti_cross_page_issued;
    const auto dropped = requested > issued ? requested - issued : 0;
    const auto cross_dropped = cross_requested > cross_issued ? cross_requested - cross_issued : 0;
    const auto same_requested = requested > cross_requested ? requested - cross_requested : 0;
    const auto same_issued = issued > cross_issued ? issued - cross_issued : 0;

    lines.emplace_back("");
    lines.push_back(fmt::format("Core_{}_vBerti_Requested {}", cpu_idx, requested));
    lines.push_back(fmt::format("Core_{}_vBerti_Cross_page_prefetch_in_Requested {}", cpu_idx, cross_requested));
    lines.push_back(fmt::format("Core_{}_vBerti_Same_page_prefetch_in_Requested {}", cpu_idx, same_requested));
    lines.push_back(fmt::format("Core_{}_vBerti_Cross_page_prefetch_of_Requested {:.6g}", cpu_idx, ratio_or_zero(cross_requested, requested)));
    lines.push_back(fmt::format("Core_{}_vBerti_Issued {}", cpu_idx, issued));
    lines.push_back(fmt::format("Core_{}_vBerti_InPQ_Same_page_prefetch {}", cpu_idx, same_issued));
    lines.push_back(fmt::format("Core_{}_vBerti_InPQ_Cross_page_prefetch {}", cpu_idx, cross_issued));
    lines.push_back(fmt::format("Core_{}_vBerti_PQ_Drop_Rate {:.6g}", cpu_idx, ratio_or_zero(dropped, requested)));
    lines.push_back(fmt::format("Core_{}_vBerti_InPQ_Cross_page_prefetch_of_Requested {:.6g}", cpu_idx, ratio_or_zero(cross_issued, requested)));
    lines.push_back(fmt::format("Core_{}_vBerti_Cross_page_PQ_Drop_rate {:.6g}", cpu_idx, ratio_or_zero(cross_dropped, cross_requested)));
    lines.push_back(fmt::format("Core_{}_vBerti_Cross_page_prefetch_of_Issued {:.6g}", cpu_idx, ratio_or_zero(cross_issued, issued)));
    lines.push_back(fmt::format("Core_{}_CP_PF_PQFULL_drop {}", cpu_idx, l1d->second.cp_pf_pqfull_drop));
    lines.push_back(fmt::format("Core_{}_CP_PF_PQFULL_TLB_rescue_enqueued {}", cpu_idx, l1d->second.cp_pf_pqfull_tlb_rescue_enqueued));
    lines.push_back(fmt::format("Core_{}_CP_PF_PQFULL_TLB_rescue_issued {}", cpu_idx, l1d->second.cp_pf_pqfull_tlb_rescue_issued));
    lines.push_back(fmt::format("Core_{}_CP_PF_PQFULL_TLB_rescue_translated {}", cpu_idx, l1d->second.cp_pf_pqfull_tlb_rescue_translated));

    const auto dtlb_counts = get_dtlb_origin_counts(dtlb->second, cpu_idx);
    const auto stlb_counts = get_stlb_origin_counts(stlb->second, cpu_idx);
    const tlb_origin_counts system_counts{
        dtlb_counts.demand_access,
        0,
        stlb_counts.demand_miss,
        0,
        dtlb_counts.demand_fill + stlb_counts.demand_fill,
        dtlb_counts.same_access,
        0,
        stlb_counts.same_miss,
        0,
        dtlb_counts.same_fill + stlb_counts.same_fill,
        dtlb_counts.cross_access,
        0,
        stlb_counts.cross_miss,
        0,
        dtlb_counts.cross_fill + stlb_counts.cross_fill,
    };

    lines.emplace_back("");
    lines.emplace_back("========= DTLB_vBerti Prefetch Stats =========");
    append_tlb_vberti_detail_metrics(lines, "DTLB", fmt::format("Core_{}_DTLB", cpu_idx), dtlb_counts, instrs,
                                     dtlb->second.tlb_cross_prefetch_issued, dtlb->second.tlb_cross_prefetch_useful,
                                     dtlb->second.tlb_cross_prefetch_useless, dtlb->second.tlb_cross_prefetch_late,
                                     dtlb->second.tlb_cross_prefetch_too_early, dtlb->second.tlb_cross_prefetch_pollution_evict,
                                     dtlb->second.tlb_cross_prefetch_pollution_demand);

    lines.emplace_back("");
    lines.emplace_back("========= STLB_vBerti Prefetch Stats =========");
    append_tlb_vberti_detail_metrics(lines, "STLB", fmt::format("Core_{}_STLB", cpu_idx), stlb_counts, instrs,
                                     stlb->second.tlb_cross_prefetch_issued, stlb->second.tlb_cross_prefetch_useful,
                                     stlb->second.tlb_cross_prefetch_useless, stlb->second.tlb_cross_prefetch_late,
                                     stlb->second.tlb_cross_prefetch_too_early, stlb->second.tlb_cross_prefetch_pollution_evict,
                                     stlb->second.tlb_cross_prefetch_pollution_demand);
    append_stlb_cp_pb_metrics(lines, fmt::format("Core_{}", cpu_idx), stlb->second, instrs);
    append_stlb_prefetch_buffer_metrics(lines, fmt::format("Core_{}", cpu_idx), stlb->second);

    const auto system_issued = dtlb->second.tlb_system_cross_prefetch_issued + stlb->second.tlb_system_cross_prefetch_issued;
    const auto system_useful = dtlb->second.tlb_system_cross_prefetch_useful + stlb->second.tlb_system_cross_prefetch_useful;
    const auto system_useless = dtlb->second.tlb_system_cross_prefetch_useless + stlb->second.tlb_system_cross_prefetch_useless;
    const auto system_late = dtlb->second.tlb_system_cross_prefetch_late + stlb->second.tlb_system_cross_prefetch_late;
    const auto system_too_early = dtlb->second.tlb_system_cross_prefetch_too_early + stlb->second.tlb_system_cross_prefetch_too_early;
    lines.emplace_back("");
    append_tlb_quality_metrics(lines, fmt::format("Core_{}_TLB", cpu_idx), system_counts, instrs, system_issued, system_useful, system_useless,
                               system_late, system_too_early);

    const auto ptw_system = champsim::tlb_ptw_system::get_counters(static_cast<uint32_t>(cpu_idx));
    const auto timely = ptw_system.prefetch_useful >= ptw_system.prefetch_late ? ptw_system.prefetch_useful - ptw_system.prefetch_late : 0;
    const auto demand_opportunities = ptw_system.prefetch_useful + ptw_system.real_demand_ptw;
    lines.emplace_back("");
    lines.emplace_back("========= PTW-derived TLB-System Prefetch Stats =========");
    lines.push_back(fmt::format("Core_{}_TLB_PTW_real_demand_ptw {}", cpu_idx, ptw_system.real_demand_ptw));
    lines.push_back(fmt::format("Core_{}_TLB_PTW_real_demand_mpki {:.6g}", cpu_idx,
                                ratio_or_zero(ptw_system.real_demand_ptw * 1000.0, instrs)));
    lines.push_back(fmt::format("Core_{}_TLB_PTW_cross_page_prefetch_issued {}", cpu_idx, system_issued));
    lines.push_back(fmt::format("Core_{}_TLB_PTW_cross_page_prefetch_ptw_started {}", cpu_idx, ptw_system.prefetch_ptw_started));
    lines.push_back(fmt::format("Core_{}_TLB_PTW_cross_page_prefetch_fill {}", cpu_idx, ptw_system.prefetch_fill));
    lines.push_back(fmt::format("Core_{}_TLB_PTW_cross_page_prefetch_useful {}", cpu_idx, ptw_system.prefetch_useful));
    lines.push_back(fmt::format("Core_{}_TLB_PTW_cross_page_prefetch_late {}", cpu_idx, ptw_system.prefetch_late));
    lines.push_back(fmt::format("Core_{}_TLB_PTW_cross_page_prefetch_timely {}", cpu_idx, timely));
    lines.push_back(fmt::format("Core_{}_TLB_PTW_cross_page_prefetch_fill_accuracy {:.6g}", cpu_idx,
                                ratio_or_zero(ptw_system.prefetch_useful, ptw_system.prefetch_fill)));
    lines.push_back(fmt::format("Core_{}_TLB_PTW_cross_page_prefetch_end_to_end_yield {:.6g}", cpu_idx,
                                ratio_or_zero(ptw_system.prefetch_useful, system_issued)));
    lines.push_back(fmt::format("Core_{}_TLB_PTW_cross_page_prefetch_coverage {:.6g}", cpu_idx,
                                ratio_or_zero(ptw_system.prefetch_useful, demand_opportunities)));
    lines.push_back(fmt::format("Core_{}_TLB_PTW_cross_page_prefetch_timely_coverage {:.6g}", cpu_idx,
                                ratio_or_zero(timely, demand_opportunities)));
  }

  return lines;
}

std::vector<std::string> format_cache_config(const champsim::cache_config_info& cfg)
{
  const auto label = config_label(cfg.name);
  return {
      fmt::format("{}_set {}", label, cfg.sets),          fmt::format("{}_way {}", label, cfg.ways),
      fmt::format("{}_rq_size {}", label, cfg.rq_size),   fmt::format("{}_wq_size {}", label, cfg.wq_size),
      fmt::format("{}_pq_size {}", label, cfg.pq_size),   fmt::format("{}_mshr_size {}", label, cfg.mshr_size),
      fmt::format("{}_hit_latency {}", label, cfg.hit_latency), fmt::format("{}_fill_latency {}", label, cfg.fill_latency),
      fmt::format("{}_max_tag_check {}", label, cfg.max_tag_check), fmt::format("{}_max_fill {}", label, cfg.max_fill)};
}

std::vector<std::string> format_extended_roi_stats(champsim::phase_stats& stats)
{
  std::vector<std::string> lines;
  lines.emplace_back("");
  lines.emplace_back("[ROI Statistics]");

  std::map<std::string, CACHE::stats_type> cache_stats_by_name;
  for (const auto& cache_stats : stats.roi_cache_stats)
    cache_stats_by_name.emplace(cache_stats.name, cache_stats);

  std::map<std::string, champsim::cache_config_info> cache_config_by_name;
  for (const auto& cache_config : stats.cache_configs)
    cache_config_by_name.emplace(cache_config.name, cache_config);

  lines.emplace_back("[System Configuration]");
  lines.push_back(fmt::format("num_cpus {}", std::size(stats.roi_cpu_stats)));
  if (!stats.core_configs.empty()) {
    const auto& cfg = stats.core_configs.front();
    lines.push_back(fmt::format("cpu_freq {}", cfg.frequency_mhz));
    lines.push_back(fmt::format("fetch_width {}", cfg.fetch_width));
    lines.push_back(fmt::format("decode_width {}", cfg.decode_width));
    lines.push_back(fmt::format("dispatch_width {}", cfg.dispatch_width));
    lines.push_back(fmt::format("execute_width {}", cfg.execute_width));
    lines.push_back(fmt::format("lq_width {}", cfg.lq_width));
    lines.push_back(fmt::format("sq_width {}", cfg.sq_width));
    lines.push_back(fmt::format("retire_width {}", cfg.retire_width));
    lines.push_back(fmt::format("scheduler_size {}", cfg.scheduler_size));
    lines.push_back(fmt::format("branch_mispredict_penalty {}", cfg.branch_mispredict_penalty));
    lines.push_back(fmt::format("rob_size {}", cfg.rob_size));
    lines.push_back(fmt::format("lq_size {}", cfg.lq_size));
    lines.push_back(fmt::format("sq_size {}", cfg.sq_size));
    lines.push_back(fmt::format("ifetch_buffer_size {}", cfg.ifetch_buffer_size));
    lines.push_back(fmt::format("decode_buffer_size {}", cfg.decode_buffer_size));
    lines.push_back(fmt::format("dispatch_buffer_size {}", cfg.dispatch_buffer_size));
    lines.push_back(fmt::format("register_file_size {}", cfg.register_file_size));
    lines.push_back(fmt::format("decode_latency {}", cfg.decode_latency));
    lines.push_back(fmt::format("dispatch_latency {}", cfg.dispatch_latency));
    lines.push_back(fmt::format("schedule_latency {}", cfg.schedule_latency));
    lines.push_back(fmt::format("execute_latency {}", cfg.execute_latency));
  }
  lines.push_back(fmt::format("page_size {}", PAGE_SIZE));
  lines.push_back(fmt::format("block_size {}", BLOCK_SIZE));

  std::set<std::string> printed_cache_configs;
  auto append_cache_config = [&](const std::string& cache_name) {
    auto found = cache_config_by_name.find(cache_name);
    if (found != std::end(cache_config_by_name)) {
      auto sublines = format_cache_config(found->second);
      std::move(std::begin(sublines), std::end(sublines), std::back_inserter(lines));
      printed_cache_configs.insert(cache_name);
    }
  };

  for (std::size_t cpu_idx = 0; cpu_idx < std::size(stats.roi_cpu_stats); ++cpu_idx) {
    for (const auto& suffix : {"ITLB", "DTLB", "STLB", "L1I", "L1D", "L2C"})
      append_cache_config(fmt::format("cpu{}_{}", cpu_idx, suffix));
  }
  append_cache_config("LLC");
  for (const auto& cache_config : stats.cache_configs)
    if (printed_cache_configs.count(cache_config.name) == 0)
      append_cache_config(cache_config.name);

  const auto& dram = stats.dram_config;
  lines.push_back(fmt::format("dram_channels {}", dram.channels));
  lines.push_back(fmt::format("dram_ranks {}", dram.ranks));
  lines.push_back(fmt::format("dram_bankgroups {}", dram.bankgroups));
  lines.push_back(fmt::format("dram_banks {}", dram.banks));
  lines.push_back(fmt::format("dram_rows {}", dram.rows));
  lines.push_back(fmt::format("dram_columns {}", dram.columns));
  lines.push_back(fmt::format("dram_channel_width {}", dram.channel_width));
  lines.push_back(fmt::format("dram_rq_size {}", dram.rq_size));
  lines.push_back(fmt::format("dram_wq_size {}", dram.wq_size));
  lines.push_back(fmt::format("dram_size {}", dram.size_bytes));

  std::set<std::string> printed_module_configs;
  auto append_prefetcher_config = [&](const std::string& cache_name) {
    auto found = cache_config_by_name.find(cache_name);
    if (found != std::end(cache_config_by_name)) {
      lines.push_back(fmt::format("{}_prefetcher {}", config_label(found->second.name), join_or_no(found->second.prefetchers)));
      printed_module_configs.insert(found->second.name);
    }
  };
  for (std::size_t cpu_idx = 0; cpu_idx < std::size(stats.roi_cpu_stats); ++cpu_idx) {
    for (const auto& suffix : {"ITLB", "DTLB", "STLB", "L1I", "L1D", "L2C"})
      append_prefetcher_config(fmt::format("cpu{}_{}", cpu_idx, suffix));
  }
  append_prefetcher_config("LLC");
  for (const auto& cache_config : stats.cache_configs)
    if (printed_module_configs.count(cache_config.name) == 0)
      append_prefetcher_config(cache_config.name);

  if (auto found = cache_config_by_name.find("LLC"); found != std::end(cache_config_by_name))
    lines.push_back(fmt::format("llc_replacement {}", join_or_no(found->second.replacements)));

  const std::array cache_order{"ITLB", "DTLB", "STLB", "L1I", "L1D", "L2C"};
  for (std::size_t cpu_idx = 0; cpu_idx < std::size(stats.roi_cpu_stats); ++cpu_idx) {
    const auto& cpu_stats = stats.roi_cpu_stats.at(cpu_idx);
    lines.emplace_back("");
    lines.push_back(fmt::format("Core_{}_instructions {}", cpu_idx, cpu_stats.instrs()));
    lines.push_back(fmt::format("Core_{}_cycles {}", cpu_idx, cpu_stats.cycles()));
    lines.push_back(fmt::format("Core_{}_IPC {:.6g}", cpu_idx, ratio_or_zero(cpu_stats.instrs(), cpu_stats.cycles())));

    uint64_t total_branch = 0;
    uint64_t total_misses = 0;
    for (const auto type : {branch_type::BRANCH_DIRECT_JUMP, branch_type::BRANCH_INDIRECT, branch_type::BRANCH_CONDITIONAL, branch_type::BRANCH_DIRECT_CALL,
                            branch_type::BRANCH_INDIRECT_CALL, branch_type::BRANCH_RETURN}) {
      total_branch += cpu_stats.total_branch_types.value_or(type, 0);
      total_misses += cpu_stats.branch_type_misses.value_or(type, 0);
    }
    lines.push_back(fmt::format("Core_{}_branch_prediction_accuracy {:.6g}", cpu_idx, 100.0 * ratio_or_zero(total_branch - total_misses, total_branch)));
    lines.push_back(fmt::format("Core_{}_branch_MPKI {:.6g}", cpu_idx, ratio_or_zero(total_misses * 1000.0, cpu_stats.instrs())));
    lines.push_back(fmt::format("Core_{}_average_ROB_occupancy_at_mispredict {:.6g}", cpu_idx,
                                ratio_or_zero(cpu_stats.total_rob_occupancy_at_branch_mispredict, total_misses)));

    for (auto suffix : cache_order) {
      auto found = cache_stats_by_name.find(fmt::format("cpu{}_{}", cpu_idx, suffix));
      if (found != std::end(cache_stats_by_name)) {
        lines.emplace_back("");
        auto sublines = format_cache_metric_block(found->second, cpu_idx, cpu_stats.instrs());
        std::move(std::begin(sublines), std::end(sublines), std::back_inserter(lines));
      }
    }
  }

  if (auto found = cache_stats_by_name.find("LLC"); found != std::end(cache_stats_by_name)) {
    lines.emplace_back("");
    for (auto cpu : cache_cpus(found->second)) {
      auto instrs = cpu < std::size(stats.roi_cpu_stats) ? stats.roi_cpu_stats.at(cpu).instrs() : 0;
      auto sublines = format_cache_metric_block(found->second, cpu, instrs);
      std::move(std::begin(sublines), std::end(sublines), std::back_inserter(lines));
    }
  }

  lines.emplace_back("");
  lines.emplace_back("[DRAM Statistics]");
  uint64_t total_rq_hit = 0;
  uint64_t total_rq_miss = 0;
  uint64_t total_wq_hit = 0;
  uint64_t total_wq_miss = 0;
  uint64_t total_wq_full = 0;
  uint64_t total_congested = 0;
  uint64_t total_congested_cycles = 0;
  for (std::size_t channel = 0; channel < std::size(stats.roi_dram_stats); ++channel) {
    const auto& dram_stats = stats.roi_dram_stats.at(channel);
    lines.push_back(fmt::format("Channel_{}_RQ_row_buffer_hit {}", channel, dram_stats.RQ_ROW_BUFFER_HIT));
    lines.push_back(fmt::format("Channel_{}_RQ_row_buffer_miss {}", channel, dram_stats.RQ_ROW_BUFFER_MISS));
    lines.push_back(fmt::format("Channel_{}_WQ_row_buffer_hit {}", channel, dram_stats.WQ_ROW_BUFFER_HIT));
    lines.push_back(fmt::format("Channel_{}_WQ_row_buffer_miss {}", channel, dram_stats.WQ_ROW_BUFFER_MISS));
    lines.push_back(fmt::format("Channel_{}_WQ_full {}", channel, dram_stats.WQ_FULL));
    lines.push_back(fmt::format("Channel_{}_dbus_congested {}", channel, dram_stats.dbus_count_congested));
    total_rq_hit += dram_stats.RQ_ROW_BUFFER_HIT;
    total_rq_miss += dram_stats.RQ_ROW_BUFFER_MISS;
    total_wq_hit += dram_stats.WQ_ROW_BUFFER_HIT;
    total_wq_miss += dram_stats.WQ_ROW_BUFFER_MISS;
    total_wq_full += dram_stats.WQ_FULL;
    total_congested += dram_stats.dbus_count_congested;
    total_congested_cycles += dram_stats.dbus_cycle_congested;
  }
  lines.push_back(fmt::format("DRAM_total_RQ_row_buffer_hit {}", total_rq_hit));
  lines.push_back(fmt::format("DRAM_total_RQ_row_buffer_miss {}", total_rq_miss));
  lines.push_back(fmt::format("DRAM_total_WQ_row_buffer_hit {}", total_wq_hit));
  lines.push_back(fmt::format("DRAM_total_WQ_row_buffer_miss {}", total_wq_miss));
  lines.push_back(fmt::format("DRAM_total_WQ_full {}", total_wq_full));
  lines.push_back(fmt::format("DRAM_total_dbus_congested {}", total_congested));
  lines.push_back(fmt::format("DRAM_avg_congested_cycle {:.6g}", ratio_or_zero(total_congested_cycles, total_congested)));

  const auto total_roi_instructions = std::accumulate(std::begin(stats.roi_cpu_stats), std::end(stats.roi_cpu_stats), uint64_t{0},
                                                      [](uint64_t acc, const auto& cpu_stats) {
                                                        return acc + static_cast<uint64_t>(cpu_stats.instrs());
                                                      });
  auto traffic_lines = format_dram_rq_read_traffic(stats.roi_dram_stats, total_roi_instructions);
  std::move(std::begin(traffic_lines), std::end(traffic_lines), std::back_inserter(lines));

  auto ptw_dram_touch_lines = format_stlb_miss_ptw_dram_touch(stats.roi_ptw_stats);
  std::move(std::begin(ptw_dram_touch_lines), std::end(ptw_dram_touch_lines), std::back_inserter(lines));

  for (std::size_t cpu_idx = 0; cpu_idx < std::size(stats.roi_cpu_stats); ++cpu_idx) {
    auto found = cache_stats_by_name.find(fmt::format("cpu{}_STLB", cpu_idx));
    if (found != std::end(cache_stats_by_name)) {
      auto sublines = format_stlb_miss_cause_block(found->second, cpu_idx);
      std::move(std::begin(sublines), std::end(sublines), std::back_inserter(lines));
    }
  }

  auto vberti_tlb_lines = format_vberti_tlb_cross_page_flow_stats(cache_stats_by_name, stats.roi_cpu_stats);
  std::move(std::begin(vberti_tlb_lines), std::end(vberti_tlb_lines), std::back_inserter(lines));

  return lines;
}
} // namespace

std::vector<std::string> champsim::plain_printer::format(O3_CPU::stats_type stats)
{
  constexpr std::array types{branch_type::BRANCH_DIRECT_JUMP, branch_type::BRANCH_INDIRECT,      branch_type::BRANCH_CONDITIONAL,
                             branch_type::BRANCH_DIRECT_CALL, branch_type::BRANCH_INDIRECT_CALL, branch_type::BRANCH_RETURN};
  auto total_branch = std::ceil(
      std::accumulate(std::begin(types), std::end(types), 0LL, [tbt = stats.total_branch_types](auto acc, auto next) { return acc + tbt.value_or(next, 0); }));
  auto total_mispredictions = std::ceil(
      std::accumulate(std::begin(types), std::end(types), 0LL, [btm = stats.branch_type_misses](auto acc, auto next) { return acc + btm.value_or(next, 0); }));

  std::vector<std::string> lines{};
  lines.push_back(fmt::format("{} cumulative IPC: {} instructions: {} cycles: {}", stats.name, ::print_ratio(stats.instrs(), stats.cycles()), stats.instrs(),
                              stats.cycles()));

  lines.push_back(fmt::format("{} Branch Prediction Accuracy: {}% MPKI: {} Average ROB Occupancy at Mispredict: {}", stats.name,
                              ::print_ratio(100 * (total_branch - total_mispredictions), total_branch),
                              ::print_ratio(std::kilo::num * total_mispredictions, stats.instrs()),
                              ::print_ratio(stats.total_rob_occupancy_at_branch_mispredict, total_mispredictions)));

  lines.emplace_back("Branch type MPKI");
  for (auto idx : types) {
    lines.push_back(fmt::format("{}: {}", branch_type_names.at(champsim::to_underlying(idx)),
                                ::print_ratio(std::kilo::num * stats.branch_type_misses.value_or(idx, 0), stats.instrs())));
  }

  return lines;
}

std::vector<std::string> champsim::plain_printer::format(CACHE::stats_type stats)
{
  using hits_value_type = typename decltype(stats.hits)::value_type;
  using misses_value_type = typename decltype(stats.misses)::value_type;
  using mshr_merge_value_type = typename decltype(stats.mshr_merge)::value_type;
  using mshr_return_value_type = typename decltype(stats.mshr_return)::value_type;

  std::vector<std::size_t> cpus;

  // build a vector of all existing cpus
  auto stat_keys = {stats.hits.get_keys(), stats.misses.get_keys(), stats.mshr_merge.get_keys(), stats.mshr_return.get_keys()};
  for (auto keys : stat_keys) {
    std::transform(std::begin(keys), std::end(keys), std::back_inserter(cpus), [](auto val) { return val.second; });
  }
  std::sort(std::begin(cpus), std::end(cpus));
  auto uniq_end = std::unique(std::begin(cpus), std::end(cpus));
  cpus.erase(uniq_end, std::end(cpus));

  for (const auto type : {access_type::LOAD, access_type::RFO, access_type::PREFETCH, access_type::WRITE, access_type::TRANSLATION}) {
    for (auto cpu : cpus) {
      stats.hits.allocate(std::pair{type, cpu});
      stats.misses.allocate(std::pair{type, cpu});
      stats.mshr_merge.allocate(std::pair{type, cpu});
      stats.mshr_return.allocate(std::pair{type, cpu});
    }
  }

  std::vector<std::string> lines{};
  for (auto cpu : cpus) {
    hits_value_type total_hits = 0;
    misses_value_type total_misses = 0;
    mshr_merge_value_type total_mshr_merge = 0;
    mshr_return_value_type total_mshr_return = 0;
    for (const auto type : {access_type::LOAD, access_type::RFO, access_type::PREFETCH, access_type::WRITE, access_type::TRANSLATION}) {
      total_hits += stats.hits.value_or(std::pair{type, cpu}, hits_value_type{});
      total_misses += stats.misses.value_or(std::pair{type, cpu}, misses_value_type{});
      total_mshr_merge += stats.mshr_merge.value_or(std::pair{type, cpu}, mshr_merge_value_type{});
      total_mshr_return += stats.mshr_return.value_or(std::pair{type, cpu}, mshr_merge_value_type{});
    }

    fmt::format_string<std::string_view, std::string_view, int, int, int> hitmiss_fmtstr{
        "cpu{}->{} {:<12s} ACCESS: {:10d} HIT: {:10d} MISS: {:10d} MSHR_MERGE: {:10d}"};
    lines.push_back(fmt::format(hitmiss_fmtstr, cpu, stats.name, "TOTAL", total_hits + total_misses, total_hits, total_misses, total_mshr_merge));
    for (const auto type : {access_type::LOAD, access_type::RFO, access_type::PREFETCH, access_type::WRITE, access_type::TRANSLATION}) {
      lines.push_back(
          fmt::format(hitmiss_fmtstr, cpu, stats.name, access_type_names.at(champsim::to_underlying(type)),
                      stats.hits.value_or(std::pair{type, cpu}, hits_value_type{}) + stats.misses.value_or(std::pair{type, cpu}, misses_value_type{}),
                      stats.hits.value_or(std::pair{type, cpu}, hits_value_type{}), stats.misses.value_or(std::pair{type, cpu}, misses_value_type{}),
                      stats.mshr_merge.value_or(std::pair{type, cpu}, mshr_merge_value_type{})));
    }

    lines.push_back(fmt::format("cpu{}->{} PREFETCH REQUESTED: {:10} ISSUED: {:10} USEFUL: {:10} USELESS: {:10} LATE: {:10} TOO_EARLY: {:10}", cpu,
                                stats.name, stats.pf_requested, stats.pf_issued, stats.pf_useful, stats.pf_useless, stats.pf_late,
                                stats.pf_too_early));

    uint64_t total_downstream_demands = total_mshr_return - stats.mshr_return.value_or(std::pair{access_type::PREFETCH, cpu}, mshr_return_value_type{});
    lines.push_back(
        fmt::format("cpu{}->{} AVERAGE MISS LATENCY: {} cycles", cpu, stats.name, ::print_ratio(stats.total_miss_latency_cycles, total_downstream_demands)));
  }

  return lines;
}

std::vector<std::string> champsim::plain_printer::format(DRAM_CHANNEL::stats_type stats)
{
  std::vector<std::string> lines{};
  lines.push_back(fmt::format("{} RQ ROW_BUFFER_HIT: {:10}", stats.name, stats.RQ_ROW_BUFFER_HIT));
  lines.push_back(fmt::format("  ROW_BUFFER_MISS: {:10}", stats.RQ_ROW_BUFFER_MISS));
  lines.push_back(fmt::format("  AVG DBUS CONGESTED CYCLE: {}", ::print_ratio(stats.dbus_cycle_congested, stats.dbus_count_congested)));
  lines.push_back(fmt::format("{} WQ ROW_BUFFER_HIT: {:10}", stats.name, stats.WQ_ROW_BUFFER_HIT));
  lines.push_back(fmt::format("  ROW_BUFFER_MISS: {:10}", stats.WQ_ROW_BUFFER_MISS));
  lines.push_back(fmt::format("  FULL: {:10}", stats.WQ_FULL));

  if (stats.refresh_cycles > 0)
    lines.push_back(fmt::format("{} REFRESHES ISSUED: {:10}", stats.name, stats.refresh_cycles));
  else
    lines.push_back(fmt::format("{} REFRESHES ISSUED: -", stats.name));

  return lines;
}

void champsim::plain_printer::print(champsim::phase_stats& stats)
{
  auto lines = format(stats);
  std::copy(std::begin(lines), std::end(lines), std::ostream_iterator<std::string>(stream, "\n"));
}

std::vector<std::string> champsim::plain_printer::format(champsim::phase_stats& stats)
{
  std::vector<std::string> lines{};
  lines.push_back(fmt::format("=== {} ===", stats.name));

  int i = 0;
  for (auto tn : stats.trace_names) {
    lines.push_back(fmt::format("CPU {} runs {}", i++, tn));
  }

  if (NUM_CPUS > 1) {
    lines.emplace_back("");
    lines.emplace_back("Total Simulation Statistics (not including warmup)");

    for (const auto& stat : stats.sim_cpu_stats) {
      auto sublines = format(stat);
      lines.emplace_back("");
      std::move(std::begin(sublines), std::end(sublines), std::back_inserter(lines));
      lines.emplace_back("");
    }

    for (const auto& stat : stats.sim_cache_stats) {
      auto sublines = format(stat);
      std::move(std::begin(sublines), std::end(sublines), std::back_inserter(lines));
    }
  }

  lines.emplace_back("");
  lines.emplace_back("Region of Interest Statistics");

  for (const auto& stat : stats.roi_cpu_stats) {
    auto sublines = format(stat);
    lines.emplace_back("");
    std::move(std::begin(sublines), std::end(sublines), std::back_inserter(lines));
    lines.emplace_back("");
  }

  for (const auto& stat : stats.roi_cache_stats) {
    auto sublines = format(stat);
    std::move(std::begin(sublines), std::end(sublines), std::back_inserter(lines));
  }

  lines.emplace_back("");
  lines.emplace_back("DRAM Statistics");
  for (const auto& stat : stats.roi_dram_stats) {
    auto sublines = format(stat);
    lines.emplace_back("");
    std::move(std::begin(sublines), std::end(sublines), std::back_inserter(lines));
  }

  auto extended_lines = format_extended_roi_stats(stats);
  std::move(std::begin(extended_lines), std::end(extended_lines), std::back_inserter(lines));

  return lines;
}

void champsim::plain_printer::print(std::vector<phase_stats>& stats)
{
  for (auto p : stats) {
    print(p);
  }
}
