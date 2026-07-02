# STLB miss PTW DRAM touch 统计修改说明

本文记录 `STLB_MISS_PTW_DRAM_TOUCH_BREAKDOWN` 这一组统计的源码修改思路。

## 统计目标

目标是回答一个问题：

对于 ROI 阶段中的 STLB miss，它触发的 PTW 过程是否至少有一次 `TRANSLATION` read request 真正成功进入 DRAM Read Queue。

如果某个 STLB miss 对应的 PTW 过程中，任意一级 PTE 访问最终进入了 DRAM RQ，则记为：

```text
stlb_miss_touch_dram
```

如果整个 PTW 过程没有任何一次 `TRANSLATION` read request 进入 DRAM RQ，则记为：

```text
stlb_miss_no_dram_touch
```

这个指标不是统计 PTW 访问 DRAM 的次数，而是统计 STLB miss/unique PTW walk 是否 touch DRAM。

## 统计口径

统计单位采用 unique PTW walk。

在 ChampSim 中，多个上游请求可能在 channel/cache MSHR 中合并。如果多个 STLB miss 合并到同一个 outstanding PTW walk，则该指标按实际发起的 unique PTW walk 计一次。

每个 unique PTW walk 最终只会被归类一次：

```text
touch DRAM
```

或者：

```text
no DRAM touch
```

不会因为一个 PTW 内部多次访问 DRAM 而重复计数。

## 核心实现思路

实现中给每个 PTW walk 分配一个共享 flag：

```cpp
std::shared_ptr<bool> ptw_dram_touched
```

这个 flag 初始为 `false`。

当 PTW 内部生成 `TRANSLATION` read request 时，该 request 会携带这个 flag。这个 flag 会继续沿着 cache/channel/DRAM 请求路径传播。

当该 `TRANSLATION` request 真正成功进入 DRAM RQ 时，在 `MEMORY_CONTROLLER::add_rq()` 入口处将 flag 置为 `true`。

PTW walk 完成时，再根据 flag 最终值分类：

```text
flag == true  -> stlb_miss_touch_dram
flag == false -> stlb_miss_no_dram_touch
```

这样可以避免在 PTW 尚未完成时提前分类，防止遗漏后续可能发生的 DRAM touch。

## 为什么在 DRAM RQ 入口处标记

本任务要求判断依据必须是：

```text
TRANSLATION read request 成功进入 DRAM RQ
```

因此不能在以下位置计数：

- STLB miss 发生时
- PTW 发起 translation request 时
- request 到达下一级 cache 时
- PTE access 在 cache 层次中命中或 miss 时

只有 `MEMORY_CONTROLLER::add_rq()` 成功接收该 read request 时，才说明它进入了 DRAM RQ。源码中只在这个位置把对应 PTW flag 置为 `true`。

## ROI-only 处理

为了避免 warmup 统计混入最终结果，STLB miss 向 PTW 发起请求时，会记录该 PTW walk 是否应该参与本统计。

具体逻辑是：

```cpp
fwd_pkt.count_ptw_dram_touch = is_stlb() && !warmup;
```

也就是说，只有非 warmup 阶段中由 STLB miss 发起的 PTW walk，才会在 PTW 完成时进入 `STLB_MISS_PTW_DRAM_TOUCH_BREAKDOWN` 统计。

PTW 的 `begin_phase()` 会清空统计，`end_phase()` 会把当前阶段的统计保存到 ROI stats 中。最终 plain printer 使用 ROI stats 打印。

## 主要修改文件

### `inc/channel.h`

在 channel request 中增加：

```cpp
std::vector<std::shared_ptr<bool>> ptw_dram_touched_flags{};
bool count_ptw_dram_touch = false;
```

`ptw_dram_touched_flags` 用于把 PTW walk 的 touch flag 传递到 DRAM RQ。

使用 vector 是因为多个 request 可能在 channel/cache 中合并。合并后，一个实际进入 DRAM RQ 的 request 可能对应多个 PTW walk，因此需要保留多个 flag。

`count_ptw_dram_touch` 用于标记这个 PTW walk 是否属于 ROI 统计范围。

### `src/channel.cc`

在 channel request merge 时合并 `ptw_dram_touched_flags`。

这样如果多个 PTW translation request 合并成一个下游 request，实际进入 DRAM RQ 时仍然可以把所有相关 PTW walk 的 flag 都标记为 touch。

### `inc/cache.h` 和 `src/cache.cc`

在 cache tag lookup 和 MSHR 中保存并传播 `ptw_dram_touched_flags`。

在 cache MSHR merge 时合并这些 flags。

在 cache miss 向下游转发 request 时继续携带这些 flags。

对于 STLB miss 向 PTW 发请求的位置，额外设置：

```cpp
fwd_pkt.count_ptw_dram_touch = is_stlb() && !warmup;
```

这一步决定该 PTW walk 是否最终纳入 ROI 统计。

### `inc/ptw.h` 和 `src/ptw.cc`

在 PTW MSHR 中增加：

```cpp
std::shared_ptr<bool> ptw_dram_touched;
bool count_ptw_dram_touch;
```

PTW 每次生成 `TRANSLATION` request 时，把自己的 `ptw_dram_touched` flag 放入 request 的 `ptw_dram_touched_flags` 中。

PTW 完成 walk 时，如果 `count_ptw_dram_touch` 为真，则根据 `ptw_dram_touched` 的最终值更新统计：

```text
stlb_miss_total
stlb_miss_touch_dram
stlb_miss_no_dram_touch
```

### `src/dram_controller.cc`

在 `MEMORY_CONTROLLER::add_rq()` 中，只有当 read request 成功进入 DRAM RQ 后，才处理：

```cpp
for (const auto& flag : packet.ptw_dram_touched_flags) {
  if (flag)
    *flag = true;
}
```

并且只对 `access_type::TRANSLATION` 的 read request 做这个标记。

### `inc/phase_info.h` 和 `src/champsim.cc`

在 phase stats 中加入 PTW stats，使得最终 printer 能拿到 ROI 阶段的 PTW 统计。

### `src/plain_printer.cc`

新增 plain text 输出：

```text
STLB_MISS_PTW_DRAM_TOUCH_BREAKDOWN:
stlb_miss_total.count = ...

stlb_miss_touch_dram.count = ...
stlb_miss_touch_dram.share = ...

stlb_miss_no_dram_touch.count = ...
stlb_miss_no_dram_touch.share = ...

STLB_MISS_PTW_DRAM_TOUCH_DEBUG:
stlb_miss_touch_plus_no_touch.count = ...
stlb_miss_total_check.count = ...
```

其中：

```text
stlb_miss_touch_dram.share = stlb_miss_touch_dram / stlb_miss_total
stlb_miss_no_dram_touch.share = stlb_miss_no_dram_touch / stlb_miss_total
```

当 `stlb_miss_total == 0` 时，share 安全输出 `0.00%`，不会除零。

### `src/json_printer.cc`

同时把 PTW touch/no-touch 统计加入 JSON 输出，方便后续如果需要用 JSON 结果做处理。

## 输出含义

```text
stlb_miss_total.count
```

ROI 中被统计到的 unique PTW walk 数量，也就是本指标口径下的 STLB miss 总数。

```text
stlb_miss_touch_dram.count
```

这些 PTW walk 中，至少有一次 `TRANSLATION` read request 成功进入 DRAM RQ 的数量。

```text
stlb_miss_no_dram_touch.count
```

这些 PTW walk 中，没有任何 `TRANSLATION` read request 成功进入 DRAM RQ 的数量。

```text
stlb_miss_touch_plus_no_touch.count
```

debug 检查值，等于：

```text
stlb_miss_touch_dram + stlb_miss_no_dram_touch
```

它应该等于：

```text
stlb_miss_total_check.count
```

如果二者不相等，说明分类统计有问题。

## 冒烟测试情况

修改后曾使用小规模 trace 做过冒烟测试，确认：

```text
stlb_miss_touch_plus_no_touch.count == stlb_miss_total_check.count
```

同时后续 `jsonnew_sweep` 的 1M warmup / 2M ROI 冒烟测试中，result log 中也能看到该 section，并且后处理脚本可以抓取这些字段生成对应图表。
