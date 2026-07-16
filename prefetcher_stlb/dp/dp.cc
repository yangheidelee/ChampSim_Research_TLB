#include "dp.h"

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

int64_t dp::vpn_distance(uint64_t current, uint64_t previous)
{
  if (current >= previous)
    return static_cast<int64_t>(current - previous);
  return -static_cast<int64_t>(previous - current);
}

void dp::touch(entry& value) { value.last_used = ++table_timestamp_; }

dp::entry* dp::find_entry(int64_t distance)
{
  const auto set_index = static_cast<std::size_t>(static_cast<uint64_t>(distance) % TABLE_SETS);
  auto& set = table_.at(set_index);
  const auto found = std::find_if(std::begin(set), std::end(set), [distance](const auto& value) { return value.valid && value.key == distance; });
  if (found == std::end(set))
    return nullptr;
  touch(*found);
  return &*found;
}

dp::allocation_result dp::allocate_table_entry(int64_t distance)
{
  const auto set_index = static_cast<std::size_t>(static_cast<uint64_t>(distance) % TABLE_SETS);
  auto& set = table_.at(set_index);
  auto victim = std::find_if(std::begin(set), std::end(set), [](const auto& value) { return !value.valid; });
  const bool replaced = victim == std::end(set);
  if (replaced)
    victim = std::min_element(std::begin(set), std::end(set), [](const auto& lhs, const auto& rhs) { return lhs.last_used < rhs.last_used; });

  *victim = entry{};
  victim->valid = true;
  victim->key = distance;
  touch(*victim);
  return {&*victim, replaced};
}

void dp::record_trigger(const champsim::modules::stlb_prefetcher_context& context)
{
  if (!context.warmup)
    ++stats_.triggers;
}

void dp::issue_deltas(const champsim::modules::stlb_prefetcher_context& context, const std::vector<int64_t>& deltas)
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

void dp::print_common_stats(std::string_view name) const
{
  fmt::print("STLB predictor {} trigger {} raw_candidate {} unique_candidate {} duplicate_drop {} current_vpn_drop {} invalid_drop {} submitted {} "
             "accepted {} rejected {}\n",
             name, stats_.triggers, stats_.raw_candidates, stats_.unique_candidates, stats_.duplicate_drops, stats_.current_vpn_drops,
             stats_.invalid_address_drops, stats_.submitted, stats_.accepted, stats_.rejected);
}

dp::entry* dp::allocate_entry(int64_t distance, bool count_stats)
{
  const auto allocated = allocate_table_entry(distance);
  if (count_stats) {
    ++table_allocations_;
    table_replacements_ += static_cast<uint64_t>(allocated.replaced);
  }
  return allocated.value;
}

void dp::train_successor(entry& source, int64_t successor, bool count_stats)
{
  if (count_stats)
    ++transition_updates_;

  for (std::size_t i = 0; i < source.successors.size(); ++i) {
    if (source.successor_valid.at(i) && source.successors.at(i) == successor) {
      source.successor_recency.at(i) = ++successor_timestamp_;
      return;
    }
  }

  auto slot = std::find(std::begin(source.successor_valid), std::end(source.successor_valid), false);
  std::size_t index = 0;
  if (slot != std::end(source.successor_valid)) {
    index = static_cast<std::size_t>(std::distance(std::begin(source.successor_valid), slot));
  } else {
    index = source.successor_recency.at(0) <= source.successor_recency.at(1) ? 0 : 1;
    if (count_stats)
      ++successor_replacements_;
  }

  source.successors.at(index) = successor;
  source.successor_valid.at(index) = true;
  source.successor_recency.at(index) = ++successor_timestamp_;
}

void dp::stlb_prefetcher_initialize()
{
  stats_ = {};
  table_ = {};
  table_timestamp_ = 0;
  previous_miss_vpn_ = 0;
  previous_distance_ = 0;
  previous_miss_valid_ = false;
  previous_distance_valid_ = false;
  successor_timestamp_ = 0;
  table_lookups_ = 0;
  table_hits_ = 0;
  table_misses_ = 0;
  table_allocations_ = 0;
  table_replacements_ = 0;
  transition_updates_ = 0;
  successor_replacements_ = 0;
}

void dp::stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context)
{
  if (context.hit)
    return;
  record_trigger(context);

  if (!previous_miss_valid_) {
    previous_miss_vpn_ = context.vpn;
    previous_miss_valid_ = true;
    return;
  }

  const auto current_distance = vpn_distance(context.vpn, previous_miss_vpn_);
  if (!context.warmup)
    ++table_lookups_;
  auto* current_entry = find_entry(current_distance);
  if (current_entry == nullptr) {
    current_entry = allocate_entry(current_distance, !context.warmup);
    if (!context.warmup)
      ++table_misses_;
  } else if (!context.warmup) {
    ++table_hits_;
  }

  std::vector<int64_t> predictions;
  for (std::size_t i = 0; i < current_entry->successors.size(); ++i)
    if (current_entry->successor_valid.at(i))
      predictions.push_back(current_entry->successors.at(i));
  issue_deltas(context, predictions);

  if (previous_distance_valid_) {
    auto* previous_entry = find_entry(previous_distance_);
    if (previous_entry == nullptr)
      previous_entry = allocate_entry(previous_distance_, !context.warmup);
    train_successor(*previous_entry, current_distance, !context.warmup);
  }

  previous_miss_vpn_ = context.vpn;
  previous_distance_ = current_distance;
  previous_distance_valid_ = true;
}

void dp::stlb_prefetcher_final_stats()
{
  print_common_stats("DP");
  fmt::print("STLB predictor DP table_lookup {} table_hit {} table_miss {} allocation {} replacement {} transition_update {} successor_replacement {}\n",
             table_lookups_, table_hits_, table_misses_, table_allocations_, table_replacements_, transition_updates_, successor_replacements_);
}
