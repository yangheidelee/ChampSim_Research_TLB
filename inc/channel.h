/*
 *    Copyright 2023 The ChampSim Contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef CHANNEL_H
#define CHANNEL_H

#include <array>
#include <cstdint>
#include <deque>
#include <limits>
#include <memory>
#include <string_view>
#include <vector>

#include "access_type.h"
#include "address.h"
#include "champsim.h"
#include "demand_tlb_pattern.h"

namespace champsim
{

struct cache_queue_stats {
  uint64_t RQ_ACCESS = 0;
  uint64_t RQ_MERGED = 0;
  uint64_t RQ_FULL = 0;
  uint64_t RQ_TO_CACHE = 0;
  uint64_t PQ_ACCESS = 0;
  uint64_t PQ_MERGED = 0;
  uint64_t PQ_FULL = 0;
  uint64_t PQ_TO_CACHE = 0;
  uint64_t WQ_ACCESS = 0;
  uint64_t WQ_MERGED = 0;
  uint64_t WQ_FULL = 0;
  uint64_t WQ_TO_CACHE = 0;
  uint64_t WQ_FORWARD = 0;
};

class channel
{
  struct request {
    bool forward_checked = false;
    bool is_translated = true;
    bool response_requested = true;

    uint8_t asid[2] = {std::numeric_limits<uint8_t>::max(), std::numeric_limits<uint8_t>::max()};
    access_type type{access_type::LOAD};
    translation_origin translation_source{translation_origin::OTHER};
    bool is_instr = false;

    uint32_t pf_metadata = 0;
    uint32_t cpu = std::numeric_limits<uint32_t>::max();

    uint32_t demand_tlb_operand_index = std::numeric_limits<uint32_t>::max();
    demand_tlb_pattern_stage demand_tlb_stage = demand_tlb_pattern_stage::NONE;
    std::vector<demand_tlb_pattern_event_ref> demand_tlb_events{};
    std::vector<demand_tlb_pattern_event_ref> demand_tlb_coalesced_events{};

    // Observation-only provenance for the unified real-demand and vBerti
    // cross-page TLB pattern stream. It never participates in matching.
    vberti_tlb_pattern_stage vberti_tlb_stage = vberti_tlb_pattern_stage::NONE;
    std::vector<vberti_tlb_pattern_event_ref> vberti_tlb_events{};
    std::vector<vberti_tlb_pattern_event_ref> vberti_tlb_coalesced_events{};

    // Stats-only provenance for end-to-end vBerti quality accounting.
    bool vberti_end_to_end_tracked = false;
    uint32_t vberti_end_to_end_cpu = std::numeric_limits<uint32_t>::max();
    uint64_t vberti_end_to_end_id = 0;

    // Stats-only provenance for a cross-page prefetch that may initiate a
    // page-table walk. These fields never affect queue matching or service.
    bool tlb_ptw_prefetch_tracked = false;
    bool tlb_ptw_real_demand_waiting = false;
    uint32_t tlb_ptw_prefetch_cpu = std::numeric_limits<uint32_t>::max();
    uint64_t tlb_ptw_prefetch_id = 0;

    // Stats-only ownership for a request initiated by the STLB-local
    // prefetcher. It never participates in channel matching.
    bool stlb_prefetch_tracked = false;
    bool stlb_prefetch_used = false;

    champsim::address address{};
    champsim::address v_address{};
    champsim::address data{};
    uint64_t instr_id = 0;
    champsim::address ip{};

    std::vector<uint64_t> instr_depend_on_me{};
    std::vector<std::shared_ptr<bool>> ptw_dram_touched_flags{};
    bool count_ptw_dram_touch = false;
  };

  struct response {
    champsim::address address{};
    champsim::address v_address{};
    champsim::address data{};
    uint32_t pf_metadata = 0;
    std::vector<uint64_t> instr_depend_on_me{};

    // Stats-only PTW initiator provenance returned with a translation.
    bool tlb_ptw_prefetch_tracked = false;
    uint32_t tlb_ptw_prefetch_cpu = std::numeric_limits<uint32_t>::max();
    uint64_t tlb_ptw_prefetch_id = 0;

    bool stlb_prefetch_tracked = false;
    bool stlb_prefetch_used = false;

    response(champsim::address addr, champsim::address v_addr, champsim::address data_, uint32_t pf_meta, std::vector<uint64_t> deps)
        : address(addr), v_address(v_addr), data(data_), pf_metadata(pf_meta), instr_depend_on_me(deps)
    {
    }
    explicit response(request req) : response(req.address, req.v_address, req.data, req.pf_metadata, req.instr_depend_on_me)
    {
      tlb_ptw_prefetch_tracked = req.tlb_ptw_prefetch_tracked;
      tlb_ptw_prefetch_cpu = req.tlb_ptw_prefetch_cpu;
      tlb_ptw_prefetch_id = req.tlb_ptw_prefetch_id;
      stlb_prefetch_tracked = req.stlb_prefetch_tracked;
      stlb_prefetch_used = req.stlb_prefetch_used;
    }
  };

  template <typename R>
  bool do_add_queue(R& queue, std::size_t queue_size, const typename R::value_type& packet);

  std::size_t RQ_SIZE = std::numeric_limits<std::size_t>::max();
  std::size_t PQ_SIZE = std::numeric_limits<std::size_t>::max();
  std::size_t WQ_SIZE = std::numeric_limits<std::size_t>::max();
  champsim::data::bits OFFSET_BITS{};
  bool match_offset_bits = false;

public:
  using response_type = response;
  using request_type = request;
  using stats_type = cache_queue_stats;

  std::deque<request_type> RQ{}, PQ{}, WQ{};
  std::deque<response_type> returned{};

  stats_type sim_stats{}, roi_stats{};

  channel() = default;
  channel(std::size_t rq_size, std::size_t pq_size, std::size_t wq_size, champsim::data::bits offset_bits, bool match_offset);

  bool add_rq(const request_type& packet);
  bool add_wq(const request_type& packet);
  bool add_pq(const request_type& packet);

  [[nodiscard]] std::size_t rq_occupancy() const;
  [[nodiscard]] std::size_t wq_occupancy() const;
  [[nodiscard]] std::size_t pq_occupancy() const;

  [[nodiscard]] std::size_t rq_size() const;
  [[nodiscard]] std::size_t wq_size() const;
  [[nodiscard]] std::size_t pq_size() const;

  void check_collision();
};
} // namespace champsim

#endif
