#include <catch.hpp>

#include "tlb_ptw_system_stats.h"

TEST_CASE("PTW-derived TLB-system stats count each walk, fill, and use once")
{
  constexpr uint32_t cpu = 0;
  const champsim::tlb_ptw_system::key first_key{cpu, 0x1234, 0xff, 0xff};
  champsim::tlb_ptw_system::reset(cpu);

  const auto first_id = champsim::tlb_ptw_system::reserve_prefetch_ptw_id(cpu);
  champsim::tlb_ptw_system::start_prefetch_ptw(cpu, first_id, first_key, false);
  REQUIRE(champsim::tlb_ptw_system::mark_fill(cpu, first_id, champsim::tlb_ptw_system::residency_level::stlb));
  REQUIRE(champsim::tlb_ptw_system::mark_fill(cpu, first_id, champsim::tlb_ptw_system::residency_level::dtlb));
  champsim::tlb_ptw_system::mark_useful(cpu, first_id, false);
  champsim::tlb_ptw_system::mark_useful(cpu, first_id, false);

  auto counts = champsim::tlb_ptw_system::get_counters(cpu);
  REQUIRE(counts.prefetch_ptw_started == 1);
  REQUIRE(counts.prefetch_fill == 1);
  REQUIRE(counts.prefetch_useful == 1);
  REQUIRE(counts.prefetch_late == 0);

  const champsim::tlb_ptw_system::key second_key{cpu, 0x5678, 0xff, 0xff};
  champsim::tlb_ptw_system::note_demand_for_key(second_key);
  const auto second_id = champsim::tlb_ptw_system::reserve_prefetch_ptw_id(cpu);
  champsim::tlb_ptw_system::start_prefetch_ptw(cpu, second_id, second_key, false);

  counts = champsim::tlb_ptw_system::get_counters(cpu);
  REQUIRE(counts.prefetch_useful == 1);
  REQUIRE(counts.prefetch_late == 0);

  REQUIRE(champsim::tlb_ptw_system::mark_fill(cpu, second_id, champsim::tlb_ptw_system::residency_level::stlb));
  champsim::tlb_ptw_system::start_real_demand_ptw(cpu);

  counts = champsim::tlb_ptw_system::get_counters(cpu);
  REQUIRE(counts.real_demand_ptw == 1);
  REQUIRE(counts.prefetch_ptw_started == 2);
  REQUIRE(counts.prefetch_fill == 2);
  REQUIRE(counts.prefetch_useful == 2);
  REQUIRE(counts.prefetch_late == 1);
}
