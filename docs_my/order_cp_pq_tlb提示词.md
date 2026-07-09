你需要在 ChampSim 中实现一个新的实验模式：**Ordered PQ-full TLB Rescue**。

这个实验模式用于验证一个假设：

> vBerti 生成的一部分 cross-page prefetch 由于 internal prefetch queue，也就是 PQ，满了而被 drop；这些被 drop 的 cross-page prefetch 如果能够至少进入 TLB/STLB/PTW translation path，可能会提前填充 demand-visible STLB，从而减少后续 demand STLB miss，提升 IPC。

本实验不是实现 Shadow-TLB，不是实现 ideal TLB prefetcher，也不是改变 Berti 的预测逻辑。
本实验只在 **PQ full 导致 cross-page prefetch 原本会被 drop** 的情况下，把这个 prefetch 放入一个 sideband rescue queue，之后按顺序发出 **translation-only request**。

最终目标是增加一个 bin 运行参数开关，默认关闭；不加参数时 ChampSim 行为必须和原始版本一致。

---

## 一、实验模式名称

建议命名为：

```text
Ordered PQ-full TLB Rescue
```

或者代码中使用：

```cpp
ordered_pqfull_tlb_rescue
```

含义：

```text
当 vBerti 生成的 cross-page prefetch 因 internal PQ full 原本会被 drop 时，
不让它直接彻底消失，
而是放入一个 sideband rescue queue。
rescue queue 中的 entry 之后只能发 translation-only request 到 TLB/STLB/PTW，
不能发 data prefetch，
不能进入 L1D data lookup，
不能产生 data cache fill。
```

---

## 二、必须添加 bin 输入参数作为开关

请添加一个运行时参数，用于打开这个模式。

推荐参数名：

```bash
--ordered-pqfull-tlb-rescue
```

或者：

```bash
--enable-ordered-pqfull-tlb-rescue
```

要求：

```text
1. 默认关闭。
2. 不加这个参数时，ChampSim 行为必须与修改前完全一致。
3. 只有显式传入该参数时，才启用 Ordered PQ-full TLB Rescue。
4. 该模式只影响 vBerti 产生的 L1D cross-page prefetch 在 internal PQ full 时的处理。
```

示例运行：

```bash
./bin/<config> --ordered-pqfull-tlb-rescue <other args>
```

默认运行：

```bash
./bin/<config> <other args>
```

默认运行必须是原始正常 ChampSim 行为。

---

## 三、核心实验语义

### 关闭模式时，也就是默认行为

保持当前 ChampSim 行为：

```text
vBerti 生成 prefetch
    -> 如果 internal PQ 未满：
           正常进入 PQ
           后续正常 translation + data prefetch
    -> 如果 internal PQ 满：
           按原始逻辑 drop
```

不能改变默认模式下的 IPC、PQ 行为、prefetch 统计、TLB 行为。

---

### 开启 Ordered PQ-full TLB Rescue 时

行为变成：

```text
vBerti 生成 prefetch
    -> 给每个 vBerti prefetch 分配单调递增的 seq_id

    -> 如果 internal PQ 未满：
           same-page prefetch 正常进入 PQ
           cross-page prefetch 正常进入 PQ
           后续行为与原始 Permit PGC 完全一致：
                正常 translation
                正常 TLB/STLB/PTW
                正常发 data prefetch

    -> 如果 internal PQ 满：
           same-page prefetch 直接 drop，保持原始行为
           cross-page prefetch 不直接 drop
           而是进入 sideband rescue queue
```

rescue queue 中的 cross-page prefetch 之后只能做：

```text
translation-only request:
    正常查 DTLB/STLB
    如果 miss，正常走 PTW
    PTW 返回后允许正常填充 demand-visible DTLB/STLB
    translation 完成后直接结束
    不发 data prefetch
    不进入 L1D data lookup
    不分配 data cache MSHR
    不访问 L1D/L2C/LLC data cache line
    不产生 data cache fill
```

也就是说：

```text
rescue entry 保留 translation-side effect；
rescue entry 不产生 data-prefetch-side effect。
```

---

## 四、只 rescue 哪些 prefetch？

必须严格限制 rescue 条件。

只有同时满足以下条件的 prefetch 才能进入 rescue queue：

```text
1. 来源是 vBerti / L1D data prefetcher。
2. 是 cross-page prefetch。
3. 该 prefetch 原本已经通过前面的合法性检查。
4. 它唯一被 drop 的原因是 internal PQ full。
5. Ordered PQ-full TLB Rescue 模式已经打开。
```

不能 rescue 以下情况：

```text
1. same-page prefetch。
2. 非 vBerti prefetch。
3. demand 访问。
4. instruction fetch。
5. 因 duplicate / already in cache / invalid address / degree limit / PGC discard 等原因被 drop 的 prefetch。
6. 因其他非 PQ full 原因被 drop 的 prefetch。
```

实现时，请把 rescue 分支放在“原本因为 PQ full 即将 drop prefetch”的代码位置附近。
不要在 prefetch 生成的一开始就无条件塞入 rescue queue。

---

## 五、cross-page 判断

如果代码中已有 cross-page metadata，请直接复用。

否则使用如下定义：

```cpp
trigger_vpn = trigger_vaddr >> LOG2_PAGE_SIZE;
pf_vpn      = pf_vaddr      >> LOG2_PAGE_SIZE;

is_cross_page_prefetch = (trigger_vpn != pf_vpn);
```

对于 vBerti 生成的每个 prefetch，需要能知道：

```text
1. trigger address / base address
2. prefetch address
3. 是否 cross-page
```

如果当前 packet 结构没有字段，请最小化添加 metadata，例如：

```cpp
bool is_vberti_prefetch;
bool is_cross_page_prefetch;
```

不要大规模改动 packet 结构。

---

## 六、seq_id 设计

每个 vBerti 发出的 prefetch 都必须分配一个单调递增的 `seq_id`。

建议每个 core 一个 seq counter：

```cpp
uint64_t vberti_pf_seq_counter = 0;
```

每次 vBerti 生成一个 prefetch packet：

```cpp
packet.seq_id = vberti_pf_seq_counter++;
```

要求：

```text
1. same-page prefetch 和 cross-page prefetch 都分配 seq_id。
2. 正常进入 PQ 的 prefetch 保留 seq_id。
3. 进入 rescue queue 的 prefetch 也保留 seq_id。
4. seq_id 只用于保证 rescue queue 发射顺序，不应改变正常 PQ 的原有调度逻辑。
```

---

## 七、rescue queue 数据结构

请实现一个 per-core sideband rescue queue。

建议命名：

```cpp
pqfull_tlb_rescue_queue
```

或者：

```cpp
cp_tlb_rescue_queue
```

这个 queue 只保存因为 PQ full 被 rescue 的 cross-page prefetch。

推荐 entry 结构：

```cpp
struct PQFullTLBRescueEntry {
    uint64_t seq_id;
    uint64_t vaddr;
    uint64_t ip;

    // 必要的 prefetch metadata
    bool is_vberti_prefetch;
    bool is_cross_page_prefetch;
    bool translation_only_rescue;
};
```

如果 translation path 需要更多字段，例如 cpu id、asid、instruction id、prefetch metadata、fill level 等，请按当前 ChampSim packet 结构最小化添加。

rescue queue 容量：

```text
推荐第一版做成足够大的有限 queue，例如 4096 entries；
也可以用 std::deque 实现为实际运行中近似无限。
```

如果实现有限容量，建议常量：

```cpp
static constexpr size_t PQFULL_TLB_RESCUE_QUEUE_SIZE = 4096;
```

如果 rescue queue 也满了，则该 cross-page prefetch 最终 drop。
但主实验最好让 rescue queue 足够大，避免 rescue queue 自己成为新的瓶颈。

---

## 八、rescue queue 的入队规则

当 vBerti prefetch 生成后：

```text
如果 internal PQ 未满：
    进入原本 PQ，行为不变。

如果 internal PQ 满：
    如果 same-page prefetch：
        直接 drop，行为与原始一致。

    如果 cross-page prefetch：
        如果 Ordered PQ-full TLB Rescue 关闭：
            直接 drop，行为与原始一致。

        如果 Ordered PQ-full TLB Rescue 打开：
            放入 rescue queue。
            不进入 internal PQ。
            后续只能发 translation-only request。
```

伪代码：

```cpp
if (internal_pq_full) {
    if (ordered_pqfull_tlb_rescue_enabled
        && packet.is_vberti_prefetch
        && packet.is_cross_page_prefetch
        && drop_reason == PQ_FULL) {

        packet.translation_only_rescue = true;
        rescue_queue.push(packet);
        stats.cp_pf_pqfull_tlb_rescue_enqueued++;
        return;
    }

    // original behavior
    drop_prefetch(packet);
    return;
}
```

注意：

```text
rescue entry 不应该占用 internal PQ entry。
rescue entry 不应该改变 internal PQ 的 full / empty 判断。
rescue entry 不应该阻塞 normal PQ 的 enqueue / dequeue。
```

---

## 九、rescue queue 的发射顺序：必须 ordered

这是本实验最关键的地方。

rescue queue 不能在 entry 入队后立刻发 translation。
否则它会绕过 internal PQ 中更老的 prefetch，导致 translation 被人为提前，实验不干净。

必须保证：

```text
rescue queue 只有在它的 head entry 已经不晚于 normal PQ 中所有更老的 entry 时，才允许发 translation。
```

更具体地说：

```text
如果 internal PQ 为空：
    rescue queue head 可以发 translation。

如果 internal PQ 非空：
    只有当 rescue_queue.head.seq_id 小于 internal PQ 中当前最老 entry 的 seq_id 时，
    rescue queue head 才可以发 translation。
```

如果 internal PQ 是严格 FIFO，最老 entry 就是 PQ head：

```cpp
rescue_can_issue = rescue_head.seq_id < internal_pq.head.seq_id;
```

如果 internal PQ 不是严格 FIFO，或者不确定是否严格 FIFO，请计算当前 internal PQ 所有 valid entry 中最小的 seq_id：

```cpp
oldest_pq_seq = min(seq_id of all valid entries in internal PQ);

rescue_can_issue = rescue_head.seq_id < oldest_pq_seq;
```

推荐使用更稳妥的版本：

```cpp
bool rescue_can_issue()
{
    if (rescue_queue.empty())
        return false;

    if (internal_pq.empty())
        return true;

    uint64_t oldest_pq_seq = get_oldest_seq_id_in_internal_pq();

    return rescue_queue.front().seq_id < oldest_pq_seq;
}
```

这个规则的含义是：

```text
rescue entry 不能越过任何比它更老的 normal PQ entry。
只有当 internal PQ 中已经没有比它更老的 prefetch 时，它才可以补发 translation。
```

这样才能保证 rescue translation 近似按照 Berti 原始 prefetch stream 的自然顺序执行。

---

## 十、rescue queue 的发射节奏

每个周期最多从 rescue queue 发出 1 个 translation-only request。

伪代码：

```cpp
if (ordered_pqfull_tlb_rescue_enabled
    && rescue_can_issue()
    && tlb_translation_request_can_accept()) {

    auto entry = rescue_queue.front();
    rescue_queue.pop_front();

    issue_translation_only_request(entry);

    stats.cp_pf_pqfull_tlb_rescue_issued++;
}
```

要求：

```text
1. rescue queue 的发射不占用 internal PQ entry。
2. rescue queue 的发射不能作为 internal PQ 阻塞条件。
3. internal PQ 能否正常发射，仍然按照原始 ChampSim 逻辑。
4. rescue translation request 应该使用真实 TLB/STLB/PTW 资源。
5. 如果 TLB translation request queue 或相关入口不能接受，rescue queue 本周期不能发。
6. normal PQ 的原始发射逻辑优先保持不变。
```

如果 normal PQ 和 rescue queue 同周期都想向 TLB 发送 translation request，而 TLB 入口资源有限：

```text
normal PQ / demand / 原始路径优先；
rescue 只在不会破坏原始路径发射的情况下发。
```

但 rescue request 进入 TLB/STLB/PTW 之后，可以真实占用 TLB/PTW 资源，产生后续竞争。
这是实验语义的一部分。

---

## 十一、rescue translation-only request 的行为

rescue entry 发出后，只能执行 translation-only path。

它必须：

```text
1. 正常查 DTLB/STLB。
2. 如果 TLB/STLB miss，正常走 PTW。
3. PTW 可以访问 cache/memory。
4. PTW 可以带来真实 page-walk latency。
5. PTW 返回后可以正常填充 demand-visible DTLB/STLB。
6. translation 完成后直接结束。
```

它绝对不能：

```text
1. 发 L1D data lookup。
2. 发 L2C/LLC data prefetch。
3. 分配 data cache MSHR。
4. 进入 data prefetch queue。
5. 产生 data cache fill。
6. 更新 data cache replacement state。
7. 被统计成 data prefetch useful/useless。
```

核心语义：

```text
rescue request = normal translation side effect + no data prefetch side effect
```

---

## 十二、translation 完成后的截断逻辑

需要在 translation 完成、拿到 PPN 后，但在真正发 data prefetch 前，检查：

```cpp
if (packet.translation_only_rescue) {
    stats.cp_pf_pqfull_tlb_rescue_translated++;
    return; // stop here
}
```

也就是说：

```text
translation side effect 已经发生；
TLB/STLB/PTW 行为已经完成；
但是 data prefetch side effect 必须被完全阻断。
```

不要在 translation 之前 drop。
不要在已经发出 data cache request 后再 drop。
正确截断点是：

```text
VA -> PA translation 完成之后；
L1D data lookup / data prefetch request 发出之前。
```

---

## 十三、这个模式下哪些行为保持不变？

必须保证：

```text
1. vBerti 的预测逻辑不变。
2. vBerti 的 same-page prefetch 行为不变，除了 PQ full 时仍按原始逻辑 drop。
3. PQ 未满时，same-page 和 cross-page prefetch 都按原始逻辑进入 PQ。
4. PQ 未满时的 Permit PGC 行为不变。
5. normal demand load/store 行为不变。
6. instruction fetch 行为不变。
7. TLB/STLB/PTW 原始行为不变。
8. cache hierarchy 配置不变。
9. 默认关闭该模式时，所有行为完全回到原始 ChampSim。
```

这个模式只改变：

```text
PQ full 时，原本要被 drop 的 vBerti cross-page prefetch 的处理：
从“完全 drop”
变成“进入 sideband rescue queue，之后 ordered 地发 translation-only request”。
```

---

## 十四、建议新增统计指标

请尽量不要新增过多统计。建议新增以下 4 个统计指标。如果必须更少，至少保留前 3 个。

```text
cp_pf_pqfull_drop
cp_pf_pqfull_tlb_rescue_enqueued
cp_pf_pqfull_tlb_rescue_issued
cp_pf_pqfull_tlb_rescue_translated
```

含义：

```text
cp_pf_pqfull_drop:
    vBerti cross-page prefetch 因 internal PQ full 原本会被 drop 的次数。
    在 rescue 模式关闭时，它等于实际 drop 数。
    在 rescue 模式打开时，它表示触发 PQ full rescue 条件的次数。

cp_pf_pqfull_tlb_rescue_enqueued:
    rescue 模式打开时，因 PQ full 进入 rescue queue 的 cross-page prefetch 数。

cp_pf_pqfull_tlb_rescue_issued:
    rescue queue 中 entry 实际发出 translation-only request 的次数。

cp_pf_pqfull_tlb_rescue_translated:
    rescue translation-only request 最终完成 translation 的次数。
```

应满足：

```text
rescue_enqueued <= cp_pf_pqfull_drop
rescue_issued <= rescue_enqueued
rescue_translated <= rescue_issued
```

如果 rescue queue 近似无限且仿真足够长，通常：

```text
rescue_enqueued ≈ cp_pf_pqfull_drop
```

另外请尽量复用已有统计：

```text
IPC
demand STLB miss
demand PTW walk
prefetch TLB lookup
prefetch STLB miss
prefetch PTW walk
cross-page prefetch generated
cross-page prefetch issued
```

不要为了本任务新增大量复杂 counter。

---

## 十五、验收条件

### 1. 默认行为回归

不传参数：

```bash
./bin/<config> <args>
```

必须保持原始 ChampSim 行为。
如果用相同 trace、相同配置、相同随机种子，结果应与修改前一致或尽可能 bit-level 一致。

---

### 2. 参数打开后 rescue 生效

传入：

```bash
./bin/<config> --ordered-pqfull-tlb-rescue <args>
```

如果 workload 中存在因 PQ full 被 drop 的 vBerti cross-page prefetch，应看到：

```text
cp_pf_pqfull_drop > 0
cp_pf_pqfull_tlb_rescue_enqueued > 0
cp_pf_pqfull_tlb_rescue_issued > 0
```

---

### 3. rescue 不发 data prefetch

必须确认：

```text
rescue entry translation 完成后不会进入 L1D data lookup；
不会发 data prefetch；
不会分配 data MSHR；
不会产生 data cache fill。
```

rescue entry 只能影响：

```text
TLB/STLB/PTW 和 page-walk 相关状态。
```

---

### 4. rescue 不越过更老的 PQ entry

必须保证：

```text
rescue entry 不能在 internal PQ 中仍存在更老 seq_id entry 的时候发 translation。
```

推荐断言或 debug 检查：

```cpp
assert(internal_pq.empty() || rescue_head.seq_id < oldest_seq_id_in_internal_pq());
```

注意：只有在即将发 rescue entry 时检查。
如果 internal PQ 为空，则允许发。

---

### 5. rescue 不阻塞 internal PQ

必须保证：

```text
rescue queue 不占用 internal PQ entry；
rescue queue 不改变 internal PQ full / empty 判断；
rescue queue 不改变 normal PQ 的原始发射节奏。
```

但 rescue translation 进入 TLB/STLB/PTW 后，允许真实占用 translation 资源，这属于实验语义。

---

## 十六、实验预期解释

该模式用于比较：

```text
Baseline:
    Permit PGC + normal internal PQ
    PQ full 的 cross-page prefetch 被完全 drop

Experiment:
    Permit PGC + Ordered PQ-full TLB Rescue
    PQ full 的 cross-page prefetch 被放入 rescue queue
    之后按 seq_id 顺序发 translation-only request
```

如果实验组相对 baseline 出现：

```text
1. rescue translated 数量明显 > 0
2. prefetch-side TLB/STLB/PTW 活动增加
3. demand STLB miss 下降
4. demand PTW walk 下降
5. IPC 上升
```

则说明：

```text
internal PQ full 确实挡住了一批潜在有用的 cross-page translation prefetch；
这些 prefetch 即使不发 data prefetch，仅作为 TLB/STLB prefetch，也能帮助 demand translation。
```

如果 rescue 增加了 prefetch PTW，但 demand STLB miss 不下降，说明：

```text
被 PQ full drop 的 cross-page prefetch 大多不是有用的 TLB prefetch。
```

如果 IPC 下降，说明：

```text
这些被 rescue 的 translation-only prefetch 可能带来 STLB pollution、PTW traffic、PTE cache pollution 或资源竞争，PQ full 原本可能起到过滤作用。
```

---

## 十七、不要做的事情

本任务不要做以下事情：

```text
1. 不要实现 Shadow-TLB。
2. 不要实现 side-effect-free PTW。
3. 不要实现 no-fill PTW。
4. 不要实现 ideal TLB prefetcher。
5. 不要让 rescue entry 直接 0-cycle 获得 translation。
6. 不要让 rescue entry 进入 L1D data lookup。
7. 不要让 rescue entry 发 data prefetch。
8. 不要让 rescue entry 分配 data cache MSHR。
9. 不要改变 vBerti 的预测逻辑。
10. 不要改变 PQ 未满时的正常行为。
11. 不要改变 same-page prefetch 的正常行为。
12. 不要在默认无参数时改变 ChampSim 行为。
13. 不要让 rescue entry 越过 internal PQ 中更老的 prefetch。
```

---

## 十八、最终交付内容

请完成代码修改，并给出简短说明：

```text
1. 修改了哪些文件。
2. 新增了哪个 bin 参数。
3. 默认关闭时如何保证原始行为不变。
4. rescue queue 的数据结构是什么。
5. seq_id 如何生成和传播。
6. PQ full 时 cross-page prefetch 如何进入 rescue queue。
7. rescue queue 如何按顺序发 translation-only request。
8. translation 完成后如何截断，避免 data prefetch side effect。
9. 新增统计指标的含义。
10. 做了哪些简单验证。
```

最终实现语义必须是：

```text
默认模式：
    完全原始 ChampSim 行为。

--ordered-pqfull-tlb-rescue 模式：
    vBerti 所有 prefetch 分配 seq_id；
    PQ 未满时，prefetch 正常进入 PQ；
    PQ 满时，same-page prefetch 正常 drop；
    PQ 满时，cross-page prefetch 进入 sideband rescue queue；
    rescue queue 不占用 PQ；
    rescue queue 只在不越过更老 PQ entry 的条件下发 translation-only request；
    rescue request 正常访问 TLB/STLB/PTW，并可以填充 demand-visible TLB/STLB；
    rescue request translation 完成后直接结束；
    rescue request 绝对不能发 data prefetch 或进入 L1D data lookup。
```
