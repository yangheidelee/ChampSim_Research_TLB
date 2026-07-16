#include "stlb_stride.h"

#include <algorithm>
#include <limits>

void stlb_stride::stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context)
{
  if (context.hit || context.type != access_type::LOAD)
    return;

  const auto vpn = context.vpn;
  const auto key = context.ip.to<uint64_t>();
  auto found = table.find(key);
  if (found == table.end()) {
    if (table.size() >= TABLE_SIZE)
      table.erase(table.begin());
    table.emplace(key, entry{vpn, 0, 0, true});
    return;
  }

  auto& state = found->second;
  const auto delta = static_cast<int64_t>(vpn) - static_cast<int64_t>(state.last_vpn);
  if (delta != 0 && delta == state.stride)
    state.confidence = static_cast<uint8_t>(std::min<unsigned>(static_cast<unsigned>(state.confidence) + 1, 3));
  else {
    state.stride = delta;
    state.confidence = 0;
  }
  state.last_vpn = vpn;

  if (state.stride == 0 || state.confidence == 0)
    return;

  const auto candidate = static_cast<int64_t>(vpn) + state.stride;
  const auto max_vpn = std::numeric_limits<uint64_t>::max() >> LOG2_PAGE_SIZE;
  if (candidate < 0 || static_cast<uint64_t>(candidate) > max_vpn)
    return;

  prefetch_translation(champsim::address{static_cast<uint64_t>(candidate) << LOG2_PAGE_SIZE}, context.metadata);
}
