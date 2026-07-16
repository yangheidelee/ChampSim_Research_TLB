#include "atp.h"

#include <limits>

#include <fmt/core.h>

void atp::fake_prefetch_queue::clear() { entries_.clear(); }

bool atp::fake_prefetch_queue::consume(uint64_t vpn)
{
  for (auto current = entries_.begin(); current != entries_.end(); ++current) {
    if (*current == vpn) {
      entries_.erase(current);
      return true;
    }
  }

  return false;
}

void atp::fake_prefetch_queue::insert(uint64_t vpn, bool& duplicate, bool& eviction)
{
  duplicate = false;
  eviction = false;

  for (const uint64_t current : entries_) {
    if (current == vpn) {
      duplicate = true;
      return;
    }
  }

  if (entries_.size() == FPQ_SIZE) {
    entries_.pop_front();
    eviction = true;
  }

  entries_.push_back(vpn);
}

std::size_t atp::fake_prefetch_queue::size() const { return entries_.size(); }

void atp::increment_counter(uint16_t& counter, uint16_t maximum)
{
  if (counter < maximum)
    ++counter;
}

void atp::decrement_counter(uint16_t& counter)
{
  if (counter > 0)
    --counter;
}

int64_t atp::vpn_distance(uint64_t current, uint64_t previous)
{
  if (current >= previous)
    return static_cast<int64_t>(current - previous);

  return -static_cast<int64_t>(previous - current);
}

bool atp::add_vpn_delta(uint64_t vpn, int64_t delta, uint64_t& target)
{
  const uint64_t max_vpn = std::numeric_limits<uint64_t>::max() >> LOG2_PAGE_SIZE;

  if (delta >= 0) {
    const uint64_t magnitude = static_cast<uint64_t>(delta);
    if (vpn > max_vpn)
      return false;
    if (magnitude > max_vpn - vpn)
      return false;

    target = vpn + magnitude;
    return true;
  }

  const uint64_t magnitude = static_cast<uint64_t>(-(delta + 1)) + 1;
  if (magnitude > vpn)
    return false;

  target = vpn - magnitude;
  if (target > max_vpn)
    return false;

  return true;
}

void atp::add_candidate(candidate_list& candidates, uint64_t current_vpn, int64_t delta) const
{
  ++candidates.raw_count;

  uint64_t target = 0;
  if (!add_vpn_delta(current_vpn, delta, target)) {
    ++candidates.invalid_drops;
    return;
  }

  if (target == current_vpn) {
    ++candidates.current_vpn_drops;
    return;
  }

  for (std::size_t index = 0; index < candidates.count; ++index) {
    if (candidates.values[index] == target) {
      ++candidates.duplicate_drops;
      return;
    }
  }

  if (candidates.count >= MAX_CANDIDATES) {
    ++candidates.invalid_drops;
    return;
  }

  candidates.values[candidates.count] = target;
  ++candidates.count;
}

atp::candidate_list atp::generate_h2p_candidates(uint64_t current_vpn)
{
  candidate_list candidates;

  if (!h2p_previous_miss_valid_) {
    h2p_previous_miss_vpn_ = current_vpn;
    h2p_previous_miss_valid_ = true;
    return candidates;
  }

  const int64_t new_distance = vpn_distance(current_vpn, h2p_previous_miss_vpn_);
  if (!h2p_previous_distance_valid_) {
    h2p_previous_distance_ = new_distance;
    h2p_previous_distance_valid_ = true;
    h2p_previous_miss_vpn_ = current_vpn;
    return candidates;
  }

  add_candidate(candidates, current_vpn, new_distance);
  add_candidate(candidates, current_vpn, h2p_previous_distance_);

  h2p_previous_distance_ = new_distance;
  h2p_previous_miss_vpn_ = current_vpn;
  return candidates;
}

atp::masp_entry* atp::find_masp_entry(uint64_t pc)
{
  const std::size_t set_index = static_cast<std::size_t>(pc % MASP_TABLE_SETS);
  std::array<masp_entry, MASP_TABLE_WAYS>& set = masp_table_[set_index];

  for (std::size_t way = 0; way < MASP_TABLE_WAYS; ++way) {
    if (set[way].valid && set[way].pc == pc) {
      touch_masp_entry(set[way]);
      return &set[way];
    }
  }

  return nullptr;
}

atp::masp_entry* atp::allocate_masp_entry(uint64_t pc, bool& replacement)
{
  const std::size_t set_index = static_cast<std::size_t>(pc % MASP_TABLE_SETS);
  std::array<masp_entry, MASP_TABLE_WAYS>& set = masp_table_[set_index];

  replacement = true;
  std::size_t victim_way = 0;

  for (std::size_t way = 0; way < MASP_TABLE_WAYS; ++way) {
    if (!set[way].valid) {
      victim_way = way;
      replacement = false;
      break;
    }

    if (set[way].last_used < set[victim_way].last_used)
      victim_way = way;
  }

  set[victim_way] = masp_entry{};
  set[victim_way].valid = true;
  set[victim_way].pc = pc;
  touch_masp_entry(set[victim_way]);
  return &set[victim_way];
}

void atp::touch_masp_entry(masp_entry& value)
{
  ++masp_timestamp_;
  value.last_used = masp_timestamp_;
}

atp::candidate_list atp::generate_masp_candidates(uint64_t current_vpn, uint64_t pc, bool record_statistics)
{
  candidate_list candidates;

  if (record_statistics)
    ++stats_.masp_table_lookups;

  masp_entry* found = find_masp_entry(pc);
  if (found == nullptr) {
    bool replacement = false;
    found = allocate_masp_entry(pc, replacement);
    found->previous_miss_vpn = current_vpn;

    if (record_statistics) {
      ++stats_.masp_table_misses;
      if (replacement)
        ++stats_.masp_table_replacements;
    }

    return candidates;
  }

  if (record_statistics)
    ++stats_.masp_table_hits;

  const int64_t new_stride = vpn_distance(current_vpn, found->previous_miss_vpn);

  if (found->stride_valid)
    add_candidate(candidates, current_vpn, found->stored_stride);
  add_candidate(candidates, current_vpn, new_stride);

  found->stored_stride = new_stride;
  found->stride_valid = true;
  found->previous_miss_vpn = current_vpn;
  return candidates;
}

atp::candidate_list atp::generate_stp_candidates(uint64_t current_vpn) const
{
  candidate_list candidates;
  add_candidate(candidates, current_vpn, -2);
  add_candidate(candidates, current_vpn, -1);
  add_candidate(candidates, current_vpn, 1);
  add_candidate(candidates, current_vpn, 2);
  return candidates;
}

void atp::update_counters(bool h2p_hit, bool masp_hit, bool stp_hit)
{
  // This is the update table in Figure 7 of the ATP paper. Keeping all eight
  // cases explicit makes the implementation directly auditable against it.
  if (!h2p_hit && !masp_hit && !stp_hit) {
    decrement_counter(enable_pref_);
    return;
  }

  increment_counter(enable_pref_, ENABLE_PREF_MAXIMUM);

  if (!h2p_hit && !masp_hit && stp_hit) {
    decrement_counter(select_1_);
    increment_counter(select_2_, SELECT_2_MAXIMUM);
    return;
  }

  if (!h2p_hit && masp_hit && !stp_hit) {
    decrement_counter(select_1_);
    decrement_counter(select_2_);
    return;
  }

  if (!h2p_hit && masp_hit && stp_hit) {
    decrement_counter(select_1_);
    return;
  }

  if (h2p_hit && !masp_hit && !stp_hit) {
    increment_counter(select_1_, SELECT_1_MAXIMUM);
    return;
  }

  if (h2p_hit && !masp_hit && stp_hit) {
    increment_counter(select_2_, SELECT_2_MAXIMUM);
    return;
  }

  if (h2p_hit && masp_hit && !stp_hit) {
    decrement_counter(select_2_);
    return;
  }

  // H2P, MASP, and STP all hit: only enable_pref is incremented.
}

atp::selected_prefetcher atp::select_prefetcher() const
{
  if (enable_pref_ < ENABLE_PREF_THRESHOLD)
    return DISABLED;

  if (select_1_ >= SELECT_1_THRESHOLD)
    return H2P;

  if (select_2_ >= SELECT_2_THRESHOLD)
    return STP;

  return MASP;
}

void atp::record_candidate_statistics(const candidate_list& h2p_candidates, const candidate_list& masp_candidates,
                                           const candidate_list& stp_candidates)
{
  stats_.h2p_raw_candidates += h2p_candidates.raw_count;
  stats_.h2p_candidates += h2p_candidates.count;
  stats_.masp_raw_candidates += masp_candidates.raw_count;
  stats_.masp_candidates += masp_candidates.count;
  stats_.stp_raw_candidates += stp_candidates.raw_count;
  stats_.stp_candidates += stp_candidates.count;

  stats_.invalid_candidate_drops += h2p_candidates.invalid_drops;
  stats_.invalid_candidate_drops += masp_candidates.invalid_drops;
  stats_.invalid_candidate_drops += stp_candidates.invalid_drops;

  stats_.current_vpn_drops += h2p_candidates.current_vpn_drops;
  stats_.current_vpn_drops += masp_candidates.current_vpn_drops;
  stats_.current_vpn_drops += stp_candidates.current_vpn_drops;

  stats_.duplicate_candidate_drops += h2p_candidates.duplicate_drops;
  stats_.duplicate_candidate_drops += masp_candidates.duplicate_drops;
  stats_.duplicate_candidate_drops += stp_candidates.duplicate_drops;
}

void atp::update_h2p_fpq(const candidate_list& candidates, bool record_statistics)
{
  for (std::size_t index = 0; index < candidates.count; ++index) {
    bool duplicate = false;
    bool eviction = false;
    h2p_fpq_.insert(candidates.values[index], duplicate, eviction);

    if (record_statistics) {
      if (duplicate)
        ++stats_.h2p_fpq_duplicates;
      else
        ++stats_.h2p_fpq_insertions;
      if (eviction)
        ++stats_.h2p_fpq_evictions;
    }
  }
}

void atp::update_masp_fpq(const candidate_list& candidates, bool record_statistics)
{
  for (std::size_t index = 0; index < candidates.count; ++index) {
    bool duplicate = false;
    bool eviction = false;
    masp_fpq_.insert(candidates.values[index], duplicate, eviction);

    if (record_statistics) {
      if (duplicate)
        ++stats_.masp_fpq_duplicates;
      else
        ++stats_.masp_fpq_insertions;
      if (eviction)
        ++stats_.masp_fpq_evictions;
    }
  }
}

void atp::update_stp_fpq(const candidate_list& candidates, bool record_statistics)
{
  for (std::size_t index = 0; index < candidates.count; ++index) {
    bool duplicate = false;
    bool eviction = false;
    stp_fpq_.insert(candidates.values[index], duplicate, eviction);

    if (record_statistics) {
      if (duplicate)
        ++stats_.stp_fpq_duplicates;
      else
        ++stats_.stp_fpq_insertions;
      if (eviction)
        ++stats_.stp_fpq_evictions;
    }
  }
}

void atp::issue_candidates(selected_prefetcher selected, const candidate_list& candidates,
                                const champsim::modules::stlb_prefetcher_context& context, bool record_statistics)
{
  for (std::size_t index = 0; index < candidates.count; ++index) {
    if (record_statistics) {
      if (selected == H2P)
        ++stats_.h2p_submitted;
      else if (selected == MASP)
        ++stats_.masp_submitted;
      else if (selected == STP)
        ++stats_.stp_submitted;
    }

    const uint64_t target_vpn = candidates.values[index];
    const champsim::address target_address{target_vpn << LOG2_PAGE_SIZE};
    const bool accepted = prefetch_translation(target_address, context.metadata);

    if (!record_statistics)
      continue;

    if (selected == H2P) {
      if (accepted)
        ++stats_.h2p_accepted;
      else
        ++stats_.h2p_rejected;
    } else if (selected == MASP) {
      if (accepted)
        ++stats_.masp_accepted;
      else
        ++stats_.masp_rejected;
    } else if (selected == STP) {
      if (accepted)
        ++stats_.stp_accepted;
      else
        ++stats_.stp_rejected;
    }
  }
}

void atp::issue_selected_candidates(selected_prefetcher selected, const candidate_list& h2p_candidates,
                                         const candidate_list& masp_candidates, const candidate_list& stp_candidates,
                                         const champsim::modules::stlb_prefetcher_context& context, bool record_statistics)
{
  if (selected == DISABLED) {
    if (record_statistics)
      ++stats_.disabled_selections;
    return;
  }

  if (selected == H2P) {
    if (record_statistics)
      ++stats_.h2p_selections;
    issue_candidates(H2P, h2p_candidates, context, record_statistics);
    return;
  }

  if (selected == MASP) {
    if (record_statistics)
      ++stats_.masp_selections;
    issue_candidates(MASP, masp_candidates, context, record_statistics);
    return;
  }

  if (record_statistics)
    ++stats_.stp_selections;
  issue_candidates(STP, stp_candidates, context, record_statistics);
}

void atp::stlb_prefetcher_initialize()
{
  stats_ = statistics{};

  // The paper specifies counter widths and MSB-based decisions, but not reset
  // values. Weakly-zero initialization is used here: each counter starts one
  // below its MSB threshold. Thus ATP initially disables prefetching without
  // strongly biasing any constituent predictor.
  enable_pref_ = ENABLE_PREF_INITIAL;
  select_1_ = SELECT_1_INITIAL;
  select_2_ = SELECT_2_INITIAL;

  h2p_fpq_.clear();
  masp_fpq_.clear();
  stp_fpq_.clear();

  h2p_previous_miss_vpn_ = 0;
  h2p_previous_distance_ = 0;
  h2p_previous_miss_valid_ = false;
  h2p_previous_distance_valid_ = false;

  masp_table_ = {};
  masp_timestamp_ = 0;
}

void atp::stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context)
{
  const bool record_statistics = !context.warmup;

  // In PB mode, prefetch_buffer_hit is the paper's real PQ-hit feedback. In
  // direct-fill mode, the first useful hit on a prefetched STLB entry is its
  // closest observable equivalent. Ordinary STLB hits did not require a
  // translation prefetch in either model.
  if (context.hit && !context.useful_prefetch) {
    if (record_statistics)
      ++stats_.ordinary_hit_events_ignored;
    return;
  }

  const bool feedback_hit = context.prefetch_buffer_hit || (context.hit && context.useful_prefetch);
  if (record_statistics) {
    ++stats_.feedback_events;
    if (context.prefetch_buffer_hit)
      ++stats_.prefetch_buffer_hit_events;
    if (feedback_hit)
      ++stats_.useful_prefetch_hit_events;
    else
      ++stats_.demand_miss_events;
  }

  // A hit consumes the fake entry, just as the corresponding prediction in
  // a real translation PQ would be consumed by the demand. Entries that are
  // never used age out under the paper's 16-entry FIFO replacement policy.
  const bool h2p_hit = h2p_fpq_.consume(context.vpn);
  const bool masp_hit = masp_fpq_.consume(context.vpn);
  const bool stp_hit = stp_fpq_.consume(context.vpn);

  if (record_statistics) {
    if (h2p_hit)
      ++stats_.h2p_fpq_hits;
    if (masp_hit)
      ++stats_.masp_fpq_hits;
    if (stp_hit)
      ++stats_.stp_fpq_hits;
  }

  update_counters(h2p_hit, masp_hit, stp_hit);
  const selected_prefetcher selected = select_prefetcher();

  // All three children train and all three FPQs receive their hypothetical
  // predictions, regardless of which child the decision tree selected.
  const candidate_list h2p_candidates = generate_h2p_candidates(context.vpn);
  const uint64_t pc = context.ip.to<uint64_t>();
  const candidate_list masp_candidates = generate_masp_candidates(context.vpn, pc, record_statistics);
  const candidate_list stp_candidates = generate_stp_candidates(context.vpn);

  if (record_statistics)
    record_candidate_statistics(h2p_candidates, masp_candidates, stp_candidates);

  update_h2p_fpq(h2p_candidates, record_statistics);
  update_masp_fpq(masp_candidates, record_statistics);
  update_stp_fpq(stp_candidates, record_statistics);

  issue_selected_candidates(selected, h2p_candidates, masp_candidates, stp_candidates, context, record_statistics);
}

void atp::stlb_prefetcher_final_stats()
{
  fmt::print("STLB predictor ATP feedback {} demand_miss {} useful_prefetch_hit {} prefetch_buffer_hit {} ordinary_hit_ignored {}\n",
             stats_.feedback_events, stats_.demand_miss_events, stats_.useful_prefetch_hit_events, stats_.prefetch_buffer_hit_events,
             stats_.ordinary_hit_events_ignored);
  fmt::print("STLB predictor ATP fpq_hit h2p {} masp {} stp {}\n", stats_.h2p_fpq_hits, stats_.masp_fpq_hits, stats_.stp_fpq_hits);
  fmt::print("STLB predictor ATP selection disabled {} h2p {} masp {} stp {}\n", stats_.disabled_selections, stats_.h2p_selections,
             stats_.masp_selections, stats_.stp_selections);
  fmt::print("STLB predictor ATP candidate h2p_raw {} h2p_unique {} masp_raw {} masp_unique {} stp_raw {} stp_unique {} invalid_drop {} "
             "current_vpn_drop {} duplicate_drop {}\n",
             stats_.h2p_raw_candidates, stats_.h2p_candidates, stats_.masp_raw_candidates, stats_.masp_candidates, stats_.stp_raw_candidates,
             stats_.stp_candidates, stats_.invalid_candidate_drops, stats_.current_vpn_drops, stats_.duplicate_candidate_drops);
  fmt::print("STLB predictor ATP fpq_update h2p_insert {} h2p_duplicate {} h2p_evict {} masp_insert {} masp_duplicate {} masp_evict {} "
             "stp_insert {} stp_duplicate {} stp_evict {}\n",
             stats_.h2p_fpq_insertions, stats_.h2p_fpq_duplicates, stats_.h2p_fpq_evictions, stats_.masp_fpq_insertions,
             stats_.masp_fpq_duplicates, stats_.masp_fpq_evictions, stats_.stp_fpq_insertions, stats_.stp_fpq_duplicates, stats_.stp_fpq_evictions);
  fmt::print("STLB predictor ATP issue h2p_submitted {} h2p_accepted {} h2p_rejected {} masp_submitted {} masp_accepted {} masp_rejected {} "
             "stp_submitted {} stp_accepted {} stp_rejected {}\n",
             stats_.h2p_submitted, stats_.h2p_accepted, stats_.h2p_rejected, stats_.masp_submitted, stats_.masp_accepted, stats_.masp_rejected,
             stats_.stp_submitted, stats_.stp_accepted, stats_.stp_rejected);
  fmt::print("STLB predictor ATP masp_table lookup {} hit {} miss {} replacement {}\n", stats_.masp_table_lookups, stats_.masp_table_hits,
             stats_.masp_table_misses, stats_.masp_table_replacements);
  fmt::print("STLB predictor ATP final_state enable_pref {} select_1 {} select_2 {} h2p_fpq_size {} masp_fpq_size {} stp_fpq_size {}\n",
             enable_pref_, select_1_, select_2_, h2p_fpq_.size(), masp_fpq_.size(), stp_fpq_.size());
}

const atp::statistics& atp::get_statistics() const { return stats_; }
