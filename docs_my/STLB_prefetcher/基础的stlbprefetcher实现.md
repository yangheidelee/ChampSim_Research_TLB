任务名称：
在已有 ChampSim STLB Prefetcher 接口中实现六种独立的 STLB 预取器：
SP、DP、ASP、STP、H2P、MASP

一、任务背景与目标

我已经在自己的 ChampSim 修改版本中扩展了独立的 STLB prefetcher 接口和基础设施。

现在需要基于论文：

“Exploiting Page Table Locality for Agile TLB Prefetching”

实现论文介绍的六种 STLB prefetcher：

基础预测器：
1. Sequential Prefetcher，SP
2. Distance Prefetcher，DP
3. Arbitrary Stride Prefetcher，ASP

论文新提出或改良的预测器：
4. Stride Prefetcher，STP
5. H2 Prefetcher，H2P
6. Modified Arbitrary Stride Prefetcher，MASP

本任务只实现这六种预测器本身的：

- 内部状态；
- 训练机制；
- 预测机制；
- 候选 VPN 生成；
- 状态初始化和复位；
- 必要的异常和重复处理；
- 基本统计与验证。

不要在本任务中实现：

- ATP 动态选择器；
- ATP 的 Fake Prefetch Queue；
- SBFP；
- Sampler；
- Free Distance Table；
- Static Free Distances；
- 论文中的 translation prefetch buffer；
- 页表 cache-line 中相邻 PTE 的 free prefetching。

特别注意：

Table II 中的 “Static Free Distances” 属于论文的 StaticFP/SBFP 对照实验，不属于 SP、DP、ASP、STP、H2P、MASP 本身的预测算法。

例如：

SP 的主体算法只预测当前 VPN 的 +1 页，不能因为 Table II 写了
Static Free Distances {+1,+3,+5,+7}
就让 SP 主动产生 +3、+5、+7 的 page walk。

二、统一术语和行为模型

1. 本文中的 last-level TLB

论文实验系统中的 last-level TLB 就是统一的二级 TLB，即 STLB。

因此，本文所说的：

- TLB miss；
- last-level TLB miss；
- L2 TLB miss；

在实现中统一理解为：

STLB miss。

2. 预测器的事件输入

这六种预测器以真实的 STLB miss event 为操作事件。

每个事件至少应提供：

- 当前造成 STLB miss 的 VPN；
- 造成该 miss 的访问指令 PC；
- CPU/core ID；
- 如果系统支持多个地址空间，则还需要 ASID，或者在上下文切换时清空状态。

预测器内部以 VPN 为基本地址单位，不使用 byte address 计算 stride。

所有 distance 和 stride 都表示“相差多少个虚拟页”，必须使用有符号数。

3. STLB miss stream 与 full access stream

DP、ASP、H2P、MASP 的历史和训练必须基于 STLB miss event，而不是所有 STLB access。

也就是说：

- STLB hit 不更新这些预测器的历史；
- STLB hit 不更新 PC table；
- STLB hit 不更新 distance history；
- STLB hit 不更新 stride confidence；
- STLB hit 不触发候选生成。

禁止为了方便而把完整 STLB access 流用于训练。

4. 禁止递归触发

由 STLB prefetcher 自己生成的 translation prefetch request，后续即使发生地址翻译或 page walk，也不能再次触发 STLB prefetcher。

否则会形成：

prefetch → translation miss → new prefetch → translation miss

这样的递归预取链。

预测器只响应框架定义的真实上层 STLB miss 事件，不响应：

- 自己生成的 STLB prefetch；
- page-table walker 内部的内存访问；
- 页表项访问；
- 内部 replay；
- 同一 STLB miss 的重复通知。

5. 训练与预取请求是否被接受相互独立

预测器的训练必须由 STLB miss 事件驱动，而不能依赖预测请求最终是否被下游接受。

即使候选 VPN 因以下原因被丢弃：

- 已存在于 STLB；
- 已存在于 translation prefetch buffer；
- 已存在于 in-flight page walk；
- 下游 prefetch queue 满；
- MSHR 满；
- 地址非法；
- 与同批候选重复；

预测器本身仍然应完成当前 miss 对应的历史和预测表更新。

不能因为预取请求被 drop 就回滚 predictor training。

6. 统一候选处理

每个预测器生成的是候选 VPN 集合。

在将候选交给已有 STLB prefetch基础设施前，至少进行以下处理：

- 同一次触发中的重复候选只保留一个；
- 候选等于当前 miss VPN 时丢弃；
- VPN 加减发生上溢或下溢时丢弃；
- 不产生非法地址空间中的 VPN；
- 不产生无效页号；
- stride 或 distance 为 0 时，不发出指向当前页的预取。

是否已经存在于：

- STLB；
- translation prefetch buffer；
- in-flight page walk；
- 已排队请求；

应尽量由已有统一基础设施完成，而不是在每个 predictor 中重复实现。

三、SP：Sequential Prefetcher

1. 设计目标

SP 用于捕获顺序增长的 STLB miss pattern。

2. 内部状态

SP 不需要学习表，不需要历史寄存器，不需要置信度。

3. 触发

每次真实 STLB miss 都触发一次 SP。

设当前 miss VPN 为：

M_t

4. 预测

SP 固定生成一个候选：

M_t + 1

5. 训练

SP 没有训练过程。

STLB hit 和过去的 miss 都不影响下一次预测。

6. 示例

当前 STLB miss：

VPN = 100

SP 输出：

101

7. 注意事项

SP 只能主动产生 +1。

不要将论文 Table II 中 SP 的 Static Free Distances
{+1,+3,+5,+7}
加入 SP 主体算法。

四、DP：Distance Prefetcher

1. 设计目标

DP 学习连续 STLB miss 之间的 distance 转移关系。

它不是简单重复最近一个 stride，而是学习：

“观察到某个当前 distance 后，下一次通常出现什么 distance。”

设连续 STLB miss VPN 为：

M_0, M_1, M_2, ...

定义：

D_t = M_t - M_{t-1}

DP 学习的关系为：

D_{t-1} → D_t

2. 内部状态

DP 每个 core 需要维护：

- previous_miss_vpn；
- previous_distance；
- previous_miss_valid；
- previous_distance_valid；
- 一个 64-entry、4-way set-associative distance prediction table。

每个 distance table entry 至少保存：

- valid；
- distance tag/key；
- predicted_distance_0；
- predicted_distance_1；
- 两个 predicted distance 的有效位；
- 两个 predicted distance 之间的局部 recency 信息；
- 表级别的 set replacement 信息。

每个表项最多保存两个可能的后继 distance。

3. 表的含义

如果某个表项的 key 为 K，并保存：

P0, P1

则含义为：

当当前观察到的 STLB miss distance 为 K 时，
未来一次 STLB miss 的 distance 可能是 P0 或 P1。

因此当前 miss VPN 为 M_t 时，预测目标是：

M_t + P0
M_t + P1

4. 第一次 STLB miss

第一次 miss 没有前一个 miss，因此无法计算 distance。

操作：

- 保存 current VPN 到 previous_miss_vpn；
- 设置 previous_miss_valid；
- 不查询 distance table；
- 不训练 transition；
- 不产生预取。

5. 后续 STLB miss 的处理顺序

收到当前 miss M_t 后：

第一步，计算当前 distance：

D_t = M_t - previous_miss_vpn

第二步，使用 D_t 查询 distance table。

如果命中 key = D_t 的表项：

- 读取其中有效的 predicted distances；
- 对每个有效预测 P，生成：

  M_t + P

- 最多产生两个候选。

如果没有命中：

- 为 D_t 分配一个新的 distance table entry；
- 新表项的两个 predicted distance 初始为无效；
- 当前没有基于 D_t 的有效预测。

第三步，训练前一个 transition。

如果 previous_distance_valid：

更新 key = previous_distance 对应的表项，将当前 D_t 插入其两个 predicted-distance 槽位。

训练关系为：

previous_distance → D_t

更新规则：

- 如果 D_t 已经存在于两个 predicted-distance 槽位之一：
  - 不重复插入；
  - 将该预测标记为最近使用。
- 如果存在空槽：
  - 将 D_t 插入空槽；
  - 标记为最近使用。
- 如果两个槽都有效且 D_t 不在其中：
  - 替换两个槽中较久未使用的一个；
  - 新插入的 D_t 标记为最近使用。

第四步，更新全局历史：

previous_miss_vpn = M_t
previous_distance = D_t
previous_distance_valid = true

6. 查询和训练顺序要求

必须先使用训练前的 distance table 为当前 miss 产生预测，再训练：

previous_distance → current_distance

不能先训练再查询，否则当 previous_distance 和 current_distance 相同时，当前事件可能错误地使用刚刚写入的信息预测自己，造成不合理的即时自学习。

7. 表分配和替换

distance table 总容量：

64 entries

相联度：

4-way

表项根据 distance 进行索引和 tag 匹配。

同一个 set 中没有空 entry 时，使用明确、稳定的 replacement policy，例如 LRU。

表级 replacement 和每个表项内部两个 predicted-distance 槽位的 recency 是两套不同的状态，不得混淆。

8. DP 示例

STLB miss VPN 序列：

100, 104, 105, 109, 110

对应 distance：

+4, +1, +4, +1

训练过程应逐步得到：

Table[+4] → +1
Table[+1] → +4

当 miss 到达 109 时：

当前 distance = +4

查询：

Table[+4] → +1

因此预测：

109 + 1 = 110

当 miss 到达 110 时：

当前 distance = +1

查询：

Table[+1] → +4

因此预测：

110 + 4 = 114

9. DP 重要属性

DP 是 global miss-distance predictor。

它不按 PC 分流。

来自不同 PC、不同数据结构的 STLB miss 会共同形成全局 distance sequence。

五、ASP：Arbitrary Stride Prefetcher

1. 设计目标

ASP 学习每个访问指令 PC 所对应的 STLB miss VPN stride。

ASP 使用的是：

per-PC STLB miss sequence

而不是某个 PC 的所有 STLB access sequence。

2. 内部状态

ASP 使用：

64-entry、4-way set-associative PC table。

每个 entry 至少保存：

- valid；
- PC tag；
- previous_miss_vpn；
- previous_miss_vpn_valid；
- learned_stride；
- stride_valid；
- stability_count；
- replacement metadata。

3. 表项含义

对于 PC = P 的表项：

previous_miss_vpn 表示：

该 PC 上一次造成 STLB miss 时的 VPN。

learned_stride 表示：

最近学习到的 per-PC STLB miss stride。

stability_count 表示：

learned_stride 在后续连续 table hit 中被重复观察到的次数。

4. PC table miss

当前 STLB miss 的 PC 在表中没有匹配 entry 时：

- 分配新 entry；
- 保存当前 PC；
- previous_miss_vpn = current VPN；
- previous_miss_vpn_valid = true；
- stride_valid = false；
- stability_count = 0；
- 不产生预取。

5. PC table hit

设当前 miss VPN 为 M_t。

计算：

new_stride = M_t - previous_miss_vpn

然后分情况处理。

情况一：stride_valid = false

- learned_stride = new_stride；
- stride_valid = true；
- stability_count = 0；
- 不产生预取。

情况二：new_stride == learned_stride

- stability_count 增加；
- learned_stride 保持不变。

情况三：new_stride != learned_stride

- learned_stride = new_stride；
- stability_count = 0；
- 本次不认为 stride 稳定。

无论哪种情况，最后都更新：

previous_miss_vpn = M_t

6. 预测条件

ASP 是保守预测器。

只有 learned_stride 已经连续重复确认至少两次后，才允许发出预取。

这里统一定义：

stability_count 表示在初次建立 learned_stride 后，
该 stride 又连续匹配成功的次数。

当：

stability_count >= 2

时，产生：

M_t + learned_stride

在 stride 不匹配并切换到新 stride 的当前事件上，不产生预取。

不要把该阈值写成语义不明确的 magic number。

应将其定义成清楚的稳定性参数，默认值为 2。

7. ASP 示例

同一个 PC 连续造成 STLB miss：

100, 104, 108, 112

处理过程：

VPN 100：
- PC table miss；
- 只分配表项；
- 无预取。

VPN 104：
- new_stride = +4；
- 初次建立 stride；
- stability_count = 0；
- 无预取。

VPN 108：
- new_stride = +4；
- stability_count = 1；
- 无预取。

VPN 112：
- new_stride = +4；
- stability_count = 2；
- 预测：

112 + 4 = 116

8. ASP 的 PC 隔离

不同 PC 必须使用不同表项和独立的 previous_miss_vpn。

例如：

PC_A：100, 104, 108
PC_B：1000, 1016, 1032

不能将两个 PC 的 VPN 混合计算 stride。

9. 重要说明

如果同一个 PC 在两次 STLB miss 之间发生了多次 STLB hit，这些 hit 不得修改 ASP 的 previous_miss_vpn。

ASP 看到的仍然是这个 PC 的两次 miss VPN 之间的距离。

六、STP：Stride Prefetcher

1. 设计目标

STP 是比 SP 更激进的固定小距离预测器。

它试图覆盖当前 miss 页前后附近的虚拟页。

2. 内部状态

STP 没有训练表，没有历史状态，没有置信度。

3. 预测

每次当前 STLB miss VPN 为 M_t 时，固定产生：

M_t - 2
M_t - 1
M_t + 1
M_t + 2

4. 候选顺序

为保证实验可复现，使用固定输出顺序：

-2, -1, +1, +2

即：

M_t - 2
M_t - 1
M_t + 1
M_t + 2

如果现有接口可以一次提交一个候选，则保持该顺序。

如果接口可以一次提交候选集合，也必须保证集合内容完全一致。

5. 训练

STP 没有训练过程。

6. 示例

当前 STLB miss：

VPN = 100

STP 输出：

98, 99, 101, 102

7. 注意事项

不要将 STP 的主体 offsets 和 Table II 中的 Static Free Distances 混合。

STP 主体 offsets 固定是：

{-2,-1,+1,+2}

Table II 中的 Static Free Distances {+1,+2} 不属于 STP 主体预测。

七、H2P：H2 Prefetcher

1. 设计目标

H2P 使用最近两个“连续 STLB miss 之间的 distance”进行预测。

它假设未来 miss 可能：

- 重复最近一次 distance；
- 或重复再前一次 distance。

2. 内部状态

H2P 每个 core 维护：

- previous_miss_vpn；
- previous_miss_valid；
- previous_distance；
- previous_distance_valid。

等价地，也可以保存最近三个 STLB miss VPN，但行为必须完全相同。

3. 第一次 STLB miss

没有 previous miss，无法计算 distance。

操作：

- 保存 current VPN；
- 不产生预取。

4. 第二次 STLB miss

可以计算第一个 distance：

D_t = M_t - previous_miss_vpn

但只有一个有效 distance，还不足以形成论文定义的“两段 history”。

操作：

- 保存 D_t 为 previous_distance；
- 更新 previous_miss_vpn；
- 不产生预取。

5. 第三次及以后 STLB miss

当前 miss 为 M_t。

计算最新 distance：

D_new = M_t - previous_miss_vpn

此时：

- D_new 是最近一次 distance；
- previous_distance 是再前一次 distance。

生成两个候选：

M_t + D_new
M_t + previous_distance

随后更新：

previous_distance = D_new
previous_miss_vpn = M_t

6. 与论文公式的对应

设最近三个造成 STLB miss 的 VPN 按时间顺序为：

A, B, E

定义有符号距离：

d(X,Y) = X - Y

H2P 预测：

E + d(E,B)
E + d(B,A)

也就是：

当前页 + 最近 distance
当前页 + 再前一次 distance

7. 重复处理

如果最近两个 distance 相同，则两个候选相同。

例如：

100, 104, 108

两个 distance 都是 +4。

H2P 只能提交一次：

108 + 4 = 112

不能重复提交两个完全相同的候选。

8. 示例

STLB miss 序列：

100, 104, 105

distance：

104 - 100 = +4
105 - 104 = +1

在 VPN 105 的 miss 上，H2P 输出：

105 + 1 = 106
105 + 4 = 109

9. H2P 与 DP 的区别

H2P：

- 不使用预测表；
- 只使用最近两个 distance；
- 没有长期 transition learning；
- 响应快，硬件成本低。

DP：

- 学习 distance 到未来 distance 的长期转移关系；
- 使用 64-entry、4-way distance table；
- 一个 distance 可以记录两个后继 distance。

不要把 H2P 实现成简化版的 DP table。

八、MASP：Modified Arbitrary Stride Prefetcher

1. 设计目标

MASP 是 ASP 的激进改良版。

与 ASP 相比，MASP 有两项关键修改：

第一，取消 ASP 的稳定性门控。

MASP 不要求同一个 stride 连续重复多次后才预取。

第二，每次 PC table hit 最多产生两个预测：

- 使用表中原有的 stored stride；
- 使用当前刚观察到的 new stride。

2. 内部状态

MASP 使用：

64-entry、4-way set-associative PC table。

每个 entry 至少保存：

- valid；
- PC tag；
- previous_miss_vpn；
- previous_miss_vpn_valid；
- stored_stride；
- stride_valid；
- replacement metadata。

MASP 不需要 ASP 的 stability_count。

3. PC table miss

当前 PC 未命中表时：

- 分配新 entry；
- 保存 PC；
- previous_miss_vpn = current VPN；
- previous_miss_vpn_valid = true；
- stride_valid = false；
- 不产生预取。

4. PC table hit

设当前 miss VPN 为 M_t。

先计算：

new_stride = M_t - previous_miss_vpn

预测必须使用更新前的 stored_stride 和刚计算出的 new_stride。

候选一：

如果 stride_valid：

M_t + stored_stride

候选二：

M_t + new_stride

随后更新表项：

stored_stride = new_stride
stride_valid = true
previous_miss_vpn = M_t

5. 更新顺序要求

必须先读取旧的 stored_stride 并生成候选，再用 new_stride 覆盖 stored_stride。

不能先写入：

stored_stride = new_stride

再生成两个候选。

否则两个候选会变成完全相同，丢失 MASP 同时尝试旧 stride 和新 stride 的设计含义。

6. 第一次 PC table hit

第一次 PC table hit 时，stride_valid 仍为 false。

此时没有有效的旧 stored_stride，因此只产生：

M_t + new_stride

然后将 new_stride 保存为 stored_stride。

7. 第二次及以后 PC table hit

如果旧 stored_stride 有效，则最多产生：

M_t + stored_stride
M_t + new_stride

如果二者相同，只提交一个候选。

8. MASP 示例

同一个 PC 的 STLB miss VPN：

100, 105, 108

VPN 100：
- 分配 entry；
- 不预测。

VPN 105：
- new_stride = +5；
- 没有旧 stride；
- 预测：

105 + 5 = 110

- 更新 stored_stride = +5。

VPN 108：
- old stored_stride = +5；
- new_stride = 108 - 105 = +3；
- 预测：

108 + 5 = 113
108 + 3 = 111

- 更新 stored_stride = +3。

9. MASP 与 ASP 的区别

ASP：

- 保存 per-PC miss stride；
- 要求 stride 连续稳定；
- 每次最多产生一个候选；
- 更保守。

MASP：

- 保存 per-PC miss stride；
- 不进行稳定性门控；
- 同时尝试旧 stride 和新 stride；
- 每次最多产生两个候选；
- 更激进。

九、状态作用域与地址空间隔离

1. 每核状态

所有 predictor state 必须是 per-core 的。

不同 CPU core 的：

- previous miss；
- distance history；
- PC table；
- confidence；
- replacement state；

不能共享，除非未来专门研究 cooperative TLB prefetching。

2. 地址空间

如果模拟器支持多个地址空间或上下文切换，不能让不同地址空间的 VPN pattern 直接混合。

采用以下两种方式之一：

- 表项和历史使用 ASID 区分；
- 上下文切换时清空 predictor state。

必须与现有 STLB 地址空间处理方式保持一致。

3. 初始化与仿真阶段

在以下时刻正确初始化 predictor state：

- 模拟器启动；
- core reset；
- predictor 切换；
- 新的 simulation phase 需要独立统计时；
- 上下文切换且采用 flush 方案时。

Warmup 阶段是否训练 predictor，必须遵循当前 ChampSim 其他 prefetcher 的统一行为。

正常推荐语义是：

- warmup 期间允许训练和预热 predictor state；
-正式 simulation 开始时清零统计；
- 不清空已经训练好的 predictor state。

十、统一统计要求

为每种 predictor 至少记录以下统计，名称可以适配当前工程：

- 收到的有效 STLB miss trigger 数量；
- 产生的原始候选数量；
- 去重后的候选数量；
- 因 target 等于 current VPN 而丢弃的数量；
- 因 VPN 上溢、下溢或非法而丢弃的数量；
- 提交给下游基础设施的候选数量；
- 下游接受数量；
- 下游因重复、已有翻译、in-flight、队列满等原因拒绝的数量。

预测器训练统计与下游接受统计必须分开。

对于表驱动预测器，还应记录：

DP：
- distance table lookup；
- table hit；
- table miss；
- table allocation；
- table replacement；
- transition update；
- successor replacement。

ASP/MASP：
- PC table lookup；
- PC table hit；
- PC table miss；
- allocation；
- replacement。

ASP：
- stride match；
- stride mismatch；
- 达到稳定阈值的次数。

H2P：
- history 未充分预热的触发数；
- 两个 distance 相同导致的候选去重数。

十一、必须完成的定向验证

在进行长 trace 仿真之前，先构造确定性的事件序列，对六种 predictor 做单元级行为验证。

测试一：SP

输入 miss：

100

期望候选：

101

测试二：STP

输入 miss：

100

期望候选，固定顺序：

98, 99, 101, 102

测试三：H2P

输入 miss：

100, 104, 105

期望：

100：无预取
104：无预取
105：106, 109

测试四：MASP

同一个 PC 的 miss：

100, 105, 108

期望：

100：无预取
105：110
108：113, 111

测试五：ASP

同一个 PC 的 miss：

100, 104, 108, 112

采用稳定阈值 2。

期望：

100：无预取
104：无预取
108：无预取
112：116

测试六：DP

输入 miss：

100, 104, 105, 109, 110

distance：

+4, +1, +4, +1

期望至少满足：

在 105 之后已经训练：

Table[+4] 包含 +1

在 109：

当前 distance = +4
预测 110

在 109 之后已经训练：

Table[+1] 包含 +4

在 110：

当前 distance = +1
预测 114

测试七：STLB hit 不参与训练

为 ASP、MASP、DP、H2P 插入若干 STLB hit event。

确认：

- previous miss VPN 不变化；
- distance history 不变化；
- PC table 不变化；
- 预测结果与没有插入 hit 时一致。

测试八：不同 PC 隔离

交错输入：

PC_A：100, 104, 108
PC_B：1000, 1016, 1032

确认 ASP 和 MASP 为两个 PC 独立学习：

PC_A stride = +4
PC_B stride = +16

不能出现跨 PC stride。

测试九：重复候选

H2P 输入：

100, 104, 108

最近两个 distance 均为 +4。

当前只能提交一次：

112

MASP 在 old stride 与 new stride 相同时，也只能提交一次候选。

测试十：禁止递归预取

由 predictor 生成的 translation prefetch 发生后，确认该请求不会再次触发任何一个 STLB predictor。

十二、最终交付要求

完成后提供一份清晰的实现说明，至少包括：

1. 六种 predictor 分别维护了哪些状态；
2. 每种 predictor 在一次 STLB miss 上的完整处理顺序；
3. 哪些 predictor 使用 global miss history；
4. 哪些 predictor 使用 per-PC miss history；
5. 每种 predictor 的最大候选数量；
6. 表容量、相联度和 replacement policy；
7. ASP 的 stability_count 精确定义；
8. DP 的 prediction 和 transition training 顺序；
9. MASP 使用 old stride 与 new stride 的顺序；
10. 如何排除自触发和递归预取；
11. 如何处理地址空间和上下文切换；
12. 定向测试的输入、输出和通过结果。

最终实现必须保证六种 predictor 可以独立选择运行。

不要默认把它们组合为 ATP，也不要让一种 predictor 的状态影响另一种 predictor。

十三、六种预测器语义汇总

SP：
- 基于当前 STLB miss VPN；
- 固定预测 +1；
- 无训练；
- 最大 1 个候选。

DP：
- 基于全局 STLB miss distance stream；
- 学习 distance → next distance；
- 64-entry、4-way distance table；
- 每个 key 保存两个后继 distance；
- 最大 2 个候选。

ASP：
- 基于 per-PC STLB miss VPN stream；
- 学习稳定 stride；
- 64-entry、4-way PC table；
- 达到稳定阈值后预测；
- 最大 1 个候选。

STP：
- 基于当前 STLB miss VPN；
- 固定预测 {-2,-1,+1,+2}；
- 无训练；
- 最大 4 个候选。

H2P：
- 基于全局最近两个 STLB miss distance；
- 预测最近 distance 和再前一次 distance；
- 无预测表；
- 最大 2 个候选。

MASP：
- 基于 per-PC STLB miss VPN stream；
- 同时使用旧 stride 和当前新 stride；
- 无稳定性门控；
- 64-entry、4-way PC table；
- 最大 2 个候选。