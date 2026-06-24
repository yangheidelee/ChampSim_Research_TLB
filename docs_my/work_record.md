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
