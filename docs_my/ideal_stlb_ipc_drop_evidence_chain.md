# Ideal STLB 条件下 IPC 反而下降的证据链

本文记录一次针对 `ideal STLB IPC upper-bound` 实验结果的排查。讨论对象是：

```text
/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound
```

对应图和 CSV：

```text
csv_figure/1core-spec0617_gapligra-idealTLB-select-trace-compare_jsonnew/select_trace/data_process_for_compare/ideal_stlb_ipc_upperbound_compare.pdf
csv_figure/1core-spec0617_gapligra-idealTLB-select-trace-compare_jsonnew/select_trace/data_process_for_compare/ideal_stlb_ipc_upperbound_compare.csv
```

重点问题是：有些 workload 在 `ideal_demand`、`ideal_l1pref` 或 `ideal_all` 条件下，IPC 反而比 `pref` baseline 更低。这看起来违反直觉，因为 ideal STLB 消除了某些 STLB miss。但从完整 result log 直接重算后确认：图和 CSV 没有算错，IPC 下降来自原始 ROI log 本身。

本文用最明显的 case `602.gcc_s-2226B` 作为证据链样例。相关 log：

```text
results/1core-spec0617_gapligra-idealTLB-select-trace-compare_jsonnew/pref-workload-sweep/602.gcc_s-2226B-tlb-pref-1core---hide-heartbeat.log
results/1core-spec0617_gapligra-idealTLB-select-trace-compare_jsonnew/ideal-all-workload-sweep/602.gcc_s-2226B-tlb-ideal-all-1core---hide-heartbeat_--stlb-ideal-mode_all.log
results/1core-spec0617_gapligra-idealTLB-select-trace-compare_jsonnew/ideal-l1pref-workload-sweep/602.gcc_s-2226B-tlb-ideal-l1pref-1core---hide-heartbeat_--stlb-ideal-mode_l1pref.log
```

## 1. 后处理结果是否可信

后处理脚本中，ideal 对比的 speedup 定义是：

```text
ideal_x_ipc / pref_baseline_ipc
```

不是相对 `nopref`。对应源码位置：

```text
launch_sim/1core-spec0617_gapligra-idealTLB-select-trace-compare_jsonnew/data_process_for_compare/tlb_select_tools.py
```

其中 `compare_ideal_configs()` 读取 `baseline_workload_agg.csv`、`ideal_demand_workload_agg.csv`、`ideal_l1pref_workload_agg.csv`、`ideal_all_workload_agg.csv`，然后计算：

```python
ideal_demand_speedup = ideal_demand_ipc / baseline_ipc
ideal_l1pref_speedup = ideal_l1pref_ipc / baseline_ipc
ideal_all_speedup    = ideal_all_ipc / baseline_ipc
```

我用独立脚本直接从四个 result log 目录的 `[ROI Statistics]` 中重新抽取 IPC，并按 workload 做 gmean 聚合，结果与现有 CSV 完全一致：

```text
trace_counts:
  pref baseline: 43
  ideal_demand: 43
  ideal_l1pref: 43
  ideal_all:    43

csv_vs_raw_ipc_values_checked: 88
max_abs_diff: 0
```

因此，PDF 中出现负收益不是画图或 CSV 后处理错误，而是原始仿真 log 给出的结果。

## 2. case A: ideal_all 为什么 IPC 下降

### 2.1 现象

`602.gcc_s-2226B` 中，`ideal_all` 相对 `pref` baseline：

```text
instructions: 50000000 -> 50000000
cycles:       91185030 -> 96945222   +5760192, +6.32%
IPC:          0.548336 -> 0.515755   -0.032581, -5.94%
```

也就是说，执行同样 50M ROI 指令，`ideal_all` 多花了约 5.76M cycles。

### 2.2 ideal STLB 确实生效

首先排除一个误解：`ideal_all` 不是没有消掉 STLB miss。log 里显示 STLB miss 被完全消除：

```text
STLB total access: 68109 -> 68092
STLB total hit:     2404 -> 68092
STLB total miss:   65705 -> 0
STLB total MPKI:  1.3141 -> 0
```

同时，translation traffic 也被消掉：

```text
L1D TRANSLATION miss: 18250 -> 0
L2C TRANSLATION miss: 14862 -> 0
```

所以从 TLB/PTW 角度看，`ideal_all` 的模型确实大幅改善。

### 2.3 但是 demand cache miss 变多

问题出在数据 cache 的 demand load 路径上：

```text
L1D LOAD miss: 1573723 -> 1930078   +356355, +22.64%
L2C LOAD miss:  112360 -> 141722     +29362, +26.13%
LLC LOAD miss:   73139 -> 127816     +54677, +74.76%
```

这些是 demand load miss，通常比 prefetch miss 更接近 critical path。也就是说，`ideal_all` 虽然省掉了 STLB/PTW 成本，但它引入了更多会阻塞执行的数据 cache demand miss。

### 2.4 L2C prefetch 质量明显恶化

`ideal_all` 下 L2C prefetch 行为发生明显退化：

```text
L2C prefetch requested: 15467884 -> 15770307   +302423
L2C prefetch issued:    15441654 -> 15761060   +319406
L2C prefetch useful:     1731927 -> 791053     -940874, -54.33%
L2C prefetch useless:    1567059 -> 2384793    +817734, +52.18%
L2C prefetch accuracy:  0.112159 -> 0.0501903
L2C prefetch coverage:  0.938938 -> 0.847835
```

L1D prefetch 也变差，尤其是 late prefetch：

```text
L1D prefetch useful:    3239959 -> 3231995   -7964
L1D prefetch useless:     43347 -> 48302     +4955
L1D prefetch late:       504621 -> 707884    +203263, +40.28%
L1D prefetch accuracy:  0.940124 -> 0.934283
L1D prefetch coverage:  0.673073 -> 0.626104
```

因此，`ideal_all` 的核心异常是：STLB 层面完全改善，但 cache/prefetch 子系统的状态被改变，尤其 L2C prefetch 质量明显下降。

### 2.5 证据链

完整链条可以写成：

```text
ideal_all 消除所有 STLB miss
  -> STLB miss: 65705 -> 0
  -> translation traffic: L1D/L2C TRANSLATION miss -> 0

但是 ideal STLB 改变了 load/prefetch 到达 cache pipeline 的时间
  -> Berti/Pythia 的训练、发射、填充、替换状态发生分叉

L2C prefetch 质量显著下降
  -> useful -54.33%
  -> useless +52.18%
  -> accuracy 0.112159 -> 0.0501903

demand cache miss 增加
  -> L1D LOAD miss +22.64%
  -> L2C LOAD miss +26.13%
  -> LLC LOAD miss +74.76%

critical-path miss 成本超过 STLB/PTW 省下的成本
  -> cycles +6.32%
  -> IPC -5.94%
```

### 2.6 结论

`ideal_all` 的 IPC 下降不是因为 ideal STLB 没生效，而是因为这个 ideal 模型改变了程序执行时序和 prefetch/cache 交互。它把 STLB/PTW 成本消掉的同时，也让 L2C prefetch 的有效性显著变差，并增加了 demand load miss。对 `602.gcc_s-2226B` 而言，增加的 demand cache miss 成本超过了消除 STLB miss 的收益。

因此，当前实现里的 `ideal_all` 更准确地说是一个“改变时序后的 ideal STLB 实验”，不一定是严格数学意义上的 IPC upper bound。

## 3. case B: ideal_l1pref 为什么 IPC 下降

### 3.1 现象

`602.gcc_s-2226B` 中，`ideal_l1pref` 相对 `pref` baseline：

```text
instructions: 50000000 -> 50000000
cycles:       91185030 -> 95245658   +4060628, +4.45%
IPC:          0.548336 -> 0.524958   -0.023378, -4.26%
```

这也是真实 log 结果，不是后处理错误。

### 3.2 ideal_l1pref 确实消除了 L1D prefetch 来源的 STLB miss

`ideal_l1pref` 不是消除所有 STLB miss，而是消除 L1D/L1I prefetch 来源的 STLB miss。对于这个 case：

```text
STLB total miss:          65705 -> 59705   -6000, -9.13%
STLB total MPKI:         1.3141 -> 1.1941
STLB L1D Prefetch miss:   6111 -> 0       -100%
STLB Demand miss:        59594 -> 59705    +111
```

也就是说：

1. L1D prefetch 来源的 STLB miss 被完全消掉。
2. Demand 来源的 STLB miss 基本还在。
3. 总 STLB miss 只下降约 9.13%，不是 `ideal_all` 那种全部清零。

源码上，这一类来源来自 `CACHE::classify_translation_origin()`：

```text
src/cache.cc
```

如果 packet 是本级 cache 产生的 prefetch，并且 cache 名字是 `_L1D`，就分类为：

```text
translation_origin::L1D_PREFETCH
```

`ideal_l1pref` 在 STLB lookup miss 时，对这类来源直接返回 ideal hit。

### 3.3 L1D 本地看起来确实更好

`ideal_l1pref` 下，L1D prefetch 指标略好：

```text
L1D prefetch requested: 3446310 -> 3445481   -829
L1D prefetch issued:    3446310 -> 3445481   -829
L1D prefetch useful:    3239959 -> 3255530   +15571, +0.48%
L1D prefetch useless:     43347 -> 41905     -1442, -3.33%
L1D prefetch late:       504621 -> 484438    -20183, -4.00%
L1D prefetch accuracy:  0.940124 -> 0.944870
L1D prefetch coverage:  0.673073 -> 0.685206
```

L1D demand load miss 也下降：

```text
L1D LOAD access: 11955280 -> 11954339   -941
L1D LOAD hit:    10381557 -> 10458698   +77141
L1D LOAD miss:    1573723 -> 1495641    -78082, -4.96%
```

这说明 `ideal_l1pref` 确实让 L1D 本地层面受益。直觉上，这应该帮助性能。

### 3.4 关键问题: L1D miss 少不等于下游 miss 少

ChampSim log 中 cache 表的语义是：

```text
ACCESS = HIT + MISS
```

`MSHR_MERGE` 是另外统计的，它表示一个请求 miss 了，但是发现同一 cache line 已有 outstanding miss，于是合并等待，没有再向下一层发一个新的 unique request。

因此，对 LOAD 来说，下游收到的 unique demand request 近似是：

```text
next_level_LOAD_access = current_level_LOAD_miss - current_level_LOAD_MSHR_MERGE
```

在 L1D 层：

```text
pref:
  L1D LOAD miss       = 1573723
  L1D LOAD MSHR_MERGE = 1308403
  L2C LOAD access     = 1573723 - 1308403 = 265320

ideal_l1pref:
  L1D LOAD miss       = 1495641
  L1D LOAD MSHR_MERGE = 1245927
  L2C LOAD access     = 1495641 - 1245927 = 249714
```

所以 L1D LOAD miss 虽然减少了 78082，但真正给 L2C 的 LOAD access 只减少了 15606：

```text
L2C LOAD access: 265320 -> 249714   -15606, -5.88%
```

很多 L1D miss 的减少发生在原本会被 MSHR merge 掉的请求上，不能等价理解为同等数量的下游 traffic 被减少。

### 3.5 L2C access 少了，但 L2C hit 少得更多

这是解释 `L2C miss 为什么反而变多` 的关键。

`ideal_l1pref` 下：

```text
L2C LOAD access: 265320 -> 249714   -15606
L2C LOAD hit:    152960 -> 132505   -20455
L2C LOAD miss:   112360 -> 117209   +4849
```

用公式看：

```text
miss = access - hit
delta_miss = delta_access - delta_hit
           = (-15606) - (-20455)
           = +4849
```

也就是说，L2C 收到的 LOAD access 少了，但少掉的那批 access 中包含了更多原本会命中的请求；剩下或新形成的请求集合，L2C hit rate 更差：

```text
L2C LOAD hit rate: 57.65% -> 53.06%
```

这说明 `ideal_l1pref` 不是在 baseline 的 L2C request stream 上简单删除一部分请求。它改变了时序后，L1D prefetch、L2C prefetch、cache fill、replacement、MSHR 状态都可能分叉。L2C 看到的是一个新的动态流，而不是 baseline L2C access 的严格子集。

### 3.6 LLC access 变多主要来自 L2C MSHR merge 大幅减少

继续看 L2C 到 LLC 的路径：

```text
pref:
  L2C LOAD miss       = 112360
  L2C LOAD MSHR_MERGE = 39123
  LLC LOAD access     = 112360 - 39123 = 73237

ideal_l1pref:
  L2C LOAD miss       = 117209
  L2C LOAD MSHR_MERGE = 21561
  LLC LOAD access     = 117209 - 21561 = 95648
```

实际 log 正好是：

```text
LLC LOAD access: 73237 -> 95648   +22411
LLC LOAD miss:   73139 -> 95450   +22311
```

LLC LOAD access 的增加可以拆成两部分：

```text
L2C LOAD miss 自身增加:      +4849
L2C LOAD MSHR_MERGE 减少:   +17562
合计 LLC LOAD access 增加:  +22411
```

因此，LLC demand miss 增多的主要原因不是 L2C prefetch 多发，而是 L2C demand miss 的时间分布和合并关系发生变化，导致更少请求能在 L2C MSHR 中合并。

### 3.7 不是 L2C prefetch 质量崩溃

这一点要和 `ideal_all` 区分开。`ideal_l1pref` 下 L2C prefetch 指标没有明显恶化，甚至略好：

```text
L2C prefetch requested: 15467884 -> 15064512   -403372
L2C prefetch issued:    15441654 -> 15038611   -403043
L2C prefetch useful:     1731927 -> 1775090    +43163, +2.49%
L2C prefetch useless:    1567059 -> 1502514    -64545, -4.12%
L2C prefetch late:         39125 -> 21562      -17563
L2C prefetch accuracy:  0.112159 -> 0.118036
L2C prefetch coverage:  0.938938 -> 0.937931
```

所以，`ideal_l1pref` 的 IPC 下降不能归因为 L2C prefetch 质量崩掉。更准确的解释是：

```text
L1D 本地 prefetch 更及时
  -> L1D LOAD miss 下降

但时序改变使下游 demand stream 重新组织
  -> L2C LOAD access 减少
  -> L2C LOAD hit 减少更多
  -> L2C LOAD miss 反而增加
  -> L2C LOAD MSHR_MERGE 大幅减少
  -> LLC LOAD access/miss 增加

critical demand miss 增加和 miss latency 上升
  -> cycles 增加
  -> IPC 下降
```

### 3.8 latency 与 IPC 下降在数量级上吻合

`ideal_l1pref` 下 miss latency 也上升：

```text
L1D average miss latency: 64.07 -> 72.92 cycles
L2C average miss latency: 192.2 -> 205.9 cycles
LLC average miss latency: 202.4 -> 203.3 cycles
```

额外 LLC LOAD miss 数量为：

```text
LLC LOAD miss: 73139 -> 95450   +22311
```

粗略数量级估算：

```text
22311 * 203 cycles ~= 4.5M cycles
```

实际 cycles 增加：

```text
91185030 -> 95245658   +4.06M cycles
```

由于乱序执行会隐藏一部分 miss latency，这不是严格等式，但数量级高度吻合。说明 `ideal_l1pref` 的 IPC 下降完全可能由额外 critical demand miss 和 miss latency 上升解释。

### 3.9 为什么只消除 L1D prefetch STLB miss 会改变 L1D/L2C 行为

这个点是理解 `ideal_l1pref` 的核心。

当前配置中 L1D 是 virtual prefetch：

```json
"L1D": {
  "virtual_prefetch": true,
  "prefetcher": "berti"
}
```

源码中，L1D prefetch packet 如果是 virtual prefetch，会设置：

```cpp
pf_packet.v_address = virtual_prefetch ? pf_addr : champsim::address{};
pf_packet.is_translated = !virtual_prefetch;
```

因此 L1D prefetch 不是直接拿物理地址查 cache，而是先要完成翻译。baseline 中，如果这类 prefetch 的 STLB lookup miss，就要等待 STLB/PTW 相关路径；`ideal_l1pref` 中，这类 `translation_origin == L1D_PREFETCH` 的 STLB miss 会被直接作为 ideal hit 返回。

所以 `ideal_l1pref` 改变的不只是一个静态计数，而是改变了 L1D prefetch 进入 cache pipeline 的时间：

```text
baseline:
  L1D virtual prefetch -> translation -> STLB miss/PTW delay -> cache access/fill

ideal_l1pref:
  L1D virtual prefetch -> ideal STLB hit -> 更早 cache access/fill
```

更早的 L1D prefetch 会影响：

1. 哪些 demand load 在 L1D 命中。
2. 哪些 demand load 还会下放到 L2C。
3. L2C 看到这些 request 的时间顺序。
4. L2C Pythia 的训练和 prefetch 发射。
5. L2C cache replacement 状态。
6. L2C MSHR 中 outstanding miss 的重叠关系。

因此，下游 L2C/LLC 的请求流不需要保持为 baseline 的子集。即使 L1D 本地 miss 少了，下游 demand miss 仍然可能增加。

### 3.10 证据链

`ideal_l1pref` 的完整证据链可以写成：

```text
ideal_l1pref 消除 L1D prefetch 来源的 STLB miss
  -> STLB_L1D_Prefetch_miss: 6111 -> 0
  -> STLB_total_miss: 65705 -> 59705

L1D virtual prefetch 更早完成翻译
  -> L1D prefetch useful 略增
  -> L1D prefetch late 略降
  -> L1D LOAD miss: 1573723 -> 1495641

但 L1D miss 下降主要不等价于同等下游 traffic 下降
  -> L1D LOAD miss -78082
  -> L2C LOAD access 只减少 -15606

L2C demand stream 的组成和时序发生变化
  -> L2C LOAD access -15606
  -> L2C LOAD hit -20455
  -> L2C LOAD miss +4849
  -> L2C LOAD hit rate 57.65% -> 53.06%

L2C outstanding miss 重叠减少
  -> L2C LOAD MSHR_MERGE: 39123 -> 21561
  -> 少合并 17562 个 load miss

更多 unique demand miss 打到 LLC
  -> LLC LOAD access +22411
  -> LLC LOAD miss +22311

critical demand miss 和平均 miss latency 上升
  -> cycles +4.45%
  -> IPC -4.26%
```

### 3.11 结论

`ideal_l1pref` 的 IPC 下降不是因为 L1D prefetch 质量变差。相反，L1D 本地指标和 L2C prefetch 指标都略有改善。问题在于：

1. `ideal_l1pref` 只消掉 L1D prefetch 来源的 STLB miss，收益规模有限。
2. L1D virtual prefetch 更早完成翻译后，改变了后续 cache pipeline 时序。
3. L2C 收到的 demand request stream 不是 baseline stream 的简单子集。
4. L2C LOAD hit 减少得比 LOAD access 更多，导致 L2C LOAD miss 增加。
5. L2C LOAD MSHR merge 显著减少，导致更多 unique demand miss 进入 LLC。
6. 额外 LLC demand miss 和更高 miss latency 超过了消除 L1D prefetch STLB miss 的收益。

因此，`ideal_l1pref` 也不一定表现为 IPC upper bound。它是一个会改变 prefetch timing 和下游 cache/MSHR 状态的实验条件。

### 3.12 其他 workload 是否呈现相同证据链

除了 `602.gcc_s-2226B`，图中 `ideal_l1pref` 下降的 workload 还包括：

```text
450.soplex
459.GemsFDTD
471.omnetpp
```

这三个 workload 的 log 也可以用同一套方法解释，但需要区分两种情况：

1. `450.soplex` 和 `471.omnetpp` 的证据链与 `602.gcc_s` 基本一致。
2. `459.GemsFDTD` 在 workload 聚合层面也呈现类似趋势，但它由 4 条 selected trace 聚合而来，trace-level 内部分化明显，主要负收益来自 `459.GemsFDTD-1320B`。

#### 3.12.1 450.soplex

`450.soplex` 只有一条 selected trace：

```text
450.soplex-92B
```

`pref -> ideal_l1pref` 的关键数据如下：

```text
IPC:                 0.643428 -> 0.635522   -1.23%
cycles:              77708781 -> 78675472   +966691, +1.24%

STLB total miss:        55829 -> 44639      -11190, -20.04%
STLB L1Dpf miss:        10252 -> 0          -100%
STLB demand miss:       45577 -> 44639      -938

L1D LOAD miss:        1369827 -> 1365546    -4281
L1D LOAD merge:        466359 -> 464250     -2109
L1D unique to L2C:     903468 -> 901296     -2172

L2C LOAD access:       903581 -> 901413     -2168
L2C LOAD hit:          462126 -> 454788     -7338
L2C LOAD miss:         441455 -> 446625     +5170
L2C LOAD merge:         50695 -> 45365      -5330
L2C LOAD hit rate:   0.511438 -> 0.504528

L2C unique to LLC:     390760 -> 401260     +10500
LLC LOAD access:       390759 -> 401260     +10501
LLC LOAD miss:         259344 -> 269243     +9899

L1D avg miss latency:   148.1 -> 150.3
L2C avg miss latency:   230.3 -> 232.6
LLC avg miss latency:   224.3 -> 225.9
```

这条链和 `602.gcc_s` 非常接近：

```text
ideal_l1pref 消除 L1D prefetch 来源的 STLB miss
  -> STLB_L1Dpf_miss: 10252 -> 0

L1D 本地略有改善
  -> L1D_LOAD_miss -4281

但下游 L2C 不是简单获得同等改善
  -> L2C_LOAD_access -2168
  -> L2C_LOAD_hit -7338
  -> L2C_LOAD_miss +5170

L2C outstanding miss 合并减少
  -> L2C_LOAD_MSHR_MERGE -5330

更多 unique demand miss 打到 LLC
  -> LLC_LOAD_miss +9899

critical demand miss 和 latency 增加
  -> cycles +1.24%
  -> IPC -1.23%
```

这里同样不是 L2C prefetch 崩溃导致的。`450.soplex` 中 L2C prefetch 发射减少，accuracy 反而上升：

```text
L2C prefetch issued:   5201260 -> 4966256   -235004
L2C prefetch useful:    730216 -> 725571    -4645
L2C prefetch useless:   634781 -> 614208    -20573
L2C prefetch accuracy: 0.140392 -> 0.146100
```

因此，`450.soplex` 支持与 gcc 相同的解释：L1D prefetch translation 变理想后，L1D 本地略好，但 L2C demand stream 的组成和时序变差，L2C hit 下降更多、merge 减少，导致 LLC demand miss 增加。

#### 3.12.2 471.omnetpp

`471.omnetpp` 也只有一条 selected trace：

```text
471.omnetpp-188B
```

`pref -> ideal_l1pref` 的关键数据如下：

```text
IPC:                 0.466123 -> 0.464354   -0.38%
cycles:             107267838 -> 107676537  +408699, +0.38%

STLB total miss:       223412 -> 208608     -14804, -6.63%
STLB L1Dpf miss:        15992 -> 0          -100%
STLB demand miss:      207420 -> 208608     +1188

L1D LOAD miss:        1262466 -> 1278467    +16001
L1D LOAD merge:        447599 -> 464233     +16634
L1D unique to L2C:     814867 -> 814234     -633

L2C LOAD access:       816582 -> 815949     -633
L2C LOAD hit:          245335 -> 243618     -1717
L2C LOAD miss:         571247 -> 572331     +1084
L2C LOAD merge:         25777 -> 23271      -2506
L2C LOAD hit rate:   0.300441 -> 0.298570

L2C unique to LLC:     545470 -> 549060     +3590
LLC LOAD access:       545470 -> 549059     +3589
LLC LOAD miss:         435792 -> 438317     +2525

L1D avg miss latency:   132.4 -> 133.0
L2C avg miss latency:   176.0 -> 176.9
LLC avg miss latency:   160.8 -> 160.9
```

`471.omnetpp` 和 gcc/450 的前半段略有差别：它的 L1D LOAD miss 没有下降，反而增加了 16001。但 L1D LOAD MSHR merge 增加了 16634，因此真正下放到 L2C 的 unique LOAD access 仍然略少：

```text
L1D unique to L2C: 814867 -> 814234   -633
```

后半段与 gcc/450 一致：

```text
L2C LOAD access 略少
  -> -633

但 L2C LOAD hit 下降更多
  -> -1717

所以 L2C LOAD miss 反而增加
  -> +1084

L2C MSHR merge 下降
  -> -2506

更多 unique demand miss 到 LLC
  -> LLC_LOAD_miss +2525

最终 IPC 小幅下降
  -> -0.38%
```

`471.omnetpp` 的 L2C prefetch 指标也不支持“prefetch 质量崩溃”这个解释：

```text
L2C prefetch issued:   1655777 -> 1509607   -146170
L2C prefetch useful:    305278 -> 305260    -18
L2C prefetch useless:   635381 -> 617715    -17666
L2C prefetch accuracy: 0.184371 -> 0.202212
```

因此，`471.omnetpp` 的结论是：虽然 L1D 层不像 gcc 那样表现为 LOAD miss 下降，但从 L2C 往下的证据链一致，都是 L2C hit/merge 关系变差导致 LLC demand miss 增加。

#### 3.12.3 459.GemsFDTD

`459.GemsFDTD` 有 4 条 selected trace：

```text
459.GemsFDTD-1169B
459.GemsFDTD-1211B
459.GemsFDTD-1320B
459.GemsFDTD-765B
```

workload 聚合层面，`pref -> ideal_l1pref` 的数据如下：

```text
IPC gmean:           0.995224 -> 0.982693   -1.26%
cycles sum:         202975901 -> 205712421  +2736520, +1.35%

STLB total miss:       580566 -> 382945     -197621, -34.04%
STLB L1Dpf miss:       228615 -> 0          -100%
STLB demand miss:      351951 -> 382945     +30994

L1D LOAD miss:        3329478 -> 3295875    -33603
L1D LOAD merge:        477174 -> 449137     -28037
L1D unique to L2C:    2852304 -> 2846738    -5566

L2C LOAD access:      2852717 -> 2847150    -5567
L2C LOAD hit:         1721849 -> 1687902    -33947
L2C LOAD miss:        1130868 -> 1159248    +28380
L2C LOAD merge:         37783 -> 35532      -2251
L2C LOAD hit rate:   0.603582 -> 0.592839

L2C unique to LLC:    1093085 -> 1123716    +30631
LLC LOAD access:      1093085 -> 1123716    +30631
LLC LOAD miss:         967999 -> 972726     +4727
```

从 workload 聚合看，它也符合 gcc 的核心链条：

```text
STLB L1D prefetch miss 被消除
  -> 228615 -> 0

L1D LOAD miss 下降
  -> -33603

但下放到 L2C 的 LOAD access 只小幅减少
  -> -5567

L2C hit 下降更多
  -> -33947

所以 L2C miss 增加
  -> +28380

L2C MSHR merge 下降
  -> -2251

更多 unique demand miss 进入 LLC
  -> LLC_LOAD_access +30631
  -> LLC_LOAD_miss +4727

最终 IPC gmean 下降
  -> -1.26%
```

但是 `459.GemsFDTD` 的 trace-level 情况不能简单说每条都一样。4 条 trace 的变化如下：

```text
459.GemsFDTD-1169B
  IPC: +0.80%
  STLB_L1Dpf_miss: -66336
  L1D_LOAD_miss: -19581
  L2C_LOAD_miss: -2472
  L2C_LOAD_merge: +812
  LLC_LOAD_miss: -1305

459.GemsFDTD-1211B
  IPC: -0.38%
  STLB_L1Dpf_miss: -34359
  L1D_LOAD_miss: -5132
  L2C_LOAD_miss: -4789
  L2C_LOAD_merge: +630
  LLC_LOAD_miss: -5463

459.GemsFDTD-1320B
  IPC: -4.66%
  STLB_L1Dpf_miss: -49856
  L1D_LOAD_miss: +2434
  L2C_LOAD_hit: -39691
  L2C_LOAD_miss: +43308
  L2C_LOAD_merge: -3175
  LLC_LOAD_miss: +18545

459.GemsFDTD-765B
  IPC: -0.72%
  STLB_L1Dpf_miss: -78064
  L1D_LOAD_miss: -11324
  L2C_LOAD_miss: -7667
  L2C_LOAD_merge: -518
  LLC_LOAD_miss: -7050
```

可以看到，`459.GemsFDTD` 的整体下降主要由 `459.GemsFDTD-1320B` 这条 trace 主导。`1320B` 的证据链非常接近 gcc：

```text
L2C_LOAD_hit 大幅下降
  -> -39691

L2C_LOAD_miss 大幅增加
  -> +43308

L2C_LOAD_MSHR_MERGE 下降
  -> -3175

LLC_LOAD_miss 增加
  -> +18545

IPC 明显下降
  -> -4.66%
```

而 `1169B` 是正收益，`1211B` 和 `765B` 的 cache miss 局部还改善，但 IPC 仍有小幅下降，说明这两个 trace 还可能有其他时序、critical path 或微小统计扰动因素。对 `459.GemsFDTD` 最稳妥的说法是：

```text
workload 聚合后的主导证据链与 gcc 类似；
但 trace-level 内部分化明显，负收益主要由 1320B 的 L2C hit/merge/LLC miss 恶化贡献。
```

#### 3.12.4 小结

这三个 workload 与 `602.gcc_s` 的关系可以总结为：

```text
450.soplex:
  与 gcc 基本一致。
  L1D 本地略好，但 L2C hit 下降更多、L2C merge 减少、LLC demand miss 增加。

471.omnetpp:
  后半段证据链与 gcc 一致。
  L1D LOAD miss 本身没有改善，但 L1D merge 增加使下放到 L2C 的 access 略少；
  随后 L2C hit/merge 变差，LLC demand miss 增加。

459.GemsFDTD:
  workload 聚合层面与 gcc 类似。
  但 trace-level 分化明显，主要由 1320B 的 L2C hit/merge/LLC miss 恶化拉低。
```

因此，`ideal_l1pref` 下降的共同模式不是“L2C prefetch 质量崩溃”，而是：

```text
L1D virtual prefetch translation 变理想
  -> L1D/L2C 请求到达时序分叉
  -> L2C demand stream 不再是 baseline stream 的简单子集
  -> L2C hit rate 和 MSHR merge 可能下降
  -> 更多 unique demand miss 到达 LLC
  -> critical-path demand miss 成本超过 STLB miss 减少带来的收益
```

## 4. 当前证据边界

当前 aggregate log 已经能证明：

1. PDF/CSV 结果与原始 result log 一致。
2. `ideal_all` 中 STLB miss 被清零，但 L2C prefetch 质量大幅恶化，demand cache miss 增加，IPC 下降。
3. `ideal_l1pref` 中 L1D prefetch 来源的 STLB miss 被清零，L1D 本地变好，但 L2C demand hit rate 下降、L2C MSHR merge 减少、LLC demand miss 增加，IPC 下降。

但是 aggregate log 不能逐地址证明：

```text
哪些具体 cache line 在 pref 中是 L2C hit，
哪些具体 cache line 在 ideal_l1pref 中变成 L2C miss，
哪些具体 miss 原本可以 MSHR merge，后来不能 merge。
```

如果要把这个问题完全坐实，需要加 per-address debug，例如记录：

```text
cycle, cache, type, address, v_address, hit/miss, mshr_merge, prefetch_from_this, translation_source
```

特别是 L2C LOAD 路径上的：

```text
addr, cycle, hit/miss, whether_mshr_merge, source instruction id
```

然后比较 `pref` 与 `ideal_l1pref` 两条 run 中的 L2C LOAD stream。这样才能从 aggregate 证据进一步推进到逐地址因果证据。
