# Ordered PQ-full TLB Rescue 修改说明

## 实验目的

这个模式用于观察：vBerti 产生的 L1D cross-page prefetch 如果因为 L1D internal PQ full 原本会被 drop，但仍然允许它按原始顺序进入 TLB/STLB/PTW translation path，会不会减少后续 demand STLB miss，并带来 IPC 收益。

该实验只保留 translation-side effect，不产生 data-prefetch-side effect。

## 运行开关

新增运行时参数：

```bash
--ordered-pqfull-tlb-rescue
```

默认关闭。不加这个参数时，ChampSim 的原始 cache/TLB/prefetch 行为不变；只会多打印新增统计项。

## 实现思路

没有修改 vBerti 预取器源码。vBerti 仍然按原来的方式调用 `CACHE::prefetch_line()`。

在 `CACHE::prefetch_line()` 中，如果发现当前 prefetch 是 L1D vBerti cross-page prefetch，并且因为 `internal_PQ` 满而原本要返回 `false`，则：

- 关闭 `--ordered-pqfull-tlb-rescue` 时：保持原行为，直接 drop。
- 开启 `--ordered-pqfull-tlb-rescue` 时：不进入 L1D internal PQ，不做 L1D tag lookup，不产生 cache fill；而是进入一个 sideband rescue queue。

rescue queue 中的 entry 之后只向 `lower_translate` 发 translation request，因此会真实使用 DTLB/STLB/PTW 资源，但不会访问 L1D data cache，也不会分配 data cache MSHR。

## 顺序约束

为了避免 rescue prefetch 人为提前，给 vBerti prefetch candidate 加了一个内部递增的 `seq_id`。

正常进入 internal PQ 的 vBerti prefetch 和进入 rescue queue 的 cross-page prefetch 都记录这个 `seq_id`。rescue queue 只有在队首 entry 已经不晚于 internal PQ 中所有更老的 vBerti prefetch 时，才允许发 translation request。

每周期最多从 rescue queue 发出 1 个 translation-only request。正常 internal PQ translation path 优先保持原样，rescue path 不占用 internal PQ entry。

## Rescue Queue 容量

当前 rescue queue 固定为 16 entry。

这是有限硬件队列实验：因为 L1D internal PQ full 被 drop 的 cross-page prefetch，只有在 rescue queue 还有空位时，才能进入 sideband rescue queue，并等待后续 ordered translation-only issue。

因此当前实验会把 rescue queue capacity 作为一个明确变量。如果观察到：

```text
Core_0_CP_PF_PQFULL_drop > Core_0_CP_PF_PQFULL_TLB_rescue_enqueued
```

则差值 `drop - enqueued` 就是因为 rescue queue full 而最终没有被 rescue 的 cross-page prefetch 数量。

## 新增打印指标

`Core_0_vBerti_InPQ_Same_page_prefetch`：ROI 内 vBerti same-page prefetch 成功进入 L1D internal PQ 的数量。

`Core_0_vBerti_InPQ_Cross_page_prefetch`：ROI 内 vBerti cross-page prefetch 成功进入 L1D internal PQ 的数量。

`Core_0_CP_PF_PQFULL_drop`：ROI 内 L1D vBerti cross-page prefetch 因 L1D internal PQ full 而原本会被 drop 的数量。

`Core_0_CP_PF_PQFULL_TLB_rescue_enqueued`：开启 rescue 模式后，上述 PQ-full cross-page prefetch 成功进入 sideband rescue queue 的数量。

`Core_0_CP_PF_PQFULL_TLB_rescue_issued`：rescue queue 中成功向 TLB translation path 发出 translation-only request 的数量。

`Core_0_CP_PF_PQFULL_TLB_rescue_translated`：rescue translation request 收到 translation 返回并完成的数量。

## 验证记录

使用 `401.bzip2-38B`，warmup 50M、ROI 100M，对比旧日志：

- `pref` 默认模式：过滤新增打印行和 wall-clock 时间后，旧日志与新日志逐行一致。
- `pref + CP-PB` 默认模式：过滤新增打印行和 wall-clock 时间后，旧日志与新日志逐行一致。

短冒烟测试：

```bash
./bin/tlb-pref-1core \
  --warmup-instructions 1000000 \
  --simulation-instructions 2000000 \
  --hide-heartbeat \
  --ordered-pqfull-tlb-rescue \
  /data0/tzh/champsim_traces/SPEC06/401.bzip2-38B.champsimtrace.xz
```

结果中 `drop/enqueued/issued/translated` 均为 64752，说明该 case 下 rescue queue 没有成为瓶颈，PQ-full cross-page prefetch 都完成了 translation-only rescue。
