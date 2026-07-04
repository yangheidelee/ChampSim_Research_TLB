你现在要修改一个基于 ChampSim DPC-4 的研究分支：


当前实验目标：
我使用 L1D data prefetcher = vBerti。这个 vBerti 是 MICRO 2022 Berti 作者提交给 ChampSim 官方 PR 的版本，已经适配到当前工程中。现在我要在当前 ChampSim 工程里添加一套统计指标，用来分析：

1. vBerti 内部发了多少 prefetch；
2. 其中多少是 cross-page prefetch；
3. 这些 prefetch 有多少因为 PQ 满被 drop；
4. same-page / cross-page prefetch 在 DTLB、STLB 和整个 TLB-system 上的 hit/miss 行为；
5. cross-page prefetch 在 DTLB、STLB、TLB-system 层面的 issued/useful/useless/late/accuracy/coverage。

这项任务不是实现新的 prefetcher，也不是改变 vBerti 算法。  
这项任务只是添加统计指标和打印输出。  
除 stats-only metadata/tag 之外，不允许改变模拟器功能行为、cache/TLB replacement 行为、prefetcher 行为。

==================================================
一、基本定义
==================================================

Demand：
程序真实 load/store/RFO data access 触发的 translation request。
不包括 L1D data prefetcher 请求。

Same-page prefetch：
vBerti 发出的 prefetch target 仍在当前虚拟页内。
定义：
    target_VPN == trigger_VPN

Cross-page prefetch：
vBerti 发出的 prefetch target 跨越 4KB page。
定义：
    target_VPN != trigger_VPN

Requested：
vBerti 内部生成的 prefetch candidate/request 数量。
这个数表示 vBerti “想发”的预取，不代表一定进入 L1D PQ。

Issued：
vBerti 生成后，最终成功进入 L1D PQ 或被 cache prefetch path 接收、进入后续 cache/TLB 处理流程的 prefetch 数量。

MPKI：
    MPKI = miss_count / retired_instructions * 1000

TLB-system：
把 DTLB + STLB 看成一个整体 translation cache system。

TLB-system hit：
    DTLB hit
    或者 DTLB miss 但 STLB hit

TLB-system miss：
    DTLB miss 且 STLB miss

因此：
    demand miss in TLB-system = demand STLB miss
    cross-page prefetch miss in TLB-system = cross-page prefetch STLB miss

==================================================
二、关键实现原则
==================================================

最关键的一点：

不要在 DTLB/STLB 端重新猜一个 prefetch 是 same-page 还是 cross-page。

必须在 vBerti 生成 prefetch 的那一刻，根据 trigger address 和 prefetch target address 判断 same-page/cross-page，然后通过 metadata 或 translation_origin 把这个信息一路传递到 DTLB/STLB。

原因：
到了 DTLB/STLB 端时，只能看到 prefetch target VA，已经不知道这个 prefetch 是由哪个 trigger VA 产生的。因此不能在 TLB 端重新判断是否跨页。

==================================================
三、需要添加的 vBerti internal behavior 指标
==================================================

请在 vBerti 模块中统计以下指标。

假设：
    trigger_vpn = trigger_addr >> LOG2_PAGE_SIZE
    target_vpn  = pf_addr      >> LOG2_PAGE_SIZE
    is_cross_page = (target_vpn != trigger_vpn)

每次 vBerti 生成 prefetch candidate 时：
    Requested++

如果 is_cross_page：
    Cross_page prefetch in Requested++

调用 prefetch_line(...) 后，根据返回值判断是否真正进入 PQ：
    if prefetch_line(...) returns true:
        Issued++
        if is_cross_page:
            InPQ_cross_page_prefetch++

需要最终打印以下指标：

1. Requested
含义：
    vBerti 内部生成的所有 prefetch request 数量。

2. Cross_page prefetch in Requested
含义：
    Requested 中 target_VPN != trigger_VPN 的 prefetch 数量。

3. Cross_page prefetch of Requested
公式：
    Cross_page prefetch in Requested / Requested
含义：
    vBerti 生成的所有 prefetch 中，跨页预取的占比。

4. Issued
含义：
    vBerti 生成的 prefetch 中，最终成功进入 PQ 或被 cache prefetch path 接收的数量。

5. PQ Drop Rate
公式：
    (Requested - Issued) / Requested
含义：
    vBerti 生成的请求中，因为 PQ 满或无法接收而被 drop 的比例。

6. InPQ Cross_page prefetch of Requested
公式：
    InPQ_cross_page_prefetch / Requested
含义：
    所有 vBerti requested prefetch 中，最终进入 PQ 的 cross-page prefetch 占比。

7. Cross_page PQ Drop rate
公式：
    (Cross_page_requested - Cross_page_inPQ) / Cross_page_requested
含义：
    cross-page prefetch 因 PQ 满或无法接收而被 drop 的比例。

8. Cross_page prefetch of Issued
公式：
    Cross_page_inPQ / Issued
含义：
    所有真正进入 PQ / 后续处理流程的 prefetch 中，cross-page prefetch 的占比。

注意：
所有除法需要 guard zero denominator。
如果 denominator 为 0，请打印 0 或 N/A，但不要输出 nan/inf。

==================================================
四、如何把 same-page/cross-page 信息传到 DTLB/STLB
==================================================

当前工程里 request 结构已经有 pf_metadata 和 translation_source 字段。请优先使用 pf_metadata 传递 same-page/cross-page 信息。

建议新增一个头文件，例如：

    inc/tlb_prefetch_metadata.h

内容类似：

    #pragma once
    #include <cstdint>

    static constexpr uint32_t L1D_PREF_META_VALID = 1u << 31;
    static constexpr uint32_t L1D_PREF_META_CROSS = 1u << 30;

    static inline bool is_l1d_pref_meta(uint32_t meta)
    {
        return (meta & L1D_PREF_META_VALID) != 0;
    }

    static inline bool is_l1d_pref_cross(uint32_t meta)
    {
        return (meta & L1D_PREF_META_CROSS) != 0;
    }

在 vBerti 发 prefetch 时：

    uint32_t pf_meta = metadata_in | L1D_PREF_META_VALID;

    if (is_cross_page)
        pf_meta |= L1D_PREF_META_CROSS;

    prefetch_line(champsim::address{pf_addr}, fill_this_level, pf_meta);

不要覆盖已有 metadata 的低位信息，只 OR 上高位 bit。

如果当前工程中 bit31/bit30 已经被别的逻辑使用，请选择其他明确未使用的高位 bit，并在头文件中统一定义。

==================================================
五、扩展 translation_origin
==================================================

当前工程中已有 translation_origin，用来区分 DEMAND_DATA、L1D_PREFETCH 等来源。现在需要把 L1D prefetch 进一步细分为 same-page 和 cross-page。

请修改 access_type.h 中的 translation_origin enum，加入：

    L1D_PREFETCH_SAME_PAGE
    L1D_PREFETCH_CROSS_PAGE

保留已有 L1D_PREFETCH 作为 fallback。

示意：

    enum class translation_origin : unsigned {
        DEMAND_DATA = 0,
        DEMAND_INSTRUCTION,

        L1D_PREFETCH,
        L1D_PREFETCH_SAME_PAGE,
        L1D_PREFETCH_CROSS_PAGE,

        L1I_PREFETCH,
        OTHER,
        NUM_TYPES,
    };

同时更新 translation_origin_names，保证数组顺序和 enum 完全一致。

==================================================
六、修改 classify_translation_origin()
==================================================

请找到当前工程中 classify_translation_origin() 的实现。

目标：
当一个 request 是 L1D 自己发出的 prefetch，并且 pf_metadata 带有 L1D_PREF_META_VALID 时，根据 L1D_PREF_META_CROSS 返回：

    L1D_PREFETCH_CROSS_PAGE
或
    L1D_PREFETCH_SAME_PAGE

伪代码：

    translation_origin CACHE::classify_translation_origin(const tag_lookup_type& q_entry) const
    {
        if (q_entry.type == access_type::PREFETCH && q_entry.prefetch_from_this) {
            if (this cache is L1D) {
                if (is_l1d_pref_meta(q_entry.pf_metadata)) {
                    if (is_l1d_pref_cross(q_entry.pf_metadata))
                        return translation_origin::L1D_PREFETCH_CROSS_PAGE;
                    else
                        return translation_origin::L1D_PREFETCH_SAME_PAGE;
                }

                return translation_origin::L1D_PREFETCH;
            }

            if (this cache is L1I)
                return translation_origin::L1I_PREFETCH;

            return translation_origin::OTHER;
        }

        if (q_entry.type == access_type::PREFETCH)
            return q_entry.translation_source;

        return q_entry.is_instr
            ? translation_origin::DEMAND_INSTRUCTION
            : translation_origin::DEMAND_DATA;
    }

注意：
不要用 access_type 来区分 demand/same/cross，因为 translation request 到 DTLB/STLB 后 type 可能会被设置成 LOAD。必须使用 translation_source。

==================================================
七、确保 pf_metadata 进入 translation request
==================================================

请检查 issue_translation() 或等价的 translation request 构造逻辑。

当前代码可能已经设置：

    fwd_pkt.translation_source = classify_translation_origin(q_entry);
    fwd_pkt.v_address = ...
    fwd_pkt.ip = ...

但请确认是否也传递了：

    fwd_pkt.pf_metadata = q_entry.pf_metadata;

如果没有，必须补上。

否则 vBerti 端打的 same-page/cross-page metadata 无法传到 DTLB/STLB。

==================================================
八、DTLB/STLB hit/miss 按 origin 分类统计
==================================================

当前工程可能已经有 stlb_origin_hits / stlb_origin_misses。  
现在需要扩展到 DTLB，同时保留 STLB。

请在 cache_stats 中添加：

    dtlb_origin_hits
    dtlb_origin_misses
    stlb_origin_hits
    stlb_origin_misses

如果已有 stlb_origin_hits/misses，则不要重复添加，只补 dtlb_origin_hits/misses。

类型建议和现有 STLB origin stats 一致，例如：

    champsim::stats::event_counter<std::pair<translation_origin, cpu_id_type>>

具体类型请根据当前工程已有实现保持一致。

需要新增或修改 helper：

    bool is_dtlb() const;
    bool is_stlb() const;

    void record_tlb_origin_hit(const tag_lookup_type& pkt);
    void record_tlb_origin_miss(const tag_lookup_type& pkt);

逻辑：

    record_tlb_origin_hit(pkt):
        if is_dtlb():
            dtlb_origin_hits[{pkt.translation_source, pkt.cpu}]++
        if is_stlb():
            stlb_origin_hits[{pkt.translation_source, pkt.cpu}]++

    record_tlb_origin_miss(pkt):
        if is_dtlb():
            dtlb_origin_misses[{pkt.translation_source, pkt.cpu}]++
        if is_stlb():
            stlb_origin_misses[{pkt.translation_source, pkt.cpu}]++

请把当前 hit path 里的 record_stlb_origin_hit(...) 替换成 record_tlb_origin_hit(...)。

请把当前 miss path 里的 record_stlb_origin_miss(...) 替换成 record_tlb_origin_miss(...)。

==================================================
九、useful / useless / late 的统计定义
==================================================

需要统计 cross-page prefetch 在 DTLB、STLB、TLB-system 层面的：

    issued
    useful
    useless
    late
    accuracy
    coverage

如果当前代码已经有类似 prefetch quality 统计，可以复用，但必须符合下面定义。

如果没有，请实现 stats-only 的轻量机制。这个机制只能用于统计，不允许改变 TLB 行为、replacement 行为或功能行为。

推荐实现方式：
给 DTLB/STLB entry 增加 stats-only metadata，或者用 side table/map 记录 VPN 状态。优先选择侵入更小、代码更稳的方式。

每一级 TLB 需要记录 cross-page prefetch translation 的状态。

定义如下。

--------------------------------------------------
1. Cross_page prefetch issued in dTLB
--------------------------------------------------
定义：
    origin == L1D_PREFETCH_CROSS_PAGE 的 request 访问 DTLB 的次数。

等价：
    DTLB cross-page prefetch hits + DTLB cross-page prefetch misses

--------------------------------------------------
2. Cross_page prefetch useful in dTLB
--------------------------------------------------
定义：
    某个 cross-page prefetch 提前使目标 VPN 的 translation 存在于 DTLB 中；
    后续 demand 访问同一 VPN 时，在 DTLB 命中了这个由 cross-page prefetch 带来的 translation。

含义：
    cross-page prefetch 在 DTLB 层面真正帮助了后续 demand。

--------------------------------------------------
3. Cross_page prefetch useless in dTLB
--------------------------------------------------
定义：
    cross-page prefetch 带入或填充的 DTLB translation 在被 demand 使用前被替换/失效；
    或者直到 ROI 结束仍然没有被 demand 使用。

含义：
    cross-page prefetch 对 DTLB 造成了无效填充，可能体现 DTLB pollution。

--------------------------------------------------
4. Cross_page prefetch late in dTLB
--------------------------------------------------
定义：
    cross-page prefetch 已经针对某个 VPN 发起 translation；
    但在该 translation 对 DTLB 可用之前，demand 已经访问同一 VPN 并发生 DTLB miss；
    或者 demand 到来时，该 prefetch translation 仍处于 pending/in-flight 状态。

含义：
    cross-page prefetch 方向可能对，但到得太晚，没能及时覆盖 demand DTLB access。

--------------------------------------------------
STLB 的 useful/useless/late 定义完全同理，只是作用对象换成 STLB。

--------------------------------------------------
TLB-system 的 useful/useless/late 定义
--------------------------------------------------
TLB-system issued：
    cross-page prefetch 进入整个 TLB translation path 的次数。
    通常等于 cross-page prefetch issued in dTLB。

TLB-system useful：
    cross-page prefetch 提前使目标 VPN 的 translation 存在于 DTLB 或 STLB 中；
    后续 demand 访问同一 VPN 时，在 DTLB 或 STLB 命中了这个由 cross-page prefetch 带来的 translation。

TLB-system useless：
    cross-page prefetch 带入或填充的 translation 在 DTLB/STLB 中没有被 demand 使用，最终被替换/失效，或者 ROI 结束仍未使用。

TLB-system late：
    demand 访问某 VPN 时，之前已经有 cross-page prefetch 针对该 VPN 发起 translation，但该 translation 尚未在 DTLB/STLB 中可用，导致 demand 仍然发生 TLB-system miss。

实现建议：
    可以为 DTLB、STLB 分别维护 active/pending 状态。
    也可以维护一个 TLB-system 级别的 active/pending 状态。
    状态 keyed by VPN。
    注意统计时只用于 stats，不改变真实结构行为。

ROI 结束时：
    尚未被 demand 使用的 active cross-prefetch translation 应计入 useless。
    pending 但未完成的 cross-prefetch translation 也可以计入 useless，或者单独忽略；请选择一种方式并在代码注释中明确。推荐计入 useless，避免 issued 后没有归宿。

==================================================
十、需要打印的完整指标
==================================================

最终输出中必须有一个清晰 section，包含下面所有指标。可以打印在 plain_printer，也可以在已有 stats printer 中打印，但标签必须清楚可 grep。

建议 section 名：

    ========== vBerti-TLB Cross-page Flow Stats ==========

请打印以下指标。

--------------------------------------------------
A. vBerti internal behavior
--------------------------------------------------

Requested:
Cross_page prefetch in Requested:
Cross_page prefetch of Requested:
Issued:
PQ Drop Rate:
InPQ Cross_page prefetch of Requested:
Cross_page PQ Drop rate:
Cross_page prefetch of Issued:

--------------------------------------------------
B. dTLB 指标
--------------------------------------------------

demand miss rate in dTLB:
demand mpki in dTLB:

Same_page prefetch miss rate in dTLB:
Same_page prefetch mpki in dTLB:

Cross_page prefetch miss rate in dTLB:
Cross_page prefetch mpki in dTLB:
Cross_page prefetch issued in dTLB:
Cross_page prefetch useful in dTLB:
Cross_page prefetch useless in dTLB:
Cross_page prefetch late in dTLB:
Cross_page prefetch accuracy in dTLB:
Cross_page prefetch coverage in dTLB:

--------------------------------------------------
C. sTLB 指标
--------------------------------------------------

demand miss rate in sTLB:
demand mpki in sTLB:

Same_page prefetch miss rate in sTLB:
Same_page prefetch mpki in sTLB:

Cross_page prefetch miss rate in sTLB:
Cross_page prefetch mpki in sTLB:
Cross_page prefetch issued in sTLB:
Cross_page prefetch useful in sTLB:
Cross_page prefetch useless in sTLB:
Cross_page prefetch late in sTLB:
Cross_page prefetch accuracy in sTLB:
Cross_page prefetch coverage in sTLB:

--------------------------------------------------
D. TLB-system 整体指标
--------------------------------------------------

demand miss rate in TLB:
demand mpki in TLB:

Same_page prefetch miss rate in TLB:
Same_page prefetch mpki in TLB:

Cross_page prefetch miss rate in TLB:
Cross_page prefetch mpki in TLB:
Cross_page prefetch issued in TLB:
Cross_page prefetch useful in TLB:
Cross_page prefetch useless in TLB:
Cross_page prefetch late in TLB:
Cross_page prefetch accuracy in TLB:
Cross_page prefetch coverage in TLB:

==================================================
十一、各指标公式
==================================================

请按以下公式计算。

--------------------------------------------------
vBerti internal
--------------------------------------------------

Cross_page prefetch of Requested =
    Cross_page_requested / Requested

PQ Drop Rate =
    (Requested - Issued) / Requested

InPQ Cross_page prefetch of Requested =
    Cross_page_issued / Requested

Cross_page PQ Drop rate =
    (Cross_page_requested - Cross_page_issued) / Cross_page_requested

Cross_page prefetch of Issued =
    Cross_page_issued / Issued

--------------------------------------------------
DTLB
--------------------------------------------------

demand miss rate in dTLB =
    demand_DTLB_miss / demand_DTLB_access

demand mpki in dTLB =
    demand_DTLB_miss / retired_instructions * 1000

Same_page prefetch miss rate in dTLB =
    same_page_prefetch_DTLB_miss / same_page_prefetch_DTLB_access

Same_page prefetch mpki in dTLB =
    same_page_prefetch_DTLB_miss / retired_instructions * 1000

Cross_page prefetch miss rate in dTLB =
    cross_page_prefetch_DTLB_miss / cross_page_prefetch_DTLB_access

Cross_page prefetch mpki in dTLB =
    cross_page_prefetch_DTLB_miss / retired_instructions * 1000

Cross_page prefetch accuracy in dTLB =
    cross_page_prefetch_useful_in_DTLB / cross_page_prefetch_issued_in_DTLB

Cross_page prefetch coverage in dTLB =
    cross_page_prefetch_useful_in_DTLB /
    (cross_page_prefetch_useful_in_DTLB + demand_DTLB_miss)

--------------------------------------------------
STLB
--------------------------------------------------

demand miss rate in sTLB =
    demand_STLB_miss / demand_STLB_access

demand mpki in sTLB =
    demand_STLB_miss / retired_instructions * 1000

Same_page prefetch miss rate in sTLB =
    same_page_prefetch_STLB_miss / same_page_prefetch_STLB_access

Same_page prefetch mpki in sTLB =
    same_page_prefetch_STLB_miss / retired_instructions * 1000

Cross_page prefetch miss rate in sTLB =
    cross_page_prefetch_STLB_miss / cross_page_prefetch_STLB_access

Cross_page prefetch mpki in sTLB =
    cross_page_prefetch_STLB_miss / retired_instructions * 1000

Cross_page prefetch accuracy in sTLB =
    cross_page_prefetch_useful_in_STLB / cross_page_prefetch_issued_in_STLB

Cross_page prefetch coverage in sTLB =
    cross_page_prefetch_useful_in_STLB /
    (cross_page_prefetch_useful_in_STLB + demand_STLB_miss)

--------------------------------------------------
TLB-system
--------------------------------------------------

demand miss rate in TLB =
    demand_STLB_miss / demand_DTLB_access

demand mpki in TLB =
    demand_STLB_miss / retired_instructions * 1000

Same_page prefetch miss rate in TLB =
    same_page_prefetch_STLB_miss / same_page_prefetch_DTLB_access

Same_page prefetch mpki in TLB =
    same_page_prefetch_STLB_miss / retired_instructions * 1000

Cross_page prefetch miss rate in TLB =
    cross_page_prefetch_STLB_miss / cross_page_prefetch_DTLB_access

Cross_page prefetch mpki in TLB =
    cross_page_prefetch_STLB_miss / retired_instructions * 1000

Cross_page prefetch issued in TLB =
    cross_page_prefetch_issued_in_DTLB

Cross_page prefetch accuracy in TLB =
    cross_page_prefetch_useful_in_TLB / cross_page_prefetch_issued_in_TLB

Cross_page prefetch coverage in TLB =
    cross_page_prefetch_useful_in_TLB /
    (cross_page_prefetch_useful_in_TLB + demand_STLB_miss)

所有除法都必须 guard zero denominator。
禁止输出 nan / inf。

==================================================
十二、需要同步修改 ROI stats / operator-
==================================================

当前工程有 warmup/ROI 统计。新增的所有 cache_stats 字段必须在以下位置同步：

1. cache_stats.h
2. cache_stats.cc 中的 operator- 或等价 stats subtract 逻辑
3. CACHE::begin_phase / end_phase 或等价 ROI stats copy 逻辑
4. plain_printer 或当前 stats 输出位置

否则可能出现：
    编译失败；
    ROI 输出不包含新增字段；
    warmup 数据污染 ROI；
    多 phase subtract 后数据错误。

请检查当前工程已有 stats 处理方式，保持风格一致。

==================================================
十三、验收标准
==================================================

完成后必须满足以下要求。

1. 编译通过。

2. 默认运行不改变 vBerti、cache、TLB 的功能行为。
   新增逻辑只用于统计，不改变 replacement、miss handling、prefetch decision。

3. 使用 L1D prefetcher = vberti 的配置可以正常运行。

4. 输出中必须能看到：

    ========== vBerti-TLB Cross-page Flow Stats ==========

并包含上述所有指标。

5. vBerti internal 指标满足基本关系：

    Requested >= Issued >= 0
    Cross_page_requested >= Cross_page_issued >= 0
    Cross_page prefetch of Requested 在 [0,1]
    PQ Drop Rate 在 [0,1]
    Cross_page PQ Drop rate 在 [0,1]
    Cross_page prefetch of Issued 在 [0,1]

6. DTLB/STLB 指标满足：

    access = hit + miss
    miss rate 在 [0,1]
    MPKI >= 0

其中：
    demand 使用 translation_origin::DEMAND_DATA
    same-page prefetch 使用 translation_origin::L1D_PREFETCH_SAME_PAGE
    cross-page prefetch 使用 translation_origin::L1D_PREFETCH_CROSS_PAGE

7. TLB-system 指标必须由 DTLB/STLB 计数推导，不要重复计算：

    demand miss in TLB = demand_STLB_miss
    demand access in TLB = demand_DTLB_access

    cross-page miss in TLB = cross_page_STLB_miss
    cross-page access in TLB = cross_page_DTLB_access

8. useful/useless/late/accuracy/coverage 不能出现 nan/inf。

9. 如果跑一个短 trace，例如 1M warmup + 5M ROI：
   输出中 Requested、Issued、DTLB/STLB demand stats 应该有合理非零值。
   如果 vBerti 确实发出跨页预取，Cross_page prefetch in Requested 应该非零。

10. 如果某个 trace 没有 cross-page prefetch，cross-page 相关比例应输出 0 或 N/A，不允许崩溃。

==================================================
十四、最终交付
==================================================

请最后给出：

1. 修改过的文件列表。
2. 每个文件主要改了什么。
3. 新增指标的打印位置。
4. 如何运行一个短 trace 验证。
5. 如果 useful/useless/late 使用了 stats-only side table 或 TLB entry tag，请说明具体实现方式，并确认它不改变功能行为。