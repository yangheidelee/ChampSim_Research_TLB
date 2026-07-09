# vBerti-TLB 新增指标说明

Core_N_vBerti_Requested：vBerti 在当前 policy 允许后、准备尝试提交给 L1D prefetch path 的 prefetch candidate 数量，不包含被 no-cross policy 提前丢弃的 candidate。

Core_N_vBerti_Cross_page_prefetch_in_Requested：在 `Core_N_vBerti_Requested` 中，prefetch target VPN 与 trigger VPN 不同的 cross-page prefetch candidate 数量。

Core_N_vBerti_Cross_page_prefetch_of_Requested：vBerti 实际尝试提交给 prefetch path 的 candidates 中，cross-page prefetch 所占比例。

Core_N_vBerti_Issued：vBerti candidate 成功进入 L1D internal PQ、被 cache prefetch path 接收的 prefetch 数量。

Core_N_vBerti_PQ_Drop_Rate：已经通过 policy gating 并尝试进入 L1D internal PQ、但没有被 L1D prefetch path 接收的 vBerti candidate 比例。

Core_N_vBerti_InPQ_Cross_page_prefetch_of_Requested：所有 vBerti requested candidates 中，最终成功进入 L1D internal PQ 的 cross-page prefetch 所占比例。

Core_N_vBerti_Cross_page_PQ_Drop_rate：vBerti requested 的 cross-page candidates 中，未能成功进入 L1D internal PQ 的比例。

Core_N_vBerti_Cross_page_prefetch_of_Issued：所有成功进入 L1D internal PQ 的 vBerti prefetch 中，cross-page prefetch 所占比例。

Core_N_DTLB_demand_miss_rate：data-side DTLB 上 demand translation request 的 miss rate，反映到达 DTLB 的 demand 访问有多少没有命中 DTLB。

Core_N_DTLB_demand_mpki：data-side DTLB 上 demand translation request 的 miss per kilo instructions。

Core_N_DTLB_same_page_prefetch_miss_rate：L1D same-page prefetch translation request 在 DTLB 上的 miss rate。

Core_N_DTLB_same_page_prefetch_mpki：L1D same-page prefetch translation request 在 DTLB 上的 miss per kilo instructions。

Core_N_DTLB_cross_page_prefetch_miss_rate：L1D cross-page prefetch translation request 在 DTLB 上的 miss rate。

Core_N_DTLB_cross_page_prefetch_mpki：L1D cross-page prefetch translation request 在 DTLB 上的 miss per kilo instructions。

Core_N_DTLB_cross_page_prefetch_issued：L1D cross-page prefetch translation request 实际访问 DTLB 的次数，等于该类请求在 DTLB 上的 hit 次数加 miss 次数。

Core_N_DTLB_cross_page_prefetch_useful：L1D cross-page prefetch 提前把某个 VPN translation 带入 DTLB，并被后续 demand 在 DTLB 命中使用的次数。

Core_N_DTLB_cross_page_prefetch_useless：L1D cross-page prefetch 带入或请求中的 DTLB translation 在 ROI 结束或被替换前没有被 demand 使用的次数。

Core_N_DTLB_cross_page_prefetch_late：L1D cross-page prefetch 已经对某个 VPN 发起 DTLB translation，但 demand 到来时 translation 仍未完成、导致 demand 仍发生 DTLB miss 的次数。

Core_N_DTLB_cross_page_prefetch_too_early：L1D cross-page prefetch 提前把某个 VPN translation 带入 DTLB，但该 translation 在被 demand 使用前已经从 DTLB 淘汰，随后同一 VPN 又发生 demand DTLB miss 的次数；匹配窗口为 DTLB 自身 `NUM_SET * NUM_WAY` 个淘汰记录。

Core_N_DTLB_cross_page_prefetch_too_early_among_fill：DTLB 层面 `cross_page_prefetch_too_early / cross_page_prefetch_fill`，表示已经 fill 进入 DTLB 的 cross-page prefetch translation 中，最终表现为 too-early 的比例。

Core_N_DTLB_cross_page_prefetch_pollution_evict：DTLB 层面，L1D cross-page prefetch translation fill 曾经踢出一个有效 DTLB entry，随后该 victim VPN 在 shadow FIFO 窗口内发生 demand DTLB miss 的次数。

Core_N_DTLB_cross_page_prefetch_pollution_demand：`Core_N_DTLB_cross_page_prefetch_pollution_evict` 中，被踢出的 victim entry 本身来源是 demand translation 的次数。

Core_N_DTLB_cross_page_prefetch_pollution_among_prefetch_fill：DTLB 层面 `cross_page_prefetch_pollution_evict / cross_page_prefetch_fill`，表示已经 fill 进入 DTLB 的 cross-page prefetch translation 中，有多少比例最终确认造成过 victim demand miss。

Core_N_DTLB_cross_page_prefetch_accuracy：L1D cross-page prefetch 在 DTLB 层面的有用率，表示访问 DTLB 的 cross-page prefetch 中有多少最终被 demand 使用。

Core_N_DTLB_cross_page_prefetch_coverage：L1D cross-page prefetch 在 DTLB 层面对 demand DTLB miss 机会的覆盖比例。

Core_N_STLB_demand_miss_rate：shared STLB 上 demand translation request 的 miss rate，可以包含 data demand 和 instruction demand 到达 STLB 后的 miss 行为。

Core_N_STLB_demand_mpki：shared STLB 上 demand translation request 的 miss per kilo instructions。

Core_N_STLB_same_page_prefetch_miss_rate：L1D same-page prefetch translation request 到达 STLB 后的 miss rate。

Core_N_STLB_same_page_prefetch_mpki：L1D same-page prefetch translation request 在 STLB 上的 miss per kilo instructions。

Core_N_STLB_cross_page_prefetch_miss_rate：L1D cross-page prefetch translation request 到达 STLB 后的 miss rate。

Core_N_STLB_cross_page_prefetch_mpki：L1D cross-page prefetch translation request 在 STLB 上的 miss per kilo instructions。

Core_N_STLB_cross_page_prefetch_issued：L1D cross-page prefetch translation request 实际访问 STLB 的次数，也就是该类请求 DTLB miss 后进入 STLB lookup 的次数。

Core_N_STLB_cross_page_prefetch_useful：L1D cross-page prefetch 提前把某个 VPN translation 带入 STLB，并被后续 demand 在 STLB 命中使用的次数。

Core_N_STLB_cross_page_prefetch_useless：L1D cross-page prefetch 带入或请求中的 STLB translation 在 ROI 结束或被替换前没有被 demand 使用的次数。

Core_N_STLB_cross_page_prefetch_late：L1D cross-page prefetch 已经对某个 VPN 发起 STLB translation，但 demand 到来时 translation 仍未完成、导致 demand 仍发生 STLB miss 的次数。

Core_N_STLB_cross_page_prefetch_too_early：L1D cross-page prefetch 提前把某个 VPN translation 带入 STLB，但该 translation 在被 demand 使用前已经从 STLB 淘汰，随后同一 VPN 又发生 demand STLB miss 的次数；匹配窗口为 STLB 自身 `NUM_SET * NUM_WAY` 个淘汰记录。

Core_N_STLB_cross_page_prefetch_too_early_among_fill：STLB 层面 `cross_page_prefetch_too_early / cross_page_prefetch_fill`，表示已经 fill 进入 STLB 的 cross-page prefetch translation 中，最终表现为 too-early 的比例。

Core_N_STLB_cross_page_prefetch_pollution_evict：STLB 层面，L1D cross-page prefetch translation fill 曾经踢出一个有效 STLB entry，随后该 victim VPN 在 shadow FIFO 窗口内发生 demand STLB miss 的次数。

Core_N_STLB_cross_page_prefetch_pollution_demand：`Core_N_STLB_cross_page_prefetch_pollution_evict` 中，被踢出的 victim entry 本身来源是 demand translation 的次数。

Core_N_STLB_cross_page_prefetch_pollution_among_prefetch_fill：STLB 层面 `cross_page_prefetch_pollution_evict / cross_page_prefetch_fill`，表示已经 fill 进入 STLB 的 cross-page prefetch translation 中，有多少比例最终确认造成过 victim demand miss。

Core_N_STLB_cross_page_prefetch_accuracy：L1D cross-page prefetch 在 STLB 层面的有用率，表示访问 STLB 的 cross-page prefetch 中有多少最终被 demand 使用。

Core_N_STLB_cross_page_prefetch_coverage：L1D cross-page prefetch 在 STLB 层面对 demand STLB miss 机会的覆盖比例。

Core_N_TLB_demand_miss_rate：把 DTLB+STLB 作为整体 data-side TLB-system 时，demand translation request 最终仍然发生 TLB-system miss 的比例。

Core_N_TLB_demand_mpki：把 DTLB+STLB 作为整体 TLB-system 时，demand translation request 的 TLB-system miss per kilo instructions。

Core_N_TLB_same_page_prefetch_miss_rate：L1D same-page prefetch translation request 在整个 DTLB+STLB system 中的 miss rate。

Core_N_TLB_same_page_prefetch_mpki：L1D same-page prefetch translation request 在整个 DTLB+STLB system 中的 miss per kilo instructions。

Core_N_TLB_cross_page_prefetch_miss_rate：L1D cross-page prefetch translation request 在整个 DTLB+STLB system 中的 miss rate。

Core_N_TLB_cross_page_prefetch_mpki：L1D cross-page prefetch translation request 在整个 DTLB+STLB system 中的 miss per kilo instructions。

Core_N_TLB_cross_page_prefetch_issued：L1D cross-page prefetch translation request 进入整个 TLB-system 的次数，当前实现等价于该类请求访问 DTLB 的次数。

Core_N_TLB_cross_page_prefetch_useful：L1D cross-page prefetch 提前把某个 VPN translation 带入 DTLB 或 STLB，并被后续 demand 在 TLB-system 中命中使用的次数。

Core_N_TLB_cross_page_prefetch_useless：L1D cross-page prefetch 带入或请求中的 translation 在整个 TLB-system 中直到 ROI 结束或被替换前没有被 demand 使用的次数。

Core_N_TLB_cross_page_prefetch_late：L1D cross-page prefetch 已经对某个 VPN 发起 translation，但 demand 到来时该 translation 在 DTLB/STLB 中仍不可用、导致 demand 仍发生 TLB-system miss 的次数。

Core_N_TLB_cross_page_prefetch_too_early：把 DTLB+STLB 作为整体时，L1D cross-page prefetch 带入的 translation 在被 demand 使用前从对应 TLB 结构淘汰，随后同一 VPN 又发生 demand TLB-system miss 的次数；shadow 记录插入时使用发生淘汰的 TLB 结构自身 `NUM_SET * NUM_WAY` 作为窗口大小。

Core_N_TLB_cross_page_prefetch_too_early_among_fill：TLB-system 层面 `cross_page_prefetch_too_early / (DTLB_cross_page_prefetch_fill + STLB_cross_page_prefetch_fill)`，表示已经 fill 进入 DTLB 或 STLB 的 cross-page prefetch translation 中，最终表现为 TLB-system too-early 的比例。

Core_N_TLB_cross_page_prefetch_accuracy：L1D cross-page prefetch 在整个 TLB-system 层面的有用率，表示进入 TLB-system 的 cross-page prefetch 中有多少最终被 demand 使用。

Core_N_TLB_cross_page_prefetch_coverage：L1D cross-page prefetch 在整个 TLB-system 层面对 demand TLB-system miss 机会的覆盖比例。

Core_N_STLB_cause_L1D_Prefetch_miss：所有 L1D prefetcher 触发的 STLB miss 总数，包含 fallback、same-page 和 cross-page 三类 L1D prefetch origin。

Core_N_STLB_cause_L1D_Prefetch_miss_rate：所有 L1D prefetcher 触发的 STLB miss 数占 STLB total access 的比例，保持旧版本 `cause_L1D_Prefetch` 的聚合语义。

Core_N_STLB_cause_L1D_Prefetch_Same_Page_miss：L1D same-page prefetch translation request 触发的 STLB miss 数。

Core_N_STLB_cause_L1D_Prefetch_Same_Page_miss_rate：L1D same-page prefetch translation request 触发的 STLB miss 数占 STLB total access 的比例。

Core_N_STLB_cause_L1D_Prefetch_Cross_Page_miss：L1D cross-page prefetch translation request 触发的 STLB miss 数。

Core_N_STLB_cause_L1D_Prefetch_Cross_Page_miss_rate：L1D cross-page prefetch translation request 触发的 STLB miss 数占 STLB total access 的比例。

Core_N_STLB_L1D_Prefetch_miss：所有 L1D prefetcher 触发的 STLB miss 总数，语义与 `Core_N_STLB_cause_L1D_Prefetch_miss` 相同。

Core_N_STLB_L1D_Prefetch_miss_rate：所有 L1D prefetcher 触发的 STLB miss 数占 STLB total access 的比例，语义与 `Core_N_STLB_cause_L1D_Prefetch_miss_rate` 相同。

Core_N_L1D_prefetch_too_early：L1D prefetch fill 进入 cache 后没有被 demand 使用就被淘汰，随后同一 cache line 又发生 demand miss 的次数；匹配窗口为该 cache 自身 `NUM_SET * NUM_WAY` 个淘汰记录。

Core_N_L1D_prefetch_too_early_among_fill：L1D cache 层面 `prefetch_too_early / prefetch_fill`，表示已经 fill 进入 L1D 的 prefetch line 中，最终表现为 too-early 的比例。

Core_N_L1D_prefetch_pollution_evict：L1D prefetch fill 曾经踢出一个有效 cache line，随后该 victim line 在 shadow FIFO 窗口内发生 demand L1D miss 的次数；victim 原本是 prefetch line 还是 demand line 都计入。

Core_N_L1D_prefetch_pollution_demand：`Core_N_L1D_prefetch_pollution_evict` 中，被踢出的 victim line 在被踢出时已经不是 prefetch line 的次数，也就是更接近 demand/normal line 被 prefetch 踢出后又被 demand miss 访问的情况。

Core_N_L1D_prefetch_pollution_among_prefetch_fill：L1D cache 层面 `prefetch_pollution_evict / prefetch_fill`，表示所有 L1D prefetch fill 中，有多少比例最终确认造成过 victim demand miss。
