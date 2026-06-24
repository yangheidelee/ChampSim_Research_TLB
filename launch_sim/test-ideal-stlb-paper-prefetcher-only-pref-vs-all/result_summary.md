# 结果记录

## 实验目的

这个实验用于隔离分析：`L1D` / `L2C` 的 data-cache prefetcher 选择，是否是影响 `ideal-STLB` IPC 上限收益的主要原因。

基础配置是原始的 `jsonnew` 配置。第一次实验只改了两个字段：

- `L1D.prefetcher`: `berti` -> `next_line`
- `L2C.prefetcher`: `pythia` -> `ip_stride`

其余配置都保持和 `jsonnew` 一致。

实验只比较两种配置：

- `pref`
- `ideal-all`

汇报的收益定义为：

```text
IPC gain = ideal-all IPC / pref IPC - 1
```

## 输出位置

- Logs: `/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/results/test-ideal-stlb-paper-prefetcher-only-pref-vs-all`
- Trace CSV: `/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/csv_figure/test-ideal-stlb-paper-prefetcher-only-pref-vs-all/prefetcher_only_pref_vs_ideal_all_trace_compare.csv`
- Summary CSV: `/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/csv_figure/test-ideal-stlb-paper-prefetcher-only-pref-vs-all/prefetcher_only_pref_vs_ideal_all_summary_compare.csv`

这次实验的 14 个 log 都是完整的。

## 整体结果

| 配置 | `ideal-all` IPC gain |
|---|---:|
| old `jsonnew` | 16.76% |
| prefetcher-only | 16.10% |
| delta | -0.65 pp |

## 每个 trace 的结果

| trace | old `jsonnew` gain | prefetcher-only gain | delta |
|---|---:|---:|---:|
| `433.milc-337B` | 15.02% | 15.53% | +0.51 pp |
| `459.GemsFDTD-1169B` | 10.30% | 18.17% | +7.87 pp |
| `483.xalancbmk-716B` | 20.98% | 18.35% | -2.63 pp |
| `620.omnetpp_s-141B` | 20.66% | 16.68% | -3.98 pp |
| `gap.cc.twitter-10B` | 11.14% | 11.06% | -0.07 pp |
| `ligra_CF...length_250M` | 41.91% | 34.97% | -6.94 pp |
| `ligra_Components...length_250M` | 1.27% | 0.63% | -0.64 pp |

## 初步结论

只改 `L1D` / `L2C` prefetcher 以后，整体 `ideal-STLB` 上限收益没有增加。`gmean` IPC gain 从 16.76% 小幅下降到 16.10%。这说明，原始的 Berti/Pythia data prefetcher 组合不是导致整体 `ideal-STLB` 收益有限的唯一原因。

不过，每个 trace 的敏感性仍然很明显。`459.GemsFDTD-1169B` 在 paper-style prefetcher 下收益明显更高，而 `ligra_CF`、`620.omnetpp_s` 和 `483.xalancbmk` 的 `ideal-STLB` 收益下降。

## 追加实验：只改 L1D Prefetcher

为了进一步区分前一次差异到底来自 `L1D` 还是 `L2C`，这个文件夹又复用做了第二次实验。第二次实验没有覆盖前一次的 `tlb-prefonly-*` log 或 CSV，而是让新生成的结果文件名带上 `tlb-l1donly-*`。

这次只从原始 `jsonnew` 配置中修改一个 prefetcher 字段：

- `L1D.prefetcher`: `berti` -> `next_line`
- `L2C.prefetcher`: 保持原始的 `pythia`

其余配置都保持和 `jsonnew` 一致。

## L1D-only 输出位置

- Logs: `/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/results/test-ideal-stlb-paper-prefetcher-only-pref-vs-all`
- Trace CSV: `/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/csv_figure/test-ideal-stlb-paper-prefetcher-only-pref-vs-all/l1d_only_pref_vs_ideal_all_trace_compare.csv`
- Summary CSV: `/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/csv_figure/test-ideal-stlb-paper-prefetcher-only-pref-vs-all/l1d_only_pref_vs_ideal_all_summary_compare.csv`

这次实验的 14 个 `tlb-l1donly-*` log 都是完整的。

## L1D-only 整体结果

| 配置 | `ideal-all` IPC gain |
|---|---:|
| old `jsonnew` | 16.76% |
| L1D-only | 18.92% |
| delta vs old `jsonnew` | +2.16 pp |
| previous L1D+L2C | 16.10% |
| L2C increment over L1D-only | -2.81 pp |

这里的 `L2C increment over L1D-only` 表示：

```text
(L1D next_line + L2C ip_stride gain) - (L1D next_line + L2C pythia gain)
```

## L1D-only 每个 trace 的结果

| trace | old `jsonnew` gain | L1D-only gain | delta vs old | previous L1D+L2C gain | L2C increment |
|---|---:|---:|---:|---:|---:|
| `433.milc-337B` | 15.02% | 18.51% | +3.49 pp | 15.53% | -2.98 pp |
| `459.GemsFDTD-1169B` | 10.30% | 21.57% | +11.27 pp | 18.17% | -3.40 pp |
| `483.xalancbmk-716B` | 20.98% | 20.27% | -0.70 pp | 18.35% | -1.92 pp |
| `620.omnetpp_s-141B` | 20.66% | 21.45% | +0.78 pp | 16.68% | -4.76 pp |
| `gap.cc.twitter-10B` | 11.14% | 12.20% | +1.07 pp | 11.06% | -1.14 pp |
| `ligra_CF...length_250M` | 41.91% | 41.21% | -0.70 pp | 34.97% | -6.24 pp |
| `ligra_Components...length_250M` | 1.27% | 0.86% | -0.41 pp | 0.63% | -0.23 pp |

## L1D-only 结论

只把 `L1D.prefetcher` 从 Berti 改成 next-line 后，采样 trace 上的整体 `ideal-STLB` gain 从 16.76% 增加到 18.92%。因此，单独的 `L1D` 改动并不能解释前一次 `L1D+L2C` prefetcher-only 实验中收益下降的现象。

在 `L1D` 已经改成 next-line 的基础上，再把 `L2C` 从 Pythia 改成 ip_stride，会让这组采样 trace 中每个 trace 的 `ideal-STLB` gain 都下降；相对于 L1D-only，整体下降 2.81 percentage points。对于这组样本，前一次 prefetcher-only 实验中的收益下降主要由 `L2C` prefetcher 改动导致，而不是由 `L1D` prefetcher 改动单独导致。

## 四组配置对比

下面把四组相关配置放在同一批采样 trace 上对比。汇报的数值仍然是：

```text
IPC gain = ideal-all IPC / pref IPC - 1
```

每一列都使用该配置自己的 `pref` run 作为 baseline。

| trace | old `jsonnew` | full paper-style json | L1D+L2C prefetcher only | L1D prefetcher only |
|---|---:|---:|---:|---:|
| `433.milc-337B` | 15.02% | 18.85% | 15.53% | 18.51% |
| `459.GemsFDTD-1169B` | 10.30% | 22.08% | 18.17% | 21.57% |
| `483.xalancbmk-716B` | 20.98% | 15.75% | 18.35% | 20.27% |
| `620.omnetpp_s-141B` | 20.66% | 15.35% | 16.68% | 21.45% |
| `gap.cc.twitter-10B` | 11.14% | 10.37% | 11.06% | 12.20% |
| `ligra_CF...length_250M` | 41.91% | 32.44% | 34.97% | 41.21% |
| `ligra_Components...length_250M` | 1.27% | 2.13% | 0.63% | 0.86% |
| **gmean summary** | **16.76%** | **16.38%** | **16.10%** | **18.92%** |

各列含义如下：

- `old jsonnew`：原始 `jsonnew` 配置。
- `full paper-style json`：更完整的 paper-style 环境改动，包括 core/cache/prefetcher 等配置变化。
- `L1D+L2C prefetcher only`：只把 `L1D.prefetcher` 从 `berti` 改成 `next_line`，并把 `L2C.prefetcher` 从 `pythia` 改成 `ip_stride`。
- `L1D prefetcher only`：只把 `L1D.prefetcher` 从 `berti` 改成 `next_line`，`L2C.prefetcher` 仍然保持 `pythia`。

从这个四组对比看，L1D-only 配置的整体采样收益最大，为 18.92%。而 L1D+L2C 配置下降到 16.10%。这再次说明，在这组采样 trace 上，prefetcher-only 实验中收益降低主要来自 `L2C` prefetcher 从 Pythia 改为 ip_stride，而不是来自 `L1D` prefetcher 的单独改动。
