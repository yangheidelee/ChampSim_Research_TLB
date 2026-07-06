# L1D prefetcher 统计逻辑笔记

本文记录当前 `Core_0_L1D_prefetch_*` 这些统计项的含义，以及 `prefetch_line()` 和 vberti 一批预取请求的执行路径。

相关源码位置：

- `src/plain_printer.cc`: `format_cache_metric_block()` 负责打印 `Core_0_L1D_prefetch_*`
- `src/cache.cc`: `CACHE::prefetch_line()`、`CACHE::try_hit()`、`CACHE::handle_miss()`、fill 相关逻辑负责计数
- `prefetcher/vberti/vberti.cc`: vberti 根据一组 delta 多次调用 `prefetch_line()`

## 1. `Core_0_L1D_prefetch_requested`

源码位置：`src/cache.cc` 中 `CACHE::prefetch_line()`
含义：
prefetcher 调用 prefetch_line() 的次数，也就是预取器内部产生的所有prefetch candidate

因此：
- 只要 prefetcher 调用了 `prefetch_line()`，就会增加 `prefetch_requested`。
- 即使 L1D `internal_PQ` 已满，后续没有真正入队，也已经算作 requested。
- 这里不检查目标 prefetch 地址是否已经在 cache 里。

## 2. `Core_0_L1D_prefetch_issued`

源码位置：`src/cache.cc` 中 `CACHE::prefetch_line()`
含义：
成功插入 L1D internal_PQ 的 prefetch 数量；因为PQ中还有空间而容纳了他们
因此：prefetch_issued <= prefetch_requested
`prefetch_requested - prefetch_issued` 主要表示 `internal_PQ` 满导致 `prefetch_line()` 返回 false 的请求数。

注意：`prefetch_issued` 也不代表这个 prefetch 已经访问下层 cache/DRAM，它只表示 L1D 接收该 prefetch 并放进 `internal_PQ`。

## 3. `requested` 和 `issued` 是否检查 cache hit
不会。

`CACHE::prefetch_line()` 中只检查 `internal_PQ` 是否满，不检查 prefetch 目标地址是否已经在 L1D cache 里。

也就是说：
requested = prefetcher 想发多少
issued    = L1D internal_PQ 接收了多少
不是：
真实发生 cache miss 并向下层发送了多少；PQ中的entry会依次送到cache中做tag check

## 4. cache 中是否会检查 prefetch 地址是否已经存在

会检查，但不是在 `prefetch_line()` 里，而是在后续正常 cache pipeline 中检查。

prefetcher 调用 prefetch_line()
  -> prefetch request 进入 L1D internal_PQ
  -> internal_PQ 请求进入 inflight_tag_check
  -> 如果需要地址翻译，先走 DTLB/STLB translation
  -> translation 完成后执行 cache tag check
  -> CACHE::try_hit() 检查目标 block 是否已在 cache 中

源码位置：`src/cache.cc` 中 `CACHE::try_hit()`
如果 prefetch 地址已经在 L1D 里：
- `try_hit()` 判断为 hit。
- 该 prefetch 不会进入 `handle_miss()`。
- 不会分配新的 MSHR。
- 不会继续向下层 cache/DRAM 发真实 miss 请求。

因此：

```text
prefetch_issued 只是进入 internal_PQ；
真正是否 cache miss，要等后续 try_hit()。
```

## 5. `Core_0_L1D_prefetch_useful`

`prefetch_useful` 有两个来源。

第一种：prefetched line 已经填入 cache，之后被 demand access 命中。

源码位置：`src/cache.cc` 中 `CACHE::try_hit()`

```cpp
const auto useful_prefetch = (hit && way->prefetch && !handle_pkt.prefetch_from_this);

if (useful_prefetch) {
  ++sim_stats.pf_useful;
  way->prefetch = false;
}
```

第二种：demand miss 到来时，同一个 block 的 prefetch 已经在 MSHR 中飞行，但是还没有回来。这种情况称为 late prefetch。

源码位置：`src/cache.cc` 中 `CACHE::handle_miss()`

```cpp
if (mshr_entry->type == access_type::PREFETCH && handle_pkt.type != access_type::PREFETCH) {
  if (mshr_entry->prefetch_from_this) {
    ++sim_stats.pf_useful;
    ++sim_stats.pf_late;
  }
}
```

因此：

```text
prefetch_useful = timely useful + late useful
```

## 6. `Core_0_L1D_prefetch_late`

含义：

```text
prefetch 已经发出并在 MSHR 中，但 demand 访问到达时数据还没回来
```

计数逻辑同上：

```cpp
++sim_stats.pf_useful;
++sim_stats.pf_late;
```

所以 late prefetch 同时也算 useful。

## 7. `Core_0_L1D_prefetch_useless`

源码位置：`src/cache.cc` 中 cache fill / eviction 相关逻辑

```cpp
if (way->valid && way->prefetch) {
  ++sim_stats.pf_useless;
}
```

含义：

```text
某条 cache line 是 prefetch 填进来的，但在被 demand 使用前就被替换掉了
```

也就是无用预取填充被驱逐。

## 8. `Core_0_L1D_prefetch_accuracy`

源码位置：`src/plain_printer.cc` 中 `format_cache_metric_block()`

```cpp
prefetch_accuracy = pf_useful / pf_issued
```

含义：

```text
成功进入 L1D internal_PQ 的 prefetch 中，有多少最终有用
```

注意分母是 `issued`，不是 `requested`。

## 9. `Core_0_L1D_prefetch_coverage`

源码位置：`src/plain_printer.cc` 中 `format_cache_metric_block()`

```cpp
demand_miss = LOAD miss + RFO miss;
prefetch_coverage = pf_useful / (pf_useful + demand_miss);
```

含义：

```text
所有可被 prefetch 覆盖的 demand miss 机会中，有多少被 prefetch 覆盖
```

其中：

- `pf_useful` 表示已经被 prefetch 覆盖的部分。
- `demand_miss` 表示仍然没有被 prefetch 覆盖、最终表现为 demand miss 的部分。

## 10. vberti 一批 prefetch 如何发出

vberti 在一次 `prefetcher_cache_operate()` 中，会根据当前 IP/hash 查 Berti table，得到一组 delta。

源码位置：`prefetcher/vberti/vberti.cc`

```cpp
std::vector<delta_t> deltas(BERTI_TABLE_DELTA_SIZE);
berti->get(ip_hash, deltas);

for (auto i: deltas)
{
  uint64_t p_addr = (line_addr + i.delta) << LOG2_BLOCK_SIZE;
  ...
  if (prefetch_line(champsim::address{p_addr}, fill_this_level, metadata_in))
  {
    ++average_issued;
    ...
  }
}
```

因此：

```text
vberti 一次触发可能产生多个 prefetch；
每个有效 delta 会单独调用一次 prefetch_line()。
```

举例：

```text
如果当前 Berti table 给出 4 个有效 delta，
那么这一次 prefetcher_cache_operate() 最多会调用 4 次 prefetch_line()。
```

每个 prefetch 请求独立判断：

- 是否被 `LatencyTable` 过滤；
- 是否是无效 delta；
- 是否跨页；
- 是否因为 `NO_CROSS_PAGE` 宏而被跳过；
- 是否填 L1D 或只填 L2；
- `prefetch_line()` 是否因为 internal_PQ 满而返回 false。

## 11. vberti 内部统计和 ChampSim cache 统计的区别

vberti 自己打印的 `BERTI TO_L1 / TO_L2 / CROSS_PAGE / NO_CROSS_PAGE` 更接近“vberti 内部产生并分类过的 prefetch candidate”。

而 `Core_0_L1D_prefetch_requested / issued / useful / useless / late` 是 ChampSim cache 层统计。

两者不能简单等同：

```text
BERTI candidate
  -> 调用 prefetch_line()
  -> requested
  -> internal_PQ 成功接收
  -> issued
  -> 后续 translation/tag check/MSHR/lower cache
  -> useful/useless/late/fill 等结果
```

所以 `BERTI CROSS_PAGE` 不等于真实跨页 TLB prefetch 次数，`BERTI TO_L1 + TO_L2` 也不等于最终真正访问下层 cache/DRAM 的 prefetch 数量。

## 12. 资源满时 drop 还是 retry

当前源码里要分两个阶段看。

### 12.1 `prefetch_line()` 入本级 `internal_PQ` 前

如果本级 `internal_PQ` 已满：
这个 prefetch 没有进入 cache pipeline，本次请求失败，cache 后续不会自动重试。可以认为这次 prefetch 被 drop 了，除非 prefetcher 之后再次生成同一个地址。

### 12.2 已进入 `internal_PQ` 后

一旦 prefetch 成功进入本级 `internal_PQ`，后续会走：
internal_PQ -> translation -> tag check -> handle_miss()

如果在 `handle_miss()` 阶段遇到：

- 本级 MSHR 满；
- 下级 PQ/RQ 满；
- 进入下级 cache 后，下级 MSHR 满；

那么 `handle_miss()` 会返回 false，但该 entry 会留在对应 cache 的 `inflight_tag_check` 中，后续 cycle 继续重试。

因此简洁结论是：

```text
本级 internal_PQ 满：
  prefetch_line() 返回 false，本次 prefetch 没入队，等价于 drop。

进入 internal_PQ 之后：
  本级 MSHR 满、下级 PQ 满、下级 MSHR 满，
  都是 backpressure/retry，不是永久 drop。
```


## 13. L1D 队列检查顺序和 tag-check 启动带宽

当前 ChampSim 的 cache pipeline 中，一个 cache 会从上游 channel 的 `WQ`、`RQ`、`PQ`，以及本 cache 自己的 `internal_PQ` 中取请求进入 `inflight_tag_check`。对 L1D 来说，demand load 通常来自上游 `RQ`，L1D prefetcher 通过 `prefetch_line()` 产生的请求进入本级 `internal_PQ`。

队列检查顺序是固定优先级，而不是 round-robin。上游 channel 内部按 `WQ -> RQ -> PQ` 的顺序消耗 tag-check 启动带宽；所有上游 channel 处理完以后，才使用剩余带宽处理本 cache 的 `internal_PQ`。因此 L1D 本地产生的 prefetch 请求优先级低于 demand read，也低于上游传来的 prefetch queue。

`MAX_TAG` 限制每周期能够启动和执行的 tag check 数量。当 `MAX_TAG` 大于 1 时，cache 并不是每个队列各取一个请求，而是按上述固定顺序尽量从高优先级队列连续取请求，直到当前周期可用的 tag-check 启动带宽被消耗完。因此如果 `WQ` 或 `RQ` 长期有大量请求，`PQ` 和 `internal_PQ` 可能长期得不到进入 tag-check pipeline 的机会。

这意味着 L1D prefetcher 的请求虽然已经被 `prefetch_line()` 接收到 `internal_PQ`，但它真正开始 translation/tag check 的时间会受到 demand traffic、writeback traffic 和 `MAX_TAG` 带宽的影响。这个机制会让 prefetch 请求天然处于较低优先级，尤其在 demand RQ 压力较大时更明显。



Core_0_L1D_prefetch_access  ：PQ中有效check的prefetch，它等于Core_0_L1D_prefetch_issued
Core_0_L1D_prefetch_hit ：check发现是hit的
Core_0_L1D_prefetch_miss ：check发现是miss的，此时它会分配MSHR，当MSHR满了就会等待后续retry/反压。这个数据代表了l1dpref一定会处理的miss，也就是最终真正prefetch有效发出的量
* 注意vberti，可能会将有的miss发到L2C的PQ，直接bypass L1D的mshr；这是它内部的置信度机制决定的



prefetch 从 internal_PQ 取出来进入 tag-check pipeline 后，才会发 translation 请求到 TLB 系统。更准确地说：translation 发生在 真正做 cache tag check 之前。


L1D prefetch 只要成功进入 internal_PQ，并且该 cache 配置是 virtual_prefetch=true，就都会走地址翻译流程，不区分 same-page 还是 cross-page。
* 也就是说如何查出来是hit的，那就白查TLB了浪费了TLB的查询带宽



只要 L1D prefetch 已经成功进入 L1D 的 internal_PQ，那么它发起的 TLB translation 不会因为“这是 prefetch”而被 TLB 系统主动 drop。
TLB 系统里会有 backpressure、合并、等待、重试，但没有针对 L1D prefetch translation 的丢弃策略。
L1D prefetch 发 translation 是走 DTLB 的 RQ，不是 PQ。issue_translation() 里，translation request 被构造成 LOAD 类型。

L1D prefetcher
-> prefetch_line()
-> L1D internal_PQ
-> L1D inflight_tag_check
-> issue_translation()
-> DTLB RQ
-> DTLB lookup
-> miss 则进 STLB RQ
-> STLB lookup
-> miss 则进 PTW

总结：在当前这个 ChampSim 工程里，L1D prefetch 的跨页翻译进入 TLB 系统以后，基本就是像一个正常 demand translation 一样处理，不会因为它是 prefetch 就特殊 drop、特殊低优先级、或者走单独的 prefetch translation queue。





# 预取，在PQ里面后来的prefetch会merge到PQ中已经有entry吗？
本级 prefetcher 发出的 prefetch 进入 internal_PQ 时不会 merge。
发到下一级 cache 的 channel PQ 后，后来的 prefetch 可以和 PQ 中已有同地址 entry merge。
如果已经不是 PQ，而是 miss 后已经分配了 MSHR，那么后续同地址请求会走 MSHR merge，不是 PQ merge。