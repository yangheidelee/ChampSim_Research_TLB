# gcc ideal STLB prefetch matrix 结果分析

本文记录 `602.gcc_s-2226B` 上三组 prefetcher 组合的对比实验结果，重点分析 `pref` 对比 `ideal_l1pref`、`pref` 对比 `ideal_all` 的 IPC 和 cache/TLB 指标变化。

## 实验范围

实验目录：

`/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/launch_sim/test-gcc-ideal-l1pref-prefetch-matrix`

结果目录：

`/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/results/test-gcc-ideal-l1pref-prefetch-matrix`

汇总 CSV：

`/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/csv_figure/test-gcc-ideal-l1pref-prefetch-matrix/gcc_ideal_prefetch_matrix_summary.csv`

同配置成对 delta：

`/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/csv_figure/test-gcc-ideal-l1pref-prefetch-matrix/gcc_ideal_prefetch_matrix_delta_vs_same_pref.csv`

固定 trace：

`602.gcc_s-2226B.champsimtrace.xz`

仿真长度：

- warmup: 20M instructions
- ROI: 50M instructions

对比组合：

- L1D Berti + L2C Pythia
- L1D Berti + L2C No prefetcher
- L1D Berti + L2C IP-stride prefetcher
- L1D No prefetcher + L2C Pythia

`ideal_l1pref` 表示只 idealize L1D prefetch translation 相关的 STLB miss。  
`ideal_all` 表示所有 STLB miss 都被 idealize。

## 新增 Berti + IPStride 配置

2026-06-26 更新：脚本矩阵已加入 `Berti + IPStride`，包含三种条件：

- `pref-berti-ip_stride`
- `ideal-l1pref-berti-ip_stride`
- `ideal-all-berti-ip_stride`

这组配置用于和已经跑完的 `Berti + NoL2`、`Berti + Pythia` 共同比较 L2C prefetcher 对 ideal STLB timing perturbation 的敏感性。下面旧结果表仍然只记录已跑完的 9 项结果；`Berti + IPStride` 的 IPC 和证据链需要等新三组 log 跑完后再补入。

## pref vs ideal_l1pref

### IPC 结果

| 配置 | pref IPC | ideal_l1pref IPC | IPC 变化 | cycle 变化 |
|---|---:|---:|---:|---:|
| Berti + Pythia | 0.548336 | 0.524958 | -4.26% | +4,060,628 |
| Berti + NoL2 | 0.323137 | 0.324163 | +0.32% | -489,936 |
| NoL1D + Pythia | 0.313331 | 0.313331 | 0.00% | 0 |

这个结果说明：`ideal_l1pref` 不是天然负收益。负收益只出现在 `Berti + Pythia` 组合中。

### Berti + Pythia 的下降链条

| 指标 | pref | ideal_l1pref | delta |
|---|---:|---:|---:|
| STLB total miss | 65,705 | 59,705 | -6,000 |
| STLB L1D prefetch miss | 6,111 | 0 | -6,111 |
| STLB demand miss | 59,594 | 59,705 | +111 |
| L1D load miss | 1,573,723 | 1,495,641 | -78,082 |
| L1D unique to L2C | 265,320 | 249,714 | -15,606 |
| L2C load access | 265,320 | 249,714 | -15,606 |
| L2C load hit | 152,960 | 132,505 | -20,455 |
| L2C load miss | 112,360 | 117,209 | +4,849 |
| L2C load MSHR merge | 39,123 | 21,561 | -17,562 |
| L2C unique to LLC | 73,237 | 95,648 | +22,411 |
| LLC load miss | 73,139 | 95,450 | +22,311 |
| IPC | 0.548336 | 0.524958 | -4.26% |

表面上看，`ideal_l1pref` 消除了 6,111 个 L1D prefetch 相关 STLB miss，而且 L1D load miss 减少了 78,082 个，这应该是好事。真正的问题发生在 L2C 以后：

- L2C load access 少了 15,606 个。
- 但 L2C load hit 少得更多，少了 20,455 个。
- 因此 L2C load miss 反而增加 4,849 个。
- 更关键的是 L2C load MSHR merge 从 39,123 降到 21,561，少了 17,562 个。
- 最后 L2C unique to LLC 增加 22,411 个，LLC load miss 增加 22,311 个。

这里可以用一个很直观的关系解释：

`L2C unique to LLC = L2C load miss - L2C load MSHR merge`

所以：

- pref: `112,360 - 39,123 = 73,237`
- ideal_l1pref: `117,209 - 21,561 = 95,648`
- 差值: `+22,411`

也就是说，IPC 下降不是因为 STLB miss 没有被消除，而是因为消除 L1D prefetch translation stall 之后，L2C 层的 demand hit 和 MSHR overlap 变差，导致更多请求真的落到 LLC。

### Berti + NoL2 的上升链条

| 指标 | pref | ideal_l1pref | delta |
|---|---:|---:|---:|
| STLB total miss | 65,718 | 59,717 | -6,001 |
| STLB L1D prefetch miss | 6,088 | 0 | -6,088 |
| STLB demand miss | 59,630 | 59,717 | +87 |
| L1D load miss | 3,020,381 | 3,016,386 | -3,995 |
| L1D unique to L2C | 320,510 | 318,855 | -1,655 |
| L2C load access | 320,510 | 318,855 | -1,655 |
| L2C load hit | 2,567 | 2,574 | +7 |
| L2C load miss | 317,943 | 316,281 | -1,662 |
| L2C load MSHR merge | 0 | 0 | 0 |
| LLC load miss | 317,704 | 316,073 | -1,631 |
| IPC | 0.323137 | 0.324163 | +0.32% |

`Berti + NoL2` 下结果符合直觉：

- L1D prefetch translation miss 被消除。
- L1D load miss 小幅减少。
- 下放到 L2C 的 demand access 小幅减少。
- L2C miss 和 LLC miss 也随之小幅减少。
- IPC 小幅上升。

这说明 L1D Berti 在 `ideal_l1pref` 条件下并不天然导致性能下降。Berti 单独看，至少在这个 gcc trace 上是小幅正收益。

### NoL1D + Pythia 为什么不变

| 指标 | pref | ideal_l1pref | delta |
|---|---:|---:|---:|
| STLB L1D prefetch miss | 0 | 0 | 0 |
| L1D load miss | 8,134,508 | 8,134,508 | 0 |
| L2C load miss | 1,157,272 | 1,157,272 | 0 |
| LLC load miss | 81,240 | 81,240 | 0 |
| IPC | 0.313331 | 0.313331 | 0.00% |

没有 L1D prefetcher 时，`ideal_l1pref` 没有可以消除的 L1D prefetch translation miss。因此所有关键指标完全一致。

### pref vs ideal_l1pref 的结论

这组 ablation 支持下面的判断：

`ideal_l1pref` 改变的是 L1D Berti prefetch 的 translation timing。这个变化本身不是必然有害的；在没有 L2C prefetcher 时，它是小幅正收益。真正导致 gcc 在 `Berti + Pythia` 中下降的是 L1D Berti timing 变化和 L2C Pythia 之间的负交互。

之前说“L2C access 局部性变差导致 miss 增多”是现象层面的描述，需要补上机制边界：这个 L2C demand 行为变差并不是和 Pythia 无关的独立事实。对比 `Berti + NoL2` 可以看到，如果没有 L2C Pythia，同样消除 L1D prefetch translation miss 后，L2C/LLC miss 没有变坏，反而小幅下降。

因此更准确的表述是：

`ideal_l1pref` 让 L1D Berti 的 prefetch 更早、更顺地进入 cache 系统；这个 timing 改变会扰动 L2C Pythia 的训练、填充、替换和 MSHR overlap。最终在 `Berti + Pythia` 中，L2C demand hit 减少、MSHR merge 减少，LLC demand miss 增多，IPC 下降。

同时也要注意，Pythia 在正常非理想条件下是有明显收益的：

- pref Berti + Pythia IPC: 0.548336
- pref Berti + NoL2 IPC: 0.323137
- pref NoL1D + Pythia IPC: 0.313331

所以不能说 Pythia 本身绝对有害。更准确是：Pythia 在 baseline 正常条件下很有用，但在 `ideal_l1pref` 改变 L1D Berti timing 后，对这个 timing perturbation 很敏感，并产生负交互。

## pref vs ideal_all

### IPC 结果

| 配置 | pref IPC | ideal_all IPC | IPC 变化 | cycle 变化 |
|---|---:|---:|---:|---:|
| Berti + Pythia | 0.548336 | 0.515755 | -5.94% | +5,760,192 |
| Berti + NoL2 | 0.323137 | 0.333611 | +3.24% | -4,857,943 |
| NoL1D + Pythia | 0.313331 | 0.308127 | -1.66% | +2,695,246 |

`ideal_all` 消除所有 STLB miss，但 IPC 仍然不一定上升。这个实验里：

- `Berti + Pythia` 明显下降。
- `Berti + NoL2` 明显上升。
- `NoL1D + Pythia` 轻微下降。

因此 `ideal_all` 也不是严格的性能上界。它会移除 page walk/translation stall，但也会改变 timing、cache 状态、prefetcher 训练和 MSHR overlap。

### Berti + Pythia 的下降链条

| 指标 | pref | ideal_all | delta |
|---|---:|---:|---:|
| STLB total miss | 65,705 | 0 | -65,705 |
| STLB L1D prefetch miss | 6,111 | 0 | -6,111 |
| STLB demand miss | 59,594 | 0 | -59,594 |
| L1D load miss | 1,573,723 | 1,930,078 | +356,355 |
| L1D unique to L2C | 265,320 | 273,082 | +7,762 |
| L2C load hit | 152,960 | 131,360 | -21,600 |
| L2C load miss | 112,360 | 141,722 | +29,362 |
| L2C load MSHR merge | 39,123 | 13,730 | -25,393 |
| L2C unique to LLC | 73,237 | 127,992 | +54,755 |
| LLC load miss | 73,139 | 127,816 | +54,677 |
| L2C prefetch useful | 1,731,927 | 791,053 | -940,874 |
| L2C prefetch useless | 1,567,059 | 2,384,793 | +817,734 |
| L2C prefetch accuracy | 0.112159 | 0.050190 | -0.061969 |
| IPC | 0.548336 | 0.515755 | -5.94% |

`Berti + Pythia` 下，`ideal_all` 的负收益比 `ideal_l1pref` 更明显。这里不只是 L1D prefetch translation timing 改了，而是 demand translation 也全部 idealized。STLB miss 被全部消除后，程序执行和 cache 访问时序进一步变化。

关键证据：

- STLB miss 全部变成 0。
- 但 L1D load miss 增加 356,355。
- L2C load miss 增加 29,362。
- L2C load MSHR merge 减少 25,393。
- LLC load miss 增加 54,677。
- Pythia 的质量明显恶化：useful 大幅下降，useless 大幅上升，accuracy 从 0.112159 下降到 0.050190。

这说明 `ideal_all` 虽然消除了 translation miss 代价，但它同时强烈改变了 Pythia 的训练和 cache 状态，导致下游 LLC miss 大量增加，最终抵消并超过了 STLB idealization 的收益。

### Berti + NoL2 的上升链条

| 指标 | pref | ideal_all | delta |
|---|---:|---:|---:|
| STLB total miss | 65,718 | 0 | -65,718 |
| STLB L1D prefetch miss | 6,088 | 0 | -6,088 |
| STLB demand miss | 59,630 | 0 | -59,630 |
| L1D load miss | 3,020,381 | 3,016,138 | -4,243 |
| L1D unique to L2C | 320,510 | 320,394 | -116 |
| L2C load hit | 2,567 | 2,509 | -58 |
| L2C load miss | 317,943 | 317,885 | -58 |
| L2C load MSHR merge | 0 | 0 | 0 |
| LLC load miss | 317,704 | 317,678 | -26 |
| IPC | 0.323137 | 0.333611 | +3.24% |

`Berti + NoL2` 下，`ideal_all` 基本符合预期：

- 所有 STLB miss 被消除。
- L1D/L2C/LLC miss 没有明显恶化。
- 没有 L2C Pythia，因此不存在 L2C prefetcher 被 timing perturbation 搅乱的问题。
- IPC 上升 3.24%。

这说明如果没有 L2C prefetcher 的负交互，STLB idealization 的收益可以正常体现出来。

### NoL1D + Pythia 的轻微下降

| 指标 | pref | ideal_all | delta |
|---|---:|---:|---:|
| STLB total miss | 65,447 | 0 | -65,447 |
| STLB L1D prefetch miss | 0 | 0 | 0 |
| STLB demand miss | 65,447 | 0 | -65,447 |
| L1D load miss | 8,134,508 | 8,132,860 | -1,648 |
| L1D unique to L2C | 3,504,821 | 3,504,630 | -191 |
| L2C load hit | 2,347,549 | 2,390,702 | +43,153 |
| L2C load miss | 1,157,272 | 1,113,928 | -43,344 |
| L2C load MSHR merge | 1,075,850 | 1,007,353 | -68,497 |
| L2C unique to LLC | 81,422 | 106,575 | +25,153 |
| LLC load miss | 81,240 | 106,358 | +25,118 |
| L2C prefetch issued | 17,746,208 | 15,622,292 | -2,123,916 |
| L2C prefetch useful | 3,422,363 | 3,397,035 | -25,328 |
| L2C prefetch useless | 53,413 | 52,701 | -712 |
| L2C prefetch accuracy | 0.192850 | 0.217448 | +0.024598 |
| IPC | 0.313331 | 0.308127 | -1.66% |

这个配置没有 L1D Berti，因此不是 L1D prefetch translation timing 的问题。`ideal_all` 消除了 demand translation miss 后，L2C hit/miss 方向本身看起来变好：

- L2C hit 增加 43,153。
- L2C miss 减少 43,344。

但 MSHR merge 减少 68,497，幅度更大。因此：

`L2C unique to LLC = L2C load miss - L2C load MSHR merge`

- pref: `1,157,272 - 1,075,850 = 81,422`
- ideal_all: `1,113,928 - 1,007,353 = 106,575`
- 差值: `+25,153`

所以虽然 L2C miss 总数下降，真正下发到 LLC 的 unique demand 反而增加，LLC load miss 增加 25,118，IPC 轻微下降。

这说明 `ideal_all` 会改变 demand execution timing 和 MSHR overlap。即使没有 L1D prefetcher，也可能因为 overlap/merge 减少而让 LLC 层面变差。

## 总体结论

这组 gcc matrix 实验给出的结论不是“ideal STLB 一定提升”或“prefetcher 一定有害”，而是更细：

1. `ideal_l1pref` 只在 `Berti + Pythia` 中明显下降。  
   `Berti + NoL2` 小幅上升，`NoL1D + Pythia` 完全不变。

2. `Berti + Pythia` 的 `ideal_l1pref` 下降来自 L1D Berti timing 改变和 L2C Pythia 的负交互。  
   证据是：没有 Pythia 时，同样的 L1D Berti idealization 不会让 L2C/LLC 变差。

3. `ideal_all` 不是严格性能上界。  
   它消除了 STLB miss，但同时也改变执行时序、cache replacement、prefetcher training、MSHR overlap。最终 IPC 可能上升，也可能下降。

4. `Berti + Pythia` 在 baseline 中仍然最强。  
   pref Berti+Pythia IPC 为 0.548336，明显高于 pref Berti+NoL2 的 0.323137 和 pref NoL1D+Pythia 的 0.313331。说明 Pythia 正常情况下很有价值。

5. 需要区分现象和因果。  
   “L2C demand access 表现出更差的 hit/merge 行为”是现象；通过 `Berti + NoL2` 的对照可以进一步判断，在 `ideal_l1pref` 的下降案例中，这个现象与 L2C Pythia 的参与密切相关。



# 对比的是/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/results/test-gcc-ideal-l1pref-prefetch-matrix的结果

对，刚才我比较错目录了，抱歉。现在看的是：

[results/test-gcc-ideal-l1pref-prefetch-matrix](/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/results/test-gcc-ideal-l1pref-prefetch-matrix)

这组只有 `602.gcc_s-2226B`，ROI 50M。`pref` vs `ideal_all` 的同配置对比如下：

| 配置 | pref IPC | ideal_all IPC | 变化 |
|---|---:|---:|---:|
| Berti + Pythia | 0.548336 | 0.515755 | **-5.94%** |
| Berti + NoL2 | 0.323137 | 0.333611 | **+3.24%** |
| NoL1D + Pythia | 0.313331 | 0.308127 | **-1.66%** |

对应 cycle：

| 配置 | pref cycles | ideal_all cycles | 变化 |
|---|---:|---:|---:|
| Berti + Pythia | 91,185,030 | 96,945,222 | +5,760,192 |
| Berti + NoL2 | 154,733,093 | 149,875,150 | -4,857,943 |
| NoL1D + Pythia | 159,575,432 | 162,270,678 | +2,695,246 |

所以这组 gcc matrix 里，`ideal_all` 不是总下降：  
`Berti + Pythia` 下降最明显，`NoL1D + Pythia` 轻微下降，但 `Berti + NoL2` 反而提升。

这个结果对我们的猜想很有用：gcc 的 `ideal_all` IPC 下降不是单纯因为“消除了 STLB miss”，而是和 prefetcher 组合强相关，尤其是带 `Pythia` 的 L2C 组合更容易出现性能反向。数据来自 [gcc_ideal_prefetch_matrix_summary.csv](/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/csv_figure/test-gcc-ideal-l1pref-prefetch-matrix/gcc_ideal_prefetch_matrix_summary.csv)。





# 再次对比一下pref和ideal l1pref的数据

这次看的是 [test-gcc-ideal-l1pref-prefetch-matrix](/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/results/test-gcc-ideal-l1pref-prefetch-matrix) 这套 `602.gcc_s-2226B` 结果。

**IPC 对比**

| 配置 | pref IPC | ideal_l1pref IPC | 变化 |
|---|---:|---:|---:|
| Berti + Pythia | 0.548336 | 0.524958 | **-4.26%** |
| Berti + NoL2 | 0.323137 | 0.324163 | **+0.32%** |
| NoL1D + Pythia | 0.313331 | 0.313331 | **0.00%** |

**关键链条**

| 配置 | STLB L1D-pref miss | L1D miss | L2C load miss | L2C MSHR merge | LLC load miss |
|---|---:|---:|---:|---:|---:|
| Berti+Pythia delta | -6111 | -78082 | **+4849** | **-17562** | **+22311** |
| Berti+NoL2 delta | -6088 | -3995 | -1662 | 0 | -1631 |
| NoL1D+Pythia delta | 0 | 0 | 0 | 0 | 0 |

所以结论很清楚：

`ideal_l1pref` 对 **Berti + Pythia** 是负收益：虽然消除了 L1D prefetch 的 STLB miss，也让 L1D miss 减少了，但 L2C 层面反而 miss 增加、MSHR merge 大幅减少，最终 LLC load miss 多了 22,311 个，IPC 下降 4.26%。

`Berti + NoL2` 则是轻微正收益：没有 Pythia 后，L2C miss 和 LLC miss 都小幅下降，所以 IPC +0.32%。

`NoL1D + Pythia` 完全不变，这点也很关键：没有 L1D prefetcher 时，`ideal_l1pref` 没有可以理想化的 L1D prefetch translation miss，所以结果逐项一致。

数据源是 [gcc_ideal_prefetch_matrix_delta_vs_same_pref.csv](/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/csv_figure/test-gcc-ideal-l1pref-prefetch-matrix/gcc_ideal_prefetch_matrix_delta_vs_same_pref.csv)。




# 之前我们看到的是berti + pythia组合中，L2C上的aceess多数是无局部性从而导致miss更多的，当时分析的这个断论和pythia无关呀？
所以为什么现在会表现出这种情况呢？
这样的对比实验情况，可以得出性能下降是由pythia在L2C倒腾导致的


对，你抓到关键矛盾了。之前那句话应该修正：

**“Berti+Pythia 里 ideal_l1pref 后，L2C 看到的 demand 行为表现为局部性/重叠性变差”是现象；但它不是一个和 Pythia 无关的因果结论。**

现在这个 ablation 能把因果链分开看了。

`Berti + NoL2` 下：

| 指标 | pref | ideal_l1pref | delta |
|---|---:|---:|---:|
| IPC | 0.323137 | 0.324163 | +0.32% |
| L1D miss | 3,020,381 | 3,016,386 | -3,995 |
| L2C access | 320,510 | 318,855 | -1,655 |
| L2C hit | 2,567 | 2,574 | +7 |
| L2C miss | 317,943 | 316,281 | -1,662 |
| LLC miss | 317,704 | 316,073 | -1,631 |

这就是“正常直觉”：L1D 稍微变好，给 L2C 的 demand 少一点，L2C/LLC miss 也少一点，IPC 小幅上升。

但 `Berti + Pythia` 下：

| 指标 | pref | ideal_l1pref | delta |
|---|---:|---:|---:|
| IPC | 0.548336 | 0.524958 | -4.26% |
| L1D miss | 1,573,723 | 1,495,641 | -78,082 |
| L2C access | 265,320 | 249,714 | -15,606 |
| L2C hit | 152,960 | 132,505 | **-20,455** |
| L2C miss | 112,360 | 117,209 | **+4,849** |
| L2C MSHR merge | 39,123 | 21,561 | **-17,562** |
| LLC miss | 73,139 | 95,450 | **+22,311** |

所以现在更准确的解释是：

**ideal_l1pref 改变了 L1D Berti 的 prefetch/translation timing；这个变化本身不一定坏。没有 L2C Pythia 时，它是小幅正收益。但有 Pythia 时，这个 timing 改变会扰动 L2C 的 prefetch 训练、填充、替换和 MSHR overlap，于是 L2C demand hit 变少、merge 变少，最终 LLC miss 变多，IPC 下降。**

也就是说，你现在这个对比实验确实支持：

**gcc 这个 trace 中，`pref -> ideal_l1pref` 的性能下降不是 Berti 单独导致的，而是 Berti 的 L1D timing 改变和 L2C Pythia 的负交互导致的。**

但要注意一句话的边界：不是“Pythia 绝对有害”。非理想 baseline 里，`Berti+Pythia` 的 IPC 是 `0.548336`，远高于 `Berti+NoL2` 的 `0.323137`。所以 Pythia 在正常条件下很有用。

更精确地说：

**Pythia 正常情况下提升性能；但是当 ideal_l1pref 消除了 L1D prefetch 的 STLB miss 后，L1D Berti 的时序变化让 Pythia 在 L2C 层产生了负交互，把一部分原本能 hit/merge 的 demand 变成了更贵的 LLC miss。**





# 对比一下berti+no，berti+ip_stride，berti+pythia；在pref、ideal l1pref、ideal all三种情况下的IPC变化，是不是呈现我们上面讨论的基本规律的

是的，基本呈现我们上面讨论的规律，而且 `ip_stride` 这个结果把结论卡得更准了：

**不是“有 L2C prefetcher 就会下降”，而是 Pythia 这种 L2C prefetcher 对 ideal STLB 改变 timing 特别敏感。**

**IPC 总表**

| L2C 配置 | pref IPC | ideal_l1pref IPC | ideal_all IPC |
|---|---:|---:|---:|
| Berti + NoL2 | 0.323137 | 0.324163 | 0.333611 |
| Berti + IPStride | 0.442265 | 0.443237 | 0.466798 |
| Berti + Pythia | 0.548336 | 0.524958 | 0.515755 |

**相对同配置 pref 的变化**

| L2C 配置 | ideal_l1pref vs pref | ideal_all vs pref |
|---|---:|---:|
| Berti + NoL2 | **+0.32%** | **+3.24%** |
| Berti + IPStride | **+0.22%** | **+5.55%** |
| Berti + Pythia | **-4.26%** | **-5.94%** |

所以规律很清楚：

1. `NoL2`：STLB ideal 后性能上升，符合直觉。
2. `IPStride`：也上升，说明普通/较简单的 L2C prefetcher 没有把 timing 变化放大成负收益。
3. `Pythia`：明显下降，说明下降更像是 **Berti timing 改变 + Pythia 动态训练/填充/MSHR 行为** 的负交互。

关键指标也支持这个判断。

**pref -> ideal_l1pref**

| 配置 | L1D miss delta | L2C miss delta | L2C merge delta | LLC miss delta | IPC |
|---|---:|---:|---:|---:|---:|
| Berti+NoL2 | -3,995 | -1,662 | 0 | -1,631 | +0.32% |
| Berti+IPStride | -6,463 | -475 | -900 | +421 | +0.22% |
| Berti+Pythia | -78,082 | +4,849 | -17,562 | +22,311 | -4.26% |

`IPStride` 这里有一点轻微扰动：LLC miss 多了 421，但很小，STLB/L1D 收益还能盖住它，所以 IPC 仍然上升。  
`Pythia` 则是 LLC miss 多了 22,311，量级完全不同，所以性能下降。

**pref -> ideal_all**

| 配置 | L1D miss delta | L2C miss delta | L2C merge delta | LLC miss delta | IPC |
|---|---:|---:|---:|---:|---:|
| Berti+NoL2 | -4,243 | -58 | 0 | -26 | +3.24% |
| Berti+IPStride | +45,537 | +1,779 | -109 | +1,887 | +5.55% |
| Berti+Pythia | +356,355 | +29,362 | -25,393 | +54,677 | -5.94% |

`ideal_all` 下 `IPStride` 虽然也有一些 cache miss 变差，但没有 Pythia 那种 prefetch 质量崩掉和 LLC miss 暴涨。Pythia 的 `ideal_all` 里，L2C prefetch useful 从 1,731,927 掉到 791,053，useless 从 1,567,059 涨到 2,384,793，这是很强的负交互证据。

所以最终结论是：

**Pythia baseline 性能仍然最好，但它对 ideal STLB 引入的 timing perturbation 最敏感；NoL2 和 IPStride 都没有出现这种反向收益。这基本支持我们之前的判断：gcc 里 ideal_l1pref / ideal_all 下降，不是 Berti 单独的问题，也不是所有 L2C prefetcher 的问题，而主要是 Berti 与 L2C Pythia 的负交互。**
