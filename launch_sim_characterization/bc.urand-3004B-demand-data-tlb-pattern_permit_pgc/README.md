# bc.urand-3004B permit-PGC TLB pattern

本目录在开启 L1D vBerti（正常 permit-PGC 数据预取语义）时，把两类真实送入 L1 DTLB 的请求放进同一条 pattern 流：

- `DATA_DEMAND`：L1D 的真实 data demand load translation。
- `VBERTI_CP_PREFETCH`：vBerti 跨页预取实际成功送入 DTLB 的 translation。same-page prefetch 不记录，PQ 中尚未发起 translation 的候选也不记录。

两类事件共享每核连续的 `global_seq`。同时保留 `load_tlb_seq`、`cross_page_prefetch_seq`、vBerti 内部
`vberti_prefetch_seq`，派生流还保留 `stlb_access_seq`/`stlb_miss_seq`。因此所有图可以用同一个公共请求时间轴比较 demand 与 prefetch，而 CSV 仍能还原各自内部顺序。

## 结果目录

- `result/dtlb_access/tlb_pattern_core_0.csv`：统一的 DTLB 请求流及完整 DTLB/STLB 生命周期。
- `result/dtlb_access/tlb_pattern_core_0_global_seq_ordered.csv`：上述原生流的完整字段副本，严格按 `(cpu, global_seq)` 排序；所有主后处理从该文件继续派生。
- `result/dtlb_access/tlb_pattern_core_0_global_seq_ordered_compact.csv`：相同行、相同顺序的精简可读副本。
- `result/stlb_access/`：从统一流筛选真正执行 STLB tag lookup 的事件。
- `result/stlb_miss/`：从 STLB access 中筛选 lookup 结果为 miss 的事件。
- `result/dtlb_access/vberti_cp_prefetch_dtlb_access_core_0.csv`：只保留 `VBERTI_CP_PREFETCH` 的 DTLB access 序列。
- `result/stlb_access/vberti_cp_prefetch_stlb_access_core_0.csv`：只保留真正执行 STLB lookup 的 `VBERTI_CP_PREFETCH` 序列。
- `result/stlb_miss/vberti_cp_prefetch_stlb_miss_core_0.csv`：只保留 STLB lookup miss 的 `VBERTI_CP_PREFETCH` 序列。
- `result/demand_only_dtlb_access/`：原有 logger 的 demand-only 兼容副本，用于证明原统计未改变，不作为本目录主图输入。
- `csv_figure/{dtlb_access,stlb_access,stlb_miss}/`：三条统一 VPN 流的整套图和 CSV。

不再生成独立的 `vberti_prefetch_vs_demand` 或任何 PPN 图目录。prefetch pattern 已经进入上述三套 VPN 主目录。

三套 result 主序列和三套 `02_local_page_offset_raster_records_global_seq.csv` 都同步生成同名 `_compact.csv`。精简版只删除
`vberti_prefetch_seq`、`prefetch_issue_cycle`、`prefetch_trigger_instr_id`、`prefetch_trigger_pc`、
`prefetch_trigger_va`、`pa`、`ppn`、`physical_region_2m`、`page_offset_in_physical_region`、
`physical_address_valid`；不改变事件集合、行顺序或其余字段。完整 CSV 继续保留，供审计和后处理使用。

原生 `tlb_pattern_core_0.csv` 在事件完成时写行，因此物理行序可能是完成顺序；后处理不会覆盖它，而是原子生成 `_global_seq_ordered.csv`。两个文件的事件和字段完全相同，只有行顺序不同。

三份 `vberti_cp_prefetch_*` 文件严格按 `event_type=VBERTI_CP_PREFETCH` 流式筛选，保留输入文件的完整字段、行顺序和原始 sequence 值，不重新编号。这样可以同时观察纯 prefetch 轨迹及其在统一 `global_seq` 时间线中的真实位置。

## 图表口径

- `01_*_region_time_heatmap`、`02_local_page_offset_raster` 和 `05*trajectory` 全部以公共 `global_seq` 为横轴；STLB 流上的空档表示这段公共时间内没有相应 STLB 事件。`01` 在同一大页依次显示全部事件、real demand、cross-page vBerti，以及 real demand 中非 merge 的 L1 DTLB+STLB 双 miss。
- `02` 在同一张大页中保留总体和两个 origin 面板；六种翻译结果的独立面板严格只画 `DATA_DEMAND`。其 records CSV 保留所选 region/公共窗口内的完整原始记录。
- `05` 轨迹图用不同颜色区分 demand 与 cross-page prefetch；TLB 图不记录或绘制 cache-line pattern。
- `03` 的 raw/去重 delta 及其 CSV 全部先筛选 `DATA_DEMAND`，再按公共顺序计算相邻 demand VPN 的 delta。
- `04` 仍是静态 load-PC 分析。prefetch 没有独立的真实 load-PC 身份，因此 PC 选择、per-PC delta 和“占全部 STLB miss”分母严格只使用 `DATA_DEMAND`；CSV 的 `event_scope` 明确记录该口径。

“STLB access”沿用现有 ChampSim lookup 口径：只有真正执行 STLB tag lookup 的请求进入该流。STLB 输入 RQ 合并不伪造独立 lookup；STLB MSHR merge 已执行 lookup，因而属于 STLB miss，并由 `stlb_merged=1` 标识。

`l1dtlb_merged` 继续作为“发生过 DTLB 侧合并”的总括布尔字段；新增互斥字段 `dtlb_merge_detail` 解释具体路径：

- `NONE`：未发生 DTLB 侧合并。
- `RQ_MERGE`：请求在 DTLB 输入 RQ 中合并到同 VPN 的既有请求。
- `MSHR_TO_DATA_DEMAND` / `MSHR_TO_INST_DEMAND`：DTLB lookup miss 后合并到当前 origin 为 data/instruction demand 的 DTLB MSHR。
- `MSHR_TO_L1D_PREFETCH`：合并到无法进一步区分同页/跨页的普通 L1D prefetch origin。
- `MSHR_TO_CP_PREFETCH` / `MSHR_TO_SP_PREFETCH`：合并到当前 origin 为 vBerti 跨页/同页 prefetch 的 DTLB MSHR。
- `MSHR_TO_L1I_PREFETCH` / `MSHR_TO_OTHER`：合并到 L1I prefetch 或其他 origin 的 DTLB MSHR。
- `PRELOOKUP_COALESCED`：未独立完成 DTLB lookup，便由已经返回的同 VPN 翻译完成；它与明确捕获的 RQ merge 分开。

MSHR 类别记录的是“新请求执行 merge 的那个时刻，既有 MSHR 中保存的 origin”。ChampSim 会在 demand 合入 prefetch MSHR 时升级 MSHR 的请求类型/origin，因此同一个未完成翻译上，第一个 demand 可能是 `MSHR_TO_CP_PREFETCH`，之后再合入的 demand 可能是 `MSHR_TO_DATA_DEMAND`；这准确表达了 merge 当时的目标，而不是把 PTW 最初发起者永久固化。

STLB 使用完全相同的目标-origin 命名，写入 `stlb_merge_detail`：`RQ_MERGE` 表示在 STLB 输入 RQ 合并，因而该事件保持 `stlb_accessed=0`；`MSHR_TO_*` 表示已经执行 STLB lookup 并 miss，随后合入对应 origin 的 STLB MSHR。`stlb_merged` 仍是其总括布尔字段。DTLB 特有的 `PRELOOKUP_COALESCED` 不会出现在 STLB 字段中。

原始全序列还由 C++ 记录器直接写出 `raster_outcome_category`，取值就是六个粗粒度 raster 类别。后处理只校验并原样保留该字段；底层 merge/result 字段仍是可审计依据。

统一原始记录为兼容现有观察器仍可能携带 PA/PPN 字段，但本脚本目录的主后处理只分析 VPN，不生成 PPN pattern 图表。

## 开关与隔离

新增观察器由环境变量控制，源码默认关闭：

```bash
DUMP_VBERTI_CROSS_PAGE_DEMAND_PATTERN=1
DUMP_VBERTI_CROSS_PAGE_DEMAND_PATTERN_OUTPUT=/path/to/result/dtlb_access
```

本目录的 `run_pattern.sh` 默认替用户打开它；设置 `VBERTI_TLB_PATTERN=0` 可关闭。观察器只在已有请求接受、cache lookup、merge 和 translation completion 触发点复制只读信息，不参与排队、匹配、替换或任何已有统计。

## 运行

正式运行（warmup 50M、ROI 100M、记录数不截断）：

```bash
cd /home/zcq/git_prj/ChampSim
N_WARM=50 N_SIM=100 MAX_EVENTS=0 SKIP_EXISTING=0 \
./launch_sim_characterization/bc.urand-3004B-demand-data-tlb-pattern_permit_pgc/scripts/run_all.sh all
```

短冒烟测试：

```bash
cd /home/zcq/git_prj/ChampSim
N_WARM=1 N_SIM=2 MAX_EVENTS=100000 SKIP_EXISTING=0 \
./launch_sim_characterization/bc.urand-3004B-demand-data-tlb-pattern_permit_pgc/scripts/run_all.sh smoke
```

只重新后处理已有统一流：

```bash
./launch_sim_characterization/bc.urand-3004B-demand-data-tlb-pattern_permit_pgc/scripts/run_all.sh analyze
```

`MAX_EVENTS=0` 表示不限制；非零值限制每核统一流的总事件数。`REGION_ID` 可固定三套 VPN 图使用的 2 MiB virtual region。
