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

#ifndef BLOCK_H
#define BLOCK_H

#include "access_type.h"
#include "champsim.h"

namespace champsim
{
struct cache_block {
  bool valid = false;
  bool prefetch = false;
  bool dirty = false;

  champsim::address address{};
  champsim::address v_address{};
  champsim::address data{};

  uint32_t pf_metadata = 0;
  uint32_t cpu = 0;
  uint8_t asid[2] = {0xff, 0xff};

  // Stats-only provenance for end-to-end vBerti quality accounting.
  bool vberti_end_to_end_tracked = false;
  uint32_t vberti_end_to_end_cpu = 0;
  uint64_t vberti_end_to_end_id = 0;

  // Stats-only provenance for a translation produced by a cross-page
  // prefetch-initiated PTW.
  bool tlb_ptw_prefetch_tracked = false;
  uint32_t tlb_ptw_prefetch_cpu = 0;
  uint64_t tlb_ptw_prefetch_id = 0;

  // Stats-only TLB prefetch provenance. These fields do not participate in
  // lookup, replacement, or functional correctness.
  translation_origin translation_source = translation_origin::OTHER;
  bool tlb_cross_prefetch = false;
  bool tlb_cross_prefetch_used = false;

  // Independent provenance for the STLB-local prefetcher. This is kept
  // separate from vBerti/L1D cross-page prefetch accounting.
  bool stlb_prefetch = false;
  bool stlb_prefetch_used = false;
};
} // namespace champsim

#endif
