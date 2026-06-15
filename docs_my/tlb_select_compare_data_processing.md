# 1core-spec17_gap-TLB-select-trace-compare 数据后处理方法说明

本文记录当前脚本
`/home/zcq/git_prj/ChampSim/launch_sim/1core-spec17_gap-TLB-select-trace-compare`
的数据后处理方法。核心脚本是：

- `run_tlb_select_compare.sh`
- `data_process_for_compare/tlb_select_tools.py`
- `data_process_for_compare/compare_pref_vs_nopref_ipc.sh`

当前实验比较两个配置：

- `nopref-workload-sweep`
- `pref-workload-sweep`

后处理输出有两套 flow：

```text
/home/zcq/git_prj/ChampSim/csv_figure/1core-spec17_gap-TLB-select-trace-compare/select_trace
/home/zcq/git_prj/ChampSim/csv_figure/1core-spec17_gap-TLB-select-trace-compare/full_trace
```

其中 `select_trace` 会先按照 nopref 的 STLB MPKI 筛选 trace，`full_trace` 不做 trace 筛选，直接处理 result 目录下所有可解析的 trace log。

## 1. Trace 筛选方法

trace 筛选只使用 `nopref-workload-sweep` 的结果作为基准。

脚本首先读取：

```text
/home/zcq/git_prj/ChampSim/results/1core-spec17_gap-TLB-select-trace-compare/nopref-workload-sweep
```

中的每个 `.log` 文件，从 `[ROI Statistics]` 后面的统计区提取：

```text
Core_0_STLB_total_MPKI
```

然后使用阈值：

```text
STLB MPKI > SELECT_THRESHOLD
```

当前默认：

```text
SELECT_THRESHOLD=1.0
```

也就是只保留 `nopref` 配置下：

```text
Core_0_STLB_total_MPKI > 1.0
```

的 trace。

筛选结果会写入：

```text
csv_figure/1core-spec17_gap-TLB-select-trace-compare/select_trace/data_process_for_compare/stlb_mpki_gt_1.0_selected_traces.json
```

后续 `nopref` 和 `pref` 两个配置都会使用同一份 selected trace list。这样可以保证两个配置比较时 trace 集合完全一致。

如果运行 `full_trace` 后处理，则跳过本节筛选逻辑。脚本通过：

```text
SELECT_TRACE_JSON=ALL
```

告诉 `single-config` 阶段不要过滤 trace。

## 2. Trace 归属规则

脚本会根据 trace 文件名推断 dataset 和 workload。

对于 SPEC17：

```text
602.gcc_s-734B
```

会被归到：

```text
dataset  = spec17
workload = 602.gcc_s
```

也就是同一个 benchmark 的多个 trace 会组成同一个 workload。

对于 GAP：

```text
gap.pr.twitter-10B
```

会被归到：

```text
dataset  = gap
workload = gap.pr.twitter-10B
```

也就是 GAP 中每个 trace 直接作为一个独立 workload。

## 3. Trace-level 原始数据

每个配置都会先生成 trace-level CSV：

```text
nopref-workload-sweep/nopref_trace_level.csv
pref-workload-sweep/pref_trace_level.csv
```

trace-level CSV 中保留每条 trace 的原始 numerator / denominator，包括：

```text
instructions
cycles
ipc
stlb_access
stlb_hit
stlb_miss
stlb_mpki
stlb_miss_rate
demand_data_miss
demand_instruction_miss
l1d_prefetch_miss
l1i_prefetch_miss
other_miss
```

后续 workload-level 和 summary-level 的 rate 类指标都从这些 trace-level 原始计数重新聚合，不直接对 trace-level 的 rate 做简单平均。

## 4. IPC 的聚合方法

### 4.1 Trace-level IPC

单条 trace 的 IPC 来自 result log：

```text
Core_0_IPC
```

如果 log 中没有有效 IPC，则脚本按下面公式补算：

```text
trace_ipc = instructions / cycles
```

### 4.2 Workload-level IPC

对于一个 workload 内部的多个 trace，使用 trace 平权几何平均：

```text
workload_ipc = gmean(trace_ipc_i)
```

展开为：

```text
workload_ipc = exp(sum(log(trace_ipc_i)) / N)
```

其中 `N` 是这个 workload 被筛选保留下来的 trace 数量。

对于 GAP，因为每个 trace 自己就是一个 workload，所以：

```text
workload_ipc = trace_ipc
```

### 4.3 Dataset summary IPC

当前脚本不再先计算每个 workload 的 IPC，再对 workload IPC 做二次 gmean。

现在使用 DPC-style trace-level 聚合方法：

```text
summary_ipc = gmean(all_selected_trace_ipc_i)
```

也就是说：

```text
gmean_spec17 = gmean(所有被选中的 SPEC17 trace IPC)
gmean_gap    = gmean(所有被选中的 GAP trace IPC)
```

这里每条被选中的 trace 权重相同。

## 5. IPC speedup 的计算方法

compare 阶段读取两个配置已经聚合好的 workload CSV：

```text
nopref-workload-sweep/nopref_workload_agg.csv
pref-workload-sweep/pref_workload_agg.csv
```

### 5.1 Workload-level IPC speedup

对于每个 workload：

```text
ipc_speedup = pref_workload_ipc / nopref_workload_ipc
```

百分比形式：

```text
ipc_speedup_pct = (ipc_speedup - 1) * 100
```

前提是 `pref` 和 `nopref` 使用完全相同的 selected trace 集合。当前脚本满足这个前提，因为二者都使用 nopref 筛选出来的同一个 selected trace json。

### 5.2 Summary-level IPC speedup

对于 summary 行：

```text
gmean_spec17 IPC speedup = pref_gmean_spec17_ipc / nopref_gmean_spec17_ipc
gmean_gap IPC speedup    = pref_gmean_gap_ipc / nopref_gmean_gap_ipc
```

注意：这里的 `pref_gmean_spec17_ipc` 和 `nopref_gmean_spec17_ipc` 本身已经是各自配置下从 selected trace IPC 直接做 gmean 得到的 summary IPC。

因此当前 summary speedup 的实际含义是：

```text
两个配置的 trace-level gmean IPC summary 之比
```

## 6. MPKI 和 miss rate 的聚合方法

MPKI 和 miss rate 都属于 rate 类指标。当前脚本遵循：

```text
先保留 trace-level 原始 numerator / denominator
再在 workload-level 或 summary-level 使用 sum numerator / sum denominator
```

不直接对 trace-level MPKI 或 miss rate 做算术平均。

### 6.1 Trace-level STLB MPKI

单条 trace：

```text
trace_stlb_mpki = stlb_miss * 1000 / instructions
```

### 6.2 Workload-level STLB MPKI

一个 workload 内部多个 trace：

```text
workload_stlb_mpki = sum(stlb_miss_i) * 1000 / sum(instructions_i)
```

### 6.3 Summary-level STLB MPKI

对于 dataset summary：

```text
gmean_spec17_stlb_mpki = sum(SPEC17 selected trace stlb_miss_i) * 1000 / sum(SPEC17 selected trace instructions_i)
gmean_gap_stlb_mpki    = sum(GAP selected trace stlb_miss_i) * 1000 / sum(GAP selected trace instructions_i)
```

这里 summary 行名字仍然叫 `gmean_spec17` / `gmean_gap`，是为了和 IPC 图表标签保持一致；但 MPKI 本身不是 gmean，而是 `sum miss / sum instructions`。

注意：CSV 中 summary 行名为了兼容仍保留为 `gmean_spec17` / `gmean_gap`。在 MPKI、miss rate、miss cause share 这类 rate 图中，绘图标签会显示为 `amean_spec17` / `amean_gap`，避免和 IPC 的 gmean 语义混淆。

### 6.4 Trace-level STLB miss rate

单条 trace：

```text
trace_stlb_miss_rate = stlb_miss / stlb_access
```

### 6.5 Workload-level STLB miss rate

一个 workload 内部多个 trace：

```text
workload_stlb_miss_rate = sum(stlb_miss_i) / sum(stlb_access_i)
```

### 6.6 Summary-level STLB miss rate

对于 dataset summary：

```text
gmean_spec17_stlb_miss_rate = sum(SPEC17 selected trace stlb_miss_i) / sum(SPEC17 selected trace stlb_access_i)
gmean_gap_stlb_miss_rate    = sum(GAP selected trace stlb_miss_i) / sum(GAP selected trace stlb_access_i)
```

同样，summary 行名字虽然叫 `gmean_spec17` / `gmean_gap`，但 miss rate 本身不是 gmean，而是 `sum miss / sum access`。

## 7. MPKI / miss rate 归一化对比方法

归一化对比必须先在每个配置内部完成 workload-level 或 summary-level 聚合，然后再做配置间比值。

也就是说，不能先对每条 trace 算：

```text
pref_trace_metric / nopref_trace_metric
```

再对这些 ratio 做平均。

当前脚本实际输出了 STLB total miss rate 的归一化对比：

```text
stlb_miss_rate_norm = pref_stlb_miss_rate / nopref_stlb_miss_rate
```

图文件名为：

```text
pref_vs_nopref_stlb_miss_rate_norm.png
```

图中的 `amean` 表示这里是 rate 类指标的聚合语义：每个配置内部先用 `sum miss / sum access` 得到 workload 或 summary 的 STLB miss rate，然后再做 `pref / nopref`。它不是 IPC 的 gmean。

百分比变化：

```text
stlb_miss_rate_change_pct = (stlb_miss_rate_norm - 1) * 100
```

### 7.1 Workload-level STLB miss rate norm

先分别计算：

```text
nopref_workload_stlb_miss_rate = sum(nopref_stlb_miss_i) / sum(nopref_stlb_access_i)
pref_workload_stlb_miss_rate   = sum(pref_stlb_miss_i) / sum(pref_stlb_access_i)
```

再计算：

```text
workload_stlb_miss_rate_norm = pref_workload_stlb_miss_rate / nopref_workload_stlb_miss_rate
```

### 7.2 Summary-level STLB miss rate norm

先分别计算：

```text
nopref_summary_stlb_miss_rate = sum(nopref selected trace stlb_miss_i) / sum(nopref selected trace stlb_access_i)
pref_summary_stlb_miss_rate   = sum(pref selected trace stlb_miss_i) / sum(pref selected trace stlb_access_i)
```

再计算：

```text
summary_stlb_miss_rate_norm = pref_summary_stlb_miss_rate / nopref_summary_stlb_miss_rate
```

### 7.3 STLB MPKI norm

当前脚本也输出 STLB MPKI 的归一化对比。计算方法和 miss rate norm 一致：

先分别在每个配置内部计算 workload 或 summary MPKI：

```text
nopref_mpki = sum(nopref_miss_i) * 1000 / sum(nopref_instructions_i)
pref_mpki   = sum(pref_miss_i) * 1000 / sum(pref_instructions_i)
```

再计算：

```text
mpki_norm = pref_mpki / nopref_mpki
```

当前 CSV 字段名是：

```text
stlb_mpki_norm = pref_stlb_mpki / nopref_stlb_mpki
stlb_mpki_change_pct = (stlb_mpki_norm - 1) * 100
```

图文件名为：

```text
pref_vs_nopref_stlb_mpki_norm.png
```

## 8. STLB miss cause share 的聚合方法

当前脚本统计的 STLB miss cause 包括：

```text
Demand Data
Demand Instruction
L1D Prefetch
L1I Prefetch
Other
```

trace-level 从 result log 中读取：

```text
Core_0_STLB_cause_Demand_Data_miss
Core_0_STLB_cause_Demand_Instruction_miss
Core_0_STLB_cause_L1D_Prefetch_miss
Core_0_STLB_cause_L1I_Prefetch_miss
Core_0_STLB_cause_Other_miss
Core_0_STLB_total_miss
```

### 8.1 Trace-level miss cause share

单条 trace 中某个 cause 的占比概念上是：

```text
trace_cause_share = trace_cause_miss / trace_stlb_total_miss
```

不过当前 trace-level CSV 主要保留的是各类 cause 的 miss 数，以及各类 cause 相对 STLB access 的 miss rate。

### 8.2 Workload-level miss cause share

一个 workload 内部多个 trace：

```text
workload_cause_share = sum(cause_miss_i) / sum(stlb_total_miss_i)
```

也就是先把这个 workload 内所有 selected trace 的同类 cause miss 加起来，再除以这些 trace 的 STLB total miss 总和。

例如：

```text
workload_demand_data_share = sum(demand_data_miss_i) / sum(stlb_total_miss_i)
```

### 8.3 Summary-level miss cause share

对于 dataset summary：

```text
summary_cause_share = sum(dataset selected trace cause_miss_i) / sum(dataset selected trace stlb_total_miss_i)
```

例如：

```text
gmean_spec17_demand_data_share =
    sum(SPEC17 selected trace demand_data_miss_i) /
    sum(SPEC17 selected trace stlb_total_miss_i)
```

这里 summary 行名字仍然叫 `gmean_spec17` / `gmean_gap`，但 cause share 本身不是 gmean，而是 `sum cause miss / sum total miss`。

## 9. 当前主要输出文件

筛选结果：

```text
select_trace/data_process_for_compare/stlb_mpki_gt_1.0_selected_traces.json
```

单配置 trace-level CSV：

```text
select_trace/nopref-workload-sweep/nopref_trace_level.csv
select_trace/pref-workload-sweep/pref_trace_level.csv
```

单配置 workload-level CSV：

```text
select_trace/nopref-workload-sweep/nopref_workload_agg.csv
select_trace/pref-workload-sweep/pref_workload_agg.csv
```

配置对比 CSV：

```text
select_trace/data_process_for_compare/pref_vs_nopref_ipc_compare.csv
```

该 CSV 当前包含：

```text
nopref_ipc
pref_ipc
ipc_speedup
ipc_speedup_pct
nopref_stlb_mpki
pref_stlb_mpki
stlb_mpki_norm
stlb_mpki_change_pct
nopref_stlb_miss_rate
pref_stlb_miss_rate
stlb_miss_rate_norm
stlb_miss_rate_change_pct
```

主要图片：

```text
select_trace/nopref-workload-sweep/nopref_stlb_miss_causes.png
select_trace/pref-workload-sweep/pref_stlb_miss_causes.png
select_trace/data_process_for_compare/pref_vs_nopref_ipc_compare.png
select_trace/data_process_for_compare/pref_vs_nopref_stlb_mpki_norm.png
select_trace/data_process_for_compare/pref_vs_nopref_stlb_miss_rate_norm.png
```

full_trace 对应输出：

```text
full_trace/nopref-workload-sweep/nopref_trace_level.csv
full_trace/nopref-workload-sweep/nopref_workload_agg.csv
full_trace/nopref-workload-sweep/nopref_stlb_miss_causes.png
full_trace/pref-workload-sweep/pref_trace_level.csv
full_trace/pref-workload-sweep/pref_workload_agg.csv
full_trace/pref-workload-sweep/pref_stlb_miss_causes.png
full_trace/data_process_for_compare/pref_vs_nopref_ipc_compare.csv
full_trace/data_process_for_compare/pref_vs_nopref_ipc_compare.png
full_trace/data_process_for_compare/pref_vs_nopref_stlb_mpki_norm.png
full_trace/data_process_for_compare/pref_vs_nopref_stlb_miss_rate_norm.png
```

生成 full_trace 后处理结果的命令：

```text
./launch_sim/1core-spec17_gap-TLB-select-trace-compare/run_tlb_select_compare.sh full-backend
```

同时生成 select_trace 和 full_trace 后处理结果：

```text
SELECT_THRESHOLD=1.0 \
./launch_sim/1core-spec17_gap-TLB-select-trace-compare/run_tlb_select_compare.sh backend-all
```

## 10. 一句话总结

当前后处理方法是：

```text
select_trace 先用 nopref 的 STLB MPKI > threshold 筛选 trace；
full_trace 不筛选 trace；
同一个 flow 内 pref 和 nopref 使用同一批 traces；
IPC 用 trace-level gmean 聚合；
MPKI / miss rate / miss cause share 用 sum numerator / sum denominator 聚合；
归一化对比先在每个配置内部聚合，再做 pref / nopref。
```
