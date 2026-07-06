/*
 * Optional L1D, DTLB, and STLB virtual-page access tracers.
 */

#include "vpn_pattern_tracker.h"

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <utility>

#include "champsim.h"
#include "util/to_underlying.h"

namespace
{
bool env_enabled(const char* env_name)
{
  const char* raw = std::getenv(env_name);
  if (raw == nullptr)
    return false;

  const std::string value{raw};
  return value == "1" || value == "true" || value == "TRUE" || value == "yes" || value == "YES" || value == "on" || value == "ON";
}

bool is_l1d_name(std::string_view cache_name)
{
  constexpr std::string_view suffix{"_L1D"};
  return cache_name.size() >= suffix.size() && cache_name.compare(cache_name.size() - suffix.size(), suffix.size(), suffix) == 0;
}

bool is_stlb_name(std::string_view cache_name)
{
  constexpr std::string_view suffix{"_STLB"};
  return cache_name.size() >= suffix.size() && cache_name.compare(cache_name.size() - suffix.size(), suffix.size(), suffix) == 0;
}

bool is_dtlb_name(std::string_view cache_name)
{
  constexpr std::string_view suffix{"_DTLB"};
  return cache_name.size() >= suffix.size() && cache_name.compare(cache_name.size() - suffix.size(), suffix.size(), suffix) == 0;
}

bool is_l1d_prefetch_origin(translation_origin origin)
{
  return origin == translation_origin::L1D_PREFETCH || origin == translation_origin::L1D_PREFETCH_SAME_PAGE
         || origin == translation_origin::L1D_PREFETCH_CROSS_PAGE;
}

class vpn_trace_writer
{
public:
  vpn_trace_writer(const char* enable_env_name, const char* file_env_name, std::string default_path, std::string header)
      : enable_env(enable_env_name), file_env(file_env_name), default_file_path(std::move(default_path)), csv_header(std::move(header))
  {
  }

  [[nodiscard]] bool enabled()
  {
    initialize();
    return is_enabled;
  }

  void write(uint64_t cycle, champsim::address ip, champsim::address vaddr, uint64_t vpn, uint64_t offset, access_type type, uint32_t cpu,
             uint64_t instr_id)
  {
    initialize();
    if (!is_enabled)
      return;

    output << access_id++ << ',' << cycle << ',' << ip.to<uint64_t>() << ',' << vaddr.to<uint64_t>() << ',' << vpn << ',' << offset << ','
           << access_type_names.at(champsim::to_underlying(type)) << ',' << cpu << ',' << instr_id << '\n';
  }

  void write_stlb(uint64_t cycle, champsim::address ip, champsim::address vaddr, uint64_t vpn, uint64_t offset, access_type type, translation_origin origin,
                  uint32_t cpu, uint64_t instr_id, bool is_instr, bool prefetch_from_this)
  {
    initialize();
    if (!is_enabled)
      return;

    output << access_id++ << ',' << cycle << ',' << ip.to<uint64_t>() << ',' << vaddr.to<uint64_t>() << ',' << vpn << ',' << offset << ','
           << access_type_names.at(champsim::to_underlying(type)) << ',' << translation_origin_names.at(champsim::to_underlying(origin)) << ',' << cpu
           << ',' << instr_id << ',' << (is_instr ? 1 : 0) << ',' << (prefetch_from_this ? 1 : 0) << '\n';
  }

private:
  void initialize()
  {
    if (initialized)
      return;

    initialized = true;
    is_enabled = env_enabled(enable_env);
    if (!is_enabled)
      return;

    const char* configured_path = std::getenv(file_env);
    const std::string path = (configured_path != nullptr && configured_path[0] != '\0') ? configured_path : default_file_path;

    output.open(path, std::ios::out | std::ios::trunc);
    if (!output) {
      std::cerr << "[WARN] " << enable_env << " is enabled, but cannot open " << path << '\n';
      is_enabled = false;
      return;
    }

    output << csv_header << '\n';
  }

  const char* enable_env;
  const char* file_env;
  std::string default_file_path;
  std::string csv_header;
  bool initialized = false;
  bool is_enabled = false;
  uint64_t access_id = 0;
  std::ofstream output{};
};

vpn_trace_writer& l1d_writer()
{
  static vpn_trace_writer instance{"DUMP_L1D_VPN", "DUMP_L1D_VPN_FILE", "l1d_vpn_trace.csv", "access_id,cycle,ip,vaddr,vpn,offset,type,cpu,instr_id"};
  return instance;
}

vpn_trace_writer& stlb_writer()
{
  static vpn_trace_writer instance{"DUMP_STLB_ACCESS", "DUMP_STLB_ACCESS_FILE", "stlb_access_trace.csv",
                                   "access_id,cycle,ip,vaddr,vpn,offset,type,origin,cpu,instr_id,is_instr,prefetch_from_this"};
  return instance;
}

vpn_trace_writer& stlb_miss_writer()
{
  static vpn_trace_writer instance{"DUMP_STLB_MISS_ACCESS", "DUMP_STLB_MISS_ACCESS_FILE", "stlb_miss_access_trace.csv",
                                   "access_id,cycle,ip,vaddr,vpn,offset,type,origin,cpu,instr_id,is_instr,prefetch_from_this"};
  return instance;
}

vpn_trace_writer& stlb_demand_writer()
{
  static vpn_trace_writer instance{"DUMP_STLB_DEMAND_ACCESS", "DUMP_STLB_DEMAND_ACCESS_FILE", "stlb_demand_access_trace.csv",
                                   "access_id,cycle,ip,vaddr,vpn,offset,type,origin,cpu,instr_id,is_instr,prefetch_from_this"};
  return instance;
}

vpn_trace_writer& stlb_l1d_prefetch_writer()
{
  static vpn_trace_writer instance{"DUMP_STLB_L1D_PREFETCH_ACCESS", "DUMP_STLB_L1D_PREFETCH_ACCESS_FILE", "stlb_l1d_prefetch_access_trace.csv",
                                   "access_id,cycle,ip,vaddr,vpn,offset,type,origin,cpu,instr_id,is_instr,prefetch_from_this"};
  return instance;
}

vpn_trace_writer& dtlb_demand_writer()
{
  static vpn_trace_writer instance{"DUMP_DTLB_DEMAND_ACCESS", "DUMP_DTLB_DEMAND_ACCESS_FILE", "dtlb_demand_access_trace.csv",
                                   "access_id,cycle,ip,vaddr,vpn,offset,type,origin,cpu,instr_id,is_instr,prefetch_from_this"};
  return instance;
}

vpn_trace_writer& dtlb_l1d_prefetch_writer()
{
  static vpn_trace_writer instance{"DUMP_DTLB_L1D_PREFETCH_ACCESS", "DUMP_DTLB_L1D_PREFETCH_ACCESS_FILE", "dtlb_l1d_prefetch_access_trace.csv",
                                   "access_id,cycle,ip,vaddr,vpn,offset,type,origin,cpu,instr_id,is_instr,prefetch_from_this"};
  return instance;
}
} // namespace

void champsim::instrumentation::record_l1d_vpn_access(std::string_view cache_name, bool is_warmup, champsim::chrono::clock::time_point current_time,
                                                      champsim::chrono::clock::duration clock_period, champsim::address ip, champsim::address vaddr,
                                                      uint64_t instr_id, uint32_t cpu, access_type type, bool prefetch_from_this, bool is_instr)
{
  if (!is_l1d_name(cache_name) || is_warmup || is_instr || prefetch_from_this || type == access_type::PREFETCH || type == access_type::TRANSLATION)
    return;

  if (type != access_type::LOAD && type != access_type::RFO && type != access_type::WRITE)
    return;

  if (!l1d_writer().enabled())
    return;

  const uint64_t raw_vaddr = vaddr.to<uint64_t>();
  const uint64_t vpn = raw_vaddr >> LOG2_PAGE_SIZE;
  const unsigned blocks_per_page_bits = LOG2_PAGE_SIZE - LOG2_BLOCK_SIZE;
  const uint64_t offset_mask = (uint64_t{1} << blocks_per_page_bits) - 1;
  const uint64_t offset = (raw_vaddr >> LOG2_BLOCK_SIZE) & offset_mask;
  const uint64_t cycle = static_cast<uint64_t>(current_time.time_since_epoch() / clock_period);

  l1d_writer().write(cycle, ip, vaddr, vpn, offset, type, cpu, instr_id);
}

void champsim::instrumentation::record_stlb_vpn_access(std::string_view cache_name, bool is_warmup, champsim::chrono::clock::time_point current_time,
                                                       champsim::chrono::clock::duration clock_period, champsim::address ip, champsim::address vaddr,
                                                       uint64_t instr_id, uint32_t cpu, access_type type, translation_origin origin,
                                                       bool prefetch_from_this, bool is_instr)
{
  if (!is_stlb_name(cache_name) || is_warmup || type != access_type::LOAD)
    return;

  const bool dump_full = stlb_writer().enabled();
  const bool dump_demand =
      (origin == translation_origin::DEMAND_DATA || origin == translation_origin::DEMAND_INSTRUCTION) && stlb_demand_writer().enabled();
  const bool dump_l1d_prefetch = is_l1d_prefetch_origin(origin) && stlb_l1d_prefetch_writer().enabled();
  if (!dump_full && !dump_demand && !dump_l1d_prefetch)
    return;

  const uint64_t raw_vaddr = vaddr.to<uint64_t>();
  const uint64_t vpn = raw_vaddr >> LOG2_PAGE_SIZE;
  const unsigned blocks_per_page_bits = LOG2_PAGE_SIZE - LOG2_BLOCK_SIZE;
  const uint64_t offset_mask = (uint64_t{1} << blocks_per_page_bits) - 1;
  const uint64_t offset = (raw_vaddr >> LOG2_BLOCK_SIZE) & offset_mask;
  const uint64_t cycle = static_cast<uint64_t>(current_time.time_since_epoch() / clock_period);

  if (dump_full)
    stlb_writer().write_stlb(cycle, ip, vaddr, vpn, offset, type, origin, cpu, instr_id, is_instr, prefetch_from_this);
  if (dump_demand)
    stlb_demand_writer().write_stlb(cycle, ip, vaddr, vpn, offset, type, origin, cpu, instr_id, is_instr, prefetch_from_this);
  if (dump_l1d_prefetch)
    stlb_l1d_prefetch_writer().write_stlb(cycle, ip, vaddr, vpn, offset, type, origin, cpu, instr_id, is_instr, prefetch_from_this);
}

void champsim::instrumentation::record_dtlb_vpn_access(std::string_view cache_name, bool is_warmup, champsim::chrono::clock::time_point current_time,
                                                       champsim::chrono::clock::duration clock_period, champsim::address ip, champsim::address vaddr,
                                                       uint64_t instr_id, uint32_t cpu, access_type type, translation_origin origin,
                                                       bool prefetch_from_this, bool is_instr)
{
  if (!is_dtlb_name(cache_name) || is_warmup || type != access_type::LOAD)
    return;

  const bool dump_demand =
      (origin == translation_origin::DEMAND_DATA || origin == translation_origin::DEMAND_INSTRUCTION) && dtlb_demand_writer().enabled();
  const bool dump_l1d_prefetch = is_l1d_prefetch_origin(origin) && dtlb_l1d_prefetch_writer().enabled();
  if (!dump_demand && !dump_l1d_prefetch)
    return;

  const uint64_t raw_vaddr = vaddr.to<uint64_t>();
  const uint64_t vpn = raw_vaddr >> LOG2_PAGE_SIZE;
  const unsigned blocks_per_page_bits = LOG2_PAGE_SIZE - LOG2_BLOCK_SIZE;
  const uint64_t offset_mask = (uint64_t{1} << blocks_per_page_bits) - 1;
  const uint64_t offset = (raw_vaddr >> LOG2_BLOCK_SIZE) & offset_mask;
  const uint64_t cycle = static_cast<uint64_t>(current_time.time_since_epoch() / clock_period);

  if (dump_demand)
    dtlb_demand_writer().write_stlb(cycle, ip, vaddr, vpn, offset, type, origin, cpu, instr_id, is_instr, prefetch_from_this);
  if (dump_l1d_prefetch)
    dtlb_l1d_prefetch_writer().write_stlb(cycle, ip, vaddr, vpn, offset, type, origin, cpu, instr_id, is_instr, prefetch_from_this);
}

void champsim::instrumentation::record_stlb_vpn_miss(std::string_view cache_name, bool is_warmup, champsim::chrono::clock::time_point current_time,
                                                     champsim::chrono::clock::duration clock_period, champsim::address ip, champsim::address vaddr,
                                                     uint64_t instr_id, uint32_t cpu, access_type type, translation_origin origin,
                                                     bool prefetch_from_this, bool is_instr)
{
  if (!is_stlb_name(cache_name) || is_warmup || type != access_type::LOAD)
    return;

  if (!stlb_miss_writer().enabled())
    return;

  const uint64_t raw_vaddr = vaddr.to<uint64_t>();
  const uint64_t vpn = raw_vaddr >> LOG2_PAGE_SIZE;
  const unsigned blocks_per_page_bits = LOG2_PAGE_SIZE - LOG2_BLOCK_SIZE;
  const uint64_t offset_mask = (uint64_t{1} << blocks_per_page_bits) - 1;
  const uint64_t offset = (raw_vaddr >> LOG2_BLOCK_SIZE) & offset_mask;
  const uint64_t cycle = static_cast<uint64_t>(current_time.time_since_epoch() / clock_period);

  stlb_miss_writer().write_stlb(cycle, ip, vaddr, vpn, offset, type, origin, cpu, instr_id, is_instr, prefetch_from_this);
}
