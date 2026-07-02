# DRAM RQ Read Traffic 来源分类统计修改记录

## 目标

本次修改的目标是在 ChampSim 的 DRAM Read Queue 入口处，统计真正成功进入 DRAM RQ 的 read request 来源组成。

这个统计不是 cache access、cache miss、STLB miss，也不是 PTW 发起尝试次数，而是：

```text
request 成功进入 MEMORY_CONTROLLER 的 DRAM RQ 之后才计数
```

因此它反映的是最终占用 DRAM read queue / DRAM read traffic 的请求组成。

## 核心统计点

统计点放在：

```text
src/dram_controller.cc
MEMORY_CONTROLLER::add_rq(...)
```

具体逻辑是在 `add_rq()` 中成功找到空闲 DRAM RQ entry，并把 request 写入 `channel.RQ` 之后，再进行分类计数。

这样可以保证：

- DRAM RQ 满导致没有成功进入的 request 不统计。
- 上层 cache miss 或 PTW 发起尝试不统计。
- 只统计 read queue，不统计 WQ/write request。
- 多级 PTW 每一级 page-table read 只有在真正进入 DRAM RQ 后才统计。

## 新增统计字段

新增字段放在：

```text
inc/dram_stats.h
```

字段包括 8 个细分类：

```text
rq_read_data_demand
rq_read_inst_demand
rq_read_cache_inst_prefetch
rq_read_cache_data_prefetch
rq_read_stlb_data_demand
rq_read_stlb_inst_demand
rq_read_stlb_l1i_pref
rq_read_stlb_l1d_pref
```

以及 debug 字段：

```text
rq_read_unclassified
rq_read_total_observed
```

这些字段也补进了：

```text
src/dram_stats.cc
```

用于保证 `dram_stats operator-` 的差分逻辑完整。

## 分类逻辑

DRAM RQ 入口处根据 `packet.type`、`packet.is_instr` 和 `packet.translation_source` 分类。

普通 cache-line read：

- `LOAD && !is_instr` -> `data_demand_read`
- `LOAD && is_instr` -> `inst_demand_read`
- `RFO` -> `data_demand_read`
- `PREFETCH && is_instr` -> `cache_inst_prefetch`
- `PREFETCH && !is_instr` -> `cache_data_prefetch`

translation / PTW read：

- `TRANSLATION && translation_source == DEMAND_DATA` -> `stlb_data_demand`
- `TRANSLATION && translation_source == DEMAND_INSTRUCTION` -> `stlb_inst_demand`
- `TRANSLATION && translation_source == L1I_PREFETCH` -> `stlb_l1i_pref`
- `TRANSLATION && translation_source == L1D_PREFETCH` -> `stlb_l1d_pref`

无法归类的 read request 会进入：

```text
unclassified_read
```

## Translation 来源保留

为了区分 PTW traffic 的原始来源，本次修改保留并传递了 `translation_source`。

相关修改：

```text
inc/ptw.h
src/ptw.cc
```

`PageTableWalker::mshr_type` 新增：

```cpp
translation_origin translation_source
```

PTW 初始 request 从上层 TLB/cache 继承 `translation_source`，后续每一级 page walk 继续把这个字段传给新的 `TRANSLATION` request。

这样一个 STLB miss 引发的多次 page-table read 都能继承原始来源，例如：

- data demand 引发的 STLB miss -> 每一级 PTW read 都计入 `stlb_data_demand`
- instruction demand 引发的 STLB miss -> 每一级 PTW read 都计入 `stlb_inst_demand`
- L1D prefetch 引发的 STLB miss -> 每一级 PTW read 都计入 `stlb_l1d_pref`
- L1I prefetch 引发的 STLB miss -> 每一级 PTW read 都计入 `stlb_l1i_pref`

## Cache Prefetch 来源标记

普通 cache prefetch traffic 本身也需要区分 instruction-side 和 data-side。

相关修改：

```text
src/cache.cc
CACHE::prefetch_line(...)
```

新增逻辑：

- 如果 cache 名字以 `_L1I` 结尾，则本地 prefetch request 标记 `is_instr = true`，并设置 `translation_source = L1I_PREFETCH`。
- 如果 cache 名字以 `_L1D` 结尾，则设置 `translation_source = L1D_PREFETCH`。

这样 L1I prefetch 取 instruction cache line 本身时，可以归入：

```text
cache_inst_prefetch
```

而 L1D prefetch 取 data cache line 本身时，可以归入：

```text
cache_data_prefetch
```

## 输出位置

最终 result 输出修改在：

```text
src/plain_printer.cc
```

新增函数：

```text
format_dram_rq_read_traffic(...)
```

它会汇总所有 DRAM channel 的 ROI `dram_stats`，并在 `[DRAM Statistics]` 后面追加新的 section。

JSON 输出也补充了对应字段：

```text
src/json_printer.cc
```

## 最终 Print 内容

新增 section 名称固定为：

```text
DRAM_RQ_READ_TRAFFIC_BREAKDOWN:
```

8 个细分类都会打印 count 和 share：

```text
data_demand_read.count = ...
data_demand_read.share = ...%

inst_demand_read.count = ...
inst_demand_read.share = ...%

cache_inst_prefetch.count = ...
cache_inst_prefetch.share = ...%

cache_data_prefetch.count = ...
cache_data_prefetch.share = ...%

stlb_data_demand.count = ...
stlb_data_demand.share = ...%

stlb_inst_demand.count = ...
stlb_inst_demand.share = ...%

stlb_l1i_pref.count = ...
stlb_l1i_pref.share = ...%

stlb_l1d_pref.count = ...
stlb_l1d_pref.share = ...%
```

随后打印 4 个汇总类别：

```text
DRAM_RQ_READ_TRAFFIC_SUMMARY:
```

```text
cache_demand.count = data_demand_read + inst_demand_read
cache_demand.share = ...%

cache_prefetch.count = cache_inst_prefetch + cache_data_prefetch
cache_prefetch.share = ...%

stlb_demand.count = stlb_data_demand + stlb_inst_demand
stlb_demand.share = ...%

stlb_prefetch.count = stlb_l1i_pref + stlb_l1d_pref
stlb_prefetch.share = ...%
```

最后打印 debug 信息：

```text
DRAM_RQ_READ_TRAFFIC_DEBUG:
```

```text
total_classified_read.count = 8 个细分类之和
unclassified_read.count = 无法归入 8 类的 read request
total_read_with_other.count = total_classified_read + unclassified_read

classified_plus_unclassified_check.count = total_classified_read + unclassified_read
dram_rq_read_total_observed.count = add_rq 成功处观察到的全部 DRAM RQ read request
dram_rq_read_total_observed.per_1K_instructions = dram_rq_read_total_observed / ROI instructions * 1000
```

正常情况下应该满足：

```text
classified_plus_unclassified_check.count == dram_rq_read_total_observed.count
```

## Share 分母

所有 8 个细分类和 4 个汇总类别的 share 使用同一个分母：

```text
total_classified_read
```

即：

```text
data_demand_read
+ inst_demand_read
+ cache_inst_prefetch
+ cache_data_prefetch
+ stlb_data_demand
+ stlb_inst_demand
+ stlb_l1i_pref
+ stlb_l1d_pref
```

`unclassified_read` 不进入 share 分母，只用于 debug。

当 `total_classified_read == 0` 时，share 安全输出为：

```text
0.00%
```

## Warmup / ROI 口径

统计字段保存在 `DRAM_CHANNEL::sim_stats` 中。

ChampSim 在每个 phase 开始时会调用：

```text
MEMORY_CONTROLLER::begin_phase()
```

这里会重置每个 channel 的 `sim_stats`。最终 result 打印的是非 warmup phase 的 ROI stats，所以 warmup traffic 不会混入最终输出。

## 验证情况

完成修改后执行：

```bash
make -j4
```

编译通过。

做过短 trace 冒烟测试，新增 section 正常输出，并且 debug check 成立。例如某次短 ROI 中：

```text
classified_plus_unclassified_check.count = 7611
dram_rq_read_total_observed.count = 7611
```

同时观察到 PTW traffic 被正确分类，例如：

```text
stlb_data_demand.count = 839
stlb_inst_demand.count = 28
stlb_l1d_pref.count = 7
```

这说明新增统计确实是在 DRAM RQ 入口处统计实际进入 read queue 的 translation read，而不是简单统计 STLB miss 数。

后续又补充了 DRAM RQ read request per 1K instructions 指标，只保留 `dram_rq_read_total_observed.per_1K_instructions`。分母是 ROI 阶段所有 core 的 retired instructions 总和。单核实验中，这个分母就是 `Core_0_instructions`。
