#include "sp.h"

#include <algorithm>
#include <limits>

#include <fmt/core.h>

namespace
{
bool add_vpn_delta(uint64_t vpn, int64_t delta, uint64_t& target)
{
  const auto max_vpn = std::numeric_limits<uint64_t>::max() >> LOG2_PAGE_SIZE;
  if (delta >= 0) {
    const auto magnitude = static_cast<uint64_t>(delta);
    if (vpn > max_vpn || magnitude > max_vpn - vpn)
      return false;
    target = vpn + magnitude;
    return true;
  }

  const auto magnitude = static_cast<uint64_t>(-(delta + 1)) + 1;
  if (magnitude > vpn)
    return false;
  target = vpn - magnitude;
  return target <= max_vpn;
}
} // namespace

void sp::record_trigger(const champsim::modules::stlb_prefetcher_context& context)
{
  if (!context.warmup)
    ++stats_.triggers;
}

void sp::issue_deltas(const champsim::modules::stlb_prefetcher_context& context, const std::vector<int64_t>& deltas)
{
  std::vector<uint64_t> candidates;
  candidates.reserve(deltas.size());

  for (const auto delta : deltas) {
    if (!context.warmup)
      ++stats_.raw_candidates;

    uint64_t target = 0;
    if (!add_vpn_delta(context.vpn, delta, target)) {
      if (!context.warmup)
        ++stats_.invalid_address_drops;
      continue;
    }
    if (target == context.vpn) {
      if (!context.warmup)
        ++stats_.current_vpn_drops;
      continue;
    }
    if (std::find(std::begin(candidates), std::end(candidates), target) != std::end(candidates)) {
      if (!context.warmup)
        ++stats_.duplicate_drops;
      continue;
    }
    candidates.push_back(target);
  }

  if (!context.warmup)
    stats_.unique_candidates += std::size(candidates);

  for (const auto target : candidates) {
    if (!context.warmup)
      ++stats_.submitted;
    const bool accepted = prefetch_translation(champsim::address{target << LOG2_PAGE_SIZE}, context.metadata);
    if (!context.warmup) {
      if (accepted)
        ++stats_.accepted;
      else
        ++stats_.rejected;
    }
  }
}

void sp::print_common_stats(std::string_view name) const
{
  fmt::print("STLB predictor {} trigger {} raw_candidate {} unique_candidate {} duplicate_drop {} current_vpn_drop {} invalid_drop {} submitted {} "
             "accepted {} rejected {}\n",
             name, stats_.triggers, stats_.raw_candidates, stats_.unique_candidates, stats_.duplicate_drops, stats_.current_vpn_drops,
             stats_.invalid_address_drops, stats_.submitted, stats_.accepted, stats_.rejected);
}

void sp::stlb_prefetcher_initialize() { stats_ = {}; }

void sp::stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context)
{
  if (context.hit)
    return;
  record_trigger(context);
  issue_deltas(context, {1});
}

void sp::stlb_prefetcher_final_stats() { print_common_stats("SP"); }
