#ifndef PREFETCHER_STLB_H2P_H
#define PREFETCHER_STLB_H2P_H

#include <cstdint>
#include <string_view>
#include <vector>

#include "modules.h"

class h2p : public champsim::modules::stlb_prefetcher
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
  candidate_stats stats_{};
  uint64_t previous_miss_vpn_ = 0;
  int64_t previous_distance_ = 0;
  bool previous_miss_valid_ = false;
  bool previous_distance_valid_ = false;

  uint64_t history_not_ready_ = 0;
  uint64_t equal_distance_deduplications_ = 0;

  static int64_t vpn_distance(uint64_t current, uint64_t previous);
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
