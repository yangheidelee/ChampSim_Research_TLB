#ifndef TLB_PTW_SYSTEM_STATS_H
#define TLB_PTW_SYSTEM_STATS_H

#include <cstdint>
#include <limits>
#include <map>
#include <set>
#include <tuple>
#include <vector>

namespace champsim::tlb_ptw_system
{
// This tracker is stats-only. None of its state participates in lookup,
// replacement, queue admission, or timing decisions.
struct key {
  uint32_t cpu = std::numeric_limits<uint32_t>::max();
  uint64_t vpn = 0;
  uint8_t asid0 = std::numeric_limits<uint8_t>::max();
  uint8_t asid1 = std::numeric_limits<uint8_t>::max();

  bool operator<(const key& other) const
  {
    return std::tie(cpu, vpn, asid0, asid1) < std::tie(other.cpu, other.vpn, other.asid0, other.asid1);
  }
};

enum class residency_level : uint8_t { dtlb = 1, stlb = 2 };

struct counters {
  uint64_t real_demand_ptw = 0;
  uint64_t prefetch_ptw_started = 0;
  uint64_t prefetch_fill = 0;
  uint64_t prefetch_useful = 0;
  uint64_t prefetch_late = 0;
};

struct prefetch_ptw_state {
  key translation{};
  bool started = false;
  bool filled = false;
  bool useful = false;
  bool late = false;
  bool demand_seen = false;
  bool demand_was_late = false;
  uint8_t residency = 0;
};

struct tracker {
  counters counts{};
  uint64_t next_id = 0;
  std::vector<prefetch_ptw_state> prefetch_ptws{};
  std::map<key, uint64_t> latest_prefetch_ptw{};
  std::set<key> demand_waiting_for_next_ptw{};
  std::set<uint64_t> demand_waiting_for_id{};
};

inline std::map<uint32_t, tracker> trackers{};

inline tracker& get_tracker(uint32_t cpu) { return trackers[cpu]; }

inline void reset(uint32_t cpu) { trackers[cpu] = {}; }

inline uint64_t reserve_prefetch_ptw_id(uint32_t cpu) { return get_tracker(cpu).next_id++; }

inline prefetch_ptw_state* find_state(uint32_t cpu, uint64_t id)
{
  auto found = trackers.find(cpu);
  if (found == std::end(trackers) || id >= found->second.prefetch_ptws.size())
    return nullptr;
  return &found->second.prefetch_ptws[id];
}

inline void mark_useful(uint32_t cpu, uint64_t id, bool late)
{
  auto* state = find_state(cpu, id);
  if (state == nullptr || !state->started || state->useful)
    return;

  // A demand that merges into an unfinished prefetch PTW is a late-use
  // candidate. Confirm it only once the translation actually fills into the
  // TLB system so ROI-boundary requests cannot make useful exceed fill.
  state->demand_seen = true;
  state->demand_was_late |= late;
  if (!state->filled)
    return;

  auto& counts = get_tracker(cpu).counts;
  state->useful = true;
  state->late = state->demand_was_late;
  ++counts.prefetch_useful;
  if (state->late)
    ++counts.prefetch_late;
}

inline void start_prefetch_ptw(uint32_t cpu, uint64_t id, const key& translation, bool demand_already_waiting)
{
  auto& state = get_tracker(cpu);
  if (id >= state.prefetch_ptws.size())
    state.prefetch_ptws.resize(id + 1);

  auto& ptw = state.prefetch_ptws[id];
  if (ptw.started)
    return;

  ptw.translation = translation;
  ptw.started = true;
  state.latest_prefetch_ptw[translation] = id;
  ++state.counts.prefetch_ptw_started;

  const bool waiting_for_key = state.demand_waiting_for_next_ptw.erase(translation) > 0;
  const bool waiting_for_id = state.demand_waiting_for_id.erase(id) > 0;
  if (demand_already_waiting || waiting_for_key || waiting_for_id)
    mark_useful(cpu, id, true);
}

inline void start_real_demand_ptw(uint32_t cpu) { ++get_tracker(cpu).counts.real_demand_ptw; }

inline bool mark_fill(uint32_t cpu, uint64_t id, residency_level level)
{
  auto* state = find_state(cpu, id);
  if (state == nullptr || !state->started)
    return false;

  if (!state->filled) {
    state->filled = true;
    ++get_tracker(cpu).counts.prefetch_fill;
  }
  state->residency |= static_cast<uint8_t>(level);
  if (state->demand_seen)
    mark_useful(cpu, id, state->demand_was_late);
  return true;
}

inline void mark_eviction(uint32_t cpu, uint64_t id, residency_level level)
{
  auto* state = find_state(cpu, id);
  if (state == nullptr || !state->started)
    return;
  state->residency &= static_cast<uint8_t>(~static_cast<uint8_t>(level));
}

inline void note_demand_for_id(uint32_t cpu, uint64_t id)
{
  auto* state = find_state(cpu, id);
  if (state == nullptr || !state->started) {
    get_tracker(cpu).demand_waiting_for_id.insert(id);
    return;
  }
  mark_useful(cpu, id, !state->filled);
}

inline void note_demand_for_key(const key& translation)
{
  auto& state = get_tracker(translation.cpu);
  auto found = state.latest_prefetch_ptw.find(translation);
  if (found != std::end(state.latest_prefetch_ptw)) {
    auto* ptw = find_state(translation.cpu, found->second);
    if (ptw != nullptr && ptw->started && (!ptw->filled || ptw->residency != 0)) {
      mark_useful(translation.cpu, found->second, !ptw->filled);
      return;
    }
  }
  state.demand_waiting_for_next_ptw.insert(translation);
}

inline void clear_waiting_for_key(const key& translation) { get_tracker(translation.cpu).demand_waiting_for_next_ptw.erase(translation); }

inline counters get_counters(uint32_t cpu)
{
  const auto found = trackers.find(cpu);
  return found == std::end(trackers) ? counters{} : found->second.counts;
}
} // namespace champsim::tlb_ptw_system

#endif
