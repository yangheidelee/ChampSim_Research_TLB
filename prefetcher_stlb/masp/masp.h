#ifndef PREFETCHER_STLB_MASP_H
#define PREFETCHER_STLB_MASP_H

#include <array>
#include <cstddef>
#include <cstdint>
#include <string_view>
#include <vector>

#include "modules.h"

class masp : public champsim::modules::stlb_prefetcher
{
public:
  struct candidate_stats {
    uint64_t triggers = 0;
    uint64_t raw_candidates = 0;
    uint64_t unique_candidates = 0;
    uint64_t duplicate_drops = 0;
    uint64_t current_vpn_drops = 0;
    uint64_t invalid_address_drops = 0;
    uint64_t submitted = 0;
    uint64_t accepted = 0;
    uint64_t rejected = 0;
  };

private:
  static constexpr std::size_t TABLE_SETS = 16;
  static constexpr std::size_t TABLE_WAYS = 4;

  struct entry {
    bool valid = false;
    uint64_t key = 0;
    uint64_t last_used = 0;
    uint64_t previous_miss_vpn = 0;
    int64_t stored_stride = 0;
    bool previous_miss_valid = false;
    bool stride_valid = false;
  };

  struct allocation_result {
    entry* value = nullptr;
    bool replaced = false;
  };

  candidate_stats stats_{};
  std::array<std::array<entry, TABLE_WAYS>, TABLE_SETS> table_{};
  uint64_t table_timestamp_ = 0;
  uint64_t table_lookups_ = 0;
  uint64_t table_hits_ = 0;
  uint64_t table_misses_ = 0;
  uint64_t table_allocations_ = 0;
  uint64_t table_replacements_ = 0;

  static int64_t vpn_distance(uint64_t current, uint64_t previous);
  void touch(entry& value);
  entry* find_entry(uint64_t pc);
  allocation_result allocate_entry(uint64_t pc);
  void record_trigger(const champsim::modules::stlb_prefetcher_context& context);
  void issue_deltas(const champsim::modules::stlb_prefetcher_context& context, const std::vector<int64_t>& deltas);
  void print_common_stats(std::string_view name) const;

public:
  using champsim::modules::stlb_prefetcher::stlb_prefetcher;

  void stlb_prefetcher_initialize();
  void stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context);
  void stlb_prefetcher_final_stats();

  [[nodiscard]] const candidate_stats& candidate_statistics() const { return stats_; }
};

#endif
