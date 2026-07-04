# vberti 行为记录

1. **跨页预取是否总是发出**

   vberti 不是“总是跨页”，而是按照 cache line 粒度的 delta 预测下一个预取地址。代码中先把当前访问地址转成 cache line address，然后用：

   ```cpp
   p_addr = (line_addr + delta) << LOG2_BLOCK_SIZE;
   ```

   得到预取地址。因此，如果 delta 较小，预取可能仍在当前 4KB page 内；如果 delta 跨过 page boundary，预取地址就会变成跨页地址。

   当前源码里会显式判断这个预取是否跨页，并维护 `cross_page` / `no_cross_page` 统计。但是默认情况下，跨页之后不会直接停止，而是继续调用 `prefetch_line()` 发出预取。只有在编译时定义了 `NO_CROSS_PAGE` 宏时，跨页预取才会在 vberti 内部被 `continue` 跳过。

   所以当前工程的默认结论是：**vberti 支持跨页虚拟预取；跨页预取不是每次都有，但一旦预测出来，默认会发出。**

2. **是不是查 DTLB 再查 STLB**

   是。当前 ChampSim 配置下，L1D vberti 一般配合：

   ```json
   "virtual_prefetch": true
   ```

   使用。此时 `prefetch_line()` 里会把预取地址同时作为 `address` 和 `v_address` 保存，并把 `is_translated` 设为 false。也就是说，L1D vberti 发出的预取还没有物理地址，需要走翻译路径。

   生成器默认连接的 L1D 翻译路径是：

   ```text
   L1D prefetch -> DTLB -> STLB -> PTW
   ```

   因此，L1D vberti 的虚拟地址预取会先查 DTLB；如果 DTLB miss，再进入 STLB；如果 STLB 也 miss，再进入 PTW/page walk。这个请求在统计来源上会被标记为 `L1D_PREFETCH`，所以它可以和 demand data、demand instruction 等 STLB 访问来源区分开。

   这里需要注意：它不是绕过 DTLB 直接查 STLB，也不是预取器自己做地址翻译。预取器只产生虚拟地址，后续翻译由 ChampSim 的 cache/TLB/PTW 通用路径完成。

   进一步说，当前正常 vberti 下，只要 prefetch 被真正发出，基本都会走 TLB translation，并不是只有跨页 prefetch 才查 TLB。vberti 内部会先判断预取地址是否跨 4KB page，但这个判断默认只用于统计 `cross_page` / `no_cross_page`，以及在 `NO_CROSS_PAGE` 宏开启时丢弃跨页请求；它不是“是否发起 TLB lookup”的开关。

   因此，**same-page prefetch 也会查 DTLB**，只是它大概率命中已有翻译；**cross-page prefetch 也会查 DTLB/STLB**，并且因为目标页可能尚未出现在 DTLB/STLB 中，所以更容易引发 STLB miss 或 PTW/page walk。

3. **什么时候会被 drop**

   跨页本身不会导致 drop，STLB miss 本身也不会导致 drop。默认行为是：跨页预取继续发出，随后和同页预取一样等待 DTLB/STLB/PTW 翻译；STLB miss 只是增加后续 page walk 过程，不代表这个预取请求被丢弃。

   当前新版 ChampSim 中，可能导致请求没有真正发出的情况主要有：

   - **L1D internal prefetch queue 满**：`prefetch_line()` 会返回 false，这个预取请求就没有进入 L1D prefetch queue。
   - **编译时启用 `NO_CROSS_PAGE`**：vberti 在发现跨页后直接跳过该预取。
   - **后续队列或 MSHR 暂时满**：这通常表现为请求暂时发不下去、等待后续周期重试，不等价于“因为 STLB miss 被永久 drop”。

   另外，当前新版 ChampSim 的 `VirtualMemory` 会在首次访问某个虚拟页时动态建立虚拟页到物理页的映射。因此，它不像旧 Berti artifact 那样有非常显式的“prefetch translation 遇到 page fault 就 drop”的路径。对当前工程来说，更准确的说法是：**vberti 的跨页预取会走正常翻译和访存流程，STLB miss 不会自动 drop。**

4. **delta 最大跨页范围，以及一次 access 能发几个 prefetch**

   vberti 内部学习和保存的是 **cache line address 的 delta**。当前源码里 `DELTA_MASK` 为 12，并且只有满足下面条件的 delta 才会被加入 Berti table：
   ```cpp
   std::abs(delta) < (1 << DELTA_MASK)
   ```
   因此，delta 的最大绝对值是 4095 条 cache line。**当前实现中，vberti 的单个 delta 最远大约可以跨 64 个 4KB page。**

   vberti 是 access-triggered 的预取器。它的 `prefetcher_cycle_operate()` 是空的，不会在后台周期性主动发预取；真正的预取生成发生在 L1D cache access 触发的 `prefetcher_cache_operate()` 里。是否触发还要看该 cache 的 `prefetch_activate` 配置，例如 `LOAD,PREFETCH` 表示允许在相应类型的访问上调用预取器。

   一次 `prefetcher_cache_operate()` 会根据当前 IP/tag 从 Berti table 中取出若干个有效 delta。当前 `BERTI_TABLE_DELTA_SIZE` 是 16，因此一个 IP/tag 最多保存 16 个 delta。函数随后遍历这些 delta，并对每个有效 delta 调用一次 `prefetch_line()`。

   **一次 access 触发最多尝试发 16 个 prefetch**。实际发出的数量通常小于等于 16，因为下面情况会减少本批次发出的请求：

   - 目标 block 已经在 latency table 中被跟踪；
   - delta 无效或处于 `BERTI_R` 状态；
   - 目标地址为 0；
   - 启用了 `NO_CROSS_PAGE` 且该 delta 跨页；
   - L1D internal prefetch queue 已满，`prefetch_line()` 返回 false。

5. **一批 prefetch 的发出顺序**

   vberti 一次 access 触发的一批 prefetch
   源码流程是：`prefetcher_cache_operate()` 先调用 `berti->get(ip_hash, deltas)` 取出当前 IP/tag 对应的一组 delta。`Berti::get()` 会先筛掉无效 delta，并对返回的 delta 做排序。随后 `prefetcher_cache_operate()` 才按排序后的 `deltas` 顺序遍历，并逐个调用 `prefetch_line()`。

   排序规则在 `compare_greater_delta()` 中，优先级大致是：BERTI_L1 优先、然后 BERTI_L2、然后 BERTI_L2R、同一 rpl 级别内部，abs(delta) 小的优先
   因此，一批 prefetch 的发出顺序更准确地说是：先按 prefetch level / confidence 分类排序，再按 abs(delta) 从小到大排序。

   例如：

   ```text
   delta = +8,  rpl = L1
   delta = -1,  rpl = L2
   delta = +2,  rpl = L1
   delta = -16, rpl = L2R
   ```

   发出顺序更接近：

   ```text
   +2  L1
   +8  L1
   -1  L2
   -16 L2R
   ```

   delta 表本身的存储顺序主要由学习、插入和替换过程决定：新 delta 通常放到第一个空位置；已有 delta 会增加 confidence；表满时会用较弱的 rpl/confidence 找替换目标。这个表内顺序不应被理解为最终预取发出顺序。
