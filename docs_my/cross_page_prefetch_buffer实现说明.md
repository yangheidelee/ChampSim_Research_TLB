# STLB Cross-page Prefetch Buffer 实现说明

本文档记录本次在 ChampSim 中添加 STLB Cross-page Prefetch Buffer, CP-PB 的实现思路，以及新增结果指标的含义。

## 目标

本次修改用于验证一个归因问题：

vBerti 的 cross-page data prefetch translation 对 TLB 系统效果不明显，是否是因为这些 translation 正常 fill 到 STLB 后污染 STLB，替换掉后续 demand-useful 的 translation。

因此新增一个实验性 CP-PB：

- 默认关闭，不影响 baseline。
- 只有运行 bin 时显式添加 `--enable-stlb-cp-pb` 才开启。
- 开启后，只改变 vBerti cross-page prefetch translation 在 STLB 层的 fill/lookup 行为。

## 总体建模语义

baseline 行为保持不变：

```text
vBerti cross-page prefetch
  -> DTLB lookup
  -> STLB lookup
  -> STLB miss 后走 PTW
  -> translation 返回后正常 fill STLB
```

开启 `--enable-stlb-cp-pb` 后：

```text
vBerti cross-page prefetch
  -> DTLB lookup
  -> STLB lookup
  -> STLB miss 后走 PTW
  -> translation 返回到 STLB fill 路径
  -> 不 fill STLB
  -> 插入 CP-PB
```

后续 demand data 访问：

```text
demand DTLB miss
  -> STLB lookup
  -> 如果 STLB hit，正常返回 translation
  -> 如果 STLB miss，先记录 raw demand miss
      -> 查 CP-PB
          -> CP-PB hit：直接返回 translation，fill STLB，fill DTLB，不触发 PTW
          -> CP-PB miss：正常走 PTW
```

CP-PB hit 被建模为 ideal/oracle hit，不额外增加访问延迟。

## 代码修改位置

### 命令行开关

在 `src/main.cc` 中新增：

```text
--enable-stlb-cp-pb
```

该参数写入 `champsim::enable_stlb_cp_pb`。这个全局开关声明在 `inc/champsim.h`，定义在 `src/cache.cc`。

### CP-PB 数据结构

在 `inc/cache.h` 的 `CACHE` 内部新增：

```text
stlb_cp_pb_entry
std::map<tlb_prefetch_key, stlb_cp_pb_entry> stlb_cp_pb
```

key 使用现有 TLB prefetch key：

```text
cpu + VPN + ASID
```

这样比单独 VPN 更稳妥，可以避免不同 CPU 或不同 ASID 下同一 VPN 混淆。

entry 保存的信息包括：

- physical translated address
- virtual address
- translated page data
- prefetch metadata
- cpu
- ASID

这些信息足够在 CP-PB hit 后生成 translation response，并将该 translation 作为 demand-useful translation 填回 STLB。

### cross-page prefetch fill 重定向

修改位置：

```text
src/cache.cc
CACHE::handle_fill()
```

当满足以下条件时：

```text
enable_stlb_cp_pb == true
当前 cache 是 STLB
fill_mshr.translation_source == L1D_PREFETCH_CROSS_PAGE
```

则不执行普通 STLB block fill，而是：

```text
insert_stlb_cp_pb(fill_mshr)
CP_PB_insert++
继续向上层返回 translation response
```

这里必须继续向上层返回 response，因为 STLB fill 路径同时负责把 translation 返回给上层 DTLB。如果直接 return 而不返回 response，会破坏原本的 translation 流。

### demand data STLB miss 后查询 CP-PB

修改位置：

```text
src/cache.cc
CACHE::handle_miss()
```

在 STLB miss 后、真正向 PTW/lower level 发送请求之前，调用：

```text
try_stlb_cp_pb_demand_hit(handle_pkt)
```

该函数只处理：

```text
enable_stlb_cp_pb == true
当前 cache 是 STLB
translation_source == DEMAND_DATA
```

也就是说，本次 CP-PB 只救 demand data translation miss，不救 instruction demand miss。原因是 CP-PB 的来源是 L1D vBerti cross-page data prefetch，用它去覆盖 instruction-side translation miss 会混淆归因。

如果 CP-PB hit：

- `STLB_raw_demand_miss++`
- `CP_PB_demand_hit++`
- 不向 PTW 发送请求
- 不分配 STLB miss MSHR
- 用 CP-PB 中保存的 translation 返回给上层 DTLB
- 同时将该 translation fill 回 STLB
- 删除 CP-PB 中对应 entry

如果 CP-PB miss 或者开关关闭，则走原始 `handle_miss()` 路径。

## baseline 行为保持

未添加 `--enable-stlb-cp-pb` 时：

- `should_redirect_stlb_cp_pb_fill()` 恒为 false。
- `try_stlb_cp_pb_demand_hit()` 恒为 false。
- vBerti cross-page prefetch translation 仍然正常 fill STLB。
- demand STLB miss 仍然正常触发 PTW。
- CP-PB 不插入、不命中、不参与功能路径。

因此原始 cache/TLB/PTW 行为不被改变。

## ROI 统计口径

新增 counter 放在 `cache_stats` 中，并在以下位置接入：

- `inc/cache_stats.h`
- `src/cache_stats.cc`
- `CACHE::end_phase()`
- `src/plain_printer.cc`
- `src/json_printer.cc`

由于 ChampSim 当前 ROI 统计是通过 `roi_stats = sim_stats` 的 phase 统计体系输出，因此这些新增指标和现有 cache/TLB 指标一样，都是 ROI 口径。

## 新增指标含义

### Core_0_STLB_raw_demand_miss

STLB 本体没有命中的 demand data miss 数。

这里的 raw 表示不考虑 CP-PB 是否救回。即使后续 CP-PB hit，这次访问仍然算作 STLB raw demand miss，因为 STLB 本体确实 miss 了。

### Core_0_CP_PB_insert

插入 CP-PB 的 translation 数。

只统计原本会 fill STLB 的 vBerti cross-page prefetch translation。demand translation、same-page prefetch translation、instruction prefetch translation 都不会进入 CP-PB。

### Core_0_CP_PB_demand_hit

demand data STLB miss 后，查询 CP-PB 命中的次数。

该指标表示 CP-PB 中保存的 cross-page prefetch translation 被后续 demand data 访问真正用到了。

### Core_0_STLB_PB_demand_miss

经过 CP-PB 之后仍然没有被救回、最终需要走 PTW 的 demand data STLB miss 数。

理论关系为：

```text
STLB_PB_demand_miss = STLB_raw_demand_miss - CP_PB_demand_hit
```

### Core_0_CP_PB_coverage

CP-PB 对 raw demand data STLB miss 的覆盖率。

计算方式：

```text
CP_PB_coverage = CP_PB_demand_hit / STLB_raw_demand_miss
```

如果分母为 0，则打印 0。

### Core_0_STLB_raw_demand_mpki

raw demand data STLB miss 的 MPKI。

计算方式：

```text
STLB_raw_demand_mpki = STLB_raw_demand_miss / retired_instruction_count * 1000
```

### Core_0_STLB_PB_demand_mpki

经过 CP-PB 之后仍需要 PTW 的 demand data STLB miss MPKI。

计算方式：

```text
STLB_PB_demand_mpki = STLB_PB_demand_miss / retired_instruction_count * 1000
```

### Core_0_CP_PB_demand_hit_mpki

CP-PB demand hit 的 MPKI。

计算方式：

```text
CP_PB_demand_hit_mpki = CP_PB_demand_hit / retired_instruction_count * 1000
```

## 验证结果

使用当前 bin 做过冒烟测试：

```text
bin/mcf-footprint-l1pref-1core
trace: /data0/tzh/champsim_traces/SPEC17/605.mcf_s-1536B.champsimtrace.xz
```

baseline 小跑结果中：

```text
Core_0_CP_PB_insert 0
Core_0_CP_PB_demand_hit 0
Core_0_STLB_PB_demand_miss == Core_0_STLB_raw_demand_miss
```

开启 `--enable-stlb-cp-pb` 的 2M ROI 冒烟中：

```text
Core_0_STLB_raw_demand_miss 44761
Core_0_CP_PB_insert 12
Core_0_CP_PB_demand_hit 1
Core_0_STLB_PB_demand_miss 44760
```

说明 CP-PB insert 路径和 demand data STLB miss 救援路径均已实际触发。
