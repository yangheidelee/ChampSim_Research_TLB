/*
 * Optional L1D, DTLB, and STLB virtual-page access tracers.
 */

#ifndef VPN_PATTERN_TRACKER_H
#define VPN_PATTERN_TRACKER_H

#include <cstdint>
#include <string_view>

#include "access_type.h"
#include "address.h"
#include "chrono.h"

namespace champsim::instrumentation
{
void record_l1d_vpn_access(std::string_view cache_name, bool is_warmup, champsim::chrono::clock::time_point current_time,
                           champsim::chrono::clock::duration clock_period, champsim::address ip, champsim::address vaddr, uint64_t instr_id,
                           uint32_t cpu, access_type type, bool prefetch_from_this, bool is_instr);
void record_stlb_vpn_access(std::string_view cache_name, bool is_warmup, champsim::chrono::clock::time_point current_time,
                            champsim::chrono::clock::duration clock_period, champsim::address ip, champsim::address vaddr, uint64_t instr_id,
                            uint32_t cpu, access_type type, translation_origin origin, bool prefetch_from_this, bool is_instr);
void record_dtlb_vpn_access(std::string_view cache_name, bool is_warmup, champsim::chrono::clock::time_point current_time,
                            champsim::chrono::clock::duration clock_period, champsim::address ip, champsim::address vaddr, uint64_t instr_id,
                            uint32_t cpu, access_type type, translation_origin origin, bool prefetch_from_this, bool is_instr);
void record_stlb_vpn_miss(std::string_view cache_name, bool is_warmup, champsim::chrono::clock::time_point current_time,
                          champsim::chrono::clock::duration clock_period, champsim::address ip, champsim::address vaddr, uint64_t instr_id,
                          uint32_t cpu, access_type type, translation_origin origin, bool prefetch_from_this, bool is_instr);
} // namespace champsim::instrumentation

#endif
