请修改 ChampSim DPC4 版本源码，实现 DRAM Read Queue 入口处的 read traffic 来源分类统计，并确保正常运行 trace 后，可以在最终 result 输出中直接 print 出统计结果。

本任务只要求完成 ChampSim 源码修改、统计逻辑添加、结果打印输出。不需要写画图脚本，不需要做额外数据分析，不需要改实验脚本，除非是为了保证新增统计能够正常输出。

一、任务目标

我希望统计 DRAM RQ 中实际进入 read queue 的请求来源，用于分析普通 cache-line 访问和 STLB miss 触发的 PTW 访问对 DRAM read traffic 的带宽占用。

统计对象必须是：

实际成功进入 DRAM RQ 的 read request。

不是：

1. 上层 L1/L2/LLC cache access 次数。
2. 上层 cache miss 次数。
3. STLB miss 次数。
4. PTW 发起尝试次数。
5. 未成功进入 DRAM RQ 的请求。
6. DRAM WQ / write request。

核心要求是：

在 DRAM RQ read request 成功进入入口处，按照来源分类计数，并在 result 中打印每一类的绝对 count 和百分比 share。

二、统计口径要求

1. 只统计 DRAM RQ read request。
2. 不统计 DRAM WQ / write request。
3. RFO / read-for-ownership 也算入 cache data demand read。
4. PTW / translation 访问必须按照实际进入 DRAM RQ 的次数统计。
5. 一个 STLB miss 可能触发多次串行 page table walk access，不能简单把一个 STLB miss 当成一次 DRAM read。
6. 每一个 page walk access 只有在真正成功进入 DRAM RQ 时才计数。
7. 最终统计要表达真实 DRAM read request traffic composition。
8. 不允许只做上层 cache/TLB 统计。
9. 不允许只统计 STLB miss 数量。
10. 不允许只统计 PTW access 请求发起数量。
11. 统计结果必须对应 simulation region 的 final statistics，不要把 warmup statistics 混入最终结果。
12. 原有 ChampSim DPC4 的统计和打印结果必须保留，新统计作为额外 section 追加。
13. 新增统计必须在没有对应 traffic 时输出 0，而不是不打印或崩溃。
14. 单核 ChampSim DPC4 必须正常工作；多核情况下至少不能破坏编译和运行，最好能正确做全局合计。

三、需要统计的 8 个细分类

请在 DRAM RQ read request 成功进入入口处，按照来源统计以下 8 类。

1. data_demand_read

含义：

数据 demand cache-line read。

包括：

* 普通 load demand 造成的 data cache-line read。
* RFO / read-for-ownership 造成的 read。

要求：

RFO 必须归入 data_demand_read。

2. inst_demand_read

含义：

指令 demand cache-line read。

包括：

* instruction fetch demand miss 最终进入 DRAM RQ 的 read request。

3. cache_inst_prefetch

含义：

指令侧 cache prefetch 产生的 cache-line read。

包括：

* L1I / instruction-side prefetch 最终进入 DRAM RQ 的 cache-line read request。

注意：

这类是 prefetch 取指令 cache line 本身造成的 DRAM read，不是 translation read。

4. cache_data_prefetch

含义：

数据侧 cache prefetch 产生的 cache-line read。

包括：

* L1D / data-side prefetch 最终进入 DRAM RQ 的 cache-line read request。

注意：

这类是 prefetch 取数据 cache line 本身造成的 DRAM read，不是 translation read。

5. stlb_data_demand

含义：

数据 demand 访问发生 STLB miss 后，PTW 触发并最终进入 DRAM RQ 的 translation read。

要求：

这类统计的是由 data demand STLB miss 引发的 page table walk read request，并且只在这些 PTW read request 真正进入 DRAM RQ 时计数。

6. stlb_inst_demand

含义：

指令 demand 访问发生 STLB miss 后，PTW 触发并最终进入 DRAM RQ 的 translation read。

要求：

这类统计的是由 instruction demand STLB miss 引发的 page table walk read request，并且只在这些 PTW read request 真正进入 DRAM RQ 时计数。

7. stlb_l1i_pref

含义：

L1I / instruction-side prefetch 访问发生 STLB miss 后，PTW 触发并最终进入 DRAM RQ 的 translation read。

要求：

这类统计的是由 instruction-side prefetch 引发的 translation traffic，不是 instruction prefetch cache line 本身的 traffic。

8. stlb_l1d_pref

含义：

L1D / data-side prefetch 访问发生 STLB miss 后，PTW 触发并最终进入 DRAM RQ 的 translation read。

要求：

这类统计的是由 data-side prefetch 引发的 translation traffic，不是 data prefetch cache line 本身的 traffic。

四、必须保留 translation request 的原始来源

对于普通 cache-line read，可以根据 request type、is_instr、prefetch 等已有信息进行分类。

但是对于 PTW / translation read，仅仅知道 request 是 TRANSLATION 不够。必须能进一步识别该 translation read 的原始来源。

translation request 到达 DRAM RQ 入口时，必须仍然能够区分它来自：

1. data demand
2. inst demand
3. L1D prefetch
4. L1I prefetch

因此，请在 ChampSim 的 request 传递路径中保留必要的 source / origin 信息，确保 translation request 到达 DRAM RQ 入口时，可以被正确分类为：

1. stlb_data_demand
2. stlb_inst_demand
3. stlb_l1d_pref
4. stlb_l1i_pref

要求：

1. 不能把所有 TRANSLATION request 都混成一类。
2. 不能只根据 is_instr 粗略区分 demand 和 prefetch。
3. 必须保留 demand / prefetch 的来源信息。
4. 必须保留 instruction-side / data-side 的来源信息。
5. PTW 内部多级访问产生的所有 translation read，都要继承原始触发者的来源信息。

五、最终需要输出的 4 个汇总类别

除了 8 个细分类，还要在 result 中输出以下 4 个汇总类别。

1. cache_demand

定义：

cache_demand
= data_demand_read

* inst_demand_read

2. cache_prefetch

定义：

cache_prefetch
= cache_inst_prefetch

* cache_data_prefetch

3. stlb_demand

定义：

stlb_demand
= stlb_data_demand

* stlb_inst_demand

4. stlb_prefetch

定义：

stlb_prefetch
= stlb_l1i_pref

* stlb_l1d_pref

六、百分比 share 的分母要求

8 个细分类的 share 和 4 个汇总类别的 share 都使用同一个主分母。

主分母为：

data_demand_read

* inst_demand_read
* cache_inst_prefetch
* cache_data_prefetch
* stlb_data_demand
* stlb_inst_demand
* stlb_l1i_pref
* stlb_l1d_pref

也就是：

total_classified_read

要求：

1. RFO 已经计入 data_demand_read。
2. write / WQ 不进入分母。
3. unclassified / other 不默认混入主分母。
4. unclassified / other 可以单独打印，用于 debug。
5. 需要额外打印 classified + unclassified 与实际观测到的 DRAM RQ read total 是否一致。

七、result 输出格式要求

请在 ChampSim 最终打印结果中增加一个清晰的 section。

section 名称建议固定为：

DRAM_RQ_READ_TRAFFIC_BREAKDOWN

要求：

1. 8 个细分类必须全部打印。
2. 4 个汇总类别必须全部打印。
3. 每个类别的绝对计数和百分比必须分成两行打印。
4. 第一行只打印 count 绝对值。
5. 第二行只打印 share 百分比。
6. 不要把 count 和 share 放在同一行。
7. 输出格式要方便后续脚本解析。
8. 建议使用固定 key 名称。
9. 即使某类 count 为 0，也必须打印。
10. share 建议保留两位小数。
11. 当 total_classified_read 为 0 时，share 应该安全输出 0.00%，不能除零崩溃。

八、result 输出示例

最终 result 中希望看到类似下面的输出格式。请严格保持 count 和 share 分开两行。

DRAM_RQ_READ_TRAFFIC_BREAKDOWN:
data_demand_read.count = xxx
data_demand_read.share = xx.xx%

inst_demand_read.count = xxx
inst_demand_read.share = xx.xx%

cache_inst_prefetch.count = xxx
cache_inst_prefetch.share = xx.xx%

cache_data_prefetch.count = xxx
cache_data_prefetch.share = xx.xx%

stlb_data_demand.count = xxx
stlb_data_demand.share = xx.xx%

stlb_inst_demand.count = xxx
stlb_inst_demand.share = xx.xx%

stlb_l1i_pref.count = xxx
stlb_l1i_pref.share = xx.xx%

stlb_l1d_pref.count = xxx
stlb_l1d_pref.share = xx.xx%

DRAM_RQ_READ_TRAFFIC_SUMMARY:
cache_demand.count = xxx
cache_demand.share = xx.xx%

cache_prefetch.count = xxx
cache_prefetch.share = xx.xx%

stlb_demand.count = xxx
stlb_demand.share = xx.xx%

stlb_prefetch.count = xxx
stlb_prefetch.share = xx.xx%

DRAM_RQ_READ_TRAFFIC_DEBUG:
total_classified_read.count = xxx
unclassified_read.count = xxx
total_read_with_other.count = xxx

classified_plus_unclassified_check.count = xxx
dram_rq_read_total_observed.count = xxx

九、debug 统计要求

请额外维护并打印以下 debug 信息：

1. total_classified_read.count

定义：

8 个细分类之和。

2. unclassified_read.count

定义：

进入 DRAM RQ 的 read request 中，无法归入上述 8 类的 request 数量。

3. total_read_with_other.count

定义：

total_classified_read + unclassified_read。

4. classified_plus_unclassified_check.count

定义：

total_classified_read + unclassified_read。

5. dram_rq_read_total_observed.count

定义：

在同一统计点观测到的所有 DRAM RQ read request 总数。

要求：

classified_plus_unclassified_check.count 应该等于 dram_rq_read_total_observed.count。

如果不相等，需要在代码或输出中能帮助定位原因。

十、正确性检查要求

完成修改后，请至少保证以下条件成立：

1. 代码可以正常编译。
2. 原有 ChampSim DPC4 功能不被破坏。
3. 原有统计输出仍然保留。
4. 新增统计输出 section 在 result 中可见。
5. 新增统计在没有相关 traffic 时输出 0。
6. 8 个细分类全部有 count 和 share 输出。
7. 4 个汇总类别全部有 count 和 share 输出。
8. 8 个细分类之和等于 4 个汇总类别之和。
9. total_classified_read 等于 8 个细分类之和。
10. cache_demand 等于 data_demand_read + inst_demand_read。
11. cache_prefetch 等于 cache_inst_prefetch + cache_data_prefetch。
12. stlb_demand 等于 stlb_data_demand + stlb_inst_demand。
13. stlb_prefetch 等于 stlb_l1i_pref + stlb_l1d_pref。
14. classified_plus_unclassified_check 等于 total_classified_read + unclassified_read。
15. classified_plus_unclassified_check 应该等于 dram_rq_read_total_observed。
16. PTW traffic 的统计必须是实际进入 DRAM RQ 的 translation read request 次数，不是 STLB miss 次数。
17. RFO 必须归入 data_demand_read。
18. write / WQ 不参与该 breakdown。
19. warmup stats 不应该混入 final simulation result。
20. result 输出格式应稳定，方便脚本解析。

十一、特别强调

这次任务的核心不是统计 cache miss，也不是统计 TLB miss，而是：

在 DRAM RQ 入口处统计实际进入 DRAM read queue 的 request 来源。

请确保最终新增 result 能表达真实的 DRAM read request traffic composition：

1. 普通 cache demand read traffic 有多少。
2. 普通 cache prefetch read traffic 有多少。
3. demand 访问引发的 STLB miss / PTW read traffic 有多少。
4. prefetch 访问引发的 STLB miss / PTW read traffic 有多少。
5. 这些 traffic 各自的绝对值和百分比 share 分别是多少。
