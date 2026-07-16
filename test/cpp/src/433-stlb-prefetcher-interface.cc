#include <catch.hpp>

#include <algorithm>
#include <array>
#include <map>
#include <vector>

#include "cache.h"
#include "defaults.hpp"
#include "mocks.hpp"
#include "modules.h"

namespace
{
using operate_context = champsim::modules::stlb_prefetcher_context;
using fill_context = champsim::modules::stlb_prefetcher_fill_context;

std::map<CACHE*, std::vector<operate_context>> operate_collector;
std::map<CACHE*, std::vector<fill_context>> fill_collector;
std::map<CACHE*, std::size_t> initialize_collector;

struct stlb_interface_collector : champsim::modules::stlb_prefetcher {
  using stlb_prefetcher::stlb_prefetcher;

  void stlb_prefetcher_initialize() { ++initialize_collector[intern_]; }

  void stlb_prefetcher_operate(const operate_context& context)
  {
    operate_collector[intern_].push_back(context);
    if (!context.hit) {
      const auto target = champsim::address{(context.vpn + 1) << LOG2_PAGE_SIZE};
      prefetch_translation(target, context.metadata);
    }
  }

  void stlb_prefetcher_fill(const fill_context& context) { fill_collector[intern_].push_back(context); }
};

template <typename Range>
void run_cycles(Range& elements, std::size_t cycles)
{
  for (std::size_t i = 0; i < cycles; ++i)
    for (auto* element : elements)
      element->_operate();
}

champsim::channel::request_type make_demand(uint64_t vpn, uint64_t instr_id)
{
  champsim::channel::request_type request;
  request.address = champsim::address{vpn << LOG2_PAGE_SIZE};
  request.v_address = request.address;
  request.ip = champsim::address{0x12345678};
  request.instr_id = instr_id;
  request.cpu = 0;
  request.asid[0] = 0;
  request.asid[1] = 0;
  request.type = access_type::LOAD;
  request.translation_source = translation_origin::DEMAND_DATA;
  request.is_translated = true;
  return request;
}
} // namespace

SCENARIO("The dedicated STLB prefetcher interface receives complete logical access and fill contexts")
{
  do_nothing_MRC lower;
  to_rq_MRP upper;
  CACHE uut{champsim::cache_builder{champsim::defaults::default_stlb}
                .name("433-context_STLB")
                .upper_levels({&upper.queues})
                .lower_level(&lower.queues)
                .sets(8)
                .ways(4)
                .mshr_size(16)
                .pq_size(16)
                .hit_latency(1)
                .fill_latency(1)
                .prefetch_activate(access_type::LOAD)
                .prefetcher<stlb_interface_collector>()};

  std::array<champsim::operable*, 3> elements{{&lower, &upper, &uut}};
  operate_collector[&uut].clear();
  fill_collector[&uut].clear();
  initialize_collector[&uut] = 0;
  for (auto* element : elements) {
    element->initialize();
    element->warmup = false;
    element->begin_phase();
  }

  REQUIRE(initialize_collector.at(&uut) == 1);

  const auto demand = make_demand(100, 7);
  REQUIRE(upper.issue(demand));
  run_cycles(elements, 50);

  REQUIRE(operate_collector.at(&uut).size() == 1);
  const auto& miss = operate_collector.at(&uut).front();
  CHECK(miss.vpn == 100);
  CHECK(miss.v_address == demand.v_address);
  CHECK(miss.ip == demand.ip);
  CHECK(miss.instr_id == demand.instr_id);
  CHECK(miss.cpu == 0);
  CHECK(miss.asid == std::array<uint8_t, 2>{0, 0});
  CHECK(miss.origin == translation_origin::DEMAND_DATA);
  CHECK_FALSE(miss.hit);
  CHECK_FALSE(miss.prefetch_buffer_hit);
  CHECK_FALSE(miss.warmup);

  CHECK(uut.sim_stats.stlb_prefetch_requested == 1);
  CHECK(uut.sim_stats.stlb_prefetch_issued == 1);
  REQUIRE(fill_collector.at(&uut).size() >= 2);
  CHECK(std::any_of(std::begin(fill_collector.at(&uut)), std::end(fill_collector.at(&uut)), [](const auto& fill) {
    return fill.prefetch && fill.origin == translation_origin::STLB_PREFETCH && fill.vpn == 101;
  }));

  auto hit_request = make_demand(100, 8);
  REQUIRE(upper.issue(hit_request));
  run_cycles(elements, 10);

  REQUIRE(operate_collector.at(&uut).size() == 2);
  CHECK(operate_collector.at(&uut).back().hit);
  CHECK(operate_collector.at(&uut).back().vpn == 100);

  REQUIRE(uut.sim_stats.stlb_prefetch_fill == 1);
  CHECK(uut.sim_stats.stlb_prefetch_useless == 0);
  CHECK(uut.sim_stats.stlb_prefetch_buffer_lookup == 0);
  CHECK(uut.sim_stats.stlb_prefetch_buffer_insert == 0);
  uut.end_phase(0);
  CHECK(uut.sim_stats.stlb_prefetch_useless == 0);
}

SCENARIO("The optional STLB prefetch buffer is serial, supplies a demand, and bypasses demand PTW")
{
  do_nothing_MRC lower;
  to_rq_MRP upper;
  CACHE uut{champsim::cache_builder{champsim::defaults::default_stlb}
                .name("433-prefetch-buffer_STLB")
                .upper_levels({&upper.queues})
                .lower_level(&lower.queues)
                .sets(8)
                .ways(4)
                .mshr_size(16)
                .pq_size(16)
                .hit_latency(1)
                .fill_latency(1)
                .prefetch_activate(access_type::LOAD)
                .set_stlb_prefetch_destination_buffer()
                .stlb_prefetch_buffer_size(16)
                .stlb_prefetch_buffer_latency(2)
                .prefetcher<stlb_interface_collector>()};

  std::array<champsim::operable*, 3> elements{{&lower, &upper, &uut}};
  operate_collector[&uut].clear();
  fill_collector[&uut].clear();
  initialize_collector[&uut] = 0;
  for (auto* element : elements) {
    element->initialize();
    element->warmup = false;
    element->begin_phase();
  }

  REQUIRE(upper.issue(make_demand(300, 1)));
  run_cycles(elements, 50);
  REQUIRE(uut.sim_stats.stlb_prefetch_buffer_insert == 1);
  REQUIRE(uut.sim_stats.stlb_prefetch_fill == 1);

  const auto target_address = champsim::address{301ull << LOG2_PAGE_SIZE};
  REQUIRE(std::count(std::begin(lower.addresses), std::end(lower.addresses), target_address) == 1);

  const auto contexts_before_demand = operate_collector.at(&uut).size();
  const auto lookups_before_demand = uut.sim_stats.stlb_prefetch_buffer_lookup;
  REQUIRE(upper.issue(make_demand(301, 2)));

  for (std::size_t cycle = 0; cycle < 20 && uut.sim_stats.stlb_prefetch_buffer_lookup == lookups_before_demand; ++cycle)
    run_cycles(elements, 1);
  REQUIRE(uut.sim_stats.stlb_prefetch_buffer_lookup == lookups_before_demand + 1);

  run_cycles(elements, 1);
  CHECK(operate_collector.at(&uut).size() == contexts_before_demand);
  run_cycles(elements, 1);

  REQUIRE(operate_collector.at(&uut).size() == contexts_before_demand + 1);
  const auto& prefetch_buffer_hit = operate_collector.at(&uut).back();
  CHECK_FALSE(prefetch_buffer_hit.hit);
  CHECK(prefetch_buffer_hit.prefetch_buffer_hit);
  CHECK(prefetch_buffer_hit.vpn == 301);
  CHECK(uut.sim_stats.stlb_prefetch_buffer_hit == 1);
  CHECK(uut.sim_stats.stlb_prefetch_useful == 1);

  run_cycles(elements, 10);
  CHECK(std::count(std::begin(lower.addresses), std::end(lower.addresses), target_address) == 1);
}

SCENARIO("A demand merges into an in-flight STLB-local prefetch before probing the optional buffer")
{
  champsim::channel lower{16, 16, 0, champsim::data::bits{LOG2_PAGE_SIZE}, false};
  to_rq_MRP upper;
  CACHE uut{champsim::cache_builder{champsim::defaults::default_stlb}
                .name("433-prefetch-buffer-late_STLB")
                .upper_levels({&upper.queues})
                .lower_level(&lower)
                .sets(8)
                .ways(4)
                .mshr_size(16)
                .pq_size(16)
                .hit_latency(1)
                .fill_latency(1)
                .prefetch_activate(access_type::LOAD)
                .set_stlb_prefetch_destination_buffer()
                .stlb_prefetch_buffer_size(16)
                .stlb_prefetch_buffer_latency(2)
                .prefetcher<stlb_interface_collector>()};

  std::array<champsim::operable*, 2> elements{{&upper, &uut}};
  operate_collector[&uut].clear();
  fill_collector[&uut].clear();
  initialize_collector[&uut] = 0;
  for (auto* element : elements) {
    element->initialize();
    element->warmup = false;
    element->begin_phase();
  }

  REQUIRE(upper.issue(make_demand(400, 1)));
  run_cycles(elements, 20);

  const auto target_address = champsim::address{401ull << LOG2_PAGE_SIZE};
  auto prefetch_request = std::find_if(std::begin(lower.PQ), std::end(lower.PQ), [target_address](const auto& request) {
    return request.address == target_address;
  });
  REQUIRE(prefetch_request != std::end(lower.PQ));

  const auto pb_lookups_before = uut.sim_stats.stlb_prefetch_buffer_lookup;
  REQUIRE(upper.issue(make_demand(401, 2)));
  run_cycles(elements, 10);

  CHECK(uut.sim_stats.stlb_prefetch_buffer_lookup == pb_lookups_before);
  CHECK(uut.sim_stats.stlb_prefetch_useful == 1);
  CHECK(uut.sim_stats.stlb_prefetch_late == 1);
  CHECK(std::count_if(std::begin(lower.RQ), std::end(lower.RQ), [target_address](const auto& request) {
          return request.address == target_address;
        }) == 0);

  auto returned_request = *prefetch_request;
  returned_request.data = champsim::address{0xabc000};
  lower.PQ.erase(prefetch_request);
  lower.returned.emplace_back(returned_request);
  run_cycles(elements, 10);

  CHECK(uut.sim_stats.stlb_prefetch_buffer_insert == 0);
  REQUIRE(upper.packets.size() == 2);
  CHECK(upper.packets.back().return_time > 0);
}

SCENARIO("A stalled STLB miss activates the dedicated prefetcher only after the miss is accepted")
{
  champsim::channel lower{1, 1, 0, champsim::data::bits{LOG2_PAGE_SIZE}, false};
  to_rq_MRP upper;
  CACHE uut{champsim::cache_builder{champsim::defaults::default_stlb}
                .name("433-retry_STLB")
                .upper_levels({&upper.queues})
                .lower_level(&lower)
                .sets(8)
                .ways(4)
                .mshr_size(16)
                .pq_size(16)
                .hit_latency(1)
                .fill_latency(1)
                .prefetch_activate(access_type::LOAD)
                .prefetcher<stlb_interface_collector>()};

  std::array<champsim::operable*, 2> elements{{&upper, &uut}};
  operate_collector[&uut].clear();
  fill_collector[&uut].clear();
  initialize_collector[&uut] = 0;
  for (auto* element : elements) {
    element->initialize();
    element->warmup = false;
    element->begin_phase();
  }

  auto blocker = make_demand(999, 1);
  REQUIRE(lower.add_rq(blocker));

  REQUIRE(upper.issue(make_demand(200, 2)));
  run_cycles(elements, 20);
  CHECK(operate_collector.at(&uut).empty());

  lower.RQ.clear();
  run_cycles(elements, 20);
  REQUIRE(operate_collector.at(&uut).size() == 1);
  CHECK_FALSE(operate_collector.at(&uut).front().hit);
  CHECK(operate_collector.at(&uut).front().vpn == 200);
}
