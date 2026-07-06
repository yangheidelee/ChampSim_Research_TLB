# vBerti 跨页预取 TLB 指标实现记录

本文记录本次按照 `docs_my/TLB指标添加.md` 在 ChampSim 中添加的统计逻辑。修改目标是分析 L1D data prefetcher = vBerti 时，same-page / cross-page prefetch 在 DTLB、STLB 和整个 TLB-system 中的行为。

本次修改只添加统计字段、stats-only metadata 和打印逻辑，不改变 vBerti 算法、cache/TLB replacement、miss handling、prefetch decision 或仿真功能行为。

## 核心思想

same-page / cross-page 的判断必须发生在 vBerti 生成 prefetch candidate 的那一刻。

原因是 DTLB/STLB 端只能看到 prefetch target virtual address，已经不知道这个 prefetch 是由哪个 trigger address 触发的。因此不能在 TLB 端重新根据 target VA 猜测是否跨页。

实现路径如下：

1. vBerti 在 `prefetcher/vberti/vberti.cc` 中生成每个 prefetch candidate。
2. 对当前 candidate 计算：

```text
trigger_vpn = trigger_addr >> LOG2_PAGE_SIZE
target_vpn  = pf_addr      >> LOG2_PAGE_SIZE
is_cross_page = target_vpn != trigger_vpn
```

3. 通过 `inc/tlb_prefetch_metadata.h` 中的 helper 把 same/cross 信息写入 `pf_metadata`。
4. `CACHE::prefetch_line()` 把 `pf_metadata` 保存在 prefetch request 中。
5. `CACHE::issue_translation()` 构造发往 TLB 的 translation request 时，把 `pf_metadata` 和 `translation_source` 一起传下去。
6. DTLB/STLB hit/miss path 根据 `translation_source` 做分类统计。

## 新增 metadata

新增文件：

```text
inc/tlb_prefetch_metadata.h
```

里面定义：

```cpp
L1D_PREF_META_VALID
L1D_PREF_META_CROSS
L1D_PREF_META_MASK
```

语义：

- `L1D_PREF_META_VALID`：该 prefetch candidate 已经被 L1D vBerti 标记过。
- `L1D_PREF_META_CROSS`：该 prefetch candidate 的 target VPN 与 trigger VPN 不同，即 cross-page prefetch。
- `L1D_PREF_META_MASK`：本次统计使用的高位 bit 集合。

实现上使用：

```cpp
make_l1d_pref_meta(metadata_in, is_cross_page)
```

这个 helper 会先清掉本统计使用的两个高位 bit，再按照当前 candidate 重新设置 valid/cross。这样可以避免旧 cache block 的 `metadata_in` 携带历史 CROSS bit，导致新的 same-page prefetch 被误标成 cross-page。

低位 metadata 保留给原有 prefetcher 逻辑使用，不被覆盖。

## 新增 translation_origin

修改文件：

```text
inc/access_type.h
```

新增：

```cpp
L1D_PREFETCH_SAME_PAGE
L1D_PREFETCH_CROSS_PAGE
```

同时保留原来的：

```cpp
L1D_PREFETCH
```

原来的 `L1D_PREFETCH` 作为 fallback：如果某个 L1D prefetch 没有携带本次新增的 metadata，就仍然使用旧的 origin。

`translation_origin_names` 同步增加：

```text
L1D_Prefetch_Same_Page
L1D_Prefetch_Cross_Page
```

## origin 如何传到 TLB

关键函数在：

```text
src/cache.cc
```

### `CACHE::classify_translation_origin()`

语义：

该函数给即将发往 TLB 的 translation request 标记来源。

实现逻辑：

- 如果 request 是 L1D 自己发出的 prefetch，并且 `pf_metadata` 有 `L1D_PREF_META_VALID`：
  - `L1D_PREF_META_CROSS` 为 true，返回 `L1D_PREFETCH_CROSS_PAGE`
  - 否则返回 `L1D_PREFETCH_SAME_PAGE`
- 如果是 L1D prefetch 但没有本次 metadata，返回旧的 `L1D_PREFETCH`
- 如果是 L1I prefetch，返回 `L1I_PREFETCH`
- 如果是 demand instruction，返回 `DEMAND_INSTRUCTION`
- 其他 demand data，返回 `DEMAND_DATA`

### `CACHE::issue_translation()`

语义：

这个函数从 cache request 构造 translation request，并送入下一级 TLB。

本次补充了：

```cpp
fwd_pkt.pf_metadata = q_entry.pf_metadata;
fwd_pkt.translation_source = classify_translation_origin(q_entry);
```

这样 vBerti 生成 candidate 时写入的 same/cross metadata 可以真正进入 DTLB/STLB。

## vBerti internal 指标

相关统计字段在：

```text
inc/cache_stats.h
```

字段：

```cpp
vberti_prefetch_requested
vberti_cross_page_requested
vberti_prefetch_issued
vberti_cross_page_issued
```

计数位置：

```text
prefetcher/vberti/vberti.cc
src/cache.cc
```

### `Core_N_vBerti_Requested`

语义：

vBerti 内部生成并且通过 policy gating、准备尝试进入 L1D internal PQ 的 prefetch candidate 数量。这个数表示 vBerti 在当前配置下真正尝试提交给 cache prefetch path 的候选请求，不代表这些 prefetch 一定成功进入 L1D internal PQ。

如果配置/编译逻辑禁止跨页预取，例如 `NO_CROSS_PAGE`，cross-page candidate 会在该 policy 判断处被丢弃，不计入 `Requested`。因此 `Requested - Issued` 不再混入 no-cross policy discard。

实现：

在 `prefetcher/vberti/vberti.cc` 中，vBerti 每生成一个合法 `p_addr` candidate 后，先判断 same/cross-page；如果当前配置允许这个 candidate 继续尝试进入 prefetch path，才调用：

```cpp
intern_->record_l1d_prefetch_candidate(pf_metadata);
```

随后在 `CACHE::record_l1d_prefetch_candidate()` 中：

```cpp
++sim_stats.vberti_prefetch_requested;
```

### `Core_N_vBerti_Cross_page_prefetch_in_Requested`

语义：

在所有 vBerti requested candidates 中，target VPN 与 trigger VPN 不同的 prefetch 数。由于 `Requested` 已经放在 no-cross policy 判断之后，如果当前配置禁止跨页预取，该值应为 0。

实现：

同样在 `CACHE::record_l1d_prefetch_candidate()` 中，如果：

```cpp
is_l1d_pref_cross(prefetch_metadata)
```

则：

```cpp
++sim_stats.vberti_cross_page_requested;
```

### `Core_N_vBerti_Cross_page_prefetch_of_Requested`

语义：

vBerti 在当前 policy 下实际尝试提交给 prefetch path 的 prefetch 中，跨页 prefetch 的比例。

公式：

```text
vberti_cross_page_requested / vberti_prefetch_requested
```

### `Core_N_vBerti_Issued`

语义：

vBerti generated candidate 中，真正被 cache prefetch path 接收并进入 L1D internal PQ 的 prefetch 数。

实现：

在 `CACHE::prefetch_line()` 中，先检查：

```cpp
if (std::size(internal_PQ) >= PQ_SIZE) return false;
```

只有成功 `internal_PQ.emplace_back(...)` 后，才计：

```cpp
++sim_stats.vberti_prefetch_issued;
```

因此 `Issued` 表示成功进入 L1D internal PQ 的 vBerti prefetch。

### `Core_N_vBerti_PQ_Drop_Rate`

语义：

vBerti requested candidates 中，已经通过 policy gating、尝试进入 L1D internal PQ 但没有成功进入的比例。

公式：

```text
(vberti_prefetch_requested - vberti_prefetch_issued) / vberti_prefetch_requested
```

因为 `Requested` 的计数点在 `NO_CROSS_PAGE` 判断之后，所以该指标不混入 no-cross policy discard。它的语义是纯粹的 prefetch path/PQ 接收失败比例，主要对应 L1D internal PQ 满或 cache prefetch path 没有接收。

### `Core_N_vBerti_InPQ_Cross_page_prefetch_of_Requested`

语义：

所有 vBerti requested candidates 中，最终成功进入 L1D internal PQ 的 cross-page prefetch 比例。

公式：

```text
vberti_cross_page_issued / vberti_prefetch_requested
```

### `Core_N_vBerti_Cross_page_PQ_Drop_rate`

语义：

vBerti requested 的 cross-page prefetch 中，没有成功进入 L1D internal PQ 的比例。

公式：

```text
(vberti_cross_page_requested - vberti_cross_page_issued) / vberti_cross_page_requested
```

### `Core_N_vBerti_Cross_page_prefetch_of_Issued`

语义：

真正进入 L1D internal PQ 的 vBerti prefetch 中，cross-page prefetch 的比例。

公式：

```text
vberti_cross_page_issued / vberti_prefetch_issued
```

## DTLB/STLB origin hit/miss 指标

相关字段：

```cpp
dtlb_origin_hits
dtlb_origin_misses
stlb_origin_hits
stlb_origin_misses
```

位置：

```text
inc/cache_stats.h
src/cache.cc
src/plain_printer.cc
```

计数函数：

```cpp
CACHE::record_tlb_origin_hit()
CACHE::record_tlb_origin_miss()
```

计数点：

- TLB tag lookup hit path：`CACHE::try_hit()`
- TLB tag lookup miss path：`CACHE::handle_miss()`
- write miss path：`CACHE::handle_write()`

注意：

TLB request 到 DTLB/STLB 时，`access_type` 往往是 `LOAD`，因此不能用 `access_type::PREFETCH` 判断 prefetch 来源。本次统计使用 `translation_source` 区分 demand、same-page prefetch、cross-page prefetch。

## DTLB 指标语义和公式

DTLB 指标由 `dtlb_origin_hits/misses` 推导。

### `Core_N_DTLB_demand_miss_rate`

语义：

demand translation request 在 DTLB 的 miss rate。

分子：

```text
DTLB misses with origin DEMAND_DATA + DEMAND_INSTRUCTION
```

分母：

```text
DTLB hits + misses with origin DEMAND_DATA + DEMAND_INSTRUCTION
```

公式：

```text
demand_DTLB_miss / demand_DTLB_access
```

### `Core_N_DTLB_demand_mpki`

语义：

demand translation request 在 DTLB 的 MPKI。

公式：

```text
demand_DTLB_miss / ROI_retired_instruction * 1000
```

### `Core_N_DTLB_same_page_prefetch_miss_rate`

语义：

same-page L1D prefetch translation request 在 DTLB 的 miss rate。

分子：

```text
DTLB misses with origin L1D_PREFETCH_SAME_PAGE
```

分母：

```text
DTLB hits + misses with origin L1D_PREFETCH_SAME_PAGE
```

公式：

```text
same_page_prefetch_DTLB_miss / same_page_prefetch_DTLB_access
```

same-page prefetch 很常见地会 DTLB hit，因此 MPKI 或 miss rate 可能为 0，这不代表 same-page prefetch 没有访问 DTLB。

### `Core_N_DTLB_same_page_prefetch_mpki`

语义：

same-page L1D prefetch translation request 在 DTLB 的 miss MPKI。

公式：

```text
same_page_prefetch_DTLB_miss / ROI_retired_instruction * 1000
```

### `Core_N_DTLB_cross_page_prefetch_miss_rate`

语义：

cross-page L1D prefetch translation request 在 DTLB 的 miss rate。

公式：

```text
cross_page_prefetch_DTLB_miss / cross_page_prefetch_DTLB_access
```

### `Core_N_DTLB_cross_page_prefetch_mpki`

语义：

cross-page L1D prefetch translation request 在 DTLB 的 miss MPKI。

公式：

```text
cross_page_prefetch_DTLB_miss / ROI_retired_instruction * 1000
```

### `Core_N_DTLB_cross_page_prefetch_issued`

语义：

cross-page L1D prefetch translation request 访问 DTLB 的次数。

实现：

在 `record_tlb_origin_hit()` 和 `record_tlb_origin_miss()` 中，只要当前 cache 是 DTLB，且：

```cpp
translation_source == L1D_PREFETCH_CROSS_PAGE
```

就增加：

```cpp
sim_stats.tlb_cross_prefetch_issued
```

因此：

```text
DTLB_cross_page_prefetch_issued = cross_page_prefetch_DTLB_hit + cross_page_prefetch_DTLB_miss
```

### `Core_N_DTLB_cross_page_prefetch_useful`

语义：

cross-page prefetch 提前把某个 VPN 的 translation 带入 DTLB，后续 demand 访问同一 VPN 并命中了这个由 prefetch 带来的 DTLB entry。

实现：

在 `CACHE::record_tlb_cross_prefetch_hit()` 中，如果 demand hit 的 TLB entry 满足：

```cpp
way.tlb_cross_prefetch == true
way.tlb_cross_prefetch_used == false
```

则：

```cpp
++sim_stats.tlb_cross_prefetch_useful;
way.tlb_cross_prefetch_used = true;
```

这个 tag 是 stats-only 字段，不参与 lookup 或 replacement。

### `Core_N_DTLB_cross_page_prefetch_late`

语义：

cross-page prefetch 已经针对某 VPN 发起 translation，但 demand 到来时该 translation 仍 pending，导致 demand 在 DTLB 仍然 miss。

实现：

在 `CACHE::record_tlb_cross_prefetch_miss()` 中，如果 demand miss 的 VPN 能在 `tlb_cross_prefetch_pending` 找到，则：

```cpp
++sim_stats.tlb_cross_prefetch_useful;
++sim_stats.tlb_cross_prefetch_late;
```

这里沿用 ChampSim cache prefetch 的 late 语义：late prefetch 方向是对的，所以同时计入 useful 和 late。

### `Core_N_DTLB_cross_page_prefetch_useless`

语义：

cross-page prefetch 带入或正在请求的 DTLB translation 在被 demand 使用前失效，或 ROI 结束时仍未被使用。

实现：

- TLB entry 被替换时，如果它是 cross-page prefetch 带来的、且没有被 demand 使用，则计 useless。
- ROI 结束时，仍 pending 的 cross-page prefetch 计 useless。
- ROI 结束时，TLB 中仍 active 但未被 demand 使用的 cross-page prefetch entry 计 useless。

对应函数：

```cpp
CACHE::record_tlb_cross_prefetch_eviction()
CACHE::finalize_tlb_cross_prefetch_stats()
```

### `Core_N_DTLB_cross_page_prefetch_accuracy`

语义：

cross-page prefetch translation 在 DTLB 层面的准确率。

公式：

```text
DTLB_cross_page_prefetch_useful / DTLB_cross_page_prefetch_issued
```

### `Core_N_DTLB_cross_page_prefetch_coverage`

语义：

cross-page prefetch 在 DTLB 层面对 demand DTLB miss 的覆盖能力。

公式：

```text
DTLB_cross_page_prefetch_useful /
(DTLB_cross_page_prefetch_useful + demand_DTLB_miss)
```

## STLB 指标语义和公式

STLB 指标与 DTLB 完全类似，只是数据来源换成：

```cpp
stlb_origin_hits
stlb_origin_misses
```

### `Core_N_STLB_demand_miss_rate`

语义：

demand translation request 到达 STLB 后的 miss rate。

公式：

```text
demand_STLB_miss / demand_STLB_access
```

注意：

只有 DTLB miss 后才会访问 STLB，因此这里的分母不是所有 demand translation，而是到达 STLB 的 demand translation。

### `Core_N_STLB_demand_mpki`

语义：

demand STLB miss 的 MPKI。

公式：

```text
demand_STLB_miss / ROI_retired_instruction * 1000
```

### `Core_N_STLB_same_page_prefetch_miss_rate`

语义：

same-page L1D prefetch 到达 STLB 后的 miss rate。

公式：

```text
same_page_prefetch_STLB_miss / same_page_prefetch_STLB_access
```

### `Core_N_STLB_same_page_prefetch_mpki`

语义：

same-page L1D prefetch 在 STLB 的 miss MPKI。

公式：

```text
same_page_prefetch_STLB_miss / ROI_retired_instruction * 1000
```

### `Core_N_STLB_cross_page_prefetch_miss_rate`

语义：

cross-page L1D prefetch 到达 STLB 后的 miss rate。

公式：

```text
cross_page_prefetch_STLB_miss / cross_page_prefetch_STLB_access
```

### `Core_N_STLB_cross_page_prefetch_mpki`

语义：

cross-page L1D prefetch 在 STLB 的 miss MPKI。

公式：

```text
cross_page_prefetch_STLB_miss / ROI_retired_instruction * 1000
```

### `Core_N_STLB_cross_page_prefetch_issued`

语义：

cross-page L1D prefetch translation request 访问 STLB 的次数。

因此它只统计那些 DTLB miss 后进入 STLB 的 cross-page prefetch，不等于 DTLB cross-page issued。

### `Core_N_STLB_cross_page_prefetch_useful/useless/late/accuracy/coverage`

语义和 DTLB 层面一致，只是作用对象换成 STLB entry。

STLB useful：

```text
cross-page prefetch 带入 STLB 的 translation 被后续 demand STLB hit 使用
```

STLB late：

```text
demand 到达 STLB 时，同 VPN 的 cross-page prefetch translation 仍 pending，导致 demand STLB miss
```

STLB useless：

```text
cross-page prefetch 带入 STLB 的 translation 未被 demand 使用就被替换，或 ROI 结束仍未被使用
```

公式：

```text
accuracy = STLB_cross_page_prefetch_useful / STLB_cross_page_prefetch_issued
coverage = STLB_cross_page_prefetch_useful /
           (STLB_cross_page_prefetch_useful + demand_STLB_miss)
```

## TLB-system 指标语义和公式

TLB-system 把 DTLB + STLB 看成整体 translation cache system。

定义：

```text
TLB-system hit  = DTLB hit 或 DTLB miss 后 STLB hit
TLB-system miss = DTLB miss 且 STLB miss
```

因此 TLB-system 的 miss 由 STLB miss 表示，access 由 DTLB access 表示。

### `Core_N_TLB_demand_miss_rate`

语义：

demand translation 在整个 DTLB+STLB 系统中的 miss rate。

公式：

```text
demand_STLB_miss / demand_DTLB_access
```

### `Core_N_TLB_demand_mpki`

语义：

demand translation 在整个 TLB-system 中 miss 的 MPKI。

公式：

```text
demand_STLB_miss / ROI_retired_instruction * 1000
```

### `Core_N_TLB_same_page_prefetch_miss_rate`

语义：

same-page L1D prefetch translation 在整个 TLB-system 中的 miss rate。

公式：

```text
same_page_prefetch_STLB_miss / same_page_prefetch_DTLB_access
```

### `Core_N_TLB_same_page_prefetch_mpki`

语义：

same-page L1D prefetch translation 在整个 TLB-system 中 miss 的 MPKI。

公式：

```text
same_page_prefetch_STLB_miss / ROI_retired_instruction * 1000
```

### `Core_N_TLB_cross_page_prefetch_miss_rate`

语义：

cross-page L1D prefetch translation 在整个 TLB-system 中的 miss rate。

公式：

```text
cross_page_prefetch_STLB_miss / cross_page_prefetch_DTLB_access
```

### `Core_N_TLB_cross_page_prefetch_mpki`

语义：

cross-page L1D prefetch translation 在整个 TLB-system 中 miss 的 MPKI。

公式：

```text
cross_page_prefetch_STLB_miss / ROI_retired_instruction * 1000
```

### `Core_N_TLB_cross_page_prefetch_issued`

语义：

cross-page L1D prefetch translation 进入整个 TLB-system 的次数。

实现：

当前实现只在 DTLB 层看到 cross-page prefetch origin 时增加 TLB-system issued。因此它等价于：

```text
cross_page_prefetch_DTLB_access
```

打印时会把 DTLB/STLB stats 中的 `tlb_system_cross_prefetch_issued` 相加；实际 STLB 侧不重复增加 issued，避免 double count。

### `Core_N_TLB_cross_page_prefetch_useful`

语义：

cross-page prefetch 使某个 VPN 的 translation 提前存在于 DTLB 或 STLB 中，后续 demand 在 DTLB 或 STLB 命中该 prefetch 带来的 translation。

实现：

使用 `src/cache.cc` 中的 stats-only `tlb_system_cross_prefetch_state` 记录 pending/active/used 状态。key 为：

```text
cpu + VPN + ASID
```

当 DTLB 或 STLB 的 demand hit 使用到 cross-page prefetch 带来的 entry 时，调用 `mark_tlb_system_useful()`，只计一次 useful。

### `Core_N_TLB_cross_page_prefetch_late`

语义：

cross-page prefetch 已经进入 TLB-system translation path，但 demand 到来时该 translation 尚未在 DTLB/STLB 中可用，导致 demand 仍然发生 TLB-system miss。

实现：

在 demand miss 时，如果对应 VPN 在 TLB-system pending map 中，计：

```text
TLB-system useful++
TLB-system late++
```

这与 ChampSim cache prefetch 的 late 语义一致：方向正确但到达太晚。

### `Core_N_TLB_cross_page_prefetch_useless`

语义：

cross-page prefetch 在整个 TLB-system 层面没有被 demand 使用。

实现：

- 如果相关 prefetched translation 被替换且没有被 demand 使用，计 useless。
- ROI 结束时仍 pending 或 active 但未 used，计 useless。

### `Core_N_TLB_cross_page_prefetch_accuracy`

公式：

```text
TLB_cross_page_prefetch_useful / TLB_cross_page_prefetch_issued
```

### `Core_N_TLB_cross_page_prefetch_coverage`

公式：

```text
TLB_cross_page_prefetch_useful /
(TLB_cross_page_prefetch_useful + demand_STLB_miss)
```

## STLB miss cause 兼容更新

已有 section：

```text
======STLB miss causes ========
```

本次新增了细分项：

```text
Core_N_STLB_cause_L1D_Prefetch_Same_Page_miss
Core_N_STLB_cause_L1D_Prefetch_Cross_Page_miss
```

同时保留旧版语义的聚合项：

```text
Core_N_STLB_cause_L1D_Prefetch_miss
Core_N_STLB_cause_L1D_Prefetch_miss_rate
Core_N_STLB_L1D_Prefetch_miss
Core_N_STLB_L1D_Prefetch_miss_rate
```

这些聚合项现在都等于：

```text
L1D_PREFETCH + L1D_PREFETCH_SAME_PAGE + L1D_PREFETCH_CROSS_PAGE
```

因此 `Core_N_STLB_cause_L1D_Prefetch_miss` 不再表示 fallback-only 的 `translation_origin::L1D_PREFETCH`，而是恢复旧版本的统计语义：所有 L1D prefetcher 触发的 STLB miss。这样旧的后处理脚本仍然可以读 `cause_L1D_Prefetch`，新的分析也可以读 same/cross 细分项。

## ROI 统计如何保证

新增字段同步修改了：

```text
inc/cache_stats.h
src/cache_stats.cc
src/cache.cc
src/plain_printer.cc
src/json_printer.cc
```

关键点：

- `cache_stats` 增加所有新字段。
- `cache_stats operator-` 中同步处理新增字段，避免多 phase/subtract 统计错误。
- `CACHE::begin_phase()` 清空 ROI stats，并清掉 TLB block 中 warmup 遗留的 stats-only `tlb_cross_prefetch` 标记。
- `CACHE::end_phase()` 调用 `finalize_tlb_cross_prefetch_stats()`，把 ROI 结束仍未使用的 pending/active prefetch 归入 useless。
- plain printer 使用 `stats.roi_cache_stats` 和 `stats.roi_cpu_stats` 打印，所以结果是 ROI 数据。

## 与其他模块的兼容修改

### DRAM read traffic

文件：

```text
src/dram_controller.cc
```

由于新增了 `L1D_PREFETCH_SAME_PAGE` 和 `L1D_PREFETCH_CROSS_PAGE`，DRAM read traffic 分类中把这两个 origin 也归入原来的 `stlb_l1d_pref` bucket，避免新增 origin 后被归到 other。

### VPN footprint dump

文件：

```text
src/vpn_pattern_tracker.cc
```

原来只把 `L1D_PREFETCH` 看作 L1D prefetch。现在 `L1D_PREFETCH_SAME_PAGE` 和 `L1D_PREFETCH_CROSS_PAGE` 也被归入 L1D prefetch dump 路径。

这样已有的 STLB/DTLB L1D prefetch footprint dump 不会因为 origin 细分而漏数据。

## 输出位置

plain text 输出段落：

```text
========== vBerti-TLB Cross-page Flow Stats ==========
```

由：

```text
src/plain_printer.cc
format_vberti_tlb_cross_page_flow_stats()
```

生成，并追加到 ROI statistics 后面的扩展统计区域。

JSON printer 也增加了 raw counter：

```text
vBerti prefetch requested
vBerti cross-page requested
vBerti prefetch issued
vBerti cross-page issued
TLB cross-page prefetch issued/useful/useless/late
TLB-system cross-page prefetch issued/useful/useless/late
```

## 除法保护

所有 ratio 都使用 `ratio_or_zero()`。当 denominator 为 0 时输出 0，避免出现：

```text
nan
inf
```

## 验证

本次验证命令：

```bash
cd /home/zcq/git_prj/ChampSim
make -j4
./bin/fotonik3d-footprint-l1pref-1core -w 100000 -i 200000 --hide-heartbeat /data0/tzh/champsim_traces/SPEC17/602.gcc_s-2226B.champsimtrace.xz > /tmp/champsim_tlb_metrics_smoke.log
```

检查新增字段：

```bash
rg -n "vBerti-TLB|Core_0_vBerti|Core_0_DTLB_|Core_0_STLB_|Core_0_TLB_" /tmp/champsim_tlb_metrics_smoke.log
```

检查没有非法浮点输出：

```bash
rg -n "nan|inf" /tmp/champsim_tlb_metrics_smoke.log
```

该 smoke 只用于验证打印链路和基本关系，不作为正式实验数据。
