# spec0617_gapligra idealTLB prefetcher sweep fill

这个目录从原始 ideal STLB 上限实验脚本复制而来：

`launch_sim/1core-spec0617_gapligra-idealTLB-select-trace-compare_jsonnew`

这个目录是 fill 对照版本：`ideal-demand`、`ideal-l1pref`、`ideal-all` 会同时传 `--stlb-ideal-mode` 和 `--stlb-ideal-fill`。因此 ideal-resolved STLB miss 会立即返回 translation，并立即填入 STLB，用来和默认 no-fill 的 `spec0617_gapligra-idealTLB_prefsweep` 做对照。

这里不包含原始的 berti + pythia，因为外部已经有这组数据。当前包含三组新配置：

- `vberti-ip_stride`: L1D=vberti, L2C=ip_stride；额外包含 `pref-discard-pgc-workload-sweep`，其中 L1D=vberti_nocross, L2C=ip_stride
- `ipcp-ip_stride`: L1D=ipcp, L2C=ip_stride
- `ipcp-pythia`: L1D=ipcp, L2C=pythia

每组内部仍然保留原始五个 flow：

- `nopref-workload-sweep`
- `pref-discard-pgc-workload-sweep`
- `pref-workload-sweep`
- `ideal-demand-workload-sweep`
- `ideal-l1pref-workload-sweep`
- `ideal-all-workload-sweep`

当前默认流程使用已经筛好的 selected trace JSON：

`launch_sim/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/stlb_mpki_gt_1.0_selected_traces.json`

这份 JSON 来自包含 SPEC06/SPEC17/GAP/Ligra/QMM/PARSEC/XSBench 的 nopref 筛选结果，包含 179 条 selected trace。旧的 selected trace JSON 仍保留在同目录下备用。默认 `all` / `run-only` 不再跑 `nopref-workload-sweep`，也不再重新筛选 trace；`vberti-ip_stride` 会 build/run：

- `pref-discard-pgc-workload-sweep`
- `pref-workload-sweep`
- `ideal-demand-workload-sweep`
- `ideal-l1pref-workload-sweep`
- `ideal-all-workload-sweep`

后处理仍然只输出 select_trace 的 CSV 和图。IPC 对比图保留以同一配置下的 `pref-workload-sweep` 为 baseline，对比 `ideal-demand`、`ideal-l1pref`、`ideal-all`；`vberti-ip_stride` 额外输出以 `pref-discard-pgc-workload-sweep` 为 baseline 的 `pref`、三种 ideal 配置 IPC 提升图，以及单独的 `pref / pref_discard_pgc` IPC 提升图。

后处理的 summary 口径是 trace-level 直接聚合：每个 benchmark family 的 `gmean_*` 直接由该 family 内所有 selected trace 计算，`gmean_all` 直接由所有 selected trace 计算；workload 行则由 workload 内 trace 等权聚合。XSBench 不展开内部 workload，所有 `xs.*` trace 只汇总成一个 `gmean_xsbench`/`amean_xsbench` summary 行。

常用命令：

```bash
cd /home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound

MAX_PARALLEL=15 N_WARM=50 N_SIM=100 \
./launch_sim/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/vberti-ip_stride/run_tlb_select_compare.sh all 15

MAX_PARALLEL=15 N_WARM=50 N_SIM=100 \
./launch_sim/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/ipcp-ip_stride/run_tlb_select_compare.sh all 15

MAX_PARALLEL=15 N_WARM=50 N_SIM=100 \
./launch_sim/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/ipcp-pythia/run_tlb_select_compare.sh all 15
```

如需临时使用其他 selected trace JSON，可以显式传入：

```bash
SELECT_TRACE_JSON=/path/to/stlb_mpki_gt_1.0_selected_traces.json \
MAX_PARALLEL=15 N_WARM=50 N_SIM=100 \
./launch_sim/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/vberti-ip_stride/run_tlb_select_compare.sh all 15
```

结果目录：

```text
results/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/vberti-ip_stride
results/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/ipcp-ip_stride
results/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/ipcp-pythia
```

CSV 和图目录：

```text
csv_figure/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/vberti-ip_stride/select_trace
csv_figure/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/ipcp-ip_stride/select_trace
csv_figure/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/ipcp-pythia/select_trace
```

只做后处理：

```bash
./launch_sim/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/vberti-ip_stride/run_tlb_select_compare.sh backend
./launch_sim/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/ipcp-ip_stride/run_tlb_select_compare.sh backend
./launch_sim/spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100/ipcp-pythia/run_tlb_select_compare.sh backend
```

`nopref-workload-sweep`、`select-json`、`run-nopref` 命令仍然保留为可选入口，用于以后需要重新筛选 trace 的情况；它们不是当前默认路径的一部分。
