# bfs.kron-128B Demand Data TLB Pattern

本目录用于分析 `bfs.kron-128B` 中 real demand data load 的三条 TLB 序列：L1 DTLB access、实际执行 STLB tag lookup 的 STLB access，以及其中 lookup 结果为 miss 的 STLB miss。一次记录同时保存 VA/VPN 和翻译返回的真实 PA/PPN，指令翻译与 data prefetch translation 均不进入这些序列。

## 目录

- `scripts/`：配置、构建、运行、校验和绘图脚本。
- `result/simulation_log/`：仿真标准输出。
- `result/dtlb_access/`：logger 原始逐 demand-load 事件 CSV、metadata 和 summary。
- `result/stlb_access/`：从原始事件中筛选 `stlb_accessed=1` 后、按 STLB lookup 顺序重新编号的流。
- `result/stlb_miss/`：从 STLB access 中筛选 `stlb_result=MISS` 后、按 miss 顺序重新编号的流。
- `result/validation/`：logger 开关前后的基线等价性测试输出。
- `csv_figure/{dtlb_access,stlb_access,stlb_miss}/`：三条流的 VPN 表格、summary、PDF 和 PNG。
- `csv_figure/{dtlb_access_ppn,stlb_access_ppn,stlb_miss_ppn}/`：同一批事件、同一套统计口径下的 PPN 结果。

`--demand-tlb-pattern` 是唯一的记录开关。打开后，同一份事件 CSV 同时包含 `va/vpn/virtual_region_2m/page_offset_in_region` 和
`pa/ppn/physical_region_2m/page_offset_in_physical_region`；`postprocess.sh` 会在一次调用中自动生成 VPN 与 PPN 六组结果，不需要分别运行模拟或设置两个开关。开关关闭时不创建 pattern 输出，也不改变已有 ChampSim 逻辑和统计。

PPN 来自 L1D 收到的真实 translation response，不是根据 VPN 在后处理中推测得到。ROI 结束时仍未返回 translation 的事件使用
`physical_address_valid=0`，VPN 分析仍保留这些事件，PPN 分析会排除它们，避免把未知 PPN 误当作物理页 0。

这里的 “STLB access” 与 ChampSim cache lookup 口径一致：只有真正进入 STLB tag lookup 的请求才计入。请求若在 STLB 输入 channel 中与同 VPN 请求合并，不会虚构为一次独立 STLB access；请求在 STLB MSHR 中合并时，则仍是一次已执行 tag lookup 的 STLB miss，并用 `stlb_merged=1` 标记。

VPN 和 PPN 后处理均生成四张全局轨迹图：原始页号、原始流的 first-touch page ID，以及删除连续重复页号后的页号和 first-touch page ID。原始流使用 `load_tlb_seq`，压缩流使用独立的 `page_transition_seq`。

VPN 目录中的 `05_deduplicated_vpn_access_stream.csv` 与 PPN 目录中的 `05_deduplicated_ppn_access_stream.csv` 保存对应流的逐项去重结果。每一行代表一个连续同页 run 的首个事件，`consecutive_run_length` 表示折叠的事件数。

`stlb_access` 和 `stlb_miss` 的 `01`、`02`、`05a`--`05d` PDF 在同一大页内同时给出两种横坐标：流内连续编号
`stlb_access_seq`/`stlb_miss_seq`，以及该事件在完整 real-demand-load 流中的原始 `load_tlb_seq`。DTLB access 本身只使用
`load_tlb_seq`。去重轨迹的原始坐标视图采用每个连续 VPN run 首事件对应的 `load_tlb_seq`。

VPN/PPN 目录中的 `03_raw_vpn_delta_global_top20.csv`/`03_raw_ppn_delta_global_top20.csv` 直接在未去重序列上计算相邻 Delta，保留 Delta=0，并给出频次最高的 20 个 delta、计数及其占全部原始相邻访问对的比例。

每个流的 `04_per_pc_delta_heatmap.pdf` 在同一大页中并列显示未去重 per-PC 序列与按 PC 删除连续重复页号后的
delta 分布。`04_per_pc_topk.csv` 先保存 `sequence_kind=raw` 部分，空一行后追加带独立表头的去重部分；VPN 与 PPN
目录分别标记为 `deduplicated_consecutive_vpn` 和 `deduplicated_consecutive_ppn`，两部分使用同一组按原始统计选出的 Top PC。

`03_global_page_delta` 上半部分保留默认的 DeltaVPN/DeltaPPN 正负 16 视图，下半部分显示正负 64 视图。可分别通过 `DELTA_LIMIT` 和 `WIDE_DELTA_LIMIT` 调整。

专用 JSON 关闭 L1D、L2C 和 LLC data prefetcher；L1I 仍使用 `next_line`。Pattern logger 本身不会修改任何 prefetcher 或微架构配置。

## 常用命令

完整执行，默认 warmup 50M、ROI 100M：

```bash
cd /home/zcq/git_prj/ChampSim
./launch_sim_characterization/bfs.kron-128B-demand-data-tlb-pattern/scripts/run_all.sh all
```

短 smoke test，warmup 1M、ROI 2M：

```bash
N_WARM=1 N_SIM=2 SKIP_EXISTING=0 \
./launch_sim_characterization/bfs.kron-128B-demand-data-tlb-pattern/scripts/run_all.sh smoke
```

只重新后处理：

```bash
./launch_sim_characterization/bfs.kron-128B-demand-data-tlb-pattern/scripts/run_all.sh analyze
```

`MAX_EVENTS=0` 表示不限制记录数。短调试可以设置非零值，但正式 pattern 分析应保持为 `0`。

`REGION_ID` 只指定 VPN 图的虚拟 2 MiB region；如需固定 PPN 图的物理 region，使用 `PHYSICAL_REGION_ID`。未指定时两套分析分别按照相同规则自动选择自己的热点 region。
