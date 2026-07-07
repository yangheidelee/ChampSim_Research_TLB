你需要在 ChampSim 中实现一个新的实验配置：**vBerti + Permit PGC + Shadow-TLB Baseline**。

这个配置用于和当前已有的 **vBerti + Permit PGC + Normal TLB behavior** 对比，评估 cross-page data prefetch 触发的 translation 在正常填充 demand-visible TLB/STLB 时，能够给后续 demand translation 带来多少真实净收益。

请注意：本任务不是实现 ideal TLB prefetcher，也不是实现 side-effect-free PTW，也不是禁止 cross-page data prefetch。我们只实现一个 **512-entry FIFO Shadow-TLB Baseline**。

---

## 一、实验目标

当前 Normal Permit-PGC 的语义是：

```text
vBerti 允许发出 cross-page data prefetch；
cross-page data prefetch 需要进行 VA -> PA translation；
prefetch translation miss 后会正常走 TLB/STLB/PTW；
PTW 返回后会正常填充 demand-visible DTLB/STLB；
后续 demand 访问同一个 page 时，可能命中这些由 prefetch 带来的 translation。
```

这意味着 Normal Permit-PGC 里，cross-page data prefetch 可能隐式地产生 TLB prefetch 效果。

现在需要实现一个 Shadow-TLB Baseline：

```text
vBerti 仍然允许发 cross-page data prefetch；
cross-page data prefetch 仍然需要真实地址翻译；
prefetch translation miss 后仍然走真实 PTW；
PTW 仍然可以访问 cache/memory，也就是保留真实 page-walk side effects；
prefetch 拿到 PPN 后，仍然可以正常发 data prefetch；
但是 prefetch translation 结果不能填充 demand-visible DTLB/STLB；
demand 访问不能查询 Shadow-TLB；
后续 demand 不能因为这个 prefetch translation 而 TLB/STLB hit。
```

最终我们会比较：

```text
IPC_normal / IPC_shadow
```

这个 speedup 解释为：

```text
Normal Permit-PGC 中，cross-page data prefetch translation 对 demand-visible TLB/STLB 的真实净收益。
```

注意：这个 Shadow baseline 保留真实 PTW。因此 prefetch PTW 可能会把 page table entries 带进 cache，从而预热后续 demand PTW。这是本实验接受的行为。不要实现 no-fill PTW，不要实现 side-effect-free PTW。

---

## 二、必须添加一个干净的运行时开关

请添加一个运行时开关，用来严格区分 normal 和 shadow 两种模式。

推荐形式：

```bash
--l1d-pf-tlb-mode=normal
--l1d-pf-tlb-mode=shadow
```

也可以用布尔开关：

```bash
--shadow-l1d-prefetch-tlb
```

但更推荐 enum 形式，方便以后扩展。

默认必须是 normal，保证不加参数时 ChampSim 行为与原始版本一致。

建议内部定义：

```cpp
enum class L1D_PF_TLB_MODE {
    NORMAL,
    SHADOW
};
```

两种模式语义：

```text
NORMAL:
    维持当前原始行为。
    L1D prefetch translation 正常查询、更新、填充 demand-visible DTLB/STLB。

SHADOW:
    只对 cross-page L1D data prefetch 启用 Shadow-TLB translation path。
    demand 访问完全不变。
    same-page prefetch 暂时保持 normal 行为。
```

---

## 三、Shadow mode 只影响哪些访问？

Shadow mode 下，特殊路径只作用于：

```text
access_type == PREFETCH
&& 是 L1D data prefetcher 产生的 prefetch
&& 是 vBerti / L1D prefetch 产生的 prefetch
&& 是 cross-page prefetch
```

cross-page 判断方式：

```cpp
trigger_vpn = trigger_vaddr >> LOG2_PAGE_SIZE;
pf_vpn      = pf_vaddr      >> LOG2_PAGE_SIZE;

is_cross_page_prefetch = (trigger_vpn != pf_vpn);
```

如果当前代码中已经有 cross-page prefetch metadata，请直接复用。
如果没有，请最小化添加 metadata，只添加必要字段，例如：

```cpp
bool is_cross_page_prefetch;
```

不要大规模改动 PACKET / metadata 结构。

---

## 四、Shadow-TLB 的结构定义

请实现一个 **per-core private 512-entry FIFO Shadow-TLB**。

它不是 STLB clone，也不是 ideal TLB，而是一个只服务 cross-page L1D data prefetch 的 private translation buffer。

具体要求：

```text
1. 每个 core 一个 Shadow-TLB，不能跨 core 共享。
2. 每个 Shadow-TLB 固定 512 entries。
3. 每个 entry 保存 4KB page translation，即 VPN -> PPN。
4. 每个 entry 至少包含 valid、vpn、ppn。
5. replacement policy 使用 FIFO。
6. Shadow-TLB hit latency 使用当前 STLB hit latency。
7. Shadow-TLB 只允许 shadow mode 下的 cross-page L1D data prefetch 查询和填充。
8. demand load/store 不能查询或填充 Shadow-TLB。
9. instruction fetch 不能查询或填充 Shadow-TLB。
10. same-page prefetch 不能查询或填充 Shadow-TLB。
11. 其他 prefetch 暂时不能查询或填充 Shadow-TLB。
12. Shadow-TLB miss 后必须走真实 PTW。
13. PTW 返回后只填 Shadow-TLB，绝对不能填 demand-visible DTLB/STLB。
```

推荐 entry 结构：

```cpp
struct ShadowTLBEntry {
    bool valid = false;
    uint64_t vpn = 0;
    uint64_t ppn = 0;
};
```

推荐实现方式：

```cpp
static constexpr size_t SHADOW_TLB_ENTRIES = 512;

std::deque<uint64_t> fifo_order;
std::unordered_map<uint64_t, uint64_t> vpn_to_ppn;
```

也可以用固定数组实现，但必须保证语义是 512-entry FIFO。

FIFO 行为：

```text
lookup hit:
    返回 PPN。
    不改变 FIFO 顺序。
    不移动到队尾。
    不模拟 LRU。

lookup miss:
    走真实 PTW。
    PTW 返回后 fill Shadow-TLB。

fill:
    如果 VPN 已经存在，只更新 PPN，不重复插入。
    如果 Shadow-TLB 未满，插入 FIFO 队尾。
    如果 Shadow-TLB 已满，移除 FIFO 队头 entry，再插入新 VPN。
```

注意：hit 时不要更新 FIFO 顺序。否则它就不是 FIFO，而更接近 LRU。

---

## 五、Shadow mode 下的 translation 查询路径

在 shadow mode 下，cross-page L1D data prefetch 的查询顺序必须是：

```text
cross-page L1D prefetch VA
    ↓
read-only 查询正常 demand-visible DTLB/STLB
    ↓ hit
        返回 PPN 给 prefetch；
        不能更新 normal DTLB/STLB replacement state；
        不能 fill normal DTLB/STLB；
        不能改变 normal DTLB/STLB 的任何状态。

    ↓ miss
        查询 512-entry FIFO Shadow-TLB
            ↓ hit
                返回 PPN 给 prefetch；
                不改变 FIFO 顺序。

            ↓ miss
                走真实 PTW；
                PTW 行为保持原始 ChampSim 行为；
                PTW 可以访问 cache/memory；
                PTW 可以产生真实 page-walk latency；
                PTW 返回 PPN 后，只填 Shadow-TLB；
                绝对不能填 normal DTLB/STLB；
                然后 prefetch 拿到 PPN，继续正常发 data prefetch。
```

伪代码语义：

```cpp
if (mode == SHADOW
    && packet.is_l1d_prefetch
    && packet.is_cross_page_prefetch) {

    vpn = packet.vaddr >> LOG2_PAGE_SIZE;

    // Step 1: read-only lookup normal demand-visible TLB hierarchy.
    if (normal_tlb_readonly_hit(vpn)) {
        ppn = normal_tlb_readonly_get_ppn(vpn);

        // 关键：
        // 不能更新 normal DTLB/STLB replacement state。
        // 不能 fill normal DTLB/STLB。
        // 不能 evict normal DTLB/STLB entry。
        return translation_done(ppn);
    }

    // Step 2: lookup 512-entry FIFO Shadow-TLB.
    shadow_cp_pf_lookup++;

    if (shadow_tlb.hit(vpn)) {
        shadow_cp_pf_hit++;
        ppn = shadow_tlb.get_ppn(vpn);

        // FIFO hit 不改变顺序。
        return translation_done(ppn);
    }

    // Step 3: Shadow miss -> real PTW.
    shadow_cp_pf_miss++;

    ppn = real_page_walk(packet);

    // real_page_walk 保持原始 PTW 行为。
    // 它可以访问 cache/memory，也可以 warm page table cache lines。
    // 本任务不要实现 no-fill PTW。

    shadow_tlb.fill(vpn, ppn);

    // 关键：
    // 绝对不能 fill normal DTLB/STLB。
    return translation_done(ppn);
}
else {
    normal_translation_path(packet);
}
```

---

## 六、read-only 查询 normal DTLB/STLB 的要求

Shadow mode 中，cross-page prefetch 可以 read-only 查询正常 DTLB/STLB。

原因是：如果某个 page 的 translation 本来已经由 demand 填进 STLB，那么 prefetch 使用这个 translation 是合理的，不能人为增加 baseline 的 translation latency。

但是这个查询必须是 read-only：

```text
可以读 PPN；
不能更新 LRU / replacement state；
不能设置 useful bit；
不能改变 normal DTLB/STLB 的任何 metadata；
不能 fill；
不能 evict。
```

如果当前 ChampSim 的 TLB lookup 函数默认会更新 replacement state，请新增一个 read-only lookup 接口，例如：

```cpp
bool lookup_readonly(uint64_t vpn, uint64_t& ppn) const;
```

或者增加参数：

```cpp
lookup(packet, update_replacement=false, allow_fill=false);
```

不要让 shadow prefetch lookup 扰动 demand-visible TLB 状态。

---

## 七、谁能填 Shadow-TLB？

只有下面这条路径可以 fill Shadow-TLB：

```text
cross-page L1D data prefetch
    -> read-only 查 normal DTLB/STLB miss
    -> 查 Shadow-TLB miss
    -> 走真实 PTW
    -> PTW 返回 PPN
    -> fill Shadow-TLB
```

以下情况不能 fill Shadow-TLB：

```text
1. demand load/store 不能 fill。
2. instruction fetch 不能 fill。
3. same-page prefetch 不能 fill。
4. 其他 prefetch 不能 fill。
5. cross-page prefetch 如果 read-only normal DTLB/STLB hit，不能 fill Shadow-TLB。
6. cross-page prefetch 如果 Shadow-TLB hit，不能重复 fill。
7. prefetch 如果在进入 translation 前被 filter / duplicate check / PQ full drop 掉，不能 fill。
```

---

## 八、Demand 访问路径绝对不能改

Demand load/store 的路径必须保持原始行为：

```text
demand load/store
    -> DTLB
    -> STLB
    -> PTW
    -> fill demand-visible DTLB/STLB
```

Demand 绝对不能：

```text
查 Shadow-TLB；
命中 Shadow-TLB；
更新 Shadow-TLB；
填充 Shadow-TLB；
把 Shadow-TLB hit 统计成 demand TLB hit。
```

Instruction fetch 路径也不能改。

---

## 九、哪些路径不能改

请严格保证以下路径不变：

```text
1. demand load/store translation path 不变。
2. instruction fetch translation path 不变。
3. same-page L1D prefetch 暂时不变。
4. 非 L1D prefetch 暂时不变。
5. vBerti 的 prefetch 生成逻辑不变。
6. Permit PGC 的 page-crossing 允许逻辑不变。
7. Normal mode 下所有行为不变。
8. PTW 原始行为不变。
```

也就是说，本次改动只影响：

```text
shadow mode 下的 cross-page L1D data prefetch translation fill 行为。
```

---

## 十、关于 PTW 的要求

Shadow mode 下，cross-page prefetch 如果 Shadow-TLB miss，仍然要走真实 PTW。

请保留：

```text
PTW latency；
PTW queue/MSHR/resource 行为；
PTW 对 cache/memory 的访问；
PTE cache line 可能进入 L1D/L2/LLC；
page-walk side effects。
```

不要实现：

```text
side-effect-free PTW；
no-fill PTW；
固定延迟 PTW；
ideal PTW；
0-cycle translation。
```

本任务的 baseline 是：

```text
Shadow-realPTW baseline。
```

---

## 十一、新增统计指标最多三个

请尽可能少加新统计。最多只新增下面三个 counter：

```text
shadow_cp_pf_lookup
shadow_cp_pf_hit
shadow_cp_pf_miss
```

含义：

```text
shadow_cp_pf_lookup:
    shadow mode 下，cross-page L1D prefetch 在 read-only normal DTLB/STLB miss 后，查询 Shadow-TLB 的次数。

shadow_cp_pf_hit:
    上述 Shadow-TLB 查询命中的次数。

shadow_cp_pf_miss:
    上述 Shadow-TLB 查询 miss 的次数。
    该 miss 后应走真实 PTW，并在 PTW 返回后 fill Shadow-TLB。
```

必须满足：

```text
shadow_cp_pf_lookup = shadow_cp_pf_hit + shadow_cp_pf_miss
```

请把这三个 counter 同时输出到 plain printer 和 json printer。

不要新增大量统计项。已有的 IPC、demand STLB miss、demand PTW walk、L1D prefetch issued、cross-page prefetch 相关统计尽量复用现有代码。

---

## 十二、关键正确性要求

### 1. Normal mode 行为不变

不加参数或者使用：

```bash
--l1d-pf-tlb-mode=normal
```

时，仿真结果应与修改前一致或尽可能 bit-level 一致。

---

### 2. Shadow mode 中 demand 不能访问 Shadow-TLB

必须保证：

```text
demand load/store 不查 Shadow-TLB；
instruction fetch 不查 Shadow-TLB；
demand miss 不填 Shadow-TLB；
Shadow-TLB hit 不能算 demand TLB hit。
```

---

### 3. Shadow mode 中 cross-page prefetch 不能填 normal DTLB/STLB

对于 shadow mode 下的 cross-page L1D prefetch：

```text
不能 fill demand-visible DTLB；
不能 fill demand-visible STLB；
不能更新 demand-visible TLB replacement state；
不能 evict demand-visible TLB entry。
```

但是它可以：

```text
read-only 查询 normal DTLB/STLB；
miss 后查询 Shadow-TLB；
Shadow-TLB miss 后走真实 PTW；
PTW 完成后 fill Shadow-TLB；
拿到 PPN 后继续发 data prefetch。
```

---

### 4. Shadow mode 中 prefetch 仍然有真实 translation latency

不能把 cross-page prefetch 的 translation 直接 bypass 成 0 latency。

如果 Shadow-TLB miss，必须经历真实 PTW 流程。

---

### 5. Shadow-TLB FIFO 行为正确

必须保证：

```text
Shadow-TLB 固定 512 entries；
hit 不改变 FIFO 顺序；
fill 时如果未满，插入队尾；
fill 时如果已满，移除队头，再插入队尾；
重复 VPN fill 只更新 PPN，不重复插入。
```

---

### 6. Shadow-TLB counter 合理

shadow mode 下，如果 workload 存在 cross-page L1D prefetch，应看到：

```text
shadow_cp_pf_lookup > 0
shadow_cp_pf_lookup = shadow_cp_pf_hit + shadow_cp_pf_miss
```

normal mode 下，这三个 counter 应该为 0 或不输出。

---

## 十三、建议的测试方式

### 测试 1：编译通过

```bash
./config.sh ...
make -j
```

确保 normal 和 shadow 两种模式都可以编译。

---

### 测试 2：Normal mode 回归

运行一个短 trace：

```bash
./bin/xxx --l1d-pf-tlb-mode=normal ...
```

确认和原始版本相比，输出指标基本一致。

---

### 测试 3：Shadow mode 功能检查

运行同一个短 trace：

```bash
./bin/xxx --l1d-pf-tlb-mode=shadow ...
```

检查：

```text
shadow_cp_pf_lookup = shadow_cp_pf_hit + shadow_cp_pf_miss
shadow_cp_pf_lookup > 0    // 如果 trace 中存在 cross-page L1D prefetch
程序不崩溃
IPC 正常输出
TLB / PTW 统计正常输出
```

---

### 测试 4：对比 Normal vs Shadow

同一个 workload，分别运行：

```bash
--l1d-pf-tlb-mode=normal
--l1d-pf-tlb-mode=shadow
```

预期：

```text
Normal 允许 cross-page prefetch translation 填 demand-visible TLB/STLB；
Shadow 禁止 cross-page prefetch translation 填 demand-visible TLB/STLB；
Shadow 中 cross-page prefetch translation 可以查 512-entry FIFO Shadow-TLB；
Shadow 中 Shadow-TLB miss 后仍然走真实 PTW；
IPC 可能不同；
demand STLB miss / PTW walk 可能不同。
```

如果 shadow mode 的 cross-page prefetch 数量和 normal mode 差异特别大，需要检查是否不小心改变了 vBerti 生成逻辑、PQ 逻辑或 prefetch timing 逻辑。

---

## 十四、不要做的事情

本任务不要实现以下内容：

```text
1. 不要实现 Ideal Demand-visible CP-PB。
2. 不要实现 side-effect-free PTW。
3. 不要实现 no-fill PTW。
4. 不要把 prefetch translation 直接变成 0 latency。
5. 不要禁止 cross-page data prefetch。
6. 不要改变 vBerti 的预测逻辑。
7. 不要改变 Permit PGC 的允许策略。
8. 不要新增超过三个统计指标。
9. 不要让 demand 查询 Shadow-TLB。
10. 不要让 Shadow-TLB entry 填入 normal DTLB/STLB。
11. 不要让 Shadow-TLB 做成无限大。
12. 不要让 Shadow-TLB 做成 LRU，当前要求是 FIFO。
```

---

## 十五、最终交付内容

请完成代码修改，并给出简短说明：

```text
1. 修改了哪些文件。
2. 新增了哪个运行时开关。
3. 512-entry FIFO Shadow-TLB 的结构是什么。
4. Shadow mode 的 translation path 如何工作。
5. 新增的三个 counter 分别是什么意思。
6. 如何运行 normal 和 shadow 两种模式。
7. 做了哪些简单验证。
```

最终实验配置语义必须是：

```text
Normal:
    vBerti + Permit PGC + normal demand-visible TLB fill

Shadow:
    vBerti + Permit PGC + 512-entry FIFO Shadow-TLB Baseline
    cross-page L1D prefetch translation 不填 demand-visible DTLB/STLB
    cross-page L1D prefetch translation 先 read-only 查 normal DTLB/STLB
    read-only miss 后查 512-entry FIFO Shadow-TLB
    Shadow-TLB miss 后走真实 PTW
    PTW 返回后只填 Shadow-TLB
    demand 永远不能查 Shadow-TLB
```

这个实现用于后续比较：

```text
IPC_normal / IPC_shadow
```

解释为：

```text
Normal Permit-PGC 中，cross-page data prefetch translation 对 demand-visible TLB/STLB 的真实净收益。
```
