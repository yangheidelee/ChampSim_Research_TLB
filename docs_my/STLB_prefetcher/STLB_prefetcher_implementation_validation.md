# STLB Prefetcher 实现与验证记录

## 2026-07：STLB 专用接口重构方案

### 重构目标

此前的最小原型让 `prefetcher_stlb/stlb_stride` 继承通用
`champsim::modules::prefetcher`，并复用：

```text
prefetcher_cache_operate()
prefetcher_cache_fill()
prefetcher_cycle_operate()
```

该方案可以打通 STLB→PTW PQ 和统计链路，但通用接口以 data-cache line
prefetcher 为设计对象，不能清楚表达 STLB predictor 的 VPN、地址空间、请求来源和
miss-stream 语义。因此正式实现改为独立的 STLB prefetcher API；通用 cache
prefetcher API、已有 data prefetcher 和配置方式保持不变。

### 普通 cache 的 stall/retry 语义

当前 ChampSim 的普通 cache 在 tag lookup 中先调用
`prefetcher_cache_operate()`，随后才尝试 `handle_miss()`。如果 MSHR 或下层队列暂时
不能接收，请求留在 `inflight_tag_check`，下一周期再次 tag lookup，因此普通 cache
prefetcher 可能重复看到同一个 stalled access。

六种基础 STLB predictor 明确定义为 STLB miss-stream predictor。重复通知会使：

- SP/STP 重复产生相同候选；
- DP/H2P 观察到伪造的零 distance；
- ASP/MASP 观察到伪造的零 stride。

本实现不改变普通 cache 的上述原生语义，也不增加 per-request notified 补丁。STLB
专用 miss 回调只在 `handle_miss()` 成功消费请求后调用；stall retry 不调用，成功
后请求从 tag-check 队列移除，因此同一个请求的 stall retry 只训练一次。后续另一个
真实 load 即使访问相同 VPN 并合并到已有 MSHR，仍是新的 access，会正常训练一次。
该顺序还保证
demand 先进入 PTW RQ，随后产生的 STLB prefetch 才进入低优先级 PTW PQ。

### STLB 专用接口

STLB 模块使用独立基类和独立回调名称：

```text
stlb_prefetcher_initialize()
stlb_prefetcher_operate(context)
stlb_prefetcher_fill(fill_context)
stlb_prefetcher_cycle_operate()
stlb_prefetcher_final_stats()
prefetch_translation()
```

`operate` context 至少提供：

- virtual address 和 VPN；
- demand PC 和 instruction ID；
- CPU 与 ASID；
- access type 与 translation origin；
- hit/miss、useful-prefetch 和 warmup 状态；
- metadata。

`fill` context 另提供 set、way、victim virtual address/VPN，以及本次 fill 是否来自
prefetch。STLB 模块继续通过现有模块发现、JSON 配置和 cache builder 实例化，配置
写法仍为：

```json
"prefetcher": "prefetcher_stlb/<module>"
```

未配置 `STLB.prefetcher` 时仍使用 ChampSim 默认 `prefetcher/no`，不需要另建
`prefetcher_stlb/no`。

### 与 cache prefetcher 接口的对应关系

STLB 接口沿用 cache prefetcher 的生命周期，但把 line-address 参数扩展为包含 VPN、
ASID 和 translation origin 的 context：

| cache prefetcher | STLB prefetcher | 作用 |
|---|---|---|
| `prefetcher_initialize()` | `stlb_prefetcher_initialize()` | 模拟启动时初始化 predictor table、history 和私有统计 |
| `prefetcher_cache_operate(...)` | `stlb_prefetcher_operate(context)` | 接收 cache/STLB lookup 事件并训练、产生候选 |
| `prefetcher_cache_fill(...)` | `stlb_prefetcher_fill(fill_context)` | 接收 line/translation fill 和 victim 信息 |
| `prefetcher_cycle_operate()` | `stlb_prefetcher_cycle_operate()` | 每个 cache/STLB 周期执行后台工作或延迟发射 |
| `prefetcher_final_stats()` | `stlb_prefetcher_final_stats()` | 模拟结束时打印 predictor 私有统计 |
| `prefetch_line(...)` | `prefetch_translation(...)` | 向本级 prefetch queue 提交 line/translation prefetch |
| `prefetcher_branch_operate(...)` | 无 | 当前 STLB predictor 不消费 branch event |

模块侧可选择实现的精确 STLB 回调签名为：

```cpp
void stlb_prefetcher_initialize();
void stlb_prefetcher_operate(
    const champsim::modules::stlb_prefetcher_context& context);
void stlb_prefetcher_fill(
    const champsim::modules::stlb_prefetcher_fill_context& context);
void stlb_prefetcher_cycle_operate();
void stlb_prefetcher_final_stats();
```

predictor 继承的发射函数为：

```cpp
bool prefetch_translation(
    champsim::address virtual_address,
    uint32_t prefetch_metadata = 0) const;
```

`stlb_prefetcher_initialize()` 在 warmup 前调用一次。`operate()` 可以收到
`context.hit=true` 的 demand hit 和 `context.hit=false` 的、已经成功消费的 demand
miss；本阶段六种算法自行忽略 hit，因此使用 miss stream 训练。这里的“成功消费”只
决定回调时机，context 仍完全来自原始 STLB access，不包含 PTW/PTE/PPN 结果。
`fill()` 在 STLB translation 真正填入时调用。`cycle_operate()` 每周期调用，但六种
算法当前均在 miss callback 内同步发射，所以没有实现后台周期逻辑。`final_stats()`
在模拟结束时输出每种算法自己的候选和 table/history 统计。

cache `operate/fill` 返回 `uint32_t`，允许修改并继续传递 metadata；当前 STLB
`operate/fill` 返回 `void`，metadata 作为只读 context 输入，发射新请求时通过
`prefetch_translation(..., metadata)` 显式携带。六种算法不需要在 fill 上改写
metadata；未来如有这种需求，可以把 STLB fill 返回值扩展为 `uint32_t`。

### Infra 改动分层

- `inc/modules.h`：定义 STLB 基类、operate/fill context 和编译期 callback detection。
- `inc/cache.h`：在原 cache module type-erasure/model 中增加 STLB operate/fill
  dispatch；仍复用同一 JSON module loader 和 cache builder。
- `src/cache.cc`：从原始 tag lookup/MSHR 构造 context；安排 hit/miss/fill 回调时机；
  实现 `CACHE::prefetch_translation()`、ownership、MSHR merge、useful/late、
  too-early 和 pollution 统计。
- `src/modules.cc`：把 predictor 侧 `prefetch_translation()` 转发到绑定的 `CACHE`。
- `Makefile`：把 `prefetcher_stlb/` 加入 prefetcher module 搜索根目录。
- `config/instantiation_file.py`：PTW `pq_size` 保持默认 0，同时允许 JSON 显式配置
  16 等非零值。
- `inc/access_type.h`、`inc/block.h`、`inc/channel.h`：增加独立
  `STLB_PREFETCH` origin 和只用于 ownership/统计的 provenance；这些字段不参与
  cache/channel 地址匹配。
- `src/ptw.cc`：STLB demand/vBerti 所在 RQ 保持高优先级，STLB-local prefetch
  所在 PQ 只使用同一 `MAX_READ` 的剩余带宽。
- `cache_stats`：增加要求的 raw counter；plain printer 输出 raw counter、比例和
  质量统计，JSON printer 当前输出 raw counter；不复用或覆盖 vBerti/data-prefetch
  计数。

### 当前实验范围

当前只要求单核、普通 ChampSim trace。普通 `input_instr` 没有 trace ASID 字段，
ChampSim 将 ASID 固定设为 `{cpu,cpu}`，所以 1-core 实验中始终为 `{0,0}`，没有
上下文切换。接口仍携带 CPU/ASID，供未来 CloudSuite、多 ASID 或共享 STLB 扩展；
本阶段六种 predictor 不建立 per-ASID 状态表。

六种 predictor 在 miss 回调中立即发射候选，不在 cycle 回调中延迟发射。因此当前
`prefetch_translation()` 使用同步请求上下文是安全的。

### 提交结果与统计

`prefetch_translation()` 保持和 cache `prefetch_line()` 一致的 `bool` 返回值：

- `true`：候选进入 STLB 本地 PQ；
- `false`：候选未进入 STLB 本地 PQ。

predictor training 不依赖该返回值，也不会在提交失败时回滚。STLB resident hit、
MSHR merge、PTW issue、fill、useful、late、too-early 和 pollution 等异步结果继续由
现有 CACHE 中央统计记录，不增加 predictor 私有的异步拒绝枚举。

### Warmup 与 ROI

- warmup 期间正常训练 predictor state，并允许正常预取；
- warmup 期间不累计六种 predictor 的正式统计；
- ROI 保留 warmup 得到的表、history、stride 和 confidence；
- 正式统计只在 `warmup == false` 时累计。

进入 ROI 时不会再次调用 `stlb_prefetcher_initialize()`，因此 predictor state 不被
清空。CACHE 的 `begin_phase()` 会清零中央计数和 warmup prefetch 的统计 provenance/
shadow tracking，但不会 flush 已经 warm 好的 STLB translation。结果是 warmup 发出的
prefetch 可以继续作为 STLB 中的 warmed translation 提供命中，但不会在 ROI 中被归因
为 ROI prefetch 的 useful、useless、late、too-early 或 pollution。这是“ROI 只评价
ROI 内发起的 prefetch”的统计边界。

### 已确定的边界约定

以下内容是本阶段讨论后采用的明确语义，不作为待定设计：

1. **训练事件边界**：六种基础 predictor 只使用已经成功消费的
   `DEMAND_DATA` STLB miss 训练。STLB hit、vBerti translation request、predictor
   自己产生的 request、instruction translation 和 PTW 内部访问均不训练这六种
   miss-stream predictor。
2. **stall 与真实重复访问**：同一个 request 因 MSHR/下层队列 backpressure 发生的
   stall retry 不重复训练；请求成功消费后只回调一次。之后另一条真实 load 即使 VPN
   相同并 merge 到已经存在的 STLB MSHR，仍是新的真实 access，正常训练一次。
3. **训练和发射解耦**：predictor 在观察到有效 miss 后先更新自己的 history/table。
   `prefetch_translation()` 返回 `false` 时不回滚 predictor state。
4. **提交返回值边界**：`bool` 只表达候选是否进入 STLB 本地 PQ，不细分重复、resident、
   MSHR merge、队列满等后续结果；当前统计不需要新增拒绝原因枚举。
5. **队列与 backpressure**：STLB 本地 PQ 满时，本次提交失败并计入 requested-issued
   drop。已经进入本地 PQ 的 request 不因 STLB MSHR 或下层暂时忙而消失，而是保留在
   原生 cache pipeline 中等待重试。
6. **RQ/PQ 语义**：`prefetch_as_load=false` 时，demand STLB miss 和 vBerti
   Permit-PGC translation 进入 STLB→PTW RQ；STLB-local prefetch 进入
   STLB→PTW PQ。PTW 每周期先处理所有 RQ，再让 PQ 使用同一个 `MAX_READ` 的剩余带宽。
   本阶段不增加 PTW MSHR 容量限制；有效约束是 STLB MSHR/队列、PTW RQ/PQ 容量以及
   PTW `MAX_READ/MAX_FILL`。
7. **地址空间边界**：本阶段只验证单核、单地址空间普通 trace，ASID 固定为 `{0,0}`。
   context 已携带 CPU/ASID，但六种 predictor 暂不做 per-core/per-ASID state
   partition；扩展到多核或多 ASID 时必须增加隔离或 context-switch flush。
8. **可选回调边界**：STLB infra 提供 initialize、operate、fill、cycle 和 final-stats
   生命周期。六种同步 miss-stream predictor 当前只需要 initialize、operate 和
   final-stats；不实现算法不需要的 fill/cycle 不是接口缺失。
9. **配置兼容边界**：旧 JSON 不写 `STLB.prefetcher` 时仍选择原生 `prefetcher/no`，
   不需要 `prefetcher_stlb/no`；不写 `PTW.pq_size` 时仍为 0。只有显式启用 STLB
   predictor 并配置 STLB/PTW PQ 时才增加新请求路径。
10. **共存边界**：vBerti Permit-PGC 和 STLB-local predictor 可以同时开启；前者继续
    使用原有 origin、RQ 链路和统计，后者使用 `STLB_PREFETCH` origin、PQ 链路和独立
    统计，二者不共享 predictor state 或 ownership。
11. **useless 判定边界**：只有 STLB-prefetched translation 在被真实 demand 使用前
    发生实际驱逐时才计入 `prefetch_useless`。ROI 结束时仍驻留或仍在 PQ、tag-check、
    translation stash、MSHR 中的请求不强制结算为 useless，与普通 cache prefetcher
    的 eviction-based 语义一致；因此 `useful + useless == fill` 不是普遍不变量。

### 实施顺序和回归约束

1. 先完成 STLB 专用接口、no 模式和接口定向测试；
2. 验证未配置 STLB prefetcher 时原有日志和统计不变；
3. 再独立实现 SP、DP、ASP、STP、H2P、MASP；
4. 完成文档中规定的确定性序列测试；
5. 验证每种 predictor 可独立配置；
6. 验证 STLB predictor 与 vBerti Permit-PGC 同时开启时，两条请求链路和统计均有效；
7. 不修改已有 characterization 脚本、data prefetcher 算法或既有统计定义。

## 最终实现内容

### 基础设施与完整调用链

- 新增独立 `translation_origin::STLB_PREFETCH`，不复用 vBerti 的 origin。
- 新增 `champsim::modules::stlb_prefetcher`、完整 operate/fill context 和五个
  STLB 专用生命周期回调；data-cache prefetcher 接口没有改名或改变调用语义。
- demand STLB hit 在命中被消费时通知专用接口；demand STLB miss 只有在
  `handle_miss()` 成功后才通知，因此下层 RQ/MSHR stall retry 不会重复训练。
- predictor 在 miss 回调中调用 `prefetch_translation()`，候选先进入 STLB
  `internal_PQ`。`prefetch_as_load=false` 时，完成 STLB lookup 后使用
  STLB→PTW channel PQ；demand 和 vBerti translation 仍使用 RQ。
- STLB 自己生成的请求使用 `STLB_PREFETCH` origin，专用 operate 回调只接受
  `DEMAND_DATA`，因此 own-prefetch、vBerti、指令翻译和 PTW 内部访问均不会递归训练。
- STLB 本地 PQ 满时 `prefetch_translation()` 返回 `false` 并计入口 drop；请求已经
  被本地 PQ 接受后，即使 STLB MSHR 或 PTW PQ 暂时不可用，也保留在原生 cache
  pipeline 中重试。
- PTW 仍以同一个 `MAX_READ`（当前 JSON 为 2）先服务 RQ，再用剩余带宽服务 PQ；
  没有额外启用或伪造 PTW MSHR 限制，约束点仍是 STLB MSHR、队列容量和 PTW
  每周期读带宽。

一次 demand miss 的顺序为：

```text
STLB tag lookup miss
  -> handle_miss() 成功：demand 进入/合并 STLB MSHR，并向 PTW RQ 提交
  -> stlb_prefetcher_operate(miss context)
  -> predictor 生成候选 VPN
  -> prefetch_translation()
  -> STLB internal_PQ
  -> STLB tag lookup / MSHR
  -> STLB→PTW PQ
  -> PTW（RQ 优先，PQ 低优先级）
  -> translation 返回、STLB fill
  -> stlb_prefetcher_fill(fill context)
```

### 六种基础 predictor

六种实现均位于 `prefetcher_stlb/`，相互独立选择，不组成 ATP：

| predictor | 历史作用域 | 主要状态 | 最大候选数 |
|---|---|---|---:|
| SP | 当前 miss | 无状态，固定 `+1` | 1 |
| DP | global miss stream | 64-entry、4-way distance→successor table，每项两个后继 | 2 |
| ASP | per-PC miss stream | 64-entry、4-way PC table，stride 连续确认两次后预测 | 1 |
| STP | 当前 miss | 无状态，固定 `{-2,-1,+1,+2}` | 4 |
| H2P | global miss stream | 最近两个有符号 miss distance | 2 |
| MASP | per-PC miss stream | 64-entry、4-way PC table，先用 old stride 再用 new stride | 2 |

三个 64-entry table 均为 16 set × 4 way，表级 replacement 为稳定 LRU。DP 每个
entry 的两个 successor 槽另有独立局部 recency；查询必须发生在本次 transition
训练之前。ASP 中 `stability_count` 的精确定义是：初次建立 stride 后，该 stride
又连续匹配成功的次数，阈值为 2。MASP 在覆盖 stored stride 前先提交 old stride，
再提交刚观察到的 new stride。

每个 predictor 在自己的目录内独立实现候选处理：按生成顺序去重，丢弃当前 VPN、
零 distance 产生的当前页，以及 VPN 上溢/下溢。下游拒绝不会回滚 history/table
更新。warmup 正常训练并允许发射，predictor 私有计数只累计 ROI，ROI 开始时保留
warmup 状态。

### Predictor 目录解耦约束

六个基础模块按 data prefetcher 的目录模式实现：

```text
prefetcher_stlb/sp/{sp.h,sp.cc}
prefetcher_stlb/dp/{dp.h,dp.cc}
prefetcher_stlb/asp/{asp.h,asp.cc}
prefetcher_stlb/stp/{stp.h,stp.cc}
prefetcher_stlb/h2p/{h2p.h,h2p.cc}
prefetcher_stlb/masp/{masp.h,masp.cc}
```

每个类直接继承公共 infra `champsim::modules::stlb_prefetcher`。算法所需的 history、
table、LRU replacement、候选生成/去重和 predictor-private 统计全部位于自己的
`.h/.cc`，不存在 `prefetcher_stlb/stlb_prefetcher_common.h`，也不 include 另一个
predictor 目录中的文件。因此删除、替换或单独修改一个 predictor 不会给其余五个
predictor 引入源码依赖。这里允许少量相同的边界检查/统计代码在各模块内重复，目的是
明确保持算法模块的独立所有权；STLB 请求 context、生命周期 dispatch 和
`prefetch_translation()` 仍只由公共 infra 提供。

### 统计语义

中央 STLB 统计严格保留要求的 raw counter：`requested`、`issued`、
`prefetch_lookups`、`prefetch_hit`、`prefetch_miss`、`prefetch_mshr_merge`、
`prefetch_fill`、`prefetch_useful`、`prefetch_useless`、`prefetch_late`、
`prefetch_too_early`、`prefetch_pollution_evict` 和
`prefetch_pollution_demand`。too-early 与 pollution 使用独立 STLB shadow
结构，不与 vBerti/data prefetch ownership 混用。

日志还输出：

```text
pq_drop_rate                         = (requested - issued) / requested
prefetch_miss_rate                   = prefetch_miss / prefetch_lookups
prefetch_mpki                        = prefetch_lookups * 1000 / ROI instructions
prefetch_too_early_among_fill        = too_early / fill
prefetch_too_early_among_useless     = too_early / useless
prefetch_pollution_among_prefetch_fill = pollution_evict / fill
prefetch_accuracy                    = useful / issued
prefetch_coverage                    = useful / (useful + demand miss)
timely                               = useful - late
timely_coverage                      = timely / (useful + demand miss)
timely_accuracy                      = timely / issued
fill_accuracy                        = (timely + late) / fill
```

每种算法另输出 trigger、raw/unique candidate、去重/地址 drop、submitted、accepted、
rejected，以及对应 table/history 统计。训练统计与下游接收统计分开。

#### Too-early 与 pollution 的事件定义

- `prefetch_too_early`：STLB prefetch 已经 fill，但在任何 demand 使用它之前就被
  eviction。该 VPN/CPU/ASID 被放入有限 shadow structure；之后真实 demand 再访问该
  translation 并 miss，才确认一次 too-early。它表达“方向可能正确，但到达得过早，
  没能存活到 demand”。
- `prefetch_pollution_evict`：一次 STLB prefetch fill 驱逐了有效 translation；被驱逐
  translation 的 VPN/CPU/ASID 被记录。若后续真实 demand 对该 translation miss，确认
  prefetch 造成了一次可观察的 pollution。
- `prefetch_pollution_demand`：上述被 prefetch 驱逐、随后产生 demand miss 的 victim
  原本是 demand fill，而不是另一条 prefetch fill。它是 pollution_evict 中更严格的
  demand-victim 子集。

shadow structure 是测量结构，不参与 STLB hit/miss、replacement 或请求调度，只用于
事后判断。如果 shadow entry 在确认前被容量淘汰，对应事件不会被计数，因此这是有限
tracking capacity 下的测量结果。

#### 普通日志与统计 JSON

ChampSim 无参数运行时总是通过 plain printer 向 stdout 输出普通文本，实验脚本重定向
得到的 `.log` 就是该输出。运行时额外添加：

```bash
--json result.json
```

才会另外生成统计结果 JSON；它与用于构建 ChampSim 的配置 JSON 不是同一种文件。
本阶段最初约定的完整统计列表以普通 `.log` 为交付目标。JSON 当前保存全部 STLB
prefetch raw counter，但不保存由 ROI instruction 数和多个 counter 组合得到的 rate、
MPKI、accuracy、coverage 与 fill_accuracy。

当 ROI 中 `stlb_prefetch_requested > 0` 时，普通 `.log` 输出最初要求的完整列表：
requested、issued、pq_drop_rate、lookups、hit、miss、MSHR merge、fill、miss rate、
MPKI、useful、useless、late、too-early、pollution、accuracy、coverage、timely coverage、
timely accuracy 和 fill_accuracy。当前实现为保持 no-prefetch 旧日志兼容，在
`requested == 0` 时不额外打印 pq_drop_rate、显式 lookups/MSHR-merge、prefetch_mpki、
timely coverage/accuracy 和 fill_accuracy 行；其他 raw counter 和比例行仍输出 0。
因此“发生过 STLB prefetch 的实验日志”字段完整，“零 request 实验也必须逐项显示 0”
尚未作为当前输出语义实现。

## 配置兼容性

旧 JSON 未填写 `STLB.prefetcher` 时仍展开为 `prefetcher/no`；不需要
`prefetcher_stlb/no`。未填写 `PTW.pq_size` 时默认值仍为 0。以下旧配置的展开
语义保持不变：

```text
1C.translation-only.json : prefetcher/no, STLB PQ=0, PTW PQ=0
1C.permit-pgc.json       : prefetcher/no, STLB PQ=0, PTW PQ=0
1C.nopref.json           : prefetcher/no, STLB PQ=0, PTW PQ=0
1C.discard-pgc.json      : prefetcher/no, STLB PQ=0, PTW PQ=0
```

启用一个新 predictor 的字段为：

```json
"STLB": {
  "prefetcher": "prefetcher_stlb/sp",
  "prefetch_activate": "LOAD",
  "prefetch_as_load": false,
  "pq_size": 16
},
"PTW": { "pq_size": 16 }
```

`sp` 可分别替换为 `dp`、`asp`、`stp`、`h2p` 或 `masp`。编译专用测试配置已经
为六者分别生成独立 executable，确认没有把多种 predictor 错误叠加到同一 STLB。

## 定向测试结果

`433-stlb-prefetcher-interface.cc` 通过 29 个断言：

- initialize、miss/hit/fill context 的 VPN、VA、PC、CPU、ASID、origin、warmup
  等字段正确；
- own-prefetch 不递归触发；
- 人为填满下层 RQ 后，同一 stalled miss 在 20 个 retry cycle 中回调 0 次；释放
  backpressure 后恰好回调 1 次；
- 未使用但仍驻留的 STLB prefetch 在 `end_phase()` 前后均不被强制计为 useless。

`434-stlb-basic-prefetchers.cc` 通过 57 个断言，覆盖文档规定的确定性序列：

```text
SP:    100                         -> 101
STP:   100                         -> 98,99,101,102
H2P:   100,104,105                 -> 106,109
MASP:  100,105,108 (same PC)       -> 110; 113,111
ASP:   100,104,108,112 (same PC)   -> 116
DP:    100,104,105,109,110         -> at 109:110; at 110:114
```

还验证了 STLB hit 不更新 DP/H2P history、ASP/MASP 的不同 PC 隔离、H2P/MASP
重复候选只提交一次，以及 warmup 训练但不累计 predictor ROI 统计。两组共 86 个
断言全部通过。

六个独立配置均通过完整构建，并各自完成 10K warmup + 50K ROI smoke run；SP、
STP、H2P、MASP 在该短窗口内产生候选，DP/ASP 正常训练但因样本尚未形成可预测
pattern 而候选为 0，六个模拟均正常结束并打印各自 final stats。

完成目录解耦后再次生成编译依赖清单：每个模块在 `prefetcher_stlb/` 范围内只列出
自己的 `.cc` 和 `.h`；接口 29 个断言、算法 57 个断言以及上述六个 smoke run 再次
全部通过，候选序列和 predictor-private 统计语义保持不变。

## 无 STLB prefetch 的全量日志回归

参考日志：

```text
launch_sim_characterization/...-evidence-chain/result/nopref/
compute_int_14_new-pgc-nopref-1core---hide-heartbeat.log
```

修改后使用原 `1C.nopref.json` 和相同 trace 全量重跑：

```text
warmup = 50,000,000 instructions
ROI    = 100,000,000 instructions
trace  = /data0/tzh/champsim_traces/QMM/compute_int_14_new.xz
```

结果保持：

```text
ROI instructions = 100000001
ROI cycles       = 55191721
IPC              = 1.812
all STLB-prefetch counters = 0
```

原始文本不可能按 byte 完全相同，因为 `Simulation time` 是墙钟值，而且参考日志生成
后、本次接口重构开始前，工程已经增加了若干 vBerti/PTW 展示行。过滤这两类非共同
内容后，旧/新全部共同日志行逐行一致；两份 normalized log 的 SHA-256 同为：

```text
e6281aebb9c1c48289678e4eace1ac1e5865e535158c7e26e3a21c85bb4b992e
```

因此未配置 STLB predictor 时，本次专用接口和六种算法没有改变原 cache、TLB、PTW
请求时序或既有统计值。

## vBerti Permit-PGC 共存验证

使用完整 `json/1C.permit-pgc-stlb-stride.json`，配置 STLB PQ=16、PTW PQ=16、
`prefetch_as_load=false`。在 `bfs.kron-128B` 的 1M warmup + 2M ROI 中：

```text
vBerti requested          = 3,581,672
vBerti issued             = 1,026,779
STLB prefetch requested   = 78
STLB prefetch issued      = 78
STLB prefetch lookups     = 78
STLB prefetch hit/miss    = 2 / 76
STLB prefetch fill        = 76
STLB prefetch useful      = 14
STLB prefetch useless     = 62
STLB prefetch late        = 0
STLB prefetch fill_accuracy = 0.184211
```

模拟正常结束。vBerti 与 STLB-local predictor 同时有非零 requested/issued，且
STLB `hit + miss = lookups`，证明两套 ownership、统计与 RQ/PQ 请求路径可以同时工作。
该记录产生于取消 phase-end useless 强制结算之前；其中 `useful + useless = fill`
来自旧结算规则，不是当前统计应满足的不变量，也不用于验证当前 useless 定义。

## 独立 STLB-local prefetch buffer

### 配置与默认兼容性

prefetch policy 和 fill destination 已解耦。任意 `prefetcher_stlb/*` 模块继续只调用
`prefetch_translation()`；由 STLB JSON 决定结果直接填 STLB，还是进入独立 PB：

```json
"STLB": {
  "prefetcher": "prefetcher_stlb/atp",
  "prefetch_activate": "LOAD",
  "prefetch_as_load": false,
  "pq_size": 16,
  "stlb_prefetch_destination": "PB",
  "stlb_prefetch_buffer_size": 64,
  "stlb_prefetch_buffer_latency": 2
},
"PTW": {
  "pq_size": 16
}
```

三个新字段都只属于 STLB：

- `stlb_prefetch_destination` 只接受 `STLB` 或 `PB`，缺省为 `STLB`；
- 选择 `PB` 时 size 必须大于 0；
- latency 单位为 STLB cycle，论文配置使用 2；
- 在非 STLB cache 上使用这些字段会在配置生成阶段报错。

所以旧 JSON 不写任何新字段时，不会构造 PB lookup、不会增加额外延迟，也不会增加
新的输出行。默认执行路径仍是原 direct-fill 路径。

### 请求与 fill 时序

实现保持论文描述的串行次序：

```text
demand -> STLB tag lookup
       -> only on STLB miss: PB lookup and configured delay
       -> PB hit: consume entry, fill STLB, return translation
       -> PB miss: original handle_miss -> STLB MSHR -> PTW RQ
```

STLB-local prefetch 自身仍是：

```text
prefetch_translation -> STLB internal_PQ -> STLB lookup/miss
                     -> STLB MSHR -> PTW PQ
                     -> completed translation -> configured destination
```

PB 是 fully-associative FIFO。key 使用 `(cpu, vpn, asid[0], asid[1])`。相同 key 的新
fill 替换旧 entry 并刷新 FIFO 位置；满时淘汰最老 entry。lookup 在开始时捕获结果，
因此 lookup 期间发生的后续 insert/evict 不会逆向改变已经开始的访问结果。

以下边界是显式实现的不变式：

1. 只有 `origin == STLB_PREFETCH && stlb_prefetch_tracked` 的完成请求能进入该 PB；
2. vBerti `L1D_PREFETCH_*` fill 完全不进入该 PB；
3. demand 已 merge 到 STLB-local prefetch MSHR 时，`tlb_ptw_real_demand_waiting` 使
   fill 绕过 PB 并直接进入 STLB，保留 late-prefetch 语义；
4. PB miss 遇到 STLB MSHR/PTW backpressure 时保留在 mature lookup queue 中重试，
   不重复训练 predictor；
5. 同时启用既有 CP-PB 时，既有 CP-PB hit 优先，继续保持原零延迟行为；
6. PB hit 通过 `stlb_prefetcher_context.prefetch_buffer_hit` 明确反馈给算法。

warmup 期间 predictor 和 PB 都正常训练/运行。ROI 开始只清统计；PB entry 和尚未完成
的 lookup 保留，以保持硬件状态连续。warmup 产生的 entry 会把 `stats_tracked` 清零，
因此它在 ROI 中仍可改善时序，但不会被错误计入 ROI useful/useless。

### 新增观测统计

原有完整 `stlb_prefetch_*` 统计继续作为算法端统计。PB 额外输出：

```text
STLB_prefetch_buffer_insert
STLB_prefetch_buffer_eviction
STLB_prefetch_buffer_lookup
STLB_prefetch_buffer_hit
STLB_prefetch_buffer_miss
STLB_prefetch_buffer_hit_rate
```

这些行只在 PB 有活动时打印，保证旧 no/default log 不因为新增零值字段发生文本变化。
PB insert 仍计入原 `stlb_prefetch_fill`；首次消费一个 ROI-tracked PB entry 计入原
`stlb_prefetch_useful`；未使用 entry 被 FIFO 淘汰时计入原 `stlb_prefetch_useless`，
并进入既有 STLB too-early shadow。PB demand hit 后才以 demand provenance 填入 STLB，
所以不会制造 STLB prefetch pollution。

### 已完成的 PB smoke 结果

`compile-stlb-stride-pb` 使用 16-entry、2-cycle PB，在 `bfs.kron-128B` 上完成
100K warmup + 500K ROI：

```text
STLB prefetch requested/issued = 142 / 142
STLB prefetch lookup/miss      = 142 / 142
STLB prefetch fill             = 142
PB insert/eviction             = 142 / 10
PB lookup/hit/miss             = 552 / 123 / 429
PB hit rate                    = 0.222826
STLB prefetch useful           = 122
```

`PB hit + PB miss == PB lookup`，模拟正常结束。`compile-stlb-atp-pb` 也完成配置生成、
完整编译和 smoke run；短随机窗口内 ATP selector 保持 disabled，因此该次只覆盖
serial PB-miss -> demand PTW 路径，未产生 ATP prefetch fill。

另外使用 `compile-vberti-stlb-stride-pb` 在同一 `bfs.kron-128B` 窗口同时开启
vBerti Permit-PGC 和 STLB-local PB：

```text
vBerti requested               = 751013
STLB-local prefetch requested  = 21
PB insert                      = 21
PB lookup/hit/miss             = 428 / 3 / 425
```

两条链路同时非零且模拟正常结束，证明 destination=PB 没有接管或关闭 vBerti 原链路。

## 自动测试与收尾约束

- `make pytest`：235 项成功，1 项按原工程设置跳过；包含 PTW PQ 默认 0、显式 16
  被保留，以及 STLB-PB 三个字段生成、作用域和非法 size 拒绝等配置测试。
- `433-stlb-prefetcher-interface` 定向 C++ 测试已单独链接并实际运行：4 个场景、
  56 个断言全部通过。覆盖默认 direct-fill 不访问 PB、2-cycle 串行 PB hit、demand
  优先 merge 在途 STLB prefetch（不被 PB lookup 延迟），以及 PTW RQ backpressure
  解除后只训练一次 predictor。
- 正常 simulator build、六个独立 predictor build、`no` build 和
  `vBerti + STLB` build 均成功；编译只有工程原有 conversion/shadow warning。
- 本次接口/算法实现没有修改 characterization 脚本、已有 data prefetcher 算法或
  vBerti permit/discard 逻辑。
- 当前明确支持并验证的是单核、单地址空间普通 trace；context 已携带 CPU/ASID，
  但六种 predictor 尚未实现共享 STLB 下的 per-core/per-ASID state partition。未来
  扩到多核或多 ASID 时必须增加隔离或 context-switch flush。

### 旧 JSON / no-STLB-prefetcher 日志回归

使用改动前保留的 `pgc-nopref-1core` 二进制和改动后由原
`1C.nopref.json` 原样重新生成、重新编译的同名二进制，执行完全相同的命令：

```text
--warmup-instructions 1000000
--simulation-instructions 1000000
--hide-heartbeat
/data2/zcq/champsim_traces_gap/tc.urand-504B.champsimtrace.xz
```

原始文本 `diff` 只有两行宿主机墙钟时间从 12 秒变为 11 秒；这是 simulator 打印的
实际运行耗时，不属于模拟状态。仅将 `(Simulation time: ...)` 字段规范化后，两份完整
log 逐字节相同，`cmp` 返回 0，且 SHA256 同为：

```text
b9a8a1bdbe943e2c6bc3ef487a57ffd473a6f5423aa1b377781fc3529dfb72a6
```

因此 simulated cycle、instruction、IPC、已有统计值和已有输出行均完全一致。旧 JSON
省略新字段时仍走默认 `destination=STLB`，不创建 PB lookup，也不打印 PB 零值统计行。
