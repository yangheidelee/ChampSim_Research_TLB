#include "cache_stats.h"

cache_stats operator-(cache_stats lhs, cache_stats rhs)
{
  cache_stats result;
  result.pf_requested = lhs.pf_requested - rhs.pf_requested;
  result.pf_issued = lhs.pf_issued - rhs.pf_issued;
  result.pf_useful = lhs.pf_useful - rhs.pf_useful;
  result.pf_useless = lhs.pf_useless - rhs.pf_useless;
  result.pf_late = lhs.pf_late - rhs.pf_late;
  result.pf_fill = lhs.pf_fill - rhs.pf_fill;
  result.vberti_prefetch_requested = lhs.vberti_prefetch_requested - rhs.vberti_prefetch_requested;
  result.vberti_cross_page_requested = lhs.vberti_cross_page_requested - rhs.vberti_cross_page_requested;
  result.vberti_prefetch_issued = lhs.vberti_prefetch_issued - rhs.vberti_prefetch_issued;
  result.vberti_cross_page_issued = lhs.vberti_cross_page_issued - rhs.vberti_cross_page_issued;
  result.tlb_cross_prefetch_issued = lhs.tlb_cross_prefetch_issued - rhs.tlb_cross_prefetch_issued;
  result.tlb_cross_prefetch_useful = lhs.tlb_cross_prefetch_useful - rhs.tlb_cross_prefetch_useful;
  result.tlb_cross_prefetch_useless = lhs.tlb_cross_prefetch_useless - rhs.tlb_cross_prefetch_useless;
  result.tlb_cross_prefetch_late = lhs.tlb_cross_prefetch_late - rhs.tlb_cross_prefetch_late;
  result.tlb_system_cross_prefetch_issued = lhs.tlb_system_cross_prefetch_issued - rhs.tlb_system_cross_prefetch_issued;
  result.tlb_system_cross_prefetch_useful = lhs.tlb_system_cross_prefetch_useful - rhs.tlb_system_cross_prefetch_useful;
  result.tlb_system_cross_prefetch_useless = lhs.tlb_system_cross_prefetch_useless - rhs.tlb_system_cross_prefetch_useless;
  result.tlb_system_cross_prefetch_late = lhs.tlb_system_cross_prefetch_late - rhs.tlb_system_cross_prefetch_late;

  result.hits = lhs.hits - rhs.hits;
  result.misses = lhs.misses - rhs.misses;
  result.mshr_merge = lhs.mshr_merge - rhs.mshr_merge;
  result.mshr_return = lhs.mshr_return - rhs.mshr_return;
  result.dtlb_origin_hits = lhs.dtlb_origin_hits - rhs.dtlb_origin_hits;
  result.dtlb_origin_misses = lhs.dtlb_origin_misses - rhs.dtlb_origin_misses;
  result.stlb_origin_hits = lhs.stlb_origin_hits - rhs.stlb_origin_hits;
  result.stlb_origin_misses = lhs.stlb_origin_misses - rhs.stlb_origin_misses;
  result.tlb_origin_mshr_merge = lhs.tlb_origin_mshr_merge - rhs.tlb_origin_mshr_merge;
  result.tlb_origin_fills = lhs.tlb_origin_fills - rhs.tlb_origin_fills;

  result.total_miss_latency_cycles = lhs.total_miss_latency_cycles - rhs.total_miss_latency_cycles;
  return result;
}
