# too-early 指标实现完整说明

本文档记录当前 ChampSim 工程中新增的 too-early 统计指标的整体实现思路。这个修改是 stats-only，不改变 ChampSim 原有 cache/TLB/prefetch/replacement 的功能行为。

## 1. 统计目标

too-early 关注的是一种“预取来得太早”的情况：

1. prefetch 成功 fill 进入 cache 或 TLB；
2. 该 prefetch entry 在被后续 demand 使用之前被替换出去；
3. 被替换出去之后，同一个 cache line 或 VPN 又发生 demand miss；
4. 如果这个 demand miss 发生在有限 shadow FIFO 窗口内，就认为之前那个 prefetch 是 too-early。

因此 too-early 不是“prefetch miss”、也不是“useless prefetch”的简单别名。它是 useless prefetch 里更具体的一类：这个预取本来方向可能是对的，但提前太多，导致 fill 后还没被 demand 用到就被淘汰。

## 2. 支持的结构

当前实现覆盖两类对象。

第一类是 cache prefetch too-early：

- 典型关注对象是 L1D data prefetch；
- key 使用 cache line 粒度；
- 指标打印为 `Core_N_L1D_prefetch_too_early` 和相关比例字段。

第二类是 TLB cross-page prefetch too-early：

- 关注 L1D cross-page prefetch 引发的 translation prefetch；
- 分别在 DTLB、STLB 和 DTLB+STLB 聚合视角下统计；
- key 使用 VPN + ASID + CPU；
- 指标打印为 `Core_N_DTLB_cross_page_prefetch_too_early`、`Core_N_STLB_cross_page_prefetch_too_early`、`Core_N_TLB_cross_page_prefetch_too_early` 和相关比例字段。

## 3. 新增数据结构

主要代码在 `inc/cache.h` 和 `src/cache.cc`。

### 3.1 cache prefetch shadow

在 `CACHE` 类中新增：

```cpp
prefetch_too_early_key
prefetch_too_early_fifo
prefetch_too_early_shadow
```

`prefetch_too_early_key` 包含：

- `cpu`
- cache line address

当一个 prefetched cache block 被淘汰且还没有被 demand 使用时，将它的 key 放入 FIFO 和 shadow map。之后如果同一个 key 发生 demand miss，则消费这个 shadow entry，并计一次 cache prefetch too-early。

### 3.2 TLB cross-page prefetch shadow

在 `CACHE` 类中新增：

```cpp
tlb_cross_prefetch_too_early_fifo
tlb_cross_prefetch_too_early_shadow
```

TLB key 包含：

- `cpu`
- VPN
- ASID

当 DTLB/STLB 中一个由 L1D cross-page prefetch fill 进来的 translation 被淘汰，并且还没有被 demand 使用时，将它放入对应 TLB 结构自己的 shadow FIFO。之后如果同一个 VPN/ASID 发生 demand TLB miss，则消费这个 shadow entry，并计一次 TLB cross-page prefetch too-early。

### 3.3 TLB-system 聚合 shadow

除了 DTLB/STLB 各自的局部统计，还维护了一个 DTLB+STLB 聚合视角：

```cpp
tlb_system_cross_prefetch_too_early_fifo
tlb_system_cross_prefetch_too_early_shadow
```

这个聚合视角用于打印 `Core_N_TLB_cross_page_prefetch_too_early`。它表示从整个 data-side TLB system 看，某个 cross-page prefetch translation 曾经进入 DTLB/STLB，但在 demand 使用前被淘汰，之后 demand 仍然发生 TLB-system miss。

## 4. Shadow FIFO 窗口大小

too-early 不是无限时间匹配，而是有限窗口匹配。

当前窗口大小按结构独立计算：

```text
shadow_fifo_size = NUM_SET * NUM_WAY
```

也就是说：

- L1D 使用自己的 set/way；
- DTLB 使用自己的 set/way；
- STLB 使用自己的 set/way；
- 其他 cache 如果打印 cache prefetch too-early，也会使用自身 set/way。

这样避免了所有结构共用固定 4096 entry 的不合理情况。

## 5. cache prefetch too-early 计数流程

### 5.1 淘汰时记录 candidate

在 cache fill 选择 victim 后，如果 victim 是有效 prefetch block，并且它被淘汰前没有被 demand 使用，那么原有逻辑会计入 `pf_useless`。

在这个位置额外做 stats-only 记录：

```text
remember_prefetch_too_early_candidate(victim)
```

这个函数只把 victim 的 cache line key 放进 shadow FIFO/map，不改变 victim 选择、不改变 replacement 状态、不改变 cache 内容。

### 5.2 demand miss 时消费 candidate

在 cache miss 处理路径中，如果当前请求是 demand data access，也就是 `LOAD` 或 `RFO`，则用当前 miss 的 cache line key 查询 shadow map。

如果命中 shadow map：

```text
pf_too_early++
```

随后移除该 shadow entry，避免同一个被淘汰 prefetch 被后续多个 demand miss 重复计数。

### 5.3 demand hit 时丢弃 candidate

如果同一个 cache line 后续发生 demand hit，说明它此时已经不应该再被视为“被过早淘汰后又 miss”。因此在 demand hit 路径会丢弃对应 shadow entry，避免未来误计。

## 6. TLB cross-page prefetch too-early 计数流程

### 6.1 cross-page prefetch translation 的来源识别

vBerti 在生成 prefetch candidate 时，通过 metadata 标记该 prefetch 是 same-page 还是 cross-page。

cache 发起 translation 后，DTLB/STLB 侧通过 `translation_origin` 识别：

```text
L1D_PREFETCH_SAME_PAGE
L1D_PREFETCH_CROSS_PAGE
```

too-early 当前只针对 `L1D_PREFETCH_CROSS_PAGE` 这类 translation prefetch 做质量统计。

### 6.2 TLB fill 时标记 block

当 cross-page prefetch translation miss 后完成 fill，填入 DTLB 或 STLB 的 block 会带上 metadata：

```text
tlb_cross_prefetch = true
tlb_cross_prefetch_used = false
```

这个标记只用于统计：表示该 TLB entry 是由 L1D cross-page prefetch 带入的，并且目前还没有被 demand 使用。

### 6.3 demand hit 时计 useful

如果后续 demand translation 在 DTLB/STLB 命中这个 `tlb_cross_prefetch` entry，并且它此前还没有被用过，则：

```text
tlb_cross_prefetch_useful++
tlb_cross_prefetch_used = true
```

同时从 too-early shadow 中丢弃同 key 的旧记录，避免一个已经被 demand hit 使用的 VPN 被未来误计成 too-early。

### 6.4 demand miss 时处理 late 和 too-early

如果 demand miss 到来时，同一 VPN 的 cross-page prefetch translation 已经发起但还没有完成，则计为 late：

```text
tlb_cross_prefetch_useful++
tlb_cross_prefetch_late++
```

late 表示方向正确但来晚了。为了避免重复分类，同一个 demand miss 如果已经计为 late，就不会再计为 too-early。

如果没有计 late，再查询 too-early shadow map。若命中，则：

```text
tlb_cross_prefetch_too_early++
```

这表示之前确实有 cross-page prefetch translation fill 进来过，但它在 demand 到来前已经被淘汰了。

### 6.5 TLB entry 淘汰时记录 candidate

当 DTLB/STLB 中的 victim 满足：

```text
victim.tlb_cross_prefetch == true
victim.tlb_cross_prefetch_used == false
```

说明该 entry 是 cross-page prefetch 带入的 translation，并且还没有被 demand 使用。此时：

```text
tlb_cross_prefetch_useless++
remember_tlb_cross_prefetch_too_early_candidate(victim)
```

局部 DTLB/STLB 指标使用各自结构的 shadow FIFO。

TLB-system 聚合指标也在这个淘汰点更新 shadow 记录，插入时使用发生淘汰的那个 TLB 结构自己的 `NUM_SET * NUM_WAY` 窗口。

## 7. ROI 处理

too-early 相关计数只统计 ROI。

在 `begin_phase()` 中会清空：

- cache prefetch too-early FIFO/map；
- TLB cross-page prefetch pending；
- TLB cross-page prefetch too-early FIFO/map；
- TLB-system cross-page prefetch状态。

这样 warmup 阶段遗留的 shadow entry 不会污染 ROI 统计。

在 `end_phase()` 中把 sim stats 拷贝到 ROI stats：

- `pf_too_early`
- `tlb_cross_prefetch_too_early`
- `tlb_system_cross_prefetch_too_early`

因此最终 result log 中打印的是 ROI 内的统计。

## 8. 打印字段

### 8.1 cache prefetch

新增或相关字段包括：

```text
Core_N_L1D_prefetch_fill
Core_N_L1D_prefetch_too_early
Core_N_L1D_prefetch_too_early_among_fill
Core_N_L1D_prefetch_too_early_among_useless
```

其中：

```text
prefetch_too_early_among_fill = prefetch_too_early / prefetch_fill
prefetch_too_early_among_useless = prefetch_too_early / prefetch_useless
```

### 8.2 DTLB/STLB cross-page prefetch

新增或相关字段包括：

```text
Core_N_DTLB_cross_page_prefetch_fill
Core_N_DTLB_cross_page_prefetch_too_early
Core_N_DTLB_cross_page_prefetch_too_early_among_fill
Core_N_DTLB_cross_page_prefetch_too_early_among_useless

Core_N_STLB_cross_page_prefetch_fill
Core_N_STLB_cross_page_prefetch_too_early
Core_N_STLB_cross_page_prefetch_too_early_among_fill
Core_N_STLB_cross_page_prefetch_too_early_among_useless
```

其中：

```text
cross_page_prefetch_too_early_among_fill =
  cross_page_prefetch_too_early / cross_page_prefetch_fill
```

### 8.3 TLB-system 聚合

相关字段包括：

```text
Core_N_TLB_cross_page_prefetch_too_early
Core_N_TLB_cross_page_prefetch_too_early_among_fill
Core_N_TLB_cross_page_prefetch_too_early_among_useless
```

其中：

```text
TLB_cross_page_prefetch_too_early_among_fill =
  TLB_cross_page_prefetch_too_early /
  (DTLB_cross_page_prefetch_fill + STLB_cross_page_prefetch_fill)
```

## 9. 与已有 useful/useless/late 的关系

too-early 与 existing cache/TLB prefetch quality 指标的关系如下：

- useful：prefetch fill 后被后续 demand hit 使用；
- late：prefetch 方向正确，但 demand 到来时 prefetch translation/data 还没有完成；
- useless：prefetch 在 ROI 结束或被淘汰前没有被 demand 使用；
- too-early：useless 中更具体的一种，表示它被淘汰后，同一 cache line/VPN 又发生 demand miss。

实现中特别避免了一个 demand miss 同时计 late 和 too-early：

- 如果 pending prefetch 命中并计 late，则不再查询 too-early shadow；
- 如果没有计 late，才允许查询 shadow 并计 too-early。

## 10. 不改变模拟行为的保证

本次 too-early 实现只新增统计字段和 shadow 数据结构，不参与：

- cache replacement victim 选择；
- TLB replacement victim 选择；
- prefetcher 生成逻辑；
- prefetch path 是否接收请求；
- MSHR/PQ/RQ/WQ 入队逻辑；
- TLB/PTW translation 时序。

shadow FIFO/map 只是旁路记录，不会反馈到 ChampSim 的核心建模逻辑。

## 11. 主要修改文件

源码相关：

- `inc/cache.h`：新增 too-early key、FIFO/map 成员和辅助函数声明；
- `inc/cache_stats.h`：新增 too-early 统计字段；
- `src/cache.cc`：实现 too-early shadow 记录、消费、清理和 ROI 统计；
- `src/cache_stats.cc`：支持 stats 差分；
- `src/plain_printer.cc`：打印 too-early 计数和比例；
- `src/json_printer.cc`：JSON stats 中加入 too-early 原始计数。

文档相关：

- `docs_my/tlb_vberti_new_metrics_dictionary.md`
- `docs_my/too_early_among_fill修改说明.md`
- `docs_my/too_early指标实现完整说明.md`
