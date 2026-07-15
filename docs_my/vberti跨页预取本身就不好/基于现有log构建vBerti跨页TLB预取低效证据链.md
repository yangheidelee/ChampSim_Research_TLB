# 基于现有 Log 构建 vBerti 跨页 TLB 预取低效证据链

## 一、问题与分析边界

实验目录：

```text
/home/zcq/git_prj/ChampSim/launch_sim_characterization/
spec0617_gapligra_qmm_parsec-TLB-select-trace-compare_vberti_50_100
```

需要只依赖该目录现有的四套日志：

```text
nopref
discard_pgc
translation_only
permit_pgc
```

回答以下问题：

> 从 TLB prefetch 加速真实 data demand TLB 访问时，为什么 vBerti 的跨页预取在很多 workload，特别是 GAP、mcf 等 trace 上不能获得良好的性能提升？主要原因是否是 vBerti 生成的跨页候选与未来真实 data-demand STLB miss 流不匹配，而不是 PQ 满、预取不及时或 TLB 污染？

本分析不再增加新实验或源码指标，而是用 trace 级结果、相关性和反例排除建立证据链。

## 二、配置职责

### discard_pgc：主基线

保留同页 vBerti 数据预取，但不发出跨页 translation，提供原始 data-demand STLB miss 和 IPC。

### translation_only：主实验配置

跨页候选正常经过：

```text
L1D PQ → DTLB → STLB/PTW → translation完成
```

translation 完成后丢弃数据预取，不继续访问数据 Cache。因此：

```text
translation_only vs discard_pgc
```

是衡量跨页 TLB prefetch 实际效果的核心对比。

### permit_pgc 与 nopref：辅助配置

- `permit_pgc vs translation_only`：判断额外收益是否来自跨页数据预取；
- `discard_pgc vs nopref`：判断同页 vBerti 数据预取的影响；
- 二者不作为证明跨页 TLB prefetch 有效性的主对比。

## 三、统计口径

主结果必须是真实 data-demand STLB miss。不要使用可能被 prefetch translation 污染的：

```text
Core_0_STLB_total_MPKI
Core_0_STLB_demand_MPKI
```

使用：

```text
Core_0_STLB_cause_Demand_Data_miss
```

统一计算：

```text
data_stlb_mpki = Demand_Data_miss × 1000 / instructions
```

小写 `Core_0_STLB_demand_mpki` 可作为 data+instruction demand 的辅助口径。

记：

```text
D_miss = discard_pgc data-demand STLB miss
T_miss = translation_only data-demand STLB miss
D_ipc  = discard_pgc IPC
T_ipc  = translation_only IPC
```

主结果：

```text
saved_data_demand_miss = D_miss - T_miss
actual_data_miss_coverage = (D_miss - T_miss) / D_miss
translation_only_ipc_gain = T_ipc / D_ipc - 1
```

`actual_data_miss_coverage` 是主结果变量；日志 useful、accuracy、coverage 只用于解释。

## 四、主数据表

生成：

```text
csv_figure/prefetch_evidence_chain/00_trace_evidence_master.csv
```

每条 trace 一行，包含：

```text
dataset, workload, trace_tag, instructions
discard_data_stlb_miss, translation_only_data_stlb_miss
discard_data_stlb_mpki, translation_only_data_stlb_mpki
saved_data_demand_miss, actual_data_miss_coverage
discard_ipc, translation_only_ipc, translation_only_ipc_gain

cross_candidate_requested, cross_candidate_admitted, cross_pq_drop_rate
candidate_per_baseline_miss, admitted_per_baseline_miss

dtlb_cross_lookup, dtlb_cross_hit, dtlb_cross_miss, dtlb_cross_merge
dtlb_redundant_rate, dtlb_duplicate_rate, stlb_reach_rate
stlb_cross_lookup, stlb_cross_hit, stlb_cross_miss, stlb_cross_merge

system_useful, system_late, system_too_early, system_useless
timely_useful, late_ratio, too_early_ratio
dtlb_pollution_demand, stlb_pollution_demand

generated_targeting_yield, admitted_targeting_yield
stlb_targeting_yield, candidates_per_saved_miss
```

## 五、证明“发得多但覆盖少”的核心指标

### Generated targeting yield

```text
saved_data_demand_miss
/ Core_0_vBerti_Cross_page_prefetch_in_Requested
```

表示每生成一个跨页候选，最终消除多少真实 data-demand STLB miss。

### Admitted targeting yield

```text
saved_data_demand_miss
/ Core_0_vBerti_InPQ_Cross_page_prefetch
```

它只考察已进入 PQ 的候选，排除了已知 PQ drop。如果仍然很低，失败不能简单归因于 PQ 满。

### STLB targeting yield

```text
saved_data_demand_miss
/ Core_0_STLB_vberti_cross_page_prefetch_miss
```

它回答：vBerti 提前触发的 STLB miss/PTW 中，有多少真正替代了未来 data-demand STLB miss？

### Candidates per saved miss

```text
Core_0_vBerti_InPQ_Cross_page_prefetch
/ saved_data_demand_miss
```

即每消除一个真实 data-demand STLB miss，需要多少个跨页 translation 候选。

## 六、图表证据链

### 图1：真实 miss 覆盖结果

输出：

```text
01_actual_data_demand_miss_coverage.pdf
```

一个大页包含：

1. discard 与 translation-only data-demand STLB MPKI dumbbell 图；
2. 按 actual coverage 排序的 trace 点图；
3. `actual coverage` 对 `translation-only IPC gain` 散点图。

第三图设置：

```text
X = actual_data_miss_coverage
Y = translation_only_ipc_gain
颜色 = dataset
点大小 = discard data-demand STLB MPKI
```

它区分“没有覆盖 miss”和“覆盖了 miss 但 miss 不关键”。

### 图2：候选数量与 miss 覆盖

输出：

```text
02_candidate_volume_vs_miss_coverage.pdf
```

包含：

```text
generated candidates / baseline miss  vs actual coverage
admitted candidates / baseline miss  vs actual coverage
STLB cross-page prefetch miss         vs saved demand miss
candidates per saved miss trace点图
```

STLB 散点加入 `y=x`、`y=0.1x`、`y=0.01x`。大量点落在 `y=0.01x` 以下，表示 vBerti 触发了很多 STLB miss/PTW，但很少替代真实 demand miss。

### 图3：跨页 translation 漏斗

输出：

```text
03_cross_page_translation_funnel.pdf
```

按每100个 generated candidate 归一化：

```text
Generated
→ PQ admitted
→ DTLB lookup
→ DTLB hit（冗余）
→ DTLB MSHR merge（在途重复）
→ STLB lookup
→ STLB hit
→ STLB miss/PTW
→ timely useful
→ actually saved demand miss
```

派生：

```text
dtlb_redundant_rate = DTLB cross hit / DTLB cross lookup
dtlb_duplicate_rate = DTLB cross merge / DTLB cross lookup
stlb_reach_rate = (DTLB cross miss - DTLB cross merge) / DTLB cross lookup
```

使用成功与失败 trace 的 small multiples，不画一个包含全部 trace 的巨大 Sankey。

### 图4：排除 PQ 是普遍主因

输出：

```text
04_pq_drop_exclusion.pdf
```

主图：

```text
X = cross-page PQ drop rate
Y = actual data-demand miss coverage
```

重点标注：

- 高 drop + 高 coverage：高 drop 不必然导致失败；
- 低 drop + 低 coverage：低覆盖不能普遍归因于 PQ 满。

再单独画 PQ drop 最低25%的 trace，并计算：

```text
rho(PQ drop, actual coverage)
rho(PQ admission rate, actual coverage)
rho(admitted targeting yield, actual coverage)
```

### 图5：排除及时性与污染

输出：

```text
05_timing_pollution_exclusion.pdf
```

计算：

```text
timely_useful = system_useful - system_late
late_ratio = system_late / system_useful
too_early_ratio = system_too_early / system_useless
```

画 `late_ratio vs actual coverage` 和 `too_early_ratio vs actual coverage`。大量低 coverage trace 同时 late/too-early 很低，说明及时性不是统一解释。

污染使用：

```text
Core_0_DTLB_cross_page_prefetch_pollution_demand
Core_0_STLB_cross_page_prefetch_pollution_demand
```

不要只用 `pollution_evict`。画 pollution demand/baseline miss 对 actual coverage；低污染、低覆盖 trace 是排除污染主因的反例。

### 图6：失败原因热力图

输出：

```text
06_failure_cause_trace_map.pdf
```

每条 trace 一行，列为：

```text
actual coverage
admitted targeting yield
STLB targeting yield
PQ drop
DTLB redundant/duplicate rate
late/too-early ratio
pollution per baseline miss
IPC gain
```

按 actual coverage 排序。希望呈现的核心模式：

```text
coverage低、targeting yield低，
但PQ drop、late和pollution不一定高。
```

### 图7：GAP与mcf trace级诊断

输出：

```text
07_gap_mcf_trace_diagnosis.pdf
```

GAP 按 `bc、bfs、cc、pr、sssp、tc` 分面；mcf 保留每条 trace，不能只画平均值。并列显示 coverage、targeting yield、PQ drop、late、pollution 和 IPC gain。

### 图8：相关性矩阵

输出：

```text
08_spearman_correlations.csv
08_spearman_correlations.pdf
```

因变量：

```text
actual_data_miss_coverage
translation_only_ipc_gain
```

自变量包括 candidate intensity、admission rate、三种 targeting yield、PQ drop、DTLB 冗余/重复、late、too-early、pollution 和 baseline demand MPKI。

希望检验：actual coverage 是否与 targeting yield 强相关，而与 PQ drop 的相关性较弱或不稳定。

## 七、代表性 trace

成功正对照：

```text
433.milc-274B
433.milc-127B
429.mcf-22B
605.mcf_s-782B
```

失败目标：

```text
429.mcf-184B
bc.urand-3004B
sssp.urand-3381B
其他低coverage GAP trace
```

mcf 必须逐 trace 展示，因为不同阶段可能呈现完全不同的效果。

## 八、milc 正对照

已完成的 `433.milc-274B` 给出：

```text
Discard demand STLB MPKI          1.20895
Translation-only demand STLB MPKI 0.00306
Demand MPKI reduction             约99.75%
Discard IPC                       1.082
Translation-only IPC              1.178
IPC提升                            约8.87%
PQ drop rate                      81.11%
End-to-end accuracy               2.37%
End-to-end coverage               99.74%
```

它说明高 PQ drop、低 accuracy 都不必然导致低 coverage。最终必须看真实 demand miss reduction 和 targeting yield，不能仅凭 accuracy/PQ drop 下结论。

## 九、最终论证顺序与结论

```text
1. translation-only vs discard证明真实data-demand miss覆盖普遍偏低
2. 候选数量图证明失败不是因为没有生成跨页候选
3. admitted targeting yield证明进入PQ后的候选仍然低效
4. STLB targeting yield证明大量STLB miss/PTW很少替代未来demand miss
5. 高drop成功、低drop失败的反例排除PQ是普遍主因
6. 低late/低pollution失败trace排除及时性和污染是统一解释
7. GAP/mcf trace级图证明低targeting yield是更一致的失败特征
8. IPC图区分没有覆盖miss与miss已覆盖但不关键
```

建议最终表述：

> 在成功 trace 上，少量有效跨页候选虽然淹没在大量冗余请求中，但仍覆盖了主要 demand STLB miss。相比之下，在大量失败 GAP、mcf trace 上，即使 vBerti 生成并向 DTLB/STLB 发出了大量跨页 translation，实际消除的 data-demand STLB miss 仍然很少，表现为极低的 admitted/STLB targeting yield。低覆盖在低 PQ drop、低 late 和低 pollution 的 trace 中仍然存在，因此，与 PQ、及时性或污染相比，vBerti 跨页候选流与真实 data-demand STLB miss 流匹配度不足，是更一致的主要解释。

## 十、结论边界与执行前提

现有日志能支持“实际生成并被接收的候选流 targeting yield 很低，PQ/及时性/污染不能普遍解释低覆盖”，但不能证明每一个被 PQ 丢掉的候选都无效。因此正式写作应使用“主要证据支持”“更一致的解释”，不要声称严格证明所有 dropped candidate 都无效。

最终出图前必须等待全部 translation-only 日志完成。曾检查到的中间状态为：

```text
nopref:           179/179
permit_pgc:       179/179
discard_pgc:      179/179
translation_only:   5/179 complete，另有部分正在运行
```

后处理必须检查完整性，不能把 partial log 当成完整结果。
