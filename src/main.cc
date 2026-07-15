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
#include <fstream>
#include <numeric>
#include <string>
#include <vector>
#include <CLI/CLI.hpp>
#include <fmt/core.h>

#include "cache.h" // for CACHE
#include "champsim.h"
#ifndef CHAMPSIM_TEST_BUILD
#include "core_inst.inc"
#endif
#include "defaults.hpp"
#include "demand_tlb_pattern.h"
#include "dpc_api.h"
#include "environment.h"
#include "ooo_cpu.h" // for O3_CPU
#include "phase_info.h"
#include "stats_printer.h"
#include "tracereader.h"
#include "vmem.h"

namespace champsim
{
std::vector<phase_stats> main(environment& env, std::vector<phase_info>& phases, std::vector<tracereader>& traces);
}

#ifndef CHAMPSIM_TEST_BUILD
using configured_environment = champsim::configured::generated_environment<CHAMPSIM_BUILD>;

const std::size_t NUM_CPUS = configured_environment::num_cpus;

const unsigned BLOCK_SIZE = configured_environment::block_size;
const unsigned PAGE_SIZE = configured_environment::page_size;
#endif
const unsigned LOG2_BLOCK_SIZE = champsim::lg2(BLOCK_SIZE);
const unsigned LOG2_PAGE_SIZE = champsim::lg2(PAGE_SIZE);

#ifndef CHAMPSIM_TEST_BUILD
// Singleton environment pointer
static configured_environment* g_env;

//------------------------------------//
// DPC4 API
//------------------------------------//
uint8_t get_dram_bw()
{
  MEMORY_CONTROLLER& mc = g_env->dram_view();
  return mc.get_bw();
}

long long get_retired_insts(uint8_t cpu_id)
{
  assert(cpu_id < NUM_CPUS);
  O3_CPU& cpu = g_env->cpu_view().at(cpu_id);
  return cpu.num_retired;
}

int main(int argc, char** argv) // NOLINT(bugprone-exception-escape)
{
  configured_environment gen_environment{};

  CLI::App app{"A microarchitecture simulator for research and education"};

  bool knob_cloudsuite{false};
  long long warmup_instructions = 0;
  long long simulation_instructions = std::numeric_limits<long long>::max();
  std::string json_file_name;
  std::vector<std::string> trace_names;
  bool hide_heartbeat{false};
  long long heartbeat_interval = 500000;
  bool demand_tlb_pattern = false;
  std::string demand_tlb_pattern_output = "demand_tlb_pattern";
  uint64_t demand_tlb_pattern_max_events = 0;

  app.add_flag("-c,--cloudsuite", knob_cloudsuite, "Read all traces using the cloudsuite format");
  app.add_flag("--hide-heartbeat", hide_heartbeat, "Hide the heartbeat output");
  app.add_flag("--enable-stlb-cp-pb", champsim::enable_stlb_cp_pb, "Enable the STLB cross-page prefetch buffer experiment");
  app.add_flag("--ordered-pqfull-tlb-rescue", champsim::ordered_pqfull_tlb_rescue, "Enable ordered translation-only rescue for PQ-full L1D cross-page prefetches");
  app.add_flag("--l1d-cross-page-pf-translation-only", champsim::l1d_cross_page_pf_translation_only,
               "Translate vBerti L1D cross-page prefetches but suppress their data-cache accesses");
  app.add_flag("--demand-tlb-pattern", demand_tlb_pattern, "Record the ROI demand-load L1 DTLB request pattern");
  app.add_option("--demand-tlb-pattern-output", demand_tlb_pattern_output, "Output directory for demand-load TLB pattern files");
  app.add_option("--demand-tlb-pattern-max-events", demand_tlb_pattern_max_events,
                 "Maximum demand-load TLB pattern events per core; zero means unlimited");
  app.add_option("--heartbeat-interval", heartbeat_interval, "The frequency of printing heartbeat");
  auto* warmup_instr_option = app.add_option("-w,--warmup-instructions", warmup_instructions, "The number of instructions in the warmup phase");
  auto* deprec_warmup_instr_option =
      app.add_option("--warmup_instructions", warmup_instructions, "[deprecated] use --warmup-instructions instead")->excludes(warmup_instr_option);
  auto* sim_instr_option = app.add_option("-i,--simulation-instructions", simulation_instructions,
                                          "The number of instructions in the detailed phase. If not specified, run to the end of the trace.");
  auto* deprec_sim_instr_option =
      app.add_option("--simulation_instructions", simulation_instructions, "[deprecated] use --simulation-instructions instead")->excludes(sim_instr_option);

  auto* json_option =
      app.add_option("--json", json_file_name, "The name of the file to receive JSON output. If no name is specified, stdout will be used")->expected(0, 1);

  app.add_option("traces", trace_names, "The paths to the traces")->required()->expected(NUM_CPUS)->check(CLI::ExistingFile);

  CLI11_PARSE(app, argc, argv);

  g_env = &gen_environment;

  for (O3_CPU& cpu : gen_environment.cpu_view()) {
    cpu.show_heartbeat = hide_heartbeat ? false : true;
    cpu.heartbeat_interval = heartbeat_interval;
  }

  const bool warmup_given = (warmup_instr_option->count() > 0) || (deprec_warmup_instr_option->count() > 0);
  const bool simulation_given = (sim_instr_option->count() > 0) || (deprec_sim_instr_option->count() > 0);

  if (deprec_warmup_instr_option->count() > 0) {
    fmt::print("WARNING: option --warmup_instructions is deprecated. Use --warmup-instructions instead.\n");
  }

  if (deprec_sim_instr_option->count() > 0) {
    fmt::print("WARNING: option --simulation_instructions is deprecated. Use --simulation-instructions instead.\n");
  }

  if (simulation_given && !warmup_given) {
    // Warmup is 20% by default
    // NOLINTNEXTLINE(cppcoreguidelines-avoid-magic-numbers,readability-magic-numbers)
    warmup_instructions = simulation_instructions / 5;
  }

  champsim::demand_tlb_pattern_config demand_pattern_config;
  demand_pattern_config.enabled = demand_tlb_pattern;
  demand_pattern_config.output_directory = demand_tlb_pattern_output;
  demand_pattern_config.max_events_per_core = demand_tlb_pattern_max_events;
  demand_pattern_config.page_size = PAGE_SIZE;
  demand_pattern_config.num_cores = NUM_CPUS;
  demand_pattern_config.warmup_instructions = static_cast<uint64_t>(warmup_instructions);
  demand_pattern_config.simulation_instructions = static_cast<uint64_t>(simulation_instructions);
  demand_pattern_config.trace_names = trace_names;
  demand_pattern_config.executable_name = argv[0];
  champsim::demand_tlb_pattern_logger().configure(std::move(demand_pattern_config));

  std::vector<champsim::tracereader> traces;
  std::transform(
      std::begin(trace_names), std::end(trace_names), std::back_inserter(traces),
      [knob_cloudsuite, repeat = simulation_given, i = uint8_t(0)](auto name) mutable { return get_tracereader(name, i++, knob_cloudsuite, repeat); });

  std::vector<champsim::phase_info> phases{
      {champsim::phase_info{"Warmup", true, warmup_instructions, std::vector<std::size_t>(std::size(trace_names), 0), trace_names},
       champsim::phase_info{"Simulation", false, simulation_instructions, std::vector<std::size_t>(std::size(trace_names), 0), trace_names}}};

  for (auto& p : phases) {
    std::iota(std::begin(p.trace_index), std::end(p.trace_index), 0);
  }

  fmt::print("\n*** ChampSim Multicore Out-of-Order Simulator ***\nWarmup Instructions: {}\nSimulation Instructions: {}\nNumber of CPUs: {}\nPage size: {}\n",
             phases.at(0).length, phases.at(1).length, std::size(gen_environment.cpu_view()), PAGE_SIZE);

  for (size_t index = 0; index < NUM_CPUS; ++index) {
    fmt::print("Core {}: {}\n", index, trace_names[index]);
  }

  auto phase_stats = champsim::main(gen_environment, phases, traces);

  fmt::print("\nChampSim completed all CPUs\n\n");

  champsim::plain_printer{std::cout}.print(phase_stats);

  for (CACHE& cache : gen_environment.cache_view()) {
    cache.impl_prefetcher_final_stats();
  }

  for (CACHE& cache : gen_environment.cache_view()) {
    cache.impl_replacement_final_stats();
  }

  if (json_option->count() > 0) {
    if (json_file_name.empty()) {
      champsim::json_printer{std::cout}.print(phase_stats);
    } else {
      std::ofstream json_file{json_file_name};
      champsim::json_printer{json_file}.print(phase_stats);
    }
  }

  return 0;
}
#endif
