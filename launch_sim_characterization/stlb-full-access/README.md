# STLB Full Access Characterization

这个实验用于记录 ROI 阶段 STLB 看到的虚拟页访问流，用来分析二级 TLB access stream 的 VPN 轨迹、相邻 VPN delta pattern，以及不同 translation origin 的访问来源。

当前脚本中的 JSON 已经将 L1D prefetcher 关闭：

```json
"L1D": {
  "prefetcher": "no"
}
```

记录口径：

- 记录的是 ROI 阶段的 STLB tag-check ready access attempt stream。
- 记录点位于 ChampSim 将 ready tag-check batch 分成 hit/miss 之前，因此 `access_id` 保留的是 STLB tag-check 阶段看到的严格 access 顺序。
- 记录 STLB 的所有 access attempt，不只记录 STLB miss。
- 不记录 warmup 阶段访问。
- 当前 CSV 不记录该访问在 STLB 中是 hit 还是 miss。
- 除了 full STLB access stream，还可以单独 dump full STLB miss stream、`Demand_Data`/`Demand_Instruction` 合并后的 STLB demand stream，以及 `L1D_Prefetch` 来源的 STLB stream。

CSV 字段含义：

- `access_id`：从 0 开始的 ROI 内 STLB access 流序号。它表示 STLB tag-check ready access 的严格顺序。
- `cycle`：STLB tag-check 阶段观察到该访问时的 ChampSim cycle。
- `ip`：产生该 translation 请求的动态指令对应的 instruction pointer，使用十进制输出。
- `vaddr`：原始虚拟地址，使用十进制输出。
- `vpn`：原始虚拟页号，计算方式为 `vaddr >> LOG2_PAGE_SIZE`。
- `offset`：虚拟页内部的 cache-line offset，计算方式为 `(vaddr >> LOG2_BLOCK_SIZE) & ((1 << (LOG2_PAGE_SIZE - LOG2_BLOCK_SIZE)) - 1)`。在 4KB page、64B cache line 下，该值范围是 0 到 63。
- `type`：ChampSim 内部传到 STLB 的 request type。当前 translation lookup 通常表现为 `LOAD`。
- `origin`：translation 来源，包括 `Demand_Data`、`Demand_Instruction`、`L1D_Prefetch`、`L1I_Prefetch`、`Other`。
- `cpu`：CPU/core id。
- `instr_id`：ChampSim 中与该 translation 请求关联的动态指令 id。
- `is_instr`：该请求是否来自 instruction-side access。
- `prefetch_from_this`：该请求是否由当前 cache level 本地 prefetcher 发出；对 STLB access 通常主要看 `origin` 字段。

目录结构：

- `scripts`：配置文件、build 脚本、运行脚本和后处理脚本。
- `result`：ChampSim log 和原始 `stlb_access_trace.csv`。
- `csv_figure`：生成的图和 CSV summary。

后处理输出：

- `fig_a_raw_vpn_trajectory.png`：原始 VPN 随 `access_id` 的轨迹。
- `fig_b_first_touch_vpn_id_trajectory.png`：按首次出现顺序重新编号后的 VPN id 轨迹。
- `fig_c_adjacent_raw_vpn_delta_sequence.png`：相邻访问的原始 VPN delta 序列，y 轴会 clip 到 `[-DELTA_CLIP, +DELTA_CLIP]`，默认是 `[-64, +64]`。
- `fig_c2_adjacent_raw_vpn_delta_sequence_symlog.png`：相邻访问的原始 VPN delta 序列，不做 clip，y 轴使用 symlog scale 展示远距离跳转。
- `fig_d_windowed_vpn_delta_coverage.png`：窗口内 top1/top4/top8 VPN delta 覆盖率，默认每 100 次 STLB access 作为一个窗口；每个点的分母是该窗口内部的 delta 总次数，而不是从 ROI 开始累计。
- `fig_d2_windowed_vpn_delta_breakdown.png`：窗口内 `delta=0`、`delta=+1`、`delta=-1` 的比例，默认每 100 次 STLB access 作为一个窗口；每个点的分母是该窗口内部的 delta 总次数。
- `fig_e_windowed_delta_ratio_stacked_area.png`：窗口堆叠面积图，展示每个窗口内 `delta=0`、`delta=+1`、`delta=-1`、`small-jump`、`medium-jump`、`large-jump` 六类 VPN delta 的比例。其中 `small-jump` 表示 `|delta| <= 4` 但不包括 `0,+1,-1`，即 `{-4,-3,-2,+2,+3,+4}`；`medium-jump` 表示 `4 < |delta| <= 16`；`large-jump` 表示 `|delta| > 16`。
- `fig_f_windowed_delta_heatmap.png`：窗口 heatmap，横轴是 window index，纵轴是 VPN delta，颜色表示该 delta 在窗口内的比例；默认展示 `[-16, +16]` 的 delta。
- `fig_g_global_delta_histogram.png`：全局 VPN delta 分布直方图，默认精确展示 `[-64, +64]` 内的 delta，并把范围外的 delta 聚合到两侧边界 bin。
- `vpn_delta_window_stats.csv`：窗口级 VPN delta 统计数据。
- `vpn_delta_window_heatmap.csv`：窗口 heatmap 使用的窗口级 delta 比例数据。
- `vpn_delta_global_histogram.csv`：全局 VPN delta histogram 使用的 bin 统计数据。
- `vpn_delta_global_topk.csv`：全局 top-k VPN delta 表，默认输出出现次数最多的 20 个 delta 及其比例。
- `stlb_origin_summary.csv`：STLB access 来源统计，按 `origin` 汇总 count 和 ratio。
- `vpn_trace_summary.csv`：整体访问条数、唯一 VPN 数量等 summary。

冒烟测试：

```bash
cd /home/zcq/git_prj/ChampSim/launch_sim_characterization/stlb-full-access
N_WARM=1 N_SIM=1 ./scripts/run_all_smoke.sh
```

冒烟测试默认 trace 是 `/data2/zcq/gap_dpc/bfs-3.trace.gz`。

运行时 dump 开关：

```bash
DUMP_STLB_ACCESS=1 DUMP_STLB_ACCESS_FILE=/path/to/stlb_access_trace.csv \
/home/zcq/git_prj/ChampSim/bin/tlb-pref-1core --warmup-instructions 1000000 --simulation-instructions 1000000 --hide-heartbeat /data2/zcq/gap_dpc/bfs-3.trace.gz
```

可选的 STLB miss 和子流 dump：

```bash
DUMP_STLB_MISS_ACCESS=1 DUMP_STLB_MISS_ACCESS_FILE=/path/to/stlb_miss_access_trace.csv \
DUMP_STLB_DEMAND_ACCESS=1 DUMP_STLB_DEMAND_ACCESS_FILE=/path/to/stlb_demand_access_trace.csv \
DUMP_STLB_L1D_PREFETCH_ACCESS=1 DUMP_STLB_L1D_PREFETCH_ACCESS_FILE=/path/to/stlb_l1d_prefetch_access_trace.csv \
/home/zcq/git_prj/ChampSim/bin/tlb-pref-1core --warmup-instructions 1000000 --simulation-instructions 1000000 --hide-heartbeat /data2/zcq/gap_dpc/bfs-3.trace.gz
```

- `DUMP_STLB_MISS_ACCESS`：只记录 STLB miss access，包含所有 `origin` 来源。
- `DUMP_STLB_DEMAND_ACCESS`：只记录 `origin` 为 `Demand_Data` 或 `Demand_Instruction` 的 STLB access。
- `DUMP_STLB_L1D_PREFETCH_ACCESS`：只记录 `origin` 为 `L1D_Prefetch` 的 STLB access。
- miss stream 和两个子流 CSV 的字段和 full STLB access CSV 保持一致。
