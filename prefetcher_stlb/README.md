# STLB prefetchers

This directory contains prefetcher policies that issue virtual-page
translations through `CACHE::prefetch_translation()`.

## Configuration

An STLB prefetcher is opt-in. Existing JSON files that omit `STLB.prefetcher`
still select `no`; if they also omit `PTW.pq_size`, the PTW PQ remains zero.

Minimal enabling fragment (replace `sp` with any policy listed below):

```json
{
  "STLB": {
    "prefetcher": "prefetcher_stlb/sp",
    "prefetch_activate": "LOAD",
    "prefetch_as_load": false,
    "pq_size": 16
  },
  "PTW": {
    "pq_size": 16
  }
}
```

With this configuration, STLB demand misses and vBerti Permit-PGC requests
continue to use the STLB-to-PTW RQ. STLB-local prefetches use the PQ. The PTW
serves every RQ before PQ and shares the configured `max_read` bandwidth across
both queues.

The prefetch policy and completed-translation destination are independent. The
default remains direct STLB fill. To enable the STLB-only independent buffer,
add:

```json
"stlb_prefetch_destination": "PB",
"stlb_prefetch_buffer_size": 64,
"stlb_prefetch_buffer_latency": 2
```

The buffer is checked serially after an STLB miss. A buffer miss starts the
ordinary demand PTW only after this configured delay. These keys are rejected
on non-STLB caches.

Available policies are:

- `prefetcher_stlb/sp`: fixed `+1` page;
- `prefetcher_stlb/dp`: global miss-distance transition table;
- `prefetcher_stlb/asp`: conservative stable per-PC miss stride;
- `prefetcher_stlb/stp`: fixed `{-2,-1,+1,+2}` pages;
- `prefetcher_stlb/h2p`: the two most recent global miss distances;
- `prefetcher_stlb/masp`: old and newly observed per-PC miss strides;
- `prefetcher_stlb/atp`: ATP policy; its destination is selected independently
  by the JSON setting above;
- `prefetcher_stlb/stlb_stride`: the original prototype retained for existing
  experiment JSON files.

Each policy is a self-contained ChampSim module. Its implementation files and
all policy-private state, candidate handling, statistics, and replacement logic
live in that policy's own directory. The six baseline policies inherit only the
public `champsim::modules::stlb_prefetcher` infrastructure; they do not include
files from another STLB policy directory or from a shared policy helper.

All six new policies train only on accepted demand-data STLB miss callbacks.
STLB hits, vBerti translation requests, the policy's own requests, PTW internal
accesses, and stalled retries do not update their miss histories. Warmup trains
state but does not increment policy-private ROI counters.

The evidence-chain `script/build_one.sh` also accepts the existing prototype:

```bash
STLB_PREF=stlb_stride STLB_PQ_SIZE=16 PTW_PQ_SIZE=16 \
  ./script/build_one.sh ...
```

If `STLB_PREF` is unset, the script leaves the old JSON STLB/PTW settings
unchanged.

## Interface

These modules inherit `champsim::modules::stlb_prefetcher`, not the generic
data-cache prefetcher base. The dedicated callbacks are
`stlb_prefetcher_initialize`, `stlb_prefetcher_operate`,
`stlb_prefetcher_fill`, `stlb_prefetcher_cycle_operate`, and
`stlb_prefetcher_final_stats`. A module submits a VPN with
`prefetch_translation()`; acceptance only controls issue statistics and never
rolls back predictor training.

`stlb_prefetcher_context::prefetch_buffer_hit` distinguishes a hit in the
independent buffer from an ordinary STLB miss. It is false on the default
direct-fill path.
