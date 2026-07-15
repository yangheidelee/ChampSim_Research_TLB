# Work Record

## 1core-spec0617_gapligra-TLB-select-trace-compare_jsonnew 0618

本次工作主要围绕脚本目录：

```text
/home/zcq/git_prj/ChampSim/launch_sim/1core-spec0617_gapligra-TLB-select-trace-compare_jsonnew
```

该目录是基于原有 `1core-spec0617_gapligra-TLB-select-trace-compare` 流程整理出的新实验脚本版本。当前版本使用新的 JSON 配置文件进行 ChampSim build，目标是采用更合理的 CPU 微架构配置重新完成四类 benchmark 的 TLB 相关实验。

覆盖的 benchmark 类型包括：

- SPEC06
- SPEC17
- GAP
- Ligra

## 当前进度

该 jsonnew 脚本对应的四类 benchmark 已经完成运行，结果使用新的 JSON 配置生成的 ChampSim binary 得到。这个配置相比之前版本更贴近当前实验希望采用的 CPU 微架构设定，因此后续关于 STLB miss、MPKI、miss rate、prefetch 对比等数据分析，应优先参考该 jsonnew 实验结果。


## 脚本主要完成的工作

`run_tlb_select_compare.sh` 是该目录的主控脚本，主要流程包括：

1. 使用目录内的 JSON 配置构建 ChampSim binary。
2. 分别运行 `nopref` 和 `pref` 两类配置。
3. 遍历 SPEC06、SPEC17、GAP、Ligra 的 trace。
4. 将仿真输出写入统一 result 目录。
5. 根据 `nopref` 结果中的 STLB MPKI 阈值筛选 trace。
6. 对筛选后的 trace 做 select trace 数据处理和画图。
7. 同时保留 full trace 处理流程，用于不经过筛选的整体观察。
8. 对 IPC、STLB miss rate、STLB MPKI、STLB miss cause share 等指标进行汇总和对比。

其中，IPC 类指标按 trace-level IPC 或 speedup 做几何平均；MPKI、miss rate、miss cause share 等 rate 类指标保留 numerator/denominator，并在聚合时使用 sum/sum 的方式计算。

## 关键路径

脚本目录：

```text
/home/zcq/git_prj/ChampSim/launch_sim/1core-spec0617_gapligra-TLB-select-trace-compare_jsonnew
```

仿真结果目录：

```text
/home/zcq/git_prj/ChampSim/results/1core-spec0617_gapligra-TLB-select-trace-compare_jsonnew
```

图表和 CSV 输出目录：

```text
/home/zcq/git_prj/ChampSim/csv_figure/1core-spec0617_gapligra-TLB-select-trace-compare_jsonnew
```

主要配置子目录：

```text
/home/zcq/git_prj/ChampSim/launch_sim/1core-spec0617_gapligra-TLB-select-trace-compare_jsonnew/nopref-workload-sweep
/home/zcq/git_prj/ChampSim/launch_sim/1core-spec0617_gapligra-TLB-select-trace-compare_jsonnew/pref-workload-sweep
```

数据后处理目录：

```text
/home/zcq/git_prj/ChampSim/launch_sim/1core-spec0617_gapligra-TLB-select-trace-compare_jsonnew/data_process_for_compare
```

## 常用命令

完整运行该实验流程时，可以使用：

```bash
N_WARM=20 N_SIM=50 ./launch_sim/1core-spec0617_gapligra-TLB-select-trace-compare_jsonnew/run_tlb_select_compare.sh all 10
```

其中 `N_WARM=20` 表示 warmup 20M instructions，`N_SIM=50` 表示 ROI simulation 50M instructions，最后的 `10` 表示最多 10 个 trace 并行运行。




# 0708

## Too-early / Pollution 统计与测试

在当前 ChampSim 中补充了 prefetch 相关的 too-early 和 pollution 观测方式，用于辅助判断 vBerti 以及 cross-page translation prefetch 的负面影响。

主要思路是：当 prefetch fill 进 cache/TLB 后，如果它在真正被 demand 使用前已经被替换出去，则可以近似认为这个 prefetch 过早；当 prefetch fill 踢出了一个 entry，而该 entry 后续又被 demand 访问到，则可以近似认为发生了 pollution。该逻辑只用于统计观察，不改变 ChampSim 原有 cache/TLB 行为。

新增和使用的指标主要包括：

- cache prefetch 的 `prefetch_too_early`、`prefetch_too_early_among_fill`、`prefetch_too_early_among_useless`。
- cache prefetch 的 `prefetch_pollution_evict`、`prefetch_pollution_demand`、`prefetch_pollution_among_prefetch_fill`。
- DTLB/STLB cross-page prefetch 的 `cross_page_prefetch_too_early`、`cross_page_prefetch_too_early_among_useless`。
- DTLB/STLB cross-page prefetch 的 `cross_page_prefetch_pollution_evict`、`cross_page_prefetch_pollution_demand`、`cross_page_prefetch_pollution_among_prefetch_fill`。

这些指标主要服务于后续判断：cross-page prefetch 是否因为太早、污染 TLB/cache、或者占用 PTW/TLB 资源而抵消了潜在收益。

## CP-PB 模式

添加了一个 STLB cross-page prefetch buffer 实验模式，运行时通过参数开启：

```bash
--enable-stlb-cp-pb
```

该模式默认关闭；不加该参数时，ChampSim 行为保持原始逻辑。

开启后，L1D cross-page prefetch 在 STLB 层完成 translation fill 时，不再按普通 STLB prefetch fill 直接进入 STLB，而是重定向到一个 side buffer，也就是 CP-PB。后续 demand data 访问如果在 STLB miss 后命中 CP-PB，就可以用这个 translation 信息补回 STLB，从而观察“cross-page prefetch translation 是否能帮助 demand STLB miss”的效果。

该模式主要用于区分 cross-page prefetch 的 translation-side effect 和 data-prefetch-side effect：它让我们可以观察被 cross-page prefetch 提前带出的 translation 是否对 demand STLB miss 有帮助，同时避免直接把所有 prefetch translation 都当作普通 STLB fill 来处理。

相关结果中重点关注：

- `Core_0_CP_PB_insert`
- `Core_0_CP_PB_demand_hit`

## Ordered PQ-full TLB Rescue

新增了一个 `--ordered-pqfull-tlb-rescue` 实验模式，用来观察：vBerti 的 L1D cross-page prefetch 如果因为 L1D internal PQ full 原本会被 drop，是否可以只保留 translation-side effect，按原始 prefetch 顺序补发 translation-only request 到 TLB/STLB/PTW。

该模式默认关闭；不加参数时不改变 ChampSim 原始行为。开启后，只有因 internal PQ full 被 drop 的 L1D cross-page prefetch 会进入 sideband rescue queue，不进入 L1D PQ，不做 L1D tag lookup，也不会产生 data cache fill。

新增统计包括正常进入 PQ 的 same-page/cross-page prefetch 数量，以及 PQ-full drop、rescue enqueue、rescue issue、rescue translated 等计数。详细说明见：

```text
docs_my/ordered_pqfull_tlb_rescue.md
```
- `Core_0_CP_PB_coverage`
- `Core_0_STLB_raw_demand_mpki`
- `Core_0_STLB_PB_demand_mpki`
- `Core_0_CP_PB_demand_hit_mpki`

其中 `STLB_raw_demand_mpki` 表示不扣除 CP-PB hit 时的原始 demand STLB miss 情况，`STLB_PB_demand_mpki` 表示扣除 CP-PB hit 后剩余的 demand STLB miss 情况。
