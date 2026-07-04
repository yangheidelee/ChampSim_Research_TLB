# L1D VPN Footprint Characterization

这个实验用于记录 ROI 阶段 L1D demand data access 的虚拟页访问流，用来分析 L1D 看到的虚拟页 footprint、VPN 轨迹和相邻 VPN delta pattern。

记录口径：

- 记录的是 ROI 阶段的 L1D translated tag-check ready demand access attempt stream。
- 记录点位于 ChampSim 将 ready tag-check batch 分成 hit/miss 之前，因此 `access_id` 保留的是 L1D tag-check 阶段看到的严格 demand access 顺序。
- 不记录 warmup 阶段访问。
- 不记录 instruction-side access。
- 不记录 L1D prefetch 请求。
- 不记录 page-table-walk translation 请求。
- 当前版本不记录该访问在 L1D 中是 hit 还是 miss。

CSV 字段含义：

- `access_id`：从 0 开始的 ROI 内访问流序号。它表示 L1D translated tag-check ready demand data access 的严格顺序。
- `cycle`：L1D tag-check 阶段观察到该访问时的 ChampSim cycle。
- `ip`：产生该数据访问的 load/store 指令的 instruction pointer，使用十进制输出。
- `vaddr`：原始虚拟数据地址，使用十进制输出。
- `vpn`：原始虚拟页号，计算方式为 `vaddr >> LOG2_PAGE_SIZE`。
- `offset`：虚拟页内部的 cache-line offset，计算方式为 `(vaddr >> LOG2_BLOCK_SIZE) & ((1 << (LOG2_PAGE_SIZE - LOG2_BLOCK_SIZE)) - 1)`。在 4KB page、64B cache line 下，该值范围是 0 到 63。
- `type`：过滤后的 ChampSim access type。正常的 demand data access 预期为 `LOAD`、`RFO` 或 `WRITE`。
- `cpu`：CPU/core id。
- `instr_id`：ChampSim 中与该访问关联的动态指令 id。

目录结构：

- `scripts`：配置文件、build 脚本、运行脚本和后处理脚本。
- `result`：ChampSim log 和原始 `l1d_vpn_trace.csv`。
- `csv_figure`：生成的图和 CSV summary。

后处理输出：

- `fig_a_raw_vpn_trajectory.png`：原始 VPN 随 `access_id` 的轨迹。
- `fig_b_first_touch_vpn_id_trajectory.png`：按首次出现顺序重新编号后的 VPN id 轨迹。
- `fig_c_adjacent_raw_vpn_delta_sequence.png`：相邻访问的原始 VPN delta 序列，y 轴会 clip 到 `[-DELTA_CLIP, +DELTA_CLIP]`，默认是 `[-64, +64]`。
- `fig_c2_adjacent_raw_vpn_delta_sequence_symlog.png`：相邻访问的原始 VPN delta 序列，不做 clip，y 轴使用 symlog scale 展示远距离跳转。
- `fig_d_windowed_vpn_delta_coverage.png`：窗口内 top1/top4/top8 VPN delta 覆盖率，默认每 10K 次 L1D demand access 作为一个窗口；每个点的分母是该窗口内部的 delta 总次数，而不是从 ROI 开始累计。
- `fig_d2_windowed_vpn_delta_breakdown.png`：窗口内 `delta=0`、`delta=+1`、`delta=-1` 的比例，默认每 10K 次 L1D demand access 作为一个窗口；每个点的分母是该窗口内部的 delta 总次数。
- `fig_e_windowed_delta_ratio_stacked_area.png`：窗口堆叠面积图，展示每个窗口内 `delta=0`、`delta=+1`、`delta=-1`、`small-jump`、`medium-jump`、`large-jump` 六类 VPN delta 的比例。其中 `small-jump` 表示 `|delta| <= 4` 但不包括 `0,+1,-1`，即 `{-4,-3,-2,+2,+3,+4}`；`medium-jump` 表示 `4 < |delta| <= 16`；`large-jump` 表示 `|delta| > 16`。
- `fig_f_windowed_delta_heatmap.png`：窗口 heatmap，横轴是 window index，纵轴是 VPN delta，颜色表示该 delta 在窗口内的比例；默认展示 `[-16, +16]` 的 delta。
- `fig_g_global_delta_histogram.png`：全局 VPN delta 分布直方图，默认精确展示 `[-64, +64]` 内的 delta，并把范围外的 delta 聚合到两侧边界 bin。
- `vpn_delta_window_stats.csv`：窗口级 VPN delta 统计数据。
- `vpn_delta_window_heatmap.csv`：窗口 heatmap 使用的窗口级 delta 比例数据。
- `vpn_delta_global_histogram.csv`：全局 VPN delta histogram 使用的 bin 统计数据。
- `vpn_delta_global_topk.csv`：全局 top-k VPN delta 表，默认输出出现次数最多的 20 个 delta 及其比例。
- `vpn_trace_summary.csv`：整体访问条数、唯一 VPN 数量等 summary。

冒烟测试：

```bash
cd /home/zcq/git_prj/ChampSim/launch_sim_characterization/l1d-vpn-footprint
N_WARM=1 N_SIM=1 ./scripts/run_all_smoke.sh
```

冒烟测试默认 trace 是 `/data2/zcq/gap_dpc/bfs-3.trace.gz`。

运行时 dump 开关：

```bash
DUMP_L1D_VPN=1 DUMP_L1D_VPN_FILE=/path/to/l1d_vpn_trace.csv \
/home/zcq/git_prj/ChampSim/bin/tlb-pref-1core --warmup-instructions 1000000 --simulation-instructions 1000000 --hide-heartbeat /data2/zcq/gap_dpc/bfs-3.trace.gz
```
