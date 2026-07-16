#include <catch.hpp>

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include "cache.h"
#include "defaults.hpp"
#include "../../../prefetcher_stlb/asp/asp.h"
#include "../../../prefetcher_stlb/dp/dp.h"
#include "../../../prefetcher_stlb/h2p/h2p.h"
#include "../../../prefetcher_stlb/masp/masp.h"
#include "../../../prefetcher_stlb/sp/sp.h"
#include "../../../prefetcher_stlb/stp/stp.h"

namespace
{
using context_type = champsim::modules::stlb_prefetcher_context;

context_type make_context(uint64_t vpn, uint64_t pc = 0x1000, bool hit = false, bool warmup = false)
{
  context_type context;
  context.vpn = vpn;
  context.v_address = champsim::address{vpn << LOG2_PAGE_SIZE};
  context.ip = champsim::address{pc};
  context.cpu = 0;
  context.asid = {0, 0};
  context.type = access_type::LOAD;
  context.origin = translation_origin::DEMAND_DATA;
  context.hit = hit;
  context.warmup = warmup;
  return context;
}

template <typename Predictor>
class predictor_harness
{
  champsim::channel lower_{64, 64, 64, champsim::data::bits{LOG2_PAGE_SIZE}, false};
  CACHE cache_{champsim::cache_builder{champsim::defaults::default_stlb}
                   .name("434-predictor_STLB")
                   .lower_level(&lower_)
                   .sets(16)
                   .ways(4)
                   .mshr_size(32)
                   .pq_size(32)
                   .tag_bandwidth(champsim::bandwidth::maximum_type{8})
                   .fill_bandwidth(champsim::bandwidth::maximum_type{8})
                   .hit_latency(1)
                   .fill_latency(1)};
  Predictor predictor_{&cache_};

public:
  predictor_harness()
  {
    cache_.initialize();
    cache_.warmup = false;
    cache_.begin_phase();
    predictor_.stlb_prefetcher_initialize();
  }

  std::vector<uint64_t> operate(uint64_t vpn, uint64_t pc = 0x1000, bool hit = false, bool warmup = false)
  {
    predictor_.stlb_prefetcher_operate(make_context(vpn, pc, hit, warmup));
    for (std::size_t cycle = 0; cycle < 16; ++cycle)
      cache_._operate();

    std::vector<uint64_t> result;
    for (const auto& request : lower_.PQ)
      result.push_back(request.v_address.to<uint64_t>() >> LOG2_PAGE_SIZE);
    lower_.PQ.clear();
    return result;
  }

  [[nodiscard]] const auto& stats() const { return predictor_.candidate_statistics(); }
};
} // namespace

SCENARIO("SP and STP generate their fixed VPN candidates in deterministic order")
{
  predictor_harness<sp> sequential;
  CHECK(sequential.operate(100) == std::vector<uint64_t>{101});

  predictor_harness<stp> fixed_stride;
  CHECK(fixed_stride.operate(100) == std::vector<uint64_t>{98, 99, 101, 102});
}

SCENARIO("H2P uses only the two most recent miss distances and removes duplicate candidates")
{
  predictor_harness<h2p> uut;
  CHECK(uut.operate(100).empty());
  CHECK(uut.operate(104).empty());
  CHECK(uut.operate(105) == std::vector<uint64_t>{106, 109});

  predictor_harness<h2p> duplicate;
  CHECK(duplicate.operate(100).empty());
  CHECK(duplicate.operate(104).empty());
  CHECK(duplicate.operate(108) == std::vector<uint64_t>{112});
  CHECK(duplicate.stats().duplicate_drops == 1);
}

SCENARIO("MASP predicts with the old per-PC stride before installing the newly observed stride")
{
  predictor_harness<masp> uut;
  CHECK(uut.operate(100).empty());
  CHECK(uut.operate(105) == std::vector<uint64_t>{110});
  CHECK(uut.operate(108) == std::vector<uint64_t>{113, 111});

  predictor_harness<masp> duplicate;
  CHECK(duplicate.operate(100).empty());
  CHECK(duplicate.operate(104) == std::vector<uint64_t>{108});
  CHECK(duplicate.operate(108) == std::vector<uint64_t>{112});
  CHECK(duplicate.stats().duplicate_drops == 1);
}

SCENARIO("ASP requires two confirmations of the learned per-PC miss stride")
{
  predictor_harness<asp> uut;
  CHECK(uut.operate(100).empty());
  CHECK(uut.operate(104).empty());
  CHECK(uut.operate(108).empty());
  CHECK(uut.operate(112) == std::vector<uint64_t>{116});
}

SCENARIO("DP predicts before training the current distance transition")
{
  predictor_harness<dp> uut;
  CHECK(uut.operate(100).empty());
  CHECK(uut.operate(104).empty());
  CHECK(uut.operate(105).empty());
  CHECK(uut.operate(109) == std::vector<uint64_t>{110});
  CHECK(uut.operate(110) == std::vector<uint64_t>{114});
}

SCENARIO("STLB hits do not alter miss histories")
{
  predictor_harness<h2p> h2_uut;
  CHECK(h2_uut.operate(100).empty());
  CHECK(h2_uut.operate(999, 0x2000, true).empty());
  CHECK(h2_uut.operate(104).empty());
  CHECK(h2_uut.operate(888, 0x2000, true).empty());
  CHECK(h2_uut.operate(105) == std::vector<uint64_t>{106, 109});

  predictor_harness<dp> dp_uut;
  CHECK(dp_uut.operate(100).empty());
  CHECK(dp_uut.operate(700, 0x3000, true).empty());
  CHECK(dp_uut.operate(104).empty());
  CHECK(dp_uut.operate(105).empty());
  CHECK(dp_uut.operate(800, 0x3000, true).empty());
  CHECK(dp_uut.operate(109) == std::vector<uint64_t>{110});
  CHECK(dp_uut.operate(110) == std::vector<uint64_t>{114});
}

SCENARIO("ASP and MASP keep independent per-PC miss histories")
{
  constexpr uint64_t pc_a = 0x1000;
  constexpr uint64_t pc_b = 0x2000;

  predictor_harness<asp> conservative;
  CHECK(conservative.operate(100, pc_a).empty());
  CHECK(conservative.operate(1000, pc_b).empty());
  CHECK(conservative.operate(104, pc_a).empty());
  CHECK(conservative.operate(1016, pc_b).empty());
  CHECK(conservative.operate(108, pc_a).empty());
  CHECK(conservative.operate(1032, pc_b).empty());
  CHECK(conservative.operate(112, pc_a) == std::vector<uint64_t>{116});
  CHECK(conservative.operate(1048, pc_b) == std::vector<uint64_t>{1064});

  predictor_harness<masp> aggressive;
  CHECK(aggressive.operate(100, pc_a).empty());
  CHECK(aggressive.operate(1000, pc_b).empty());
  CHECK(aggressive.operate(104, pc_a) == std::vector<uint64_t>{108});
  CHECK(aggressive.operate(1016, pc_b) == std::vector<uint64_t>{1032});
  CHECK(aggressive.operate(108, pc_a) == std::vector<uint64_t>{112});
  CHECK(aggressive.operate(1032, pc_b) == std::vector<uint64_t>{1048});
}

SCENARIO("Warmup trains predictor state without contributing predictor-private ROI statistics")
{
  predictor_harness<asp> uut;
  CHECK(uut.operate(100, 0x1000, false, true).empty());
  CHECK(uut.operate(104, 0x1000, false, true).empty());
  CHECK(uut.operate(108, 0x1000, false, true).empty());
  CHECK(uut.stats().triggers == 0);
  CHECK(uut.operate(112) == std::vector<uint64_t>{116});
  CHECK(uut.stats().triggers == 1);
}
