# ATP STLB prefetcher

`atp` implements the Agile TLB Prefetcher (ATP) described in
*Exploiting Page Table Locality for Agile TLB Prefetching* (ISCA 2021).
It is intentionally self-contained: all policy state and logic live in this
directory, and the module uses only the public STLB-prefetcher interface.

Configure it with:

```json
"STLB": {
  "prefetcher": "prefetcher_stlb/atp",
  "prefetch_activate": "LOAD",
  "prefetch_as_load": false,
  "pq_size": 16,
  "stlb_prefetch_destination": "STLB"
},
"PTW": {
  "pq_size": 16
}
```

## Implemented ATP behavior

- P0 is H2P and predicts with the two most recently observed global TLB-miss
  distances.
- P1 is MASP and uses a 64-entry, 4-way, LRU-replaced per-PC table.
- P2 is STP and predicts the fixed page distances `{-2, -1, +1, +2}`.
- Every child has a private 16-entry, fully associative, FIFO Fake Prefetch
  Queue (FPQ). An FPQ contains VPNs only.
- Every feedback event probes all FPQs, updates the 8-bit `enable_pref`, 6-bit
  `select_1`, and 2-bit `select_2` counters according to Figure 7, and then
  makes the selection from the updated counter values.
- All child predictors and all FPQs are updated even when ATP disables
  prefetching or chooses a different child.
- Only the chosen child's candidates are submitted with
  `prefetch_translation()`.
- Predictor state is trained during warmup. Module-private statistics count
  ROI events only.

To use the independent paper-style destination buffer without changing the ATP
policy module, replace the destination and add the two PB parameters:

```json
"stlb_prefetch_destination": "PB",
"stlb_prefetch_buffer_size": 64,
"stlb_prefetch_buffer_latency": 2
```

## Destination boundary

The ATP policy is independent of the destination. With the default `STLB`
destination, accepted translations fill the STLB directly. With `PB`, completed
translations enter an independent fully-associative FIFO buffer. A demand first
misses the STLB, then performs the configured serial PB lookup, and starts or
merges into an ordinary demand PTW only after a PB miss.

In direct-fill mode, the first demand hit on a prefetched STLB entry
(`useful_prefetch == true`) is treated as the closest equivalent of a
paper-level PQ hit. In PB mode, `context.prefetch_buffer_hit` is the real PQ-hit
feedback. Ordinary STLB hits are ignored. Demand STLB misses and either form of
prefetch hit update the three predictors, FPQs, and selector counters.

This version deliberately excludes SBFP free-PTE candidates, the SBFP Sampler,
and multiple-page-size speculative walks.

## Explicit implementation choices

The paper specifies counter widths and MSB decisions but does not state reset
values. This implementation starts each counter one below its MSB threshold:
`enable_pref=127`, `select_1=31`, and `select_2=1`. This is a weakly-zero reset:
prefetching begins disabled, while no child is strongly favored.

An FPQ hit consumes the matching VPN, mirroring consumption of a matching
request in a real translation PQ. Repeated insertion of a VPN already present
in an FPQ is ignored and does not refresh FIFO age. Invalid, current-page, and
duplicate candidates are not inserted or submitted.

The paper specifies the 64-entry, 4-way organization of the MASP table but not
its replacement policy; this implementation uses deterministic LRU
replacement. The paper also flushes ATP state on context switches. The current
module follows the project's agreed single-core, single-address-space trace
scope and therefore does not add an ASID-change heuristic that could
incorrectly flush a shared STLB when several cores are modeled.
