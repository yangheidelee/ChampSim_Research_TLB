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

std::vector<std::string> format_stlb_miss_cause_block(const CACHE::stats_type& stats, std::size_t cpu)
{
  std::vector<std::string> lines;
  lines.emplace_back("");
  lines.emplace_back("======STLB miss causes ========");

  const std::array detailed_origins{translation_origin::DEMAND_DATA, translation_origin::DEMAND_INSTRUCTION, translation_origin::L1D_PREFETCH,
                                    translation_origin::L1I_PREFETCH, translation_origin::OTHER};
  const std::array detailed_names{"Demand_Data", "Demand_Instruction", "L1D_Prefetch", "L1I_Prefetch", "Other"};

  const auto label = cache_label(cpu, stats.name);
  const auto stlb_total_access = access_count(stats, access_type::LOAD, cpu) + access_count(stats, access_type::RFO, cpu)
                                 + access_count(stats, access_type::PREFETCH, cpu) + access_count(stats, access_type::WRITE, cpu);
  lines.push_back(fmt::format("{}_miss_cause_breakdown", label));

  for (std::size_t idx = 0; idx < std::size(detailed_origins); ++idx) {
    const auto origin = detailed_origins.at(idx);
    const auto misses = origin_counter_value(stats.stlb_origin_misses, origin, cpu);
    lines.push_back(fmt::format("{}_cause_{}_miss {}", label, detailed_names.at(idx), misses));
    lines.push_back(fmt::format("{}_cause_{}_miss_rate {:.6g}", label, detailed_names.at(idx), ratio_or_zero(misses, stlb_total_access)));
  }

  const auto demand_misses = origin_counter_value(stats.stlb_origin_misses, translation_origin::DEMAND_DATA, cpu)
                             + origin_counter_value(stats.stlb_origin_misses, translation_origin::DEMAND_INSTRUCTION, cpu);
  const auto l1d_prefetch_misses = origin_counter_value(stats.stlb_origin_misses, translation_origin::L1D_PREFETCH, cpu);
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

std::vector<std::string> format_cache_metric_block(const CACHE::stats_type& stats, std::size_t cpu, long long instrs)
{
  std::vector<std::string> lines;
  const auto label = cache_label(cpu, stats.name);
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
    lines.push_back(fmt::format("{}_{}_access {}", label, name, accesses));
    lines.push_back(fmt::format("{}_{}_hit {}", label, name, hits));
    lines.push_back(fmt::format("{}_{}_miss {}", label, name, misses));
    lines.push_back(fmt::format("{}_{}_MPKI {:.6g}", label, name, ratio_or_zero(misses * 1000.0, instrs)));
    lines.push_back(fmt::format("{}_{}_miss_rate {:.6g}", label, name, ratio_or_zero(misses, accesses)));
  }

  lines.push_back(fmt::format("{}_prefetch_requested {}", label, stats.pf_requested));
  lines.push_back(fmt::format("{}_prefetch_issued {}", label, stats.pf_issued));
  lines.push_back(fmt::format("{}_prefetch_useful {}", label, stats.pf_useful));
  lines.push_back(fmt::format("{}_prefetch_useless {}", label, stats.pf_useless));
  lines.push_back(fmt::format("{}_prefetch_late {}", label, stats.pf_late));
  lines.push_back(fmt::format("{}_prefetch_accuracy {:.6g}", label, ratio_or_zero(stats.pf_useful, stats.pf_issued)));
  lines.push_back(fmt::format("{}_prefetch_coverage {:.6g}", label, ratio_or_zero(stats.pf_useful, stats.pf_useful + demand_miss)));

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

  for (std::size_t cpu_idx = 0; cpu_idx < std::size(stats.roi_cpu_stats); ++cpu_idx) {
    auto found = cache_stats_by_name.find(fmt::format("cpu{}_STLB", cpu_idx));
    if (found != std::end(cache_stats_by_name)) {
      auto sublines = format_stlb_miss_cause_block(found->second, cpu_idx);
      std::move(std::begin(sublines), std::end(sublines), std::back_inserter(lines));
    }
  }

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

    lines.push_back(fmt::format("cpu{}->{} PREFETCH REQUESTED: {:10} ISSUED: {:10} USEFUL: {:10} USELESS: {:10} LATE: {:10}", cpu, stats.name,
                                stats.pf_requested, stats.pf_issued, stats.pf_useful, stats.pf_useless, stats.pf_late));

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
