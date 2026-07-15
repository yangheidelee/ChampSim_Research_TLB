# vBerti-TLB 新增指标说明

本文中的 `N` 表示 core 编号；`{A|B}` 表示该位置分别替换为 `A` 或 `B`。`MPKI` 的统一分母是该 core 在 ROI 内退休的指令数，`miss_rate` 的统一分母是同一类请求在对应层级的 `access`。除名称中明确写出 data 或 instruction 的指标外，`demand` 在 TLB origin 统计中表示 `DEMAND_DATA + DEMAND_INSTRUCTION`。

对于 DTLB/STLB origin 明细，`access = hit + miss`；`mshr_merge` 是 miss 中与已有未完成请求合并的子集；`fill` 是最终完成并写入该层级的次数，因此受 merge 和 ROI 边界影响，不要求与 miss 相等。

Core_N_vBerti_Requested：vBerti 在当前 policy 允许后、准备尝试提交给 L1D prefetch path 的 prefetch candidate 数量，不包含被 no-cross policy 提前丢弃的 candidate。

Core_N_vBerti_Cross_page_prefetch_in_Requested：在 `Core_N_vBerti_Requested` 中，prefetch target VPN 与 trigger VPN 不同的 cross-page prefetch candidate 数量。

Core_N_vBerti_Same_page_prefetch_in_Requested：在 `Core_N_vBerti_Requested` 中，prefetch target VPN 与 trigger VPN 相同的 same-page candidate 数量，等于 `Requested - Cross_page_prefetch_in_Requested`。

Core_N_vBerti_Cross_page_prefetch_of_Requested：vBerti 实际尝试提交给 prefetch path 的 candidates 中，cross-page prefetch 所占比例。

Core_N_vBerti_Issued：vBerti candidate 成功进入 L1D internal PQ、被 cache prefetch path 接收的 prefetch 数量。

Core_N_vBerti_InPQ_Same_page_prefetch：成功进入 L1D internal PQ 的 same-page vBerti prefetch 数量。

Core_N_vBerti_InPQ_Cross_page_prefetch：成功进入 L1D internal PQ 的 cross-page vBerti prefetch 数量；与 `Core_N_vBerti_InPQ_Same_page_prefetch` 之和等于 `Core_N_vBerti_Issued`。

Core_N_vBerti_PQ_Drop_Rate：已经通过 policy gating 并尝试进入 L1D internal PQ、但没有被 L1D prefetch path 接收的 vBerti candidate 比例。

Core_N_vBerti_InPQ_Cross_page_prefetch_of_Requested：所有 vBerti requested candidates 中，最终成功进入 L1D internal PQ 的 cross-page prefetch 所占比例。

Core_N_vBerti_Cross_page_PQ_Drop_rate：vBerti requested 的 cross-page candidates 中，未能成功进入 L1D internal PQ 的比例。

Core_N_vBerti_Cross_page_prefetch_of_Issued：所有成功进入 L1D internal PQ 的 vBerti prefetch 中，cross-page prefetch 所占比例。

Core_N_CP_PF_PQFULL_drop：cross-page vBerti candidate 到达 `prefetch_line()` 时发现 L1D internal PQ 已满而被常规路径拒绝的次数。该计数不等于所有 cross-page drop；它只描述 PQ-full 这一种直接原因。

Core_N_CP_PF_PQFULL_TLB_rescue_enqueued：启用 `--ordered-pqfull-tlb-rescue` 后，原本因 PQ full 被拒绝的 cross-page candidate 成功进入独立、固定 16 项 rescue queue 的次数；未启用该开关时为 0。

Core_N_CP_PF_PQFULL_TLB_rescue_issued：rescue queue 中的请求满足相对 L1D PQ 的原始顺序约束，并成功向 DTLB 发出 translation request 的次数。

Core_N_CP_PF_PQFULL_TLB_rescue_translated：上述 rescue translation 收到返回、完成地址翻译的次数。rescue 只执行 translation，不继续发出 data-cache prefetch。

Core_N_L1D_cross_page_pf_translation_only_requested：启用 `--l1d-cross-page-pf-translation-only` 后，vBerti 标记为 translation-only、并尝试进入 L1D prefetch path 的 cross-page candidate 数量。

Core_N_L1D_cross_page_pf_translation_only_issued：上述 candidate 成功进入 L1D internal PQ 的数量；仍然受正常 PQ 容量限制。

Core_N_L1D_cross_page_pf_translation_only_dropped：translation-only 请求已经完成 DTLB/STLB/PTW 翻译，随后在 L1D data tag lookup 和下层 cache 请求之前被主动删除的数量。这里的 `dropped` 表示“翻译后截断 data access”，不是 PQ-full drop。

Core_N_{DTLB|STLB}_demand_access / hit / miss：按 translation origin 汇总的 demand translation lookup、命中和未命中次数；这里的 demand 同时包含 data demand 与 instruction demand。

Core_N_{DTLB|STLB}_demand_mshr_merge：上述 demand miss 中，与该 TLB 层级已有 MSHR 请求合并的次数。

Core_N_{DTLB|STLB}_demand_fill：origin 为 demand 的 translation 最终 fill 进入该 TLB 层级的次数。

Core_N_{DTLB|STLB}_vberti_prefetch_access / hit / miss：same-page 与 cross-page 两类 L1D vBerti translation request 在对应 TLB 层级的 lookup、命中和未命中总数。

Core_N_{DTLB|STLB}_vberti_prefetch_mshr_merge / fill：上述 vBerti translation miss 中的 MSHR merge 次数，以及最终 fill 进入对应 TLB 层级的次数。

Core_N_{DTLB|STLB}_vberti_prefetch_miss_rate：`vberti_prefetch_miss / vberti_prefetch_access`。

Core_N_{DTLB|STLB}_vberti_prefetch_mpki：`vberti_prefetch_miss * 1000 / ROI instructions`。

Core_N_{DTLB|STLB}_vberti_same_page_prefetch / hit / miss / mshr_merge / fill：same-page vBerti translation request 在对应层级的完整 origin 明细；不带后缀的 `vberti_same_page_prefetch` 表示 access。

Core_N_{DTLB|STLB}_vberti_cross_page_prefetch / hit / miss / mshr_merge / fill：cross-page vBerti translation request 在对应层级的完整 origin 明细；不带后缀的 `vberti_cross_page_prefetch` 表示 access。

Core_N_{DTLB|STLB}_vberti_{same|cross}_page_prefetch_miss_rate：对应类别的 `miss / access`。

Core_N_{DTLB|STLB}_vberti_{same|cross}_page_prefetch_mpki：对应类别的 `miss * 1000 / ROI instructions`。日志中不带 `vberti_` 的 `same_page_prefetch_*` 和 `cross_page_prefetch_*` rate/MPKI 是同一组 origin 计数的兼容别名。

Core_N_DTLB_demand_miss_rate：data-side DTLB 上 demand translation request 的 miss rate，反映到达 DTLB 的 demand 访问有多少没有命中 DTLB。

Core_N_DTLB_demand_mpki：data-side DTLB 上 demand translation request 的 miss per kilo instructions。

Core_N_DTLB_same_page_prefetch_miss_rate：L1D same-page prefetch translation request 在 DTLB 上的 miss rate。

Core_N_DTLB_same_page_prefetch_mpki：L1D same-page prefetch translation request 在 DTLB 上的 miss per kilo instructions。

Core_N_DTLB_cross_page_prefetch_miss_rate：L1D cross-page prefetch translation request 在 DTLB 上的 miss rate。

Core_N_DTLB_cross_page_prefetch_mpki：L1D cross-page prefetch translation request 在 DTLB 上的 miss per kilo instructions。

Core_N_DTLB_cross_page_prefetch_issued：DTLB 质量跟踪器记录的 cross-page translation lookup 次数；当前实现中每次 DTLB cross-page origin hit 或 miss 各计一次，因此应与 `Core_N_DTLB_cross_page_prefetch_lookups` 相等。

Core_N_DTLB_cross_page_prefetch_lookups：由 DTLB origin hit/miss 计数直接求和得到的 cross-page translation lookup 数，即 `vberti_cross_page_prefetch_hit + vberti_cross_page_prefetch_miss`。

Core_N_DTLB_cross_page_prefetch_useful：cross-page translation 被后续 demand 有效利用的次数，包含 demand 及时命中已 fill 的预取 translation，以及 demand 到达时同 VPN 预取 translation 仍未完成而被记为 late 的情况。

Core_N_DTLB_cross_page_prefetch_useless：L1D cross-page prefetch 带入或请求中的 DTLB translation 在 ROI 结束或被替换前没有被 demand 使用的次数。

Core_N_DTLB_cross_page_prefetch_late：L1D cross-page prefetch 已经对某个 VPN 发起 DTLB translation，但 demand 到来时 translation 仍未完成、导致 demand 仍发生 DTLB miss 的次数。

Core_N_DTLB_cross_page_prefetch_too_early：L1D cross-page prefetch 提前把某个 VPN translation 带入 DTLB，但该 translation 在被 demand 使用前已经从 DTLB 淘汰，随后同一 VPN 又发生 demand DTLB miss 的次数；匹配窗口为 DTLB 自身 `NUM_SET * NUM_WAY` 个淘汰记录。

Core_N_DTLB_cross_page_prefetch_too_early_among_fill：DTLB 层面 `cross_page_prefetch_too_early / cross_page_prefetch_fill`，表示已经 fill 进入 DTLB 的 cross-page prefetch translation 中，最终表现为 too-early 的比例。

Core_N_DTLB_cross_page_prefetch_too_early_among_useless：DTLB 层面 `cross_page_prefetch_too_early / cross_page_prefetch_useless`，表示最终无用的 cross-page translation 中，有多少可以进一步归因为过早淘汰。

Core_N_DTLB_cross_page_prefetch_pollution_evict：DTLB 层面，L1D cross-page prefetch translation fill 曾经踢出一个有效 DTLB entry，随后该 victim VPN 在 shadow FIFO 窗口内发生 demand DTLB miss 的次数。

Core_N_DTLB_cross_page_prefetch_pollution_demand：`Core_N_DTLB_cross_page_prefetch_pollution_evict` 中，被踢出的 victim entry 本身来源是 demand translation 的次数。

Core_N_DTLB_cross_page_prefetch_pollution_among_prefetch_fill：DTLB 层面 `cross_page_prefetch_pollution_evict / cross_page_prefetch_fill`，表示已经 fill 进入 DTLB 的 cross-page prefetch translation 中，有多少比例最终确认造成过 victim demand miss。

Core_N_DTLB_cross_page_prefetch_accuracy：DTLB 层面的 `cross_page_prefetch_useful / cross_page_prefetch_issued`；`useful` 包含 timely 与 late 两类。

Core_N_DTLB_cross_page_prefetch_coverage：DTLB 层面的 `useful / (useful + demand_miss)`。这是运行过程中实际记录的覆盖口径，不等价于相对另一配置 baseline miss 的离线覆盖率。

Core_N_STLB_demand_miss_rate：shared STLB 上 demand translation request 的 miss rate，可以包含 data demand 和 instruction demand 到达 STLB 后的 miss 行为。

Core_N_STLB_demand_mpki：shared STLB 上 demand translation request 的 miss per kilo instructions。

Core_N_STLB_same_page_prefetch_miss_rate：L1D same-page prefetch translation request 到达 STLB 后的 miss rate。

Core_N_STLB_same_page_prefetch_mpki：L1D same-page prefetch translation request 在 STLB 上的 miss per kilo instructions。

Core_N_STLB_cross_page_prefetch_miss_rate：L1D cross-page prefetch translation request 到达 STLB 后的 miss rate。

Core_N_STLB_cross_page_prefetch_mpki：L1D cross-page prefetch translation request 在 STLB 上的 miss per kilo instructions。

Core_N_STLB_cross_page_prefetch_issued：STLB 质量跟踪器记录的 cross-page translation lookup 次数；当前实现中每次 STLB cross-page origin hit 或 miss 各计一次，因此应与 `Core_N_STLB_cross_page_prefetch_lookups` 相等。

Core_N_STLB_cross_page_prefetch_lookups：由 STLB origin hit/miss 计数直接求和得到的 cross-page translation lookup 数，即真正越过 DTLB、到达 STLB 的该类请求数。

Core_N_STLB_cross_page_prefetch_useful：cross-page translation 在 STLB 被后续 demand 有效利用的次数，包含及时命中已 fill translation 与 demand 到达时 translation 仍在飞行的 late 情况。

Core_N_STLB_cross_page_prefetch_useless：L1D cross-page prefetch 带入或请求中的 STLB translation 在 ROI 结束或被替换前没有被 demand 使用的次数。

Core_N_STLB_cross_page_prefetch_late：L1D cross-page prefetch 已经对某个 VPN 发起 STLB translation，但 demand 到来时 translation 仍未完成、导致 demand 仍发生 STLB miss 的次数。

Core_N_STLB_cross_page_prefetch_too_early：L1D cross-page prefetch 提前把某个 VPN translation 带入 STLB，但该 translation 在被 demand 使用前已经从 STLB 淘汰，随后同一 VPN 又发生 demand STLB miss 的次数；匹配窗口为 STLB 自身 `NUM_SET * NUM_WAY` 个淘汰记录。

Core_N_STLB_cross_page_prefetch_too_early_among_fill：STLB 层面 `cross_page_prefetch_too_early / cross_page_prefetch_fill`，表示已经 fill 进入 STLB 的 cross-page prefetch translation 中，最终表现为 too-early 的比例。

Core_N_STLB_cross_page_prefetch_too_early_among_useless：STLB 层面 `cross_page_prefetch_too_early / cross_page_prefetch_useless`，表示最终无用的 cross-page translation 中，有多少可以进一步归因为过早淘汰。

Core_N_STLB_cross_page_prefetch_pollution_evict：STLB 层面，L1D cross-page prefetch translation fill 曾经踢出一个有效 STLB entry，随后该 victim VPN 在 shadow FIFO 窗口内发生 demand STLB miss 的次数。

Core_N_STLB_cross_page_prefetch_pollution_demand：`Core_N_STLB_cross_page_prefetch_pollution_evict` 中，被踢出的 victim entry 本身来源是 demand translation 的次数。

Core_N_STLB_cross_page_prefetch_pollution_among_prefetch_fill：STLB 层面 `cross_page_prefetch_pollution_evict / cross_page_prefetch_fill`，表示已经 fill 进入 STLB 的 cross-page prefetch translation 中，有多少比例最终确认造成过 victim demand miss。

Core_N_STLB_cross_page_prefetch_accuracy：STLB 层面的 `cross_page_prefetch_useful / cross_page_prefetch_issued`；`useful` 包含 timely 与 late 两类。

Core_N_STLB_cross_page_prefetch_coverage：STLB 层面的 `useful / (useful + demand_miss)`。这里的 demand miss 是 permit 配置自身观察到的运行时 miss，不是其他配置的 baseline miss。

Core_N_STLB_raw_demand_miss：启用 STLB cross-page prefetch buffer（CP-PB）实验时，data-demand 在正常 STLB 中未命中的原始次数，包含随后命中 CP-PB 和最终仍未命中的两部分；未启用实验时等于 data-demand STLB miss。

Core_N_CP_PB_insert：启用 `--enable-stlb-cp-pb` 后，原本要 fill 进 STLB 的 L1D cross-page prefetch translation 被重定向写入 CP-PB 的次数。

Core_N_CP_PB_demand_hit：data demand 在正常 STLB miss 后命中 CP-PB 的次数；命中项会从 CP-PB 移除并回填 STLB。

Core_N_STLB_PB_demand_miss：经过 CP-PB 检查后仍未命中的 data-demand STLB miss 数，等于 `STLB_raw_demand_miss - CP_PB_demand_hit`。

Core_N_CP_PB_coverage：`CP_PB_demand_hit / STLB_raw_demand_miss`。

Core_N_STLB_raw_demand_mpki / STLB_PB_demand_mpki / CP_PB_demand_hit_mpki：分别是 raw demand miss、经过 CP-PB 后剩余 demand miss、CP-PB demand hit 的每千条 ROI 指令计数；未启用 CP-PB 时后者为 0。

Core_N_TLB_demand_miss_rate：把 DTLB+STLB 作为整体 data-side TLB-system 时，demand translation request 最终仍然发生 TLB-system miss 的比例。

Core_N_TLB_demand_mpki：把 DTLB+STLB 作为整体 TLB-system 时，demand translation request 的 TLB-system miss per kilo instructions。

Core_N_TLB_same_page_prefetch_miss_rate：L1D same-page prefetch translation request 在整个 DTLB+STLB system 中的 miss rate。

Core_N_TLB_same_page_prefetch_mpki：L1D same-page prefetch translation request 在整个 DTLB+STLB system 中的 miss per kilo instructions。

Core_N_TLB_cross_page_prefetch_miss_rate：L1D cross-page prefetch translation request 在整个 DTLB+STLB system 中的 miss rate。

Core_N_TLB_cross_page_prefetch_mpki：L1D cross-page prefetch translation request 在整个 DTLB+STLB system 中的 miss per kilo instructions。

Core_N_TLB_cross_page_prefetch_issued：TLB-system 去重质量跟踪器记录的 cross-page request 数，当前在 DTLB cross-page origin hit/miss 时计数，因此等价于访问 DTLB 的次数，并应与 `Core_N_TLB_cross_page_prefetch_lookups` 相等。

Core_N_TLB_cross_page_prefetch_lookups：整个 TLB-system 的入口 lookup 数，当前直接采用 DTLB cross-page access。

Core_N_TLB_cross_page_prefetch_useful：同一 cross-page translation 在 DTLB/STLB 整体范围内被 demand 利用的去重次数，包含 timely 与 late；同一预测不会因为经过两个 TLB 层级而重复算 useful。

Core_N_TLB_cross_page_prefetch_useless：L1D cross-page prefetch 带入或请求中的 translation 在整个 TLB-system 中直到 ROI 结束或被替换前没有被 demand 使用的次数。

Core_N_TLB_cross_page_prefetch_late：L1D cross-page prefetch 已经对某个 VPN 发起 translation，但 demand 到来时该 translation 在 DTLB/STLB 中仍不可用、导致 demand 仍发生 TLB-system miss 的次数。

Core_N_TLB_cross_page_prefetch_too_early：把 DTLB+STLB 作为整体时，L1D cross-page prefetch 带入的 translation 在被 demand 使用前从对应 TLB 结构淘汰，随后同一 VPN 又发生 demand TLB-system miss 的次数；shadow 记录插入时使用发生淘汰的 TLB 结构自身 `NUM_SET * NUM_WAY` 作为窗口大小。

Core_N_TLB_cross_page_prefetch_too_early_among_fill：TLB-system 层面 `cross_page_prefetch_too_early / (DTLB_cross_page_prefetch_fill + STLB_cross_page_prefetch_fill)`，表示已经 fill 进入 DTLB 或 STLB 的 cross-page prefetch translation 中，最终表现为 TLB-system too-early 的比例。

Core_N_TLB_cross_page_prefetch_too_early_among_useless：TLB-system 层面 `cross_page_prefetch_too_early / cross_page_prefetch_useless`，表示系统级无用预测中可归因为过早淘汰的比例。

Core_N_TLB_cross_page_prefetch_accuracy：TLB-system 层面的 `cross_page_prefetch_useful / cross_page_prefetch_issued`。

Core_N_TLB_cross_page_prefetch_coverage：TLB-system 层面的 `useful / (useful + system demand_miss)`；其中 system demand miss 采用最终到达 STLB 后仍 miss 的 demand 次数。

以下 `Core_N_TLB_PTW_*` 指标采用 PTW-derived 口径：只跟踪真正越过 DTLB 和 STLB、并由 L1D vBerti cross-page prefetch 新启动的 PTW。每个 PTW 使用独立 ID 贯穿 PTW 返回、STLB/DTLB fill、demand hit 和 eviction，因此同一 translation 同时 fill 到 STLB 与 DTLB 时不会重复计数。这组指标与上面的 TLB-system 去重质量指标并列存在，不替换任何旧指标。

Core_N_TLB_PTW_real_demand_ptw：ROI 内由 real demand 新启动的 PTW 数量，real demand 严格为 `DEMAND_DATA + DEMAND_INSTRUCTION`。如果 demand 到达时与一个已经在飞行的 prefetch PTW 合并，该 demand 记入对应 prefetch 的 late/useful，而不会再计为一条新的 real-demand PTW。

Core_N_TLB_PTW_real_demand_mpki：`TLB_PTW_real_demand_ptw * 1000 / ROI instructions`，表示整个 DTLB+STLB system 最终没有提供 translation、实际由 real demand 新启动 PTW 的 MPKI。

Core_N_TLB_PTW_cross_page_prefetch_issued：L1D vBerti cross-page prefetch 在 TLB-system 入口执行 DTLB lookup 的次数。该值复用既有 TLB-system issued 计数，包含 DTLB hit、后续 STLB hit 以及最终启动 PTW 的请求。

Core_N_TLB_PTW_cross_page_prefetch_ptw_started：上述 issued 请求中，依次未命中 DTLB、STLB，且没有与已有 translation request 合并，最终真正新启动 PTW 的次数。这是后续 PTW-derived fill/useful 链路的起点。

Core_N_TLB_PTW_cross_page_prefetch_fill：prefetch-initiated PTW 完成后，translation 至少成功 fill 进入 DTLB 或 STLB 一次的 PTW 数量。同一 PTW 即使同时 fill 到 STLB 和 DTLB，也只计一次；ROI 结束时尚未完成 fill 的 PTW 不计入。

Core_N_TLB_PTW_cross_page_prefetch_useful：上述 prefetch-initiated PTW 产生的 translation 第一次被 real demand 利用的数量，包含 demand 及时命中已 fill 的 DTLB/STLB entry，以及 demand 与仍在飞行的 prefetch translation 合并的 late 情况；每个 PTW ID 最多计一次。late 情况只有在该 PTW 后续确实完成并 fill 进入 TLB system 后才确认 useful，避免 ROI 边界使 useful 超过 fill。

Core_N_TLB_PTW_cross_page_prefetch_late：`TLB_PTW_cross_page_prefetch_useful` 的子集；表示 real demand 到达时，对应的 prefetch PTW 尚未完成，demand 仍需等待该 translation 的数量。

Core_N_TLB_PTW_cross_page_prefetch_timely：`TLB_PTW_cross_page_prefetch_useful - TLB_PTW_cross_page_prefetch_late`，表示 real demand 到达前 translation 已经可在 DTLB/STLB 中使用的有效预取数量。

Core_N_TLB_PTW_cross_page_prefetch_fill_accuracy：`TLB_PTW_cross_page_prefetch_useful / TLB_PTW_cross_page_prefetch_fill`，衡量真正完成并进入 TLB system 的 prefetch-initiated PTW 中有多少被 real demand 使用。分母为 0 时输出 0。

Core_N_TLB_PTW_cross_page_prefetch_end_to_end_yield：`TLB_PTW_cross_page_prefetch_useful / TLB_PTW_cross_page_prefetch_issued`，从全部 cross-page DTLB lookup 到最终 PTW-derived useful 的端到端产出率；它同时反映 DTLB/STLB 已命中、请求合并和最终 useful 等链路筛选。

Core_N_TLB_PTW_cross_page_prefetch_coverage：`TLB_PTW_cross_page_prefetch_useful / (TLB_PTW_cross_page_prefetch_useful + TLB_PTW_real_demand_ptw)`。分母把已经被该类预取覆盖的 demand translation 与仍由 real demand 新启动的 PTW 合并为运行时 demand-PTW opportunities；这是同一配置内的 PTW-derived coverage，不等价于相对 baseline 的离线 miss reduction。

Core_N_TLB_PTW_cross_page_prefetch_timely_coverage：`TLB_PTW_cross_page_prefetch_timely / (TLB_PTW_cross_page_prefetch_useful + TLB_PTW_real_demand_ptw)`，只把 demand 到达前已经完成的 timely translation 视为覆盖。

Core_N_vBerti_end_to_end_issued：ROI 内成功进入 L1D internal PQ、并开始端到端跟踪的普通 vBerti prefetch 数量，包含 same-page 和 permit 模式下的 cross-page；translation-only cross-page 请求不纳入该 cache-data 端到端统计。

Core_N_vBerti_end_to_end_useful：上述请求最终被 data demand 利用的数量，包含 demand 命中预取填入的 cache line，以及 demand 与仍在飞行的预取 MSHR/channel request 合并两种情况。

Core_N_vBerti_end_to_end_late：`end_to_end_useful` 中，data demand 到达时预取仍未完成、通过 MSHR 或 channel merge 判定为 useful 的数量。

Core_N_vBerti_end_to_end_accuracy：`end_to_end_useful / end_to_end_issued`。

Core_N_vBerti_end_to_end_timely_accuracy：`(end_to_end_useful - end_to_end_late) / end_to_end_issued`，只保留在 demand 到达前已经完成的及时 useful。

Core_N_STLB_cause_L1D_Prefetch_miss：所有 L1D prefetcher 触发的 STLB miss 总数，包含 fallback、same-page 和 cross-page 三类 L1D prefetch origin。

Core_N_STLB_cause_L1D_Prefetch_miss_rate：所有 L1D prefetcher 触发的 STLB miss 数占 STLB total access 的比例，保持旧版本 `cause_L1D_Prefetch` 的聚合语义。

Core_N_STLB_cause_L1D_Prefetch_Same_Page_miss：L1D same-page prefetch translation request 触发的 STLB miss 数。

Core_N_STLB_cause_L1D_Prefetch_Same_Page_miss_rate：L1D same-page prefetch translation request 触发的 STLB miss 数占 STLB total access 的比例。

Core_N_STLB_cause_L1D_Prefetch_Cross_Page_miss：L1D cross-page prefetch translation request 触发的 STLB miss 数。

Core_N_STLB_cause_L1D_Prefetch_Cross_Page_miss_rate：L1D cross-page prefetch translation request 触发的 STLB miss 数占 STLB total access 的比例。

Core_N_STLB_cause_Demand_Data_miss / miss_rate：data-demand translation 触发的 STLB miss 数，以及该数占 STLB total access 的比例；这里不包含任何 L1D prefetch origin。

Core_N_STLB_cause_Demand_Instruction_miss / miss_rate：instruction-demand translation 触发的 STLB miss 数，以及该数占 STLB total access 的比例。

Core_N_STLB_cause_L1I_Prefetch_miss / miss_rate：L1I prefetch translation 触发的 STLB miss 数，以及该数占 STLB total access 的比例。

Core_N_STLB_cause_Other_miss / miss_rate：无法归入 demand、L1D prefetch 或 L1I prefetch origin 的 STLB miss 数，以及该数占 STLB total access 的比例。

Core_N_STLB_Demand_miss / miss_rate：`Demand_Data + Demand_Instruction` 的聚合 STLB miss 数，以及该数占 STLB total access 的比例。

Core_N_STLB_Other_miss / miss_rate：`L1I_Prefetch + Other` 的聚合 STLB miss 数，以及该数占 STLB total access 的比例。

Core_N_STLB_L1D_Prefetch_miss：所有 L1D prefetcher 触发的 STLB miss 总数，语义与 `Core_N_STLB_cause_L1D_Prefetch_miss` 相同。

Core_N_STLB_L1D_Prefetch_miss_rate：所有 L1D prefetcher 触发的 STLB miss 数占 STLB total access 的比例，语义与 `Core_N_STLB_cause_L1D_Prefetch_miss_rate` 相同。

Core_N_L1D_prefetch_too_early：L1D prefetch fill 进入 cache 后没有被 demand 使用就被淘汰，随后同一 cache line 又发生 demand miss 的次数；匹配窗口为该 cache 自身 `NUM_SET * NUM_WAY` 个淘汰记录。

Core_N_L1D_prefetch_too_early_among_fill：L1D cache 层面 `prefetch_too_early / prefetch_fill`，表示已经 fill 进入 L1D 的 prefetch line 中，最终表现为 too-early 的比例。

Core_N_L1D_prefetch_too_early_among_useless：L1D cache 层面 `prefetch_too_early / prefetch_useless`，表示最终无用的 prefetch line 中，有多少可以进一步归因为过早淘汰。

Core_N_L1D_prefetch_pollution_evict：L1D prefetch fill 曾经踢出一个有效 cache line，随后该 victim line 在 shadow FIFO 窗口内发生 demand L1D miss 的次数；victim 原本是 prefetch line 还是 demand line 都计入。

Core_N_L1D_prefetch_pollution_demand：`Core_N_L1D_prefetch_pollution_evict` 中，被踢出的 victim line 在被踢出时已经不是 prefetch line 的次数，也就是更接近 demand/normal line 被 prefetch 踢出后又被 demand miss 访问的情况。

Core_N_L1D_prefetch_pollution_among_prefetch_fill：L1D cache 层面 `prefetch_pollution_evict / prefetch_fill`，表示所有 L1D prefetch fill 中，有多少比例最终确认造成过 victim demand miss。

Core_N_L1D_prefetch_accuracy_berti_artifact：按照 Berti Artifact 附录口径计算的 L1D data-cache prefetch accuracy，即 `L1D_prefetch_useful / (L1D_prefetch_useful + L1D_prefetch_useless)`。这里直接使用 ChampSim 已有的 L1D `pf_useful` 和 `pf_useless` 计数，不包含 L2C 或 TLB 层级事件；输出为 0 到 1 的比例，例如 `0.8` 表示 80%。它不同于既有的 `Core_N_L1D_prefetch_accuracy = L1D_prefetch_useful / L1D_prefetch_issued`。

data_demand_read.count / inst_demand_read.count：被 DRAM read queue 实际接收、类型分别为 data demand（LOAD/RFO）和 instruction demand（instruction LOAD）的 cache-side read 数。

cache_data_prefetch.count / cache_inst_prefetch.count：被 DRAM read queue 实际接收、类型为 PREFETCH 的 data-side 和 instruction-side cache prefetch read 数。

stlb_data_demand.count / stlb_inst_demand.count：PTW 因 data-demand 或 instruction-demand STLB miss 发出的 translation read 中，实际进入 DRAM read queue 的次数。它们统计的是页表遍历产生的 DRAM read，不是 STLB miss 数。

stlb_l1d_pref.count / stlb_l1i_pref.count：PTW 因 L1D 或 L1I prefetch-origin STLB miss 发出的 translation read 中，实际进入 DRAM read queue 的次数；L1D 项聚合 fallback、same-page 和 cross-page origin。

上述八类 `*.share`：对应 `count / total_classified_read`，分母只包含已成功分类到这八类的 DRAM reads，不包含 `unclassified_read`。

cache_demand.count / cache_prefetch.count / stlb_demand.count / stlb_prefetch.count：上述明细的四类聚合，分别为 cache demand、cache prefetch、STLB demand-origin PTW read 和 STLB prefetch-origin PTW read；其 `share` 使用同一个 `total_classified_read` 分母。

total_classified_read.count：八个已分类 DRAM read 明细计数之和。

unclassified_read.count：进入 DRAM read queue、但 translation origin 或访问类型未归入上述八类的 read 数。

total_read_with_other.count / classified_plus_unclassified_check.count：`total_classified_read + unclassified_read` 的两个一致性检查别名。

dram_rq_read_total_observed.count：DRAM read queue 实际接收的全部 read 数，用于与 classified 加 unclassified 的和做一致性检查。

dram_rq_read_total_observed.per_1K_instructions：全部 DRAM read queue reads 除以所有 core 的 ROI 指令总数后乘 1000。

stlb_miss_total.count：进入 PTW 并完成页表遍历、且被标记为需要跟踪 DRAM touch 的 STLB miss 总数；包含不同 translation origin，不等同于只统计真实 data demand。

stlb_miss_touch_dram.count / share：上述 STLB miss 中，其页表遍历至少产生一次实际进入 DRAM read queue 的 translation read 的数量，以及占 `stlb_miss_total` 的比例。

stlb_miss_no_dram_touch.count / share：上述 STLB miss 中，页表遍历没有产生实际 DRAM read 的数量及比例，例如遍历所需项被页表缓存命中。

stlb_miss_touch_plus_no_touch.count / stlb_miss_total_check.count：分别为 touch 与 no-touch 之和、原始 total 的调试检查值，正常情况下二者应相等。
