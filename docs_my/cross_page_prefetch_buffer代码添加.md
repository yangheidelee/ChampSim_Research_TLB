你需要在当前 ChampSim 代码中实现一个用于实验归因的 **STLB Cross-page Prefetch Buffer, CP-PB** 配置，用来验证：vBerti 的 cross-page data prefetch 对 TLB 系统效果差，是否是因为 cross-page prefetch translation 正常进入 STLB 时会产生污染 / replacement 干扰；如果把这些 translation 放入一个独立 buffer，并在 demand STLB miss 后查询它，能否减少 STLB demand miss / PTW / 提升 IPC。

核心要求：**默认 baseline 行为必须完全不变**。只有显式通过命令行参数开启时，才启用 CP-PB 实验配置。

---

## 1. 新增命令行开关

请新增一个 bin 运行参数，例如：

```bash
--enable-stlb-cp-pb
```

语义：

* 默认不加该参数：baseline 行为完全不变。
* 加上该参数：启用 STLB CP-PB 实验配置。

如果当前 ChampSim 项目已有命令行参数解析框架，请接入现有框架。
如果没有，请在当前 binary/main 入口处添加一个干净的 bool 全局/配置变量，例如：

```cpp
bool enable_stlb_cp_pb = false;
```

并保证该开关可以被 STLB/TLB 层访问。

重要要求：

```text
未启用 --enable-stlb-cp-pb 时：
1. 不改变任何 cache/TLB/PTW 行为。
2. 不改变 vBerti 原本 cross-page prefetch 的流向。
3. 不改变已有统计口径。
4. 新增统计可以打印 0，但不能影响原始统计。
```

---

## 2. CP-PB 实验配置的语义

启用 `--enable-stlb-cp-pb` 后，只改变 **vBerti cross-page prefetch translation** 在 STLB 层的处理方式。

### 2.1 Baseline 行为

正常 Permit PGC 下：

```text
vBerti cross-page prefetch
→ 触发 DTLB / STLB lookup
→ 如果 STLB miss 并最终获得 translation
→ translation 正常 fill 进 STLB
```

这样 cross-page prefetch translation 会占用 STLB entry，可能替换 demand-useful translation。

---

### 2.2 CP-PB 行为

启用 CP-PB 后：

```text
vBerti cross-page prefetch
→ 触发 DTLB / STLB lookup
→ 如果 STLB miss 并最终获得 translation
→ 不 fill 进 STLB
→ 而是 fill 进 CP-PB
```

也就是说：

```text
cross-page prefetch translation 不再污染 STLB；
它被隔离保存到独立 CP-PB 中。
```

后续 demand 的路径：

```text
demand DTLB miss
    ↓
正常查 STLB
    ↓
如果 STLB hit：
    正常 STLB hit，正常 fill DTLB
如果 STLB miss：
    raw_STLB_demand_miss++
    再查 CP-PB
        ↓
        如果 CP-PB hit：
            CP_PB_demand_hit++
            使用 CP-PB 中的 translation
            fill DTLB
            fill STLB
            删除 CP-PB 中该 entry
            不触发 PTW
        如果 CP-PB miss：
            STLB_PB_demand_miss++
            正常触发 PTW
```

注意：

* CP-PB hit 不加额外延迟，作为 ideal / oracle 实验。
* CP-PB hit 后需要 fill 回 STLB，因为此时该 translation 已经被 demand 访问，属于 demand-useful translation。
* CP-PB hit 后需要 fill DTLB，否则后续同页 demand 仍会不合理地重复 miss。
* CP-PB hit 后不要再触发 PTW。
* CP-PB hit 后不要增加 `stlb_miss_touch_dram.count` 或 PTW 相关访问计数。

---

## 3. CP-PB 的结构

第一版 CP-PB 做成理想无限 buffer 即可，目的是归因，不是最终硬件设计。

建议实现为：

```cpp
std::unordered_map<uint64_t, TranslationEntry> stlb_cp_pb;
```

key 使用 VPN，不要使用 cache block address。

`TranslationEntry` 至少需要保存：

```cpp
struct TranslationEntry {
    uint64_t vpn;
    uint64_t ppn;
    // 如果当前 TLB entry 还包含 page size、permission、metadata，也需要一并保存。
};
```

如果当前 ChampSim 的 TLB entry / block 结构中已经有完整 translation 信息，请直接复制必要字段，不要只保存 VPN，否则 CP-PB hit 后无法正确完成地址翻译。

如果项目中虚拟地址到物理地址转换只需要 PPN，则保存 VPN→PPN 即可。

---

## 4. 哪些 prefetch 可以进入 CP-PB

只能让下面这一类进入 CP-PB：

```text
vBerti cross-page prefetch 触发的 translation
并且原本会 fill STLB 的 translation
```

不要让以下访问进入 CP-PB：

```text
1. demand translation
2. same-page prefetch translation
3. 非 vBerti 的 prefetch translation
4. instruction prefetch / L1I prefetch translation
5. 普通 data prefetch 但不是 cross-page 的 translation
```

因此你需要在 request / packet / metadata 中确认是否已经能识别：

```text
is_prefetch
is_vberti
is_cross_page
source == L1D_vBerti_cross_page_prefetch
```

如果当前代码已有类似统计字段，例如：

```text
Core_0_STLB_vberti_cross_page_prefetch
Core_0_STLB_vberti_cross_page_prefetch_miss
```

请复用同一套判断条件，确保 CP-PB 接收对象和这些统计口径一致。

如果当前 packet 中没有足够 metadata，请补充 metadata，并沿 DTLB → STLB → PTW → fill 路径传递。

---

## 5. STLB demand lookup 中的行为

启用 CP-PB 后，demand 访问路径要变成：

```cpp
if (is_demand) {
    access DTLB;

    if (DTLB miss) {
        access STLB;

        if (STLB hit) {
            // 正常路径
            fill DTLB;
        } else {
            stats.raw_STLB_demand_miss++;

            if (enable_stlb_cp_pb && cp_pb.contains(vpn)) {
                stats.CP_PB_demand_hit++;

                translation = cp_pb[vpn];

                fill DTLB with translation;
                fill STLB with translation;  // 作为 demand-useful translation
                cp_pb.erase(vpn);

                // 不触发 PTW
            } else {
                stats.STLB_PB_demand_miss++;

                // 正常 PTW 路径
                issue_page_walk;
            }
        }
    }
}
```

注意：

* `raw_STLB_demand_miss` 表示 STLB 本体没有命中的 demand miss。
* `CP_PB_demand_hit` 表示 STLB miss 后被 CP-PB 救回。
* `STLB_PB_demand_miss` 表示 STLB miss 且 CP-PB miss，最终仍要 PTW。
* 因此：

```text
STLB_PB_demand_miss = raw_STLB_demand_miss - CP_PB_demand_hit
```

---

## 6. Cross-page prefetch fill 中的行为

在 baseline 下，vBerti cross-page prefetch translation 原本如何填 STLB，保持不变。

启用 CP-PB 后：

```cpp
if (enable_stlb_cp_pb
    && request_is_vberti_cross_page_prefetch
    && this_translation_would_fill_STLB) {

    insert translation into CP-PB;
    stats.CP_PB_insert++;

    // 不 fill STLB
    return;
}
```

重要：

* 只 redirect 原本要 fill STLB 的 vBerti cross-page prefetch translation。
* 不要影响 demand fill STLB。
* 不要影响 same-page prefetch。
* 不要影响 STLB hit 的情况，因为 hit 时本来就不需要 fill。
* 如果 CP-PB 中已有相同 VPN，可以覆盖旧 entry，或者保持一份即可；建议覆盖并统计一次 insert。

---

## 7. 新增统计指标

请新增并打印以下统计：

```text
Core_0_STLB_raw_demand_miss
Core_0_CP_PB_insert
Core_0_CP_PB_demand_hit
Core_0_STLB_PB_demand_miss
Core_0_CP_PB_coverage
Core_0_STLB_raw_demand_mpki
Core_0_STLB_PB_demand_mpki
Core_0_CP_PB_demand_hit_mpki
```

其中：

```text
Core_0_STLB_raw_demand_miss
= demand DTLB miss 后，STLB lookup miss 的次数，不考虑 CP-PB 是否救回。
```

```text
Core_0_CP_PB_demand_hit
= STLB miss 后，CP-PB 命中的次数。
```

```text
Core_0_STLB_PB_demand_miss
= STLB miss 且 CP-PB miss，最终需要 PTW 的 demand miss。
```

```text
Core_0_CP_PB_coverage
= Core_0_CP_PB_demand_hit / Core_0_STLB_raw_demand_miss
```

如果分母为 0，则 coverage 打印为 0。

MPKI 计算：

```text
Core_0_STLB_raw_demand_mpki =
Core_0_STLB_raw_demand_miss / retired_instruction_count * 1000
```

```text
Core_0_STLB_PB_demand_mpki =
Core_0_STLB_PB_demand_miss / retired_instruction_count * 1000
```

```text
Core_0_CP_PB_demand_hit_mpki =
Core_0_CP_PB_demand_hit / retired_instruction_count * 1000
```

如果项目已有统计系统，请按现有 stats 类、plain_printer、json_printer 的风格添加。

---

## 8. Baseline 与 CP-PB 配置必须严格区分

这是最重要的要求。

### 未启用 `--enable-stlb-cp-pb`

行为必须是：

```text
vBerti cross-page prefetch translation 正常 fill STLB
demand STLB miss 正常触发 PTW
CP-PB 不参与 lookup
CP-PB 不接收任何 entry
```

也就是说 baseline 的 IPC、MPKI、STLB demand miss、PTW 访问等应当和修改前完全一致。

---

### 启用 `--enable-stlb-cp-pb`

行为才变为：

```text
vBerti cross-page prefetch translation 不 fill STLB，而是 fill CP-PB
demand STLB miss 后查 CP-PB
CP-PB hit 避免 PTW，并 fill DTLB/STLB
```

不要通过编译宏、手工改代码、注释代码来切换。必须通过运行参数切换。

---

## 9. 验收标准

请完成后用至少一个 trace 跑两组配置：

### Baseline

```bash
./bin/xxx ... 
```

不加 `--enable-stlb-cp-pb`

### CP-PB 配置

```bash
./bin/xxx ... --enable-stlb-cp-pb
```

比较输出指标。

### Baseline 预期

```text
Core_0_CP_PB_insert = 0
Core_0_CP_PB_demand_hit = 0
Core_0_CP_PB_coverage = 0
Core_0_STLB_PB_demand_miss 应该等于普通 STLB demand miss 或 raw_STLB_demand_miss
```

并且 baseline 行为应与修改前一致。

### CP-PB 配置预期

如果存在 cross-page translation benefit，则可能看到：

```text
Core_0_CP_PB_insert > 0
Core_0_CP_PB_demand_hit > 0
Core_0_CP_PB_coverage > 0
Core_0_STLB_PB_demand_miss < Core_0_STLB_raw_demand_miss
stlb_miss_touch_dram.count 可能下降
IPC 可能提升
```

如果：

```text
Core_0_CP_PB_demand_hit 很低
Core_0_STLB_PB_demand_miss 几乎等于 Core_0_STLB_raw_demand_miss
IPC 不变
```

则说明 cross-page prefetch translation 本身和 future demand STLB miss stream 匹配度低，而不是 STLB pollution / retention 问题。

---

## 10. 注意事项

1. CP-PB key 必须是 VPN，不是 cache block address。
2. CP-PB 中必须保存足够 translation 信息，至少 VPN→PPN。
3. CP-PB hit 不加额外延迟。
4. CP-PB hit 后必须避免 PTW。
5. CP-PB hit 后建议 fill DTLB 和 STLB，并删除 CP-PB entry。
6. CP-PB 只接收 vBerti cross-page prefetch translation。
7. Demand translation 永远不能直接插入 CP-PB。
8. 未启用开关时，CP-PB 不能影响任何路径。
9. 统计 raw miss 与 PB 后 miss 时要避免重复计数。
10. coverage 公式应为：

```text
CP_PB_coverage = CP_PB_demand_hit / raw_STLB_demand_miss
```

不要写成：

```text
CP_PB_demand_hit / (CP_PB_demand_hit + raw_STLB_demand_miss)
```

因为 raw_STLB_demand_miss 已经包含 CP_PB_demand_hit。
