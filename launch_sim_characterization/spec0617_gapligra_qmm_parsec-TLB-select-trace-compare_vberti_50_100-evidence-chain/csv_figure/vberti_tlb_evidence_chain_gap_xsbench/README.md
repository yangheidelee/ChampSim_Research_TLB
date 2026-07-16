# vBerti 跨页 TLB 预取证据链（GAP + XSBench）

本目录的分析范围为 **GAP + XSBench**，并使用副本中已经完成的 `nopref`、`discard_pgc` 和 `permit_pgc` 日志进行后处理，不重新运行模拟器，也不读取或依赖 translation-only 日志。共纳入 **99** 条三配置齐全的 trace。

## 要回答的问题

目标不是简单证明 `permit_pgc` 的 IPC 不高，而是检查下面这个更具体的假设：

> vBerti 可以产生大量跨页 cache-prefetch 候选，但这些候选很少真正需要新的 STLB translation，更少成为后来真实 data demand 使用的 translation，因此它先天能够覆盖的 demand STLB miss 很有限。

## 推荐阅读顺序

如果希望一次顺序浏览全部图，直接打开 `00_all_evidence_chain_figures.pdf`；它按下面的 01–16 顺序合并。

1. `01_demand_opportunity_and_outcome.pdf`：先确认 discard 下的 demand STLB MPKI，以及 permit 是否真的减少 demand miss。右图 IPC 仅作混合系统结果，不作纯 TLB 因果结论。
2. `02_cross_page_flow_funnel.pdf`：从跨页 request 一直追到 STLB useful。全体 trace 按计数求和后，PQ drop 为 **81.38%**；只有 **0.2993%** 的跨页请求触发 STLB translation，最终只有 **0.01855%** 成为 STLB useful。即使只看已经通过 PQ 的候选，也只有 **1.607%** 触发 translation、**0.09966%** 最终 useful。
3. `03_prediction_quality_and_coverage.pdf`：验证“发得多”是否等于“覆盖多”。STLB useful 仅相当于 discard demand miss 的 **0.04914%**，而 permit 相对 discard 的净 demand miss reduction 为 **0.6387%**。
4. `04_pq_bottleneck_test.pdf`：检查 PQ drop 与覆盖/净结果的关系。总体 PQ 损失显著，但通过 PQ 后到 translation/useful 的条件保留率仍很低，因此需要把“PQ 压力”和“候选本身的 TLB 价值不足”作为两段损失分别判断。
5. `05_timeliness_and_pollution.pdf`：只在确认预测覆盖供给后，再检查 too-early 和 pollution 等后端损失。
6. `06_spearman_correlation_map.pdf`：跨 trace 的描述性相关性，不能单独作为因果证明。
7. `07_gap_xsbench_focus.pdf`：把 GAP + XSBench 各 workload group 的需求强度、有效覆盖供给、净 miss reduction 并排看。
8. `08_high_need_low_coverage_quadrant.pdf`：最直接地寻找 demand STLB MPKI 高、但 useful/miss 覆盖供给低的 trace；左图圈出、右图列出该象限评分最高的 trace。
9. `09_pq_drop_rate_workload_benchmark_all.pdf`：比较全部 vBerti PQ drop 与跨页 PQ drop，依次给出 workload、benchmark(dataset) 和 `amean_all`。
10. `10_pq_drop_rate_benchmark_all.pdf`：只保留 benchmark(dataset) 和 `amean_all`。PQ drop rate 是比例型诊断指标，所有层级均采用内部 trace 等权 amean，不使用 gmean。
11. `11_stlb_cross_page_accuracy.pdf`：同一页给出全部 workload+suite+All，以及仅 suite+All 的 STLB accuracy。
12. `12_stlb_cross_page_coverage.pdf`：同一页给出两个范围的 STLB coverage。
13. `13_stlb_cross_page_too_early.pdf`：同一页四个面板，分别给出两个范围的 `too_early/useless` 和 too-early 绝对计数 amean。
14. `14_stlb_cross_page_too_late.pdf`：同一页四个面板，分别给出两个范围的 `late/useful` 和 late 绝对计数 amean；useful 已包含 late。
15. `15_stlb_cross_page_pollution.pdf`：同一页四个面板，分别给出两个范围的 `STLB cross-page pollution_evict / STLB cross-page fill` 和 pollution-candidate 绝对计数 amean。
16. `16_vberti_end_to_end_accuracy.pdf`：同一页给出全部 workload+suite+All，以及仅 suite+All 的 vBerti data-prefetch 端到端准确率；由 useful/issued 原始计数重算，零分母保留 NaN。

## 关键口径

- `discard_pgc` 用作 TLB 行为比较基线：保留同页 vBerti 行为，丢弃跨页 PGC；`permit_pgc` 放行跨页 PGC。
- `cross_requested` 是 vBerti 产生的跨页 cache-prefetch 请求，不等于 TLB prefetch，也不等于可覆盖的 STLB miss。
- `trigger_translation_pct_of_requested = STLB cross-page prefetch miss / cross_requested`，衡量候选中真正需要新 translation 的比例。
- `stlb_cross_useful` 在 STLB 预取项被后续 demand 命中时计数。
- 源码打印的 `STLB_cross_page_prefetch_accuracy = useful / issued`；`coverage = useful / (useful + permit demand miss)`。
- 本分析另外给出 `useful_vs_discard_miss_pct = useful / discard demand miss`，用于表达相对于基线 miss 需求的有效覆盖供给。
- `demand_miss_reduction_pct = (discard demand miss - permit demand miss) / discard demand miss`，它是净结果，允许为负。
- `pollution_per_fill_pct` 的分子是被 STLB 跨页预取填充驱逐的有效项（pollution candidate），不是已经证明造成性能损失的精确次数。
- 所有带 `weighted` 的 workload/dataset 比例均采用“先求和计数、再做比值”，避免小 trace 与大 trace 被等权。

## 当前数据给出的总体读数

- 跨页候选到 STLB translation 的保留率：**0.299252%**。
- 跨页候选到 STLB useful 的保留率：**0.0185543%**。
- 已通过 PQ 的候选到 STLB translation/useful：**1.60733% / 0.0996581%**。因此 PQ 是显著损失，但不能单独解释剩余候选的低有效覆盖。
- useful 相对于 discard demand miss：**0.049143%**。
- permit 相对 discard 的净 demand STLB miss reduction：**0.638704%**。
- 净 miss reduction 大于日志直接记录的 STLB useful 覆盖供给，因此不能把 permit/discard 的全部 miss 差异都解释成 translation prefetch 的直接覆盖；跨页 data-cache prefetch 对访问流和时序的耦合变化也在这个差值里。
- GAP + XSBench workload摘要：xsbench:XL64nuclide: useful/miss=0.00354%, net=0.0255%, xsbench:XL100nuclide: useful/miss=0.00384%, net=0.0251%, gap:sssp: useful/miss=0.0124%, net=0.268%, xsbench:XXL100nuclide: useful/miss=0.015%, net=0.0456%, gap:tc: useful/miss=0.0168%, net=0.359%, gap:pr: useful/miss=0.0266%, net=0.154%, xsbench:XXL64nuclide: useful/miss=0.0322%, net=0.0762%, gap:bc: useful/miss=0.0462%, net=0.395%, xsbench:XXL64hash: useful/miss=0.127%, net=0.305%, gap:cc: useful/miss=0.133%, net=3.75%, xsbench:XXL100hash: useful/miss=0.141%, net=0.367%, xsbench:XL64hash: useful/miss=0.228%, net=0.524%, gap:bfs: useful/miss=0.23%, net=3.08%, xsbench:XXL100unionized: useful/miss=0.255%, net=0.558%, xsbench:XXL64unionized: useful/miss=0.258%, net=0.556%, xsbench:XL100hash: useful/miss=0.288%, net=0.593%, xsbench:XL100unionized: useful/miss=2.48%, net=4.7%, xsbench:XL64unionized: useful/miss=2.49%, net=4.73%

与 demand miss reduction 绝对相关性较高的几个 trace-level 指标为：

- `cross_requested_mpki`: rho=0.797, p=5.45e-23, n=99
- `useful_vs_discard_miss_pct`: rho=0.736, p=3.89e-18, n=99
- `cross_pq_drop_rate_pct`: rho=0.666, p=5.67e-14, n=99
- `discard_stlb_demand_mpki`: rho=-0.662, p=8.23e-14, n=99

这些数字应结合图中的离群点和 `00_trace_metrics.csv` 检查，不能只用总体求和替代逐 trace 判断。

## 结论边界

这套结果可以支持或反驳“vBerti 跨页候选对真实 demand STLB miss 的有效覆盖供给不足”，也能判断 PQ/timeliness/pollution 是否与结果一致。它不能把 `permit_pgc` 与 `discard_pgc` 的 IPC 差异完全归因于 translation，因为 permit 同时放行了跨页 data-cache prefetch。translation-only 完整后，可把纯 translation IPC/MPKI 作为额外因果对照加入，但不影响当前对 TLB 内部事件链的统计。

## 可复算数据

- `00_trace_metrics.csv`：每条 trace 的原始计数和派生比例。
- `00_workload_summary.csv`：按 workload 汇总。
- `00_dataset_summary.csv`：按数据集汇总。
- `00_spearman_correlations.csv`：相关系数、p 值和样本数。
- `00_gap_xsbench_focus.csv`：GAP + XSBench 各 workload group 的表格版结果。
- `00_high_need_low_coverage_rank.csv`：高 demand 需求、低 useful 覆盖的 trace 排名。
- `09_pq_drop_rate_workload_benchmark_all.csv`、`10_pq_drop_rate_benchmark_all.csv`：两张 PQ drop 分组柱状图的可复算数据。
- `11_stlb_cross_page_accuracy.csv` 至 `15_stlb_cross_page_pollution.csv`：五张 STLB 质量单页图的可复算数据，包含每个指标的有效 trace 数 `n`。
- `16_vberti_end_to_end_accuracy.csv`：vBerti 端到端 data-prefetch accuracy 的可复算数据。
- `00_missing_required_logs.csv`：三配置缺失清单；为空表示所有纳入配置齐全。

## 复现

在本副本目录执行：

```bash
python3 script/postprocess_evidence_chain.py --datasets gap,xsbench --output-subdir vberti_tlb_evidence_chain_gap_xsbench
```

脚本只读取 `result/{nopref,discard_pgc,permit_pgc}/*.log`，并覆盖本子目录中的同名后处理文件。
