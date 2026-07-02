#include "dram_stats.h"

dram_stats operator-(dram_stats lhs, dram_stats rhs)
{
  lhs.dbus_cycle_congested -= rhs.dbus_cycle_congested;
  lhs.dbus_count_congested -= rhs.dbus_count_congested;
  lhs.WQ_ROW_BUFFER_HIT -= rhs.WQ_ROW_BUFFER_HIT;
  lhs.WQ_ROW_BUFFER_MISS -= rhs.WQ_ROW_BUFFER_MISS;
  lhs.RQ_ROW_BUFFER_HIT -= rhs.RQ_ROW_BUFFER_HIT;
  lhs.RQ_ROW_BUFFER_MISS -= rhs.RQ_ROW_BUFFER_MISS;
  lhs.WQ_FULL -= rhs.WQ_FULL;
  lhs.rq_read_data_demand -= rhs.rq_read_data_demand;
  lhs.rq_read_inst_demand -= rhs.rq_read_inst_demand;
  lhs.rq_read_cache_inst_prefetch -= rhs.rq_read_cache_inst_prefetch;
  lhs.rq_read_cache_data_prefetch -= rhs.rq_read_cache_data_prefetch;
  lhs.rq_read_stlb_data_demand -= rhs.rq_read_stlb_data_demand;
  lhs.rq_read_stlb_inst_demand -= rhs.rq_read_stlb_inst_demand;
  lhs.rq_read_stlb_l1i_pref -= rhs.rq_read_stlb_l1i_pref;
  lhs.rq_read_stlb_l1d_pref -= rhs.rq_read_stlb_l1d_pref;
  lhs.rq_read_unclassified -= rhs.rq_read_unclassified;
  lhs.rq_read_total_observed -= rhs.rq_read_total_observed;
  return lhs;
}
