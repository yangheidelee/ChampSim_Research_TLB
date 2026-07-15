#ifndef VBERTI_END_TO_END_H
#define VBERTI_END_TO_END_H

#include <cstdint>
#include <map>
#include <vector>

namespace champsim::vberti_end_to_end
{
enum class request_state : uint8_t { untracked, pending, useful_timely, useful_late, cancelled };

struct counters {
  uint64_t issued = 0;
  uint64_t useful = 0;
  uint64_t late = 0;
};

struct tracker {
  counters counts{};
  std::vector<request_state> states{};
};

inline std::map<uint32_t, tracker> trackers{};

inline void reset(uint32_t cpu) { trackers[cpu] = {}; }

inline void issue(uint32_t cpu, uint64_t id)
{
  auto& state = trackers[cpu];
  if (id >= state.states.size())
    state.states.resize(id + 1, request_state::untracked);

  if (state.states[id] == request_state::untracked) {
    state.states[id] = request_state::pending;
    ++state.counts.issued;
  }
}

inline void mark_useful(uint32_t cpu, uint64_t id, bool late)
{
  auto found = trackers.find(cpu);
  if (found == trackers.end() || id >= found->second.states.size() || found->second.states[id] != request_state::pending)
    return;

  found->second.states[id] = late ? request_state::useful_late : request_state::useful_timely;
  ++found->second.counts.useful;
  if (late)
    ++found->second.counts.late;
}

inline void cancel(uint32_t cpu, uint64_t id)
{
  auto found = trackers.find(cpu);
  if (found == trackers.end() || id >= found->second.states.size() || found->second.states[id] != request_state::pending)
    return;

  found->second.states[id] = request_state::cancelled;
}

inline counters get_counters(uint32_t cpu)
{
  const auto found = trackers.find(cpu);
  return found == trackers.end() ? counters{} : found->second.counts;
}
} // namespace champsim::vberti_end_to_end

#endif
