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
  result.pf_too_early = lhs.pf_too_early - rhs.pf_too_early;
  result.pf_pollution_evict = lhs.pf_pollution_evict - rhs.pf_pollution_evict;
  result.pf_pollution_demand = lhs.pf_pollution_demand - rhs.pf_pollution_demand;
  result.stlb_prefetch_requested = lhs.stlb_prefetch_requested - rhs.stlb_prefetch_requested;
  result.stlb_prefetch_issued = lhs.stlb_prefetch_issued - rhs.stlb_prefetch_issued;
  result.stlb_prefetch_lookups = lhs.stlb_prefetch_lookups - rhs.stlb_prefetch_lookups;
  result.stlb_prefetch_hit = lhs.stlb_prefetch_hit - rhs.stlb_prefetch_hit;
  result.stlb_prefetch_miss = lhs.stlb_prefetch_miss - rhs.stlb_prefetch_miss;
  result.stlb_prefetch_mshr_merge = lhs.stlb_prefetch_mshr_merge - rhs.stlb_prefetch_mshr_merge;
  result.stlb_prefetch_fill = lhs.stlb_prefetch_fill - rhs.stlb_prefetch_fill;
  result.stlb_prefetch_useful = lhs.stlb_prefetch_useful - rhs.stlb_prefetch_useful;
  result.stlb_prefetch_useless = lhs.stlb_prefetch_useless - rhs.stlb_prefetch_useless;
  result.stlb_prefetch_late = lhs.stlb_prefetch_late - rhs.stlb_prefetch_late;
  result.stlb_prefetch_too_early = lhs.stlb_prefetch_too_early - rhs.stlb_prefetch_too_early;
  result.stlb_prefetch_pollution_evict = lhs.stlb_prefetch_pollution_evict - rhs.stlb_prefetch_pollution_evict;
  result.stlb_prefetch_pollution_demand = lhs.stlb_prefetch_pollution_demand - rhs.stlb_prefetch_pollution_demand;
  result.stlb_prefetch_buffer_insert = lhs.stlb_prefetch_buffer_insert - rhs.stlb_prefetch_buffer_insert;
  result.stlb_prefetch_buffer_eviction = lhs.stlb_prefetch_buffer_eviction - rhs.stlb_prefetch_buffer_eviction;
  result.stlb_prefetch_buffer_lookup = lhs.stlb_prefetch_buffer_lookup - rhs.stlb_prefetch_buffer_lookup;
  result.stlb_prefetch_buffer_hit = lhs.stlb_prefetch_buffer_hit - rhs.stlb_prefetch_buffer_hit;
  result.stlb_prefetch_buffer_miss = lhs.stlb_prefetch_buffer_miss - rhs.stlb_prefetch_buffer_miss;
  result.vberti_prefetch_requested = lhs.vberti_prefetch_requested - rhs.vberti_prefetch_requested;
  result.vberti_cross_page_requested = lhs.vberti_cross_page_requested - rhs.vberti_cross_page_requested;
  result.vberti_prefetch_issued = lhs.vberti_prefetch_issued - rhs.vberti_prefetch_issued;
  result.vberti_cross_page_issued = lhs.vberti_cross_page_issued - rhs.vberti_cross_page_issued;
  result.cross_page_pf_translation_only_requested =
      lhs.cross_page_pf_translation_only_requested - rhs.cross_page_pf_translation_only_requested;
  result.cross_page_pf_translation_only_issued = lhs.cross_page_pf_translation_only_issued - rhs.cross_page_pf_translation_only_issued;
  result.cross_page_pf_translation_only_dropped = lhs.cross_page_pf_translation_only_dropped - rhs.cross_page_pf_translation_only_dropped;
  result.cp_pf_pqfull_drop = lhs.cp_pf_pqfull_drop - rhs.cp_pf_pqfull_drop;
  result.cp_pf_pqfull_tlb_rescue_enqueued = lhs.cp_pf_pqfull_tlb_rescue_enqueued - rhs.cp_pf_pqfull_tlb_rescue_enqueued;
  result.cp_pf_pqfull_tlb_rescue_issued = lhs.cp_pf_pqfull_tlb_rescue_issued - rhs.cp_pf_pqfull_tlb_rescue_issued;
  result.cp_pf_pqfull_tlb_rescue_translated = lhs.cp_pf_pqfull_tlb_rescue_translated - rhs.cp_pf_pqfull_tlb_rescue_translated;
  result.tlb_cross_prefetch_issued = lhs.tlb_cross_prefetch_issued - rhs.tlb_cross_prefetch_issued;
  result.tlb_cross_prefetch_useful = lhs.tlb_cross_prefetch_useful - rhs.tlb_cross_prefetch_useful;
  result.tlb_cross_prefetch_useless = lhs.tlb_cross_prefetch_useless - rhs.tlb_cross_prefetch_useless;
  result.tlb_cross_prefetch_late = lhs.tlb_cross_prefetch_late - rhs.tlb_cross_prefetch_late;
  result.tlb_cross_prefetch_too_early = lhs.tlb_cross_prefetch_too_early - rhs.tlb_cross_prefetch_too_early;
  result.tlb_cross_prefetch_pollution_evict = lhs.tlb_cross_prefetch_pollution_evict - rhs.tlb_cross_prefetch_pollution_evict;
  result.tlb_cross_prefetch_pollution_demand = lhs.tlb_cross_prefetch_pollution_demand - rhs.tlb_cross_prefetch_pollution_demand;
  result.tlb_system_cross_prefetch_issued = lhs.tlb_system_cross_prefetch_issued - rhs.tlb_system_cross_prefetch_issued;
  result.tlb_system_cross_prefetch_useful = lhs.tlb_system_cross_prefetch_useful - rhs.tlb_system_cross_prefetch_useful;
  result.tlb_system_cross_prefetch_useless = lhs.tlb_system_cross_prefetch_useless - rhs.tlb_system_cross_prefetch_useless;
  result.tlb_system_cross_prefetch_late = lhs.tlb_system_cross_prefetch_late - rhs.tlb_system_cross_prefetch_late;
  result.tlb_system_cross_prefetch_too_early = lhs.tlb_system_cross_prefetch_too_early - rhs.tlb_system_cross_prefetch_too_early;
  result.stlb_cp_pb_raw_demand_miss = lhs.stlb_cp_pb_raw_demand_miss - rhs.stlb_cp_pb_raw_demand_miss;
  result.stlb_cp_pb_insert = lhs.stlb_cp_pb_insert - rhs.stlb_cp_pb_insert;
  result.stlb_cp_pb_demand_hit = lhs.stlb_cp_pb_demand_hit - rhs.stlb_cp_pb_demand_hit;
  result.stlb_cp_pb_demand_miss = lhs.stlb_cp_pb_demand_miss - rhs.stlb_cp_pb_demand_miss;

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
