# bc.urand-3004B Demand Data TLB Pattern

本目录用于分析 `bc.urand-3004B` 中 real demand data load 的三条 VPN 序列：L1 DTLB access、实际执行 STLB tag lookup 的 STLB access，以及其中 lookup 结果为 miss 的 STLB miss。指令翻译与 data prefetch translation 均不进入这些序列。

## 目录

- `scripts/`：配置、构建、运行、校验和绘图脚本。
- `result/simulation_log/`：仿真标准输出。
- `result/dtlb_access/`：logger 原始逐 demand-load 事件 CSV、metadata 和 summary。
- `result/stlb_access/`：从原始事件中筛选 `stlb_accessed=1` 后、按 STLB lookup 顺序重新编号的流。
- `result/stlb_miss/`：从 STLB access 中筛选 `stlb_result=MISS` 后、按 miss 顺序重新编号的流。
- `result/validation/`：logger 开关前后的基线等价性测试输出。
- `csv_figure/{dtlb_access,stlb_access,stlb_miss}/`：三条流分别使用同一套统计口径生成的表格、summary、PDF 和 PNG。

这里的 “STLB access” 与 ChampSim cache lookup 口径一致：只有真正进入 STLB tag lookup 的请求才计入。请求若在 STLB 输入 channel 中与同 VPN 请求合并，不会虚构为一次独立 STLB access；请求在 STLB MSHR 中合并时，则仍是一次已执行 tag lookup 的 STLB miss，并用 `stlb_merged=1` 标记。

后处理额外生成四张全局轨迹图：原始 VPN、原始流的 first-touch VPN ID，以及删除连续重复 VPN 后的 VPN 和 first-touch VPN ID。原始流使用 `load_tlb_seq`，压缩流使用独立的 `page_transition_seq`。

每个 `csv_figure/<stream>/05_deduplicated_vpn_access_stream.csv` 保存对应流的逐项去重结果。每一行代表一个连续 VPN run 的首个事件，`consecutive_run_length` 表示该行折叠了多少个连续同 VPN 事件。

`stlb_access` 和 `stlb_miss` 的 `01`、`02`、`05a`--`05d` PDF 在同一大页内同时给出两种横坐标：流内连续编号
`stlb_access_seq`/`stlb_miss_seq`，以及该事件在完整 real-demand-load 流中的原始 `load_tlb_seq`。DTLB access 本身只使用
`load_tlb_seq`。去重轨迹的原始坐标视图采用每个连续 VPN run 首事件对应的 `load_tlb_seq`。

每个流目录中的 `03_raw_vpn_delta_global_top20.csv` 直接在未去重 VPN 序列上计算相邻 DeltaVPN，保留 `DeltaVPN=0`，
并给出频次最高的 20 个 delta、计数及其占全部原始相邻访问对的比例。

每个流的 `04_per_pc_delta_heatmap.pdf` 在同一大页中并列显示未去重 per-PC 序列与按 PC 删除连续重复 VPN 后的
delta 分布。`04_per_pc_topk.csv` 先保存 `sequence_kind=raw` 部分，空一行后追加带独立表头的
`sequence_kind=deduplicated_consecutive_vpn` 部分；两部分使用同一组按原始统计选出的 Top PC。

`03_global_page_delta` 上半部分保留默认的 `DeltaVPN` 正负 16 视图，下半部分显示正负 64 视图。可分别通过 `DELTA_LIMIT` 和 `WIDE_DELTA_LIMIT` 调整。

专用 JSON 关闭 L1D、L2C 和 LLC data prefetcher；L1I 仍使用 `next_line`。Pattern logger 本身不会修改任何 prefetcher 或微架构配置。

## 常用命令

完整执行，默认 warmup 50M、ROI 100M：

```bash
cd /home/zcq/git_prj/ChampSim
./launch_sim_characterization/bc.urand-3004B-demand-data-tlb-pattern/scripts/run_all.sh all
```

短 smoke test，warmup 1M、ROI 2M：

```bash
N_WARM=1 N_SIM=2 SKIP_EXISTING=0 \
./launch_sim_characterization/bc.urand-3004B-demand-data-tlb-pattern/scripts/run_all.sh smoke
```

只重新后处理：

```bash
./launch_sim_characterization/bc.urand-3004B-demand-data-tlb-pattern/scripts/run_all.sh analyze
```

`MAX_EVENTS=0` 表示不限制记录数。短调试可以设置非零值，但正式 pattern 分析应保持为 `0`。
