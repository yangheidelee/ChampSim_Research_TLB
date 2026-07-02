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

#ifndef PHASE_INFO_H
#define PHASE_INFO_H

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include "cache_stats.h"
#include "core_stats.h"
#include "dram_stats.h"
#include "ptw.h"

namespace champsim
{

struct phase_info {
  std::string name;
  bool is_warmup;
  long long length;
  std::vector<std::size_t> trace_index;
  std::vector<std::string> trace_names;
};

struct core_config_info {
  std::size_t cpu = 0;
  long frequency_mhz = 0;
  std::size_t ifetch_buffer_size = 0;
  std::size_t decode_buffer_size = 0;
  std::size_t dispatch_buffer_size = 0;
  std::size_t register_file_size = 0;
  std::size_t rob_size = 0;
  std::size_t lq_size = 0;
  std::size_t sq_size = 0;
  long fetch_width = 0;
  long decode_width = 0;
  long dispatch_width = 0;
  long scheduler_size = 0;
  long execute_width = 0;
  long lq_width = 0;
  long sq_width = 0;
  long retire_width = 0;
  long branch_mispredict_penalty = 0;
  long decode_latency = 0;
  long dispatch_latency = 0;
  long schedule_latency = 0;
  long execute_latency = 0;
};

struct cache_config_info {
  std::string name;
  std::vector<std::string> prefetchers;
  std::vector<std::string> replacements;
  std::size_t sets = 0;
  std::size_t ways = 0;
  std::size_t rq_size = 0;
  std::size_t pq_size = 0;
  std::size_t wq_size = 0;
  std::size_t mshr_size = 0;
  long hit_latency = 0;
  long fill_latency = 0;
  long max_tag_check = 0;
  long max_fill = 0;
};

struct dram_config_info {
  std::size_t channels = 0;
  std::size_t ranks = 0;
  std::size_t bankgroups = 0;
  std::size_t banks = 0;
  std::size_t rows = 0;
  std::size_t columns = 0;
  std::size_t rq_size = 0;
  std::size_t wq_size = 0;
  std::size_t channel_width = 0;
  std::size_t size_bytes = 0;
};

struct phase_stats {
  std::string name;
  std::vector<std::string> trace_names;
  std::vector<core_config_info> core_configs;
  std::vector<cache_config_info> cache_configs;
  dram_config_info dram_config;
  std::vector<O3_CPU::stats_type> roi_cpu_stats, sim_cpu_stats;
  std::vector<CACHE::stats_type> roi_cache_stats, sim_cache_stats;
  std::vector<DRAM_CHANNEL::stats_type> roi_dram_stats, sim_dram_stats;
  std::vector<PageTableWalker::stats_type> roi_ptw_stats, sim_ptw_stats;
};

} // namespace champsim

#endif
