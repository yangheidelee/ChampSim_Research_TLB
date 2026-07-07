# spec0617_gapligra infinite STLB prefetcher sweep

这个目录从 `spec0617_gapligra-idealTLB_prefsweep_fill` 复制而来，用来做 normal STLB vs infinite STLB 的上限对比。

当前包含三组 prefetcher 配置：

- `berti-ip_stride`: L1D=berti, L2C=ip_stride
- `ipcp-ip_stride`: L1D=ipcp, L2C=ip_stride
- `ipcp-pythia`: L1D=ipcp, L2C=pythia

默认 active flow 只有两组：

- `pref-workload-sweep`: 正常 STLB 大小，作为 baseline
- `infinite_stlb-workload-sweep`: 同样 prefetcher 配置，但 STLB 放大到 `262144 sets x 16 ways`

`infinite_stlb-workload-sweep` 不传 `--stlb-ideal-mode` 和 `--stlb-ideal-fill`，因此不是零延迟 ideal translation；它只是用大容量 STLB 近似无限 STLB。可以用环境变量覆盖容量：

```bash
INFINITE_STLB_SETS=262144 INFINITE_STLB_WAYS=16
```

默认使用 selected trace JSON：

`launch_sim/spec0617_gapligra-infinite_stlb_prefsweep_fill/stlb_mpki_gt_1.0_selected_traces_qmm_parsec.json`

后处理只输出 select_trace 结果，并以 `pref-workload-sweep` 为 baseline，对比 `infinite_stlb-workload-sweep` 的 IPC upper bound。summary 口径保持 trace-level 直接聚合：每个 benchmark family 的 `gmean_*` 直接由该 family 内所有 selected trace 计算，`gmean_all` 直接由所有 selected trace 计算；workload 行由 workload 内 trace 等权聚合。

常用命令：

```bash
cd /home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound

MAX_PARALLEL=15 N_WARM=20 N_SIM=50 \
./launch_sim/spec0617_gapligra-infinite_stlb_prefsweep_fill/berti-ip_stride/run_tlb_select_compare.sh all 15

MAX_PARALLEL=15 N_WARM=20 N_SIM=50 \
./launch_sim/spec0617_gapligra-infinite_stlb_prefsweep_fill/ipcp-ip_stride/run_tlb_select_compare.sh all 15

MAX_PARALLEL=15 N_WARM=20 N_SIM=50 \
./launch_sim/spec0617_gapligra-infinite_stlb_prefsweep_fill/ipcp-pythia/run_tlb_select_compare.sh all 15
```

只做后处理：

```bash
./launch_sim/spec0617_gapligra-infinite_stlb_prefsweep_fill/berti-ip_stride/run_tlb_select_compare.sh backend
./launch_sim/spec0617_gapligra-infinite_stlb_prefsweep_fill/ipcp-ip_stride/run_tlb_select_compare.sh backend
./launch_sim/spec0617_gapligra-infinite_stlb_prefsweep_fill/ipcp-pythia/run_tlb_select_compare.sh backend
```

`nopref-workload-sweep`、`select-json`、`run-nopref` 仍保留为可选入口；它们不是默认路径的一部分。
