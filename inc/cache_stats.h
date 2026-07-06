#ifndef CACHE_STATS_H
#define CACHE_STATS_H

#include <cstdint>
#include <string>
#include <type_traits>
#include <utility>

#include "channel.h"
#include "event_counter.h"

struct cache_stats {
  std::string name;
  // prefetch stats
  uint64_t pf_requested = 0;
  uint64_t pf_issued = 0;
  uint64_t pf_useful = 0;
  uint64_t pf_useless = 0;
  uint64_t pf_late = 0;
  uint64_t pf_fill = 0;

  // vBerti L1D prefetch candidate flow. These counters are updated only when
  // the prefetcher attaches L1D_PREF_META_VALID to pf_metadata.
  uint64_t vberti_prefetch_requested = 0;
  uint64_t vberti_cross_page_requested = 0;
  uint64_t vberti_prefetch_issued = 0;
  uint64_t vberti_cross_page_issued = 0;

  // Cross-page L1D prefetch translation quality at a single TLB level.
  uint64_t tlb_cross_prefetch_issued = 0;
  uint64_t tlb_cross_prefetch_useful = 0;
  uint64_t tlb_cross_prefetch_useless = 0;
  uint64_t tlb_cross_prefetch_late = 0;

  // Cross-page L1D prefetch translation quality for the DTLB+STLB system.
  uint64_t tlb_system_cross_prefetch_issued = 0;
  uint64_t tlb_system_cross_prefetch_useful = 0;
  uint64_t tlb_system_cross_prefetch_useless = 0;
  uint64_t tlb_system_cross_prefetch_late = 0;

  champsim::stats::event_counter<std::pair<access_type, std::remove_cv_t<decltype(NUM_CPUS)>>> hits = {};
  champsim::stats::event_counter<std::pair<access_type, std::remove_cv_t<decltype(NUM_CPUS)>>> misses = {};
  champsim::stats::event_counter<std::pair<access_type, std::remove_cv_t<decltype(NUM_CPUS)>>> mshr_merge = {};
  champsim::stats::event_counter<std::pair<access_type, std::remove_cv_t<decltype(NUM_CPUS)>>> mshr_return = {};

  champsim::stats::event_counter<std::pair<translation_origin, std::remove_cv_t<decltype(NUM_CPUS)>>> dtlb_origin_hits = {};
  champsim::stats::event_counter<std::pair<translation_origin, std::remove_cv_t<decltype(NUM_CPUS)>>> dtlb_origin_misses = {};
  champsim::stats::event_counter<std::pair<translation_origin, std::remove_cv_t<decltype(NUM_CPUS)>>> stlb_origin_hits = {};
  champsim::stats::event_counter<std::pair<translation_origin, std::remove_cv_t<decltype(NUM_CPUS)>>> stlb_origin_misses = {};
  champsim::stats::event_counter<std::pair<translation_origin, std::remove_cv_t<decltype(NUM_CPUS)>>> tlb_origin_mshr_merge = {};
  champsim::stats::event_counter<std::pair<translation_origin, std::remove_cv_t<decltype(NUM_CPUS)>>> tlb_origin_fills = {};

  long total_miss_latency_cycles{};
};

cache_stats operator-(cache_stats lhs, cache_stats rhs);

#endif
