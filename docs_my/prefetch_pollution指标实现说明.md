# prefetch pollution 指标实现说明

本文档记录当前 ChampSim 工程中新增的 prefetch pollution 统计逻辑。该修改只增加统计计数和打印输出，不改变 ChampSim 原有 cache/TLB/prefetch/replacement 的功能行为。

## 1. 指标目标

本次要统计的 pollution 不是简单的“prefetch fill 踢出了 valid entry”，而是更强的确认型语义：

1. 一个 prefetch fill 进入 cache 或 TLB；
2. 这个 prefetch fill 替换掉一个 valid victim；
3. victim 的 line/VPN 被放入一个 shadow FIFO；
4. 后续同一个 line/VPN 在 FIFO 窗口内发生 demand miss；
5. 这个 demand miss 才确认计入 pollution。

因此该指标表示：

```text
prefetch-evicted victim later demand-missed within shadow window
```

也就是：prefetch 曾经踢掉一个 entry，并且后续 demand 的确又需要这个 entry。

## 2. 当前支持的统计对象

### 2.1 cache prefetch pollution

对所有 cache 的 prefetch fill 都可统计，重点关注 L1D：

```text
Core_N_L1D_prefetch_pollution_evict
Core_N_L1D_prefetch_pollution_demand
Core_N_L1D_prefetch_pollution_among_prefetch_fill
```

这里使用 cache line 作为 key。

### 2.2 DTLB/STLB cross-page prefetch pollution

只统计由 vBerti/L1D prefetcher 触发的 cross-page translation prefetch，不混入 same-page prefetch。

打印字段包括：

```text
Core_N_DTLB_cross_page_prefetch_pollution_evict
Core_N_DTLB_cross_page_prefetch_pollution_demand
Core_N_DTLB_cross_page_prefetch_pollution_among_prefetch_fill

Core_N_STLB_cross_page_prefetch_pollution_evict
Core_N_STLB_cross_page_prefetch_pollution_demand
Core_N_STLB_cross_page_prefetch_pollution_among_prefetch_fill
```

这里使用 VPN + ASID + CPU 作为 key。

## 3. 指标语义

### 3.1 `prefetch_pollution_evict`

对 cache：

```text
Core_N_L1D_prefetch_pollution_evict
```

表示：L1D prefetch fill 曾经踢出一个 valid cache line，随后这个 victim line 在 shadow FIFO 窗口内发生 demand L1D miss。

victim 原本是 prefetch line 还是 demand/normal line 都计入。

对 TLB：

```text
Core_N_DTLB_cross_page_prefetch_pollution_evict
Core_N_STLB_cross_page_prefetch_pollution_evict
```

表示：L1D cross-page prefetch translation fill 曾经踢出一个 valid TLB entry，随后这个 victim VPN 在 shadow FIFO 窗口内发生 demand TLB miss。

### 3.2 `prefetch_pollution_demand`

对 cache：

```text
Core_N_L1D_prefetch_pollution_demand
```

表示：`prefetch_pollution_evict` 中，被 prefetch 踢出的 victim 在被踢出时不是 prefetch line，即 `victim.prefetch == false`。

这个字段更接近“prefetch 踢掉 demand/normal line 后，该 line 又被 demand miss 访问”的情况。

对 TLB：

```text
Core_N_DTLB_cross_page_prefetch_pollution_demand
Core_N_STLB_cross_page_prefetch_pollution_demand
```

表示：`cross_page_prefetch_pollution_evict` 中，被踢出的 victim entry 的 `translation_source` 是 demand origin，即：

```text
DEMAND_DATA 或 DEMAND_INSTRUCTION
```

### 3.3 `prefetch_pollution_among_prefetch_fill`

对 cache：

```text
Core_N_L1D_prefetch_pollution_among_prefetch_fill =
  Core_N_L1D_prefetch_pollution_evict / Core_N_L1D_prefetch_fill
```

对 DTLB/STLB：

```text
Core_N_DTLB_cross_page_prefetch_pollution_among_prefetch_fill =
  Core_N_DTLB_cross_page_prefetch_pollution_evict /
  Core_N_DTLB_vberti_cross_page_prefetch_fill

Core_N_STLB_cross_page_prefetch_pollution_among_prefetch_fill =
  Core_N_STLB_cross_page_prefetch_pollution_evict /
  Core_N_STLB_vberti_cross_page_prefetch_fill
```

所有除法都使用 `ratio_or_zero()`，分母为 0 时输出 0，不输出 nan/inf。

## 4. 新增统计字段

文件：

```text
inc/cache_stats.h
```

新增 cache prefetch pollution 字段：

```cpp
uint64_t pf_pollution_evict = 0;
uint64_t pf_pollution_demand = 0;
```

新增 TLB cross-page prefetch pollution 字段：

```cpp
uint64_t tlb_cross_prefetch_pollution_evict = 0;
uint64_t tlb_cross_prefetch_pollution_demand = 0;
```

这些字段也在：

```text
src/cache_stats.cc
```

中加入了 stats subtraction，保证 warmup/ROI 或其他 stats 差分场景下行为一致。

## 5. 新增 shadow 数据结构

文件：

```text
inc/cache.h
```

### 5.1 cache pollution key

新增：

```cpp
struct prefetch_pollution_key {
  uint32_t cpu = 0;
  uint64_t line = 0;
};
```

该 key 使用：

```text
CPU + cache line address
```

这样可以避免不同 CPU 的相同 line 混在一起。

### 5.2 TLB pollution key

TLB 侧复用已有：

```cpp
tlb_prefetch_key
```

该 key 包含：

```text
CPU + VPN + ASID
```

### 5.3 FIFO + shadow map

cache 侧新增：

```cpp
std::deque<std::tuple<prefetch_pollution_key, bool, uint64_t>> prefetch_pollution_fifo{};
std::map<prefetch_pollution_key, std::pair<uint64_t, bool>> prefetch_pollution_shadow{};
uint64_t prefetch_pollution_next_id = 0;
```

TLB 侧新增：

```cpp
std::deque<std::tuple<tlb_prefetch_key, bool, uint64_t>> tlb_cross_prefetch_pollution_fifo{};
std::map<tlb_prefetch_key, std::pair<uint64_t, bool>> tlb_cross_prefetch_pollution_shadow{};
uint64_t tlb_cross_prefetch_pollution_next_id = 0;
```

shadow map 中每个 key 只保留一个 outstanding pollution candidate。原因是 pollution 的因果链应该是：

```text
prefetch fill 踢出某个 victim
victim 在重新进入结构之前，被后续 demand miss 访问到
```

因此同一个 line/VPN 在窗口内再次被 prefetch fill 踢出时，会覆盖旧 candidate。FIFO 中仍然保存 id，用于限制窗口大小；旧 id 如果已经被覆盖，窗口弹出时不会误删新的 candidate。

## 6. Shadow FIFO 窗口

pollution shadow FIFO 使用和 too-early 一致的窗口大小：

```text
NUM_SET * NUM_WAY
```

实现函数：

```cpp
CACHE::too_early_shadow_size()
```

虽然函数名沿用了 too-early，但当前用于 too-early 和 pollution 两类 shadow 窗口。窗口大小按结构独立计算：

- L1D 用 L1D 自身的 set/way；
- DTLB 用 DTLB 自身的 set/way；
- STLB 用 STLB 自身的 set/way。

## 7. 通用 shadow 辅助函数

文件：

```text
src/cache.cc
```

新增：

```cpp
remember_pollution_candidate(...)
consume_pollution_candidate(...)
discard_pollution_candidates(...)
```

### 7.1 `remember_pollution_candidate`

功能：

1. 为本次 pollution candidate 分配递增 id；
2. 把 `(key, demand_victim, id)` 放入 FIFO；
3. 把 `(id, demand_victim)` 放入 `shadow[key]`；
4. 如果 FIFO 超过窗口大小，移除最老记录；
5. 同步从 shadow map 中删除对应 id。

`demand_victim` 表示 victim 在被踢出时是否属于 demand/normal entry。

### 7.2 `consume_pollution_candidate`

功能：

1. 后续 demand miss 到来时，用当前 line/VPN key 查询 shadow；
2. 如果存在记录，弹出该 key 下最早的一条记录；
3. 返回 `{true, demand_victim}`；
4. 如果不存在，返回 `{false, false}`。

这样保证同一个 victim record 最多只计一次 pollution。

### 7.3 `discard_pollution_candidates`

功能：

当后续 demand hit 到某个 line/VPN 时，说明当前访问没有形成 pollution miss，因此删除该 key 下的 shadow 记录，避免未来误计。

## 8. cache prefetch pollution 的记录位置

文件：

```text
src/cache.cc
```

函数：

```cpp
CACHE::handle_fill(...)
```

在 fill 已经选出 victim 之后，如果满足：

```cpp
way != set_end
way->valid
fill_mshr.type == access_type::PREFETCH
```

则调用：

```cpp
remember_prefetch_pollution_candidate(*way, way->cpu);
```

这表示：当前 fill 是 prefetch fill，且它确实替换掉了一个 valid victim。此时只记录 candidate，不立即计 pollution。

被记录的 victim 属性：

```cpp
demand_victim = !victim.prefetch
```

也就是说，如果被踢出的 line 在被踢出时已经不是 prefetch line，就认为它属于 demand/normal victim。

## 9. cache prefetch pollution 的确认位置

文件：

```text
src/cache.cc
```

函数：

```cpp
CACHE::handle_miss(...)
```

在 cache miss 已经确认并更新原有 miss 统计之后，调用：

```cpp
consume_prefetch_pollution_candidate(handle_pkt);
```

内部只接受 demand data request：

```cpp
LOAD 或 RFO
```

如果 shadow 命中：

```cpp
pf_pollution_evict++
```

如果该 shadow record 的 victim 是 demand/normal victim：

```cpp
pf_pollution_demand++
```

## 10. cache demand hit 时的处理

文件：

```text
src/cache.cc
```

函数：

```cpp
CACHE::try_hit(...)
```

如果后续 demand hit 到某个 line，则调用：

```cpp
discard_prefetch_pollution_candidate(handle_pkt);
```

这会删除该 line 对应的 pollution shadow record，避免这个 line 未来再 miss 时被错误归因到更早的 prefetch eviction。

此外，在 `CACHE::handle_fill(...)` 中，当某个 line 被重新 fill 回当前 cache 结构时，也会清掉该 line 的旧 pollution candidate。这样可以表达：

```text
victim 已经重新进入结构，之前那次被 prefetch 踢出的污染因果链结束
```

也就是说，一个 candidate 只有在“被踢出后、重新 fill 回来前”的第一次 demand miss 上才会计一次 pollution。

## 11. TLB cross-page pollution 的记录位置

文件：

```text
src/cache.cc
```

函数：

```cpp
CACHE::handle_fill(...)
```

在 fill 已经选出 victim 后，如果满足：

```cpp
way != set_end
way->valid
is_tlb()
is_l1d_cross_page_prefetch_origin(fill_mshr.translation_source)
```

则调用：

```cpp
remember_tlb_cross_prefetch_pollution_candidate(*way, way->cpu);
```

这里的关键是：

```cpp
is_l1d_cross_page_prefetch_origin(fill_mshr.translation_source)
```

因此只有 L1D cross-page prefetch translation fill 会记录 TLB pollution candidate，same-page prefetch 不会进入这套统计。

被记录的 victim 属性：

```cpp
demand_victim = is_demand_origin(victim.translation_source)
```

即 victim entry 在被踢出时如果来源是 `DEMAND_DATA` 或 `DEMAND_INSTRUCTION`，则计为 demand victim。

## 12. TLB cross-page pollution 的确认位置

文件：

```text
src/cache.cc
```

函数：

```cpp
CACHE::record_tlb_cross_prefetch_miss(...)
```

在 demand translation miss 分支中调用：

```cpp
consume_tlb_cross_prefetch_pollution_candidate(handle_pkt);
```

该函数只接受：

```cpp
is_tlb()
is_demand_origin(handle_pkt.translation_source)
```

如果 shadow 命中：

```cpp
tlb_cross_prefetch_pollution_evict++
```

如果 victim 是 demand origin：

```cpp
tlb_cross_prefetch_pollution_demand++
```

## 13. TLB demand hit 时的处理

文件：

```text
src/cache.cc
```

函数：

```cpp
CACHE::record_tlb_origin_hit(...)
```

当 demand translation hit 到某个 VPN 时，调用：

```cpp
discard_tlb_cross_prefetch_pollution_candidate(handle_pkt);
```

这会清除同 VPN/ASID 的 pollution shadow record，避免后续 miss 误归因。

## 14. ROI 处理

在：

```cpp
CACHE::begin_phase()
```

中清空：

```cpp
prefetch_pollution_fifo
prefetch_pollution_shadow
prefetch_pollution_next_id
tlb_cross_prefetch_pollution_fifo
tlb_cross_prefetch_pollution_shadow
tlb_cross_prefetch_pollution_next_id
```

这样 warmup 阶段产生的 shadow candidate 不会进入 ROI。

在：

```cpp
CACHE::end_phase(...)
```

中把 sim stats 拷贝到 roi stats：

```cpp
pf_pollution_evict
pf_pollution_demand
tlb_cross_prefetch_pollution_evict
tlb_cross_prefetch_pollution_demand
```

因此最终 result log 中打印的是 ROI 内的 pollution 统计。

## 15. 打印位置

文件：

```text
src/plain_printer.cc
```

### 15.1 cache prefetch pollution

在每个 cache 的 prefetch stats 后打印：

```text
Core_N_L1D_prefetch_pollution_evict
Core_N_L1D_prefetch_pollution_demand
Core_N_L1D_prefetch_pollution_among_prefetch_fill
```

由于这个打印函数对所有 cache 通用，因此 ITLB/DTLB/STLB/L1I/L2C/LLC 也会有同名 cache prefetch pollution 字段；对于没有 cache prefetch fill 的结构通常为 0。

### 15.2 DTLB/STLB cross-page prefetch pollution

在 vBerti-TLB Cross-page Flow Stats 中打印：

```text
Core_N_DTLB_cross_page_prefetch_pollution_evict
Core_N_DTLB_cross_page_prefetch_pollution_demand
Core_N_DTLB_cross_page_prefetch_pollution_among_prefetch_fill

Core_N_STLB_cross_page_prefetch_pollution_evict
Core_N_STLB_cross_page_prefetch_pollution_demand
Core_N_STLB_cross_page_prefetch_pollution_among_prefetch_fill
```

这部分只对应 cross-page prefetch，不包含 same-page prefetch。

## 16. JSON 输出

文件：

```text
src/json_printer.cc
```

新增 JSON stats key：

```text
prefetch pollution evict
prefetch pollution demand
TLB cross-page prefetch pollution evict
TLB cross-page prefetch pollution demand
```

## 17. 与 too-early 的区别

too-early 和 pollution 使用相似的 shadow FIFO 方法，但记录对象不同：

### too-early

记录的是：

```text
prefetch 自己被淘汰
```

后续 demand miss 到这个 prefetch 自己时，说明这个 prefetch 来得太早。

### pollution

记录的是：

```text
prefetch fill 踢出的 victim
```

后续 demand miss 到 victim 时，说明这个 prefetch 可能污染了 cache/TLB。

两者不是互斥指标，语义不同。

## 18. 不改变原 ChampSim 行为的保证

本次修改只做旁路统计，不改变：

- victim 选择；
- replacement 状态更新；
- cache/TLB lookup；
- MSHR/PQ/RQ/WQ 入队；
- prefetcher 生成逻辑；
- prefetch fill 逻辑；
- TLB/PTW translation 逻辑；
- 已有统计字段的计算方式。

所有新增 shadow FIFO/map 只用于记录和匹配统计事件，不参与模拟器功能行为。

## 19. 冒烟测试

使用当前 `mcf-footprint-l1pref-1core` 跑了短测试：

```text
warmup = 1M
ROI = 2M
trace = /data0/tzh/champsim_traces/SPEC17/605.mcf_s-1536B.champsimtrace.xz
```

输出 log：

```text
/home/zcq/git_prj/ChampSim/tmp/pollution_smoke/605.mcf_s-1536B-l1pref-pollution-smoke.log
```

该 log 中已正常打印：

```text
Core_0_L1D_prefetch_pollution_evict
Core_0_L1D_prefetch_pollution_demand
Core_0_L1D_prefetch_pollution_among_prefetch_fill
Core_0_DTLB_cross_page_prefetch_pollution_evict
Core_0_DTLB_cross_page_prefetch_pollution_demand
Core_0_DTLB_cross_page_prefetch_pollution_among_prefetch_fill
Core_0_STLB_cross_page_prefetch_pollution_evict
Core_0_STLB_cross_page_prefetch_pollution_demand
Core_0_STLB_cross_page_prefetch_pollution_among_prefetch_fill
```

并且程序正常完成。
