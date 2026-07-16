#include "asp.h"

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

int64_t asp::vpn_distance(uint64_t current, uint64_t previous)
{
  if (current >= previous)
    return static_cast<int64_t>(current - previous);
  return -static_cast<int64_t>(previous - current);
}

void asp::touch(entry& value) { value.last_used = ++table_timestamp_; }

asp::entry* asp::find_entry(uint64_t pc)
{
  auto& set = table_.at(static_cast<std::size_t>(pc % TABLE_SETS));
  const auto found = std::find_if(std::begin(set), std::end(set), [pc](const auto& value) { return value.valid && value.key == pc; });
  if (found == std::end(set))
    return nullptr;
  touch(*found);
  return &*found;
}

asp::allocation_result asp::allocate_entry(uint64_t pc)
{
  auto& set = table_.at(static_cast<std::size_t>(pc % TABLE_SETS));
  auto victim = std::find_if(std::begin(set), std::end(set), [](const auto& value) { return !value.valid; });
  const bool replaced = victim == std::end(set);
  if (replaced)
    victim = std::min_element(std::begin(set), std::end(set), [](const auto& lhs, const auto& rhs) { return lhs.last_used < rhs.last_used; });

  *victim = entry{};
  victim->valid = true;
  victim->key = pc;
  touch(*victim);
  return {&*victim, replaced};
}

void asp::record_trigger(const champsim::modules::stlb_prefetcher_context& context)
{
  if (!context.warmup)
    ++stats_.triggers;
}

void asp::issue_deltas(const champsim::modules::stlb_prefetcher_context& context, const std::vector<int64_t>& deltas)
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

void asp::print_common_stats(std::string_view name) const
{
  fmt::print("STLB predictor {} trigger {} raw_candidate {} unique_candidate {} duplicate_drop {} current_vpn_drop {} invalid_drop {} submitted {} "
             "accepted {} rejected {}\n",
             name, stats_.triggers, stats_.raw_candidates, stats_.unique_candidates, stats_.duplicate_drops, stats_.current_vpn_drops,
             stats_.invalid_address_drops, stats_.submitted, stats_.accepted, stats_.rejected);
}

void asp::stlb_prefetcher_initialize()
{
  stats_ = {};
  table_ = {};
  table_timestamp_ = 0;
  table_lookups_ = 0;
  table_hits_ = 0;
  table_misses_ = 0;
  table_allocations_ = 0;
  table_replacements_ = 0;
  stride_matches_ = 0;
  stride_mismatches_ = 0;
  stable_predictions_ = 0;
}

void asp::stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context)
{
  if (context.hit)
    return;
  record_trigger(context);

  const auto pc = context.ip.to<uint64_t>();
  if (!context.warmup)
    ++table_lookups_;
  auto* found = find_entry(pc);
  if (found == nullptr) {
    const auto allocated = allocate_entry(pc);
    found = allocated.value;
    found->previous_miss_vpn = context.vpn;
    found->previous_miss_valid = true;
    if (!context.warmup) {
      ++table_misses_;
      ++table_allocations_;
      table_replacements_ += static_cast<uint64_t>(allocated.replaced);
    }
    return;
  }

  if (!context.warmup)
    ++table_hits_;
  const auto new_stride = vpn_distance(context.vpn, found->previous_miss_vpn);
  bool predict = false;

  if (!found->stride_valid) {
    found->learned_stride = new_stride;
    found->stride_valid = true;
    found->stability_count = 0;
  } else if (new_stride == found->learned_stride) {
    found->stability_count = static_cast<uint8_t>(std::min<unsigned>(found->stability_count + 1, std::numeric_limits<uint8_t>::max()));
    predict = found->stability_count >= STABILITY_THRESHOLD;
    if (!context.warmup) {
      ++stride_matches_;
      if (predict)
        ++stable_predictions_;
    }
  } else {
    found->learned_stride = new_stride;
    found->stability_count = 0;
    if (!context.warmup)
      ++stride_mismatches_;
  }

  found->previous_miss_vpn = context.vpn;
  found->previous_miss_valid = true;
  if (predict)
    issue_deltas(context, {found->learned_stride});
}

void asp::stlb_prefetcher_final_stats()
{
  print_common_stats("ASP");
  fmt::print("STLB predictor ASP table_lookup {} table_hit {} table_miss {} allocation {} replacement {} stride_match {} stride_mismatch {} "
             "stable_prediction {} threshold {}\n",
             table_lookups_, table_hits_, table_misses_, table_allocations_, table_replacements_, stride_matches_, stride_mismatches_,
             stable_predictions_, STABILITY_THRESHOLD);
}
