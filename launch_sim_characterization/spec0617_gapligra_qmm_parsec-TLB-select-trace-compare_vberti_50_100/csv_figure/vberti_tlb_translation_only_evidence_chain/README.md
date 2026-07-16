# vBerti 跨页 TLB 预取证据链（全部数据集）

本目录的分析范围为 **全部数据集**，只使用已经完成的 `translation_only` 和 `discard_pgc` 日志进行后处理，不重新运行模拟器，也不读取 `permit_pgc` 或 `nopref` 日志。共纳入 **179** 条两配置齐全的 trace。

## 要回答的问题

目标是利用 `translation_only - discard_pgc` 这组对照，检查下面这个更具体的假设：

> vBerti 可以产生大量跨页 cache-prefetch 候选，但这些候选很少真正需要新的 STLB translation，更少成为后来真实 data demand 使用的 translation，因此它先天能够覆盖的 demand STLB miss 很有限。

## 推荐阅读顺序

如果希望一次顺序浏览全部图，直接打开 `00_all_evidence_chain_figures.pdf`；它按下面的 01–17 顺序合并。

1. `01_demand_opportunity_and_outcome.pdf`：先确认 discard 下的 **data-demand** STLB MPKI，以及 translation-only 是否减少 data-demand miss；右图检查纯跨页 translation 机制的净 IPC 结果。
2. `02_cross_page_flow_funnel.pdf`：版式与原始 permit/discard evidence-chain 图一致。左图完整追踪 Requested → PQ → DTLB → STLB → PTW → Useful at STLB；右图按 dataset 展示 Reach STLB、Trigger walk 和 STLB Useful。每个点和柱都先对单条 trace 计算相对 `cross_requested` 的比例，再做非加权 amean（DPC4-style），不是 ratio-of-sums。PQ drop amean 为 **54.08%**；只有 **1.613%** 的跨页请求发生 STLB miss 并触发 PTW，最终有 **0.5084%** 成为 STLB useful。已通过 PQ 的候选中，触发 PTW 和最终 STLB useful 的条件比例 amean 为 **2.853% / 0.6566%**。
3. `03_prediction_quality_and_coverage.pdf`：验证“发得多”是否等于“覆盖多”。去重 TLB-system useful 相当于 discard data-demand STLB miss 的 **9.659%**，而 translation-only 相对 discard 的净 data-demand miss reduction 为 **11.04%**。
4. `04_pq_bottleneck_test.pdf`：检查 PQ drop 与覆盖/净结果的关系。总体 PQ 损失显著，但通过 PQ 后到 translation/useful 的条件保留率仍很低，因此需要把“PQ 压力”和“候选本身的 TLB 价值不足”作为两段损失分别判断。
5. `05_timeliness_and_pollution.pdf`：只在确认预测覆盖供给后，再检查 too-early 和 pollution 等后端损失。
6. `06_spearman_correlation_map.pdf`：跨 trace 的描述性相关性，不能单独作为因果证明；p 值未进行多重比较校正。
7. `07_gap_mcf_focus.pdf`：把 GAP and mcf 各 workload group 的需求强度、有效覆盖供给、净 miss reduction 并排看。
8. `08_high_need_low_coverage_quadrant.pdf`：最直接地寻找 demand STLB MPKI 高、但 useful/miss 覆盖供给低的 trace；左图圈出、右图列出该象限评分最高的 trace。
9. `09_pq_drop_rate_workload_benchmark_all.pdf`：比较全部 vBerti PQ drop 与跨页 PQ drop，依次给出 workload、benchmark(dataset) 和 `amean_all`。
10. `10_pq_drop_rate_benchmark_all.pdf`：只保留 benchmark(dataset) 和 `amean_all`。PQ drop rate 是比例型诊断指标，所有层级均采用内部 trace 等权 amean，不使用 gmean。
11. `11_stlb_cross_page_accuracy.pdf`：同一页给出全部 workload+suite+All，以及仅 suite+All 的 STLB accuracy。
12. `12_stlb_cross_page_coverage.pdf`：同一页给出两个范围的 STLB coverage。
13. `13_stlb_cross_page_too_early.pdf`：同一页四个面板，分别给出两个范围的 `too_early/useless` 和 too-early 绝对计数 amean。
14. `14_stlb_cross_page_too_late.pdf`：同一页四个面板，分别给出两个范围的 `late/useful` 和 late 绝对计数 amean；useful 已包含 late。
15. `15_stlb_cross_page_pollution.pdf`：同一页四个面板，分别给出两个范围的 `STLB cross-page pollution_evict / STLB cross-page fill` 和 pollution-candidate 绝对计数 amean。
16. `16_vberti_end_to_end_accuracy.pdf`：同一页给出全部 workload+suite+All，以及仅 suite+All 的 vBerti data-prefetch 端到端准确率；由 useful/issued 原始计数重算，零分母保留 NaN。
17. `17_dtlb_cross_page_too_late.pdf`：与 14 的版式和 DPC4 trace 平权方式相同，但使用 DTLB 本级 `late/useful` 和 DTLB late 绝对计数。对同 VPN 的 demand 在跨页翻译返回前到达时，它通常先合并到 DTLB MSHR，因此该口径比 STLB-local late 更能反映真实 demand 观察到的翻译不及时。

## 关键口径

- `discard_pgc` 保留同页 vBerti data prefetch，但丢弃跨页 candidate；`translation_only` 让跨页 candidate 经过 L1D PQ 和 DTLB/STLB/PTW，翻译完成后在 data-cache tag lookup 之前主动删除。
- `cross_requested` 是 vBerti 产生的跨页 cache-prefetch 请求，不等于 TLB prefetch，也不等于可覆盖的 STLB miss。
- `trigger_page_walk_pct_of_requested = STLB cross-page prefetch miss / cross_requested`，表示候选在 STLB miss 并进一步触发 PTW/page walk 的比例。
- `tlb_cross_useful` 使用 `Core_N_TLB_cross_page_prefetch_useful`，在 DTLB+STLB 整体范围内去重；它包含 DTLB useful，不能只用 STLB useful 替代，否则会漏掉后续 demand 直接在 DTLB 命中、因而不再访问 STLB 的覆盖。
- `DTLB late/useful` 使用 `Core_N_DTLB_cross_page_prefetch_late / Core_N_DTLB_cross_page_prefetch_useful`。STLB-local late 在当前层次中可能被上游 DTLB MSHR merge 遮蔽，因此图 17 专门补充 demand 首先观察到的 DTLB timelyness。
- 源码打印的 `TLB_cross_page_prefetch_accuracy = useful / issued`；`coverage = useful / (useful + translation-only system demand miss)`。
- 所有 demand miss 和 demand MPKI 都只使用 `Core_0_STLB_cause_Demand_Data_miss`，明确排除 instruction demand。
- `useful_vs_discard_miss_pct = TLB-system useful / discard data-demand STLB miss`；`demand_miss_reduction_pct` 也只比较 data-demand miss。
- `combined_fill_productivity_pct` 的分母是 DTLB+STLB fill 之和，可能跨层重复计入同一预测，只作为 combined-fill 诊断量，不视为标准 accuracy。
- `combined_local_pollution_candidates_per_fill_pct` 汇总 DTLB 和 STLB 两级本地 pollution candidate，未做系统级去重，也不等于已证明造成性能损失的次数。
- 主汇总采用 trace 等权：每条 trace 先计算比例，再报告 amean，并提供 median/P25/P75 和有效样本数 `n`。IPC speedup 使用 per-trace speedup 的 geomean。
- `_weighted` 列是“计数先求和、再做比值”的 request-weighted 补充结果，不作为主结论。

## 当前数据给出的总体读数

- 跨页候选到 STLB miss/PTW 的等权 amean：**1.61288%**。
- 跨页候选到去重 TLB-system useful 的保留率：**0.692779%**。
- 已通过 PQ 的候选到 STLB miss/PTW 和 TLB-system useful 的等权 amean：**2.85348% / 1.45605%**。PQ 是显著损失，但不能单独解释剩余候选的低有效覆盖。
- useful/discard data-demand miss：amean **9.65868%**，median **0.428848%**。
- data-demand STLB miss reduction：amean **11.0441%**，median **0.509162%**。
- 规模加权补充：PTW/request、useful/request、useful/discard miss、净 miss reduction 分别为 **0.234741% / 0.159272% / 1.26515% / 1.49429%**。
- 净 miss reduction 不要求与日志直接记录的 STLB useful 数严格相等：TLB replacement/pollution、late、运行时序以及跨页请求占用 L1D PQ 对同页预取的间接影响都会进入配置间净差值。
- GAP and mcf workload摘要：gap:pr: useful/miss=0.184%, net=0.184%, gap:bc: useful/miss=0.379%, net=0.419%, spec06:429.mcf: useful/miss=0.419%, net=1.75%, gap:sssp: useful/miss=0.599%, net=0.58%, gap:tc: useful/miss=0.731%, net=0.67%, gap:bfs: useful/miss=7.8%, net=7.7%, gap:cc: useful/miss=18.7%, net=18.7%, spec17:605.mcf_s: useful/miss=29.8%, net=33%

与 demand miss reduction 绝对相关性较高的几个 trace-level 指标为：

- `useful_vs_discard_miss_pct`: rho=0.975, p=6.94e-118, n=179
- `cross_requested_mpki`: rho=0.787, p=6.16e-39, n=179
- `combined_fill_productivity_pct`: rho=0.647, p=5.15e-22, n=174
- `cross_pq_drop_rate_pct`: rho=0.576, p=3.11e-17, n=179

这些数字应结合图中的离群点和 `00_trace_metrics.csv` 检查，不能只用总体求和替代逐 trace 判断。

## 零分母与有效样本

分母为 0 时比例保留为 NaN，不会静默改成 0；相关性和汇总排除该指标的 NaN，并在 CSV 中记录 `n`：

- `combined_fill_productivity_pct`: 有效 n=174/179
- `too_early_among_useless_pct`: 有效 n=172/179
- `combined_local_pollution_candidates_per_fill_pct`: 有效 n=174/179

## 结论边界

这套结果直接衡量当前实现下跨页 translation-only 机制相对 discard 的净 TLB 与 IPC 效果，不包含跨页 data-cache lookup/fill/traffic。仍需注意，translation-only 请求会占用正常 L1D PQ、TLB/PTW 和可能的页表 DRAM 带宽，因此这是可实现机制的净效果，不是无资源代价的理想预测上界。

## 可复算数据

- `00_trace_metrics.csv`：每条 trace 的原始计数和派生比例。
- `00_overall_summary.csv`：当前分析范围的 trace 等权主汇总、分位数以及 request-weighted 补充结果。
- `00_workload_summary.csv`：按 workload 汇总。
- `00_dataset_summary.csv`：按数据集汇总。
- `00_spearman_correlations.csv`：相关系数、p 值和样本数。
- `00_gap_mcf_focus.csv`：GAP and mcf 各 workload group 的表格版结果。
- `00_high_need_low_coverage_rank.csv`：高 demand 需求、低 useful 覆盖的 trace 排名。
- `09_pq_drop_rate_workload_benchmark_all.csv`、`10_pq_drop_rate_benchmark_all.csv`：两张 PQ drop 分组柱状图的可复算数据。
- `11_stlb_cross_page_accuracy.csv` 至 `15_stlb_cross_page_pollution.csv`：五张 STLB 质量单页图的可复算数据，包含每个指标的有效 trace 数 `n`。
- `16_vberti_end_to_end_accuracy.csv`：vBerti 端到端 data-prefetch accuracy 的可复算数据。
- `17_dtlb_cross_page_too_late.csv`：DTLB 本级 late/useful 和 late 绝对计数的 trace 平权汇总。
- `00_missing_required_logs.csv`：缺失日志、未完成日志和必需指标缺失清单；为空表示所有纳入日志通过完整性检查。

## 复现

在本实验目录执行：

```bash
python3 script/postprocess_translation_only_evidence_chain.py
```

脚本只读取 `result/{discard_pgc,translation_only}/*.log`，并覆盖本子目录中的同名后处理文件。
