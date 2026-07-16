#include "h2p.h"

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

int64_t h2p::vpn_distance(uint64_t current, uint64_t previous)
{
  if (current >= previous)
    return static_cast<int64_t>(current - previous);
  return -static_cast<int64_t>(previous - current);
}

void h2p::record_trigger(const champsim::modules::stlb_prefetcher_context& context)
{
  if (!context.warmup)
    ++stats_.triggers;
}

void h2p::issue_deltas(const champsim::modules::stlb_prefetcher_context& context, const std::vector<int64_t>& deltas)
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

void h2p::print_common_stats(std::string_view name) const
{
  fmt::print("STLB predictor {} trigger {} raw_candidate {} unique_candidate {} duplicate_drop {} current_vpn_drop {} invalid_drop {} submitted {} "
             "accepted {} rejected {}\n",
             name, stats_.triggers, stats_.raw_candidates, stats_.unique_candidates, stats_.duplicate_drops, stats_.current_vpn_drops,
             stats_.invalid_address_drops, stats_.submitted, stats_.accepted, stats_.rejected);
}

void h2p::stlb_prefetcher_initialize()
{
  stats_ = {};
  previous_miss_vpn_ = 0;
  previous_distance_ = 0;
  previous_miss_valid_ = false;
  previous_distance_valid_ = false;
  history_not_ready_ = 0;
  equal_distance_deduplications_ = 0;
}

void h2p::stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context)
{
  if (context.hit)
    return;
  record_trigger(context);

  if (!previous_miss_valid_) {
    previous_miss_vpn_ = context.vpn;
    previous_miss_valid_ = true;
    if (!context.warmup)
      ++history_not_ready_;
    return;
  }

  const auto new_distance = vpn_distance(context.vpn, previous_miss_vpn_);
  if (!previous_distance_valid_) {
    previous_distance_ = new_distance;
    previous_distance_valid_ = true;
    previous_miss_vpn_ = context.vpn;
    if (!context.warmup)
      ++history_not_ready_;
    return;
  }

  if (!context.warmup && new_distance == previous_distance_)
    ++equal_distance_deduplications_;
  issue_deltas(context, {new_distance, previous_distance_});

  previous_distance_ = new_distance;
  previous_miss_vpn_ = context.vpn;
}

void h2p::stlb_prefetcher_final_stats()
{
  print_common_stats("H2P");
  fmt::print("STLB predictor H2P history_not_ready {} equal_distance_dedup {}\n", history_not_ready_, equal_distance_deduplications_);
}
