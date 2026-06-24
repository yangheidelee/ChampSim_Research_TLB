# Result Summary

## Purpose

This experiment checks whether a more paper-like core/cache/data-prefetcher
environment changes the IPC upper bound of ideal STLB all-hit modeling.

Compared with the original jsonnew baseline, this case changes several
system-level parameters together: 4-wide core, L1I/L1D/L2/LLC cache settings,
L1D/L2C prefetchers, and DRAM timing/capacity-related fields.

Only two configurations are compared:

- `pref`
- `ideal-all`

The reported gain is `ideal-all IPC / pref IPC - 1`.

## Output

- Logs: `/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/results/test-ideal-stlb-paper-env-pref-vs-all`
- Trace CSV: `/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/csv_figure/test-ideal-stlb-paper-env-pref-vs-all/paper_env_pref_vs_ideal_all_trace_compare.csv`
- Summary CSV: `/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/csv_figure/test-ideal-stlb-paper-env-pref-vs-all/paper_env_pref_vs_ideal_all_summary_compare.csv`

All 14 logs were complete.

## Overall Result

| Config | ideal-all IPC gain |
|---|---:|
| old jsonnew | 16.76% |
| paper-env | 16.38% |
| delta | -0.37 pp |

## Per-Trace Result

| trace | old jsonnew gain | paper-env gain | delta |
|---|---:|---:|---:|
| `433.milc-337B` | 15.02% | 18.85% | +3.83 pp |
| `459.GemsFDTD-1169B` | 10.30% | 22.08% | +11.78 pp |
| `483.xalancbmk-716B` | 20.98% | 15.75% | -5.22 pp |
| `620.omnetpp_s-141B` | 20.66% | 15.35% | -5.32 pp |
| `gap.cc.twitter-10B` | 11.14% | 10.37% | -0.76 pp |
| `ligra_CF...length_250M` | 41.91% | 32.44% | -9.47 pp |
| `ligra_Components...length_250M` | 1.27% | 2.13% | +0.86 pp |

## Conclusion

The paper-like environment changes individual traces noticeably, but it does
not increase the overall ideal-STLB upper bound. The gmean IPC gain slightly
drops from 16.76% to 16.38%. Therefore, the small overall ideal-STLB benefit is
not simply explained by the original jsonnew environment being too aggressive.
