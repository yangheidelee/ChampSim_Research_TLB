#ifndef PREFETCHER_STLB_STRIDE_H
#define PREFETCHER_STLB_STRIDE_H

#include <cstdint>
#include <map>

#include "address.h"
#include "modules.h"

// A deliberately small first STLB-prefetcher policy: learn one VPN stride per
// demand-load PC and predict one VPN after two matching deltas.
class stlb_stride : public champsim::modules::stlb_prefetcher
{
  struct entry {
    uint64_t last_vpn = 0;
    int64_t stride = 0;
    uint8_t confidence = 0;
    bool valid = false;
  };

  static constexpr std::size_t TABLE_SIZE = 1024;
  std::map<uint64_t, entry> table{};

public:
  using stlb_prefetcher::stlb_prefetcher;

  void stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context);
};

#endif
