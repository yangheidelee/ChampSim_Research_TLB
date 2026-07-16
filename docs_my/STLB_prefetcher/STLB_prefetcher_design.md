# STLB 专用 Prefetcher 设计方案与实现约束

## 1. 文档目的

本文记录在当前 ChampSim 工程中增加 STLB 专用 translation prefetcher 的已确认设计方案、兼容性要求、队列及带宽语义、与 vBerti Permit-PGC 同时开启时的交互规则，以及必须输出的统计指标。

设计的首要目标是：

1. `STLB prefetcher = no` 时，现有 vBerti Permit-PGC 的请求路径、模拟时序、IPC 和已有统计值保持不变；新增 STLB-prefetch 统计应全部为 0。
2. STLB prefetcher 与 vBerti Permit-PGC 可以单独或同时开启，并保持功能和统计归属语义正确。
3. STLB prefetch 使用低优先级 PTW PQ；真实 demand 和现有 vBerti translation 继续使用 PTW RQ。
4. 尽可能复用当前 `CACHE` 的 prefetch、MSHR merge、backpressure、too-early 和 pollution 语义，不额外引入不必要的独立硬件结构。

## 2. 当前工程中的基础事实

### 2.1 STLB 本身是一个 `CACHE`

当前 ITLB、DTLB 和 STLB 都通过 `CACHE` 建模，因此 STLB 已经具备模块化 prefetcher 接口、`internal_PQ`、tag lookup、MSHR、fill、replacement 和 prefetcher callback 等基础设施。

STLB 可以在配置中使用：

```json
"STLB": {
  "prefetcher": "no"
}
```

或者指定新的 STLB prefetcher 模块。

### 2.2 现有 vBerti Permit-PGC translation 的类型

vBerti 跨页数据预取触发地址翻译时，请求具有：

```text
type               = LOAD
translation_source = L1D_PREFETCH_CROSS_PAGE
```

该请求经过 DTLB、STLB 后仍保持 `type = LOAD`，所以在 STLB miss 下发时进入 PTW RQ，而不是 PQ。

因此现有路径是：

```text
vBerti Permit-PGC cross-page translation
    -> DTLB
    -> STLB
    -> PTW RQ
```

### 2.3 当前 PTW 的 `MSHR_SIZE` 未实际限制请求数量

`PageTableWalker` 虽然保存了 `MSHR_SIZE`，当前请求接收路径却没有使用 `MSHR.size() >= MSHR_SIZE` 进行准入限制。因此配置中的：

```json
"PTW": {
  "mshr_size": 5
}
```

当前并不形成真正的 5-entry PTW walk 上限。

本项目暂不修复这个既有行为，避免在 `STLB prefetcher = no` 时改变 Permit-PGC 基线。

### 2.4 实际 outstanding translation 上限来自 STLB MSHR

当前 STLB 的 MSHR 数量为 16。正常 demand、vBerti translation 以及计划中的 STLB prefetch 都必须在成功下发 PTW 后保留一个 STLB MSHR，直至 translation 返回并完成 STLB fill。

因此在当前拓扑和请求语义下，近似满足：

```text
PTW RQ 中等待的请求
+ PTW PQ 中等待的请求
+ PTW 正在执行的 walk
+ PTW 已完成但尚未被 STLB 释放的请求
<= STLB MSHR_SIZE = 16
```

这里不是将 PTW 的结构性 MSHR 定义为 16，而是由 STLB 的 16-entry MSHR 构成端到端 outstanding translation 的实际上限。

该结论依赖以下前提：

1. STLB prefetch 使用 `fill_this_level = true` 和 `response_requested = true`，必须保留 STLB MSHR。
2. 所有相关 PTW 请求均经过 STLB，不存在绕过 STLB 的新请求源。
3. STLB 只有在下层 channel 成功接受请求后才分配对应 MSHR。

## 3. 总体请求路径

新增 STLB prefetcher 后，系统路径为：

```text
真实 data demand -----------+
                            +-> STLB -> PTW RQ -> page walk
vBerti Permit-PGC ----------+

STLB predictor
    -> STLB internal_PQ
    -> STLB lookup/MSHR
    -> STLB-to-PTW channel PQ
    -> page walk
```

STLB 配置保持：

```json
"prefetch_as_load": false
```

新的 STLB prefetch请求使用：

```text
type               = PREFETCH
translation_source = STLB_PREFETCH
```

需要在 `translation_origin` 中新增独立的 `STLB_PREFETCH`，且不得改变现有 origin 的编号、名字和统计含义。

## 4. PTW PQ 设计

### 4.1 使用既有 channel PQ

不在 `PageTableWalker` 内部再增加第二个独立 `std::deque`。直接使用 STLB 到 PTW 的 channel PQ 表达排队和 backpressure：

```text
STLB -> PTW channel RQ：demand/vBerti
STLB -> PTW channel PQ：STLB prefetch
```

计划容量：

```text
PTW input PQ size = 16
```

当前配置生成器将 PTW channel 的 `pq_size` 硬编码为 0，需要改为读取 PTW JSON 配置，并保持未配置时默认为 0：

```json
"PTW": {
  "rq_size": 16,
  "pq_size": 16,
  "mshr_size": 5,
  "max_read": 2,
  "max_write": 2
}
```

### 4.2 PTW RQ/PQ 仲裁

RQ 和 PQ 共享同一个 `MAX_READ` 带宽：

```text
每周期先处理 RQ；
PQ 只能使用本周期剩余的 MAX_READ 带宽。
```

当 `max_read = 2` 时：

| 本周期成功接收的 RQ | 本周期最多接收的 PQ |
| ---: | ---: |
| 2 | 0 |
| 1 | 1 |
| 0 | 2 |

不能分别给 RQ 和 PQ 各自 2 个请求，否则总入口带宽会错误地变成 4。

第一版不增加 starvation promotion 或 PQ aging；严格保持 demand RQ 优先。

### 4.3 PQ 满和 backpressure 语义

必须区分两处 PQ：

#### STLB `internal_PQ` 满

predictor 调用 `prefetch_translation()` 时，如果 STLB 本地 `internal_PQ` 已满：

```text
requested 增加；
issued 不增加；
接口返回 false；
该候选直接 drop。
```

这是正式 `pq_drop_rate` 的来源。

#### STLB-to-PTW channel PQ 满

如果请求已经通过 STLB lookup，但 PTW channel PQ 暂时已满：

```text
STLB handle_miss() 返回 false；
请求保留在 STLB inflight_tag_check；
后续周期继续重试；
不得静默丢失。
```

请求一旦被 PTW PQ 接受，后续即使暂时无法推进 page walk，也必须留在 PQ 或 PTW 状态中等待，不得再次计为入口 drop。

## 5. PTW 带宽和容量约束

### 5.1 `max_read = 2`

`max_read` 映射到 `MAX_READ`，限制每个 PTW cycle 从上游 RQ/PQ 合计接收的新 walk 数量。加入 PQ 后，RQ 和 PQ 必须共享这个限制。

### 5.2 `max_write = 2`

`max_write` 映射到 `MAX_FILL`。它不是普通内存写带宽，而是限制每个 PTW cycle 能够完成或推进的 page-walk fill/step 数量。

以下两个阶段共享 `MAX_FILL`：

1. 将最后一级已完成的 translation 返回 STLB。
2. 将完成当前页表层级的 walk 推进到下一个层级。

### 5.3 不启用 PTW 的 5-entry MSHR 限制

第一版明确保持当前 PTW RQ 行为，不加入新的 `MSHR_SIZE=5` 准入检查，也不增加 demand-reserved MSHR 或 prefetch quota。

原因是：

1. 当前 5-entry 限制没有生效，突然启用会改变现有 Permit-PGC baseline。
2. STLB 的 16-entry MSHR 已经限制端到端 outstanding translation 数量。
3. demand、vBerti 和 STLB prefetch会自然竞争同一组 STLB MSHR，更符合本次实验希望观察的共享资源行为。

MSHR merge 仍遵循 Cache 风格：

```text
先检查相同 CPU+ASID+VPN 是否已有 STLB MSHR；
找到则 merge，即使 MSHR 已满；
找不到才检查是否能够建立新的 STLB MSHR；
资源不足则请求保留并重试。
```

## 6. `STLB prefetcher = no` 的基线兼容要求

当 STLB 配置为 `no` 时：

1. STLB predictor不得生成任何请求。
2. STLB `internal_PQ` 始终为空。
3. PTW PQ 始终为空。
4. 新增 PQ 消费逻辑不得改变原有 RQ 的请求顺序、带宽和启动周期。
5. vBerti Permit-PGC 继续使用 PTW RQ。
6. 不启用新的 PTW MSHR 限制。
7. 原有 IPC、请求路径和已有统计值应与修改前的逻辑 A 一致。
8. 新增 STLB-prefetch统计全部输出 0。

日志会因为增加新指标而不再逐字节相同，但原有指标的数值必须一致。

### 6.1 旧 JSON 配置的默认值兼容

以下现有实验配置必须无需修改即可继续使用并保持原语义：

```text
1C.translation-only.json
1C.permit-pgc.json
1C.nopref.json
1C.discard-pgc.json
```

这些配置当前都具有：

```json
"STLB": {
  "pq_size": 0,
  "mshr_size": 16,
  "prefetch_as_load": false
},
"PTW": {
  "rq_size": 16,
  "mshr_size": 5,
  "max_read": 2,
  "max_write": 2
}
```

它们没有显式填写 STLB `prefetcher`，也没有填写 PTW `pq_size`。配置系统必须保持以下默认值：

```text
STLB prefetcher omitted -> no
PTW pq_size omitted      -> 0
```

因此实现时只能把 PTW queue 配置生成逻辑从“硬编码0”改为：

```python
ptw.get("pq_size", 0)
```

不得把未配置 PTW PQ 的全局默认值改成16。只有显式开启 STLB prefetcher的新实验 JSON 才同时配置：

```json
"STLB": {
  "prefetcher": "<stlb-prefetcher-name>",
  "pq_size": 16,
  "prefetch_as_load": false
},
"PTW": {
  "pq_size": 16
}
```

在旧配置中，STLB本地PQ容量为0、STLB prefetcher为`no`、PTW PQ容量默认为0；现有vBerti/translation-only请求仍以`type=LOAD`进入PTW RQ，因而其功能路径不受新增PQ代码影响。

需要保留旧 binary 与新 `STLB prefetcher=no` binary 的定向 equivalence test，至少比较：

```text
IPC
retired instructions
DTLB/STLB demand hit/miss/MSHR merge/fill
vBerti requested/issued/PQ drop
vBerti DTLB/STLB useful/late/useless/too-early/pollution
PTW DRAM-touch统计
```

## 7. vBerti Permit-PGC 与 STLB prefetcher 双开语义

### 7.1 训练过滤

当前 vBerti translation 到达 STLB 时表现为：

```text
type               = LOAD
prefetch_from_this = false
translation_source = L1D_PREFETCH_CROSS_PAGE
```

因此 STLB predictor不能只检查 `type == LOAD` 或 `!prefetch_from_this`。第一版只允许真实 data demand 训练并产生预测：

```text
translation_source == DEMAND_DATA
```

以下来源不得触发 STLB predictor：

```text
DEMAND_INSTRUCTION
L1D_PREFETCH
L1D_PREFETCH_SAME_PAGE
L1D_PREFETCH_CROSS_PAGE
L1I_PREFETCH
STLB_PREFETCH
OTHER
```

这可以避免 vBerti 访问再次触发 STLB predictor，以及 STLB predictor递归训练自身。

### 7.2 匹配 key

所有 TLB prefetch、pending、MSHR关联、too-early 和 pollution 记录都必须至少使用：

```text
CPU + ASID[0] + ASID[1] + VPN
```

不能只按 VPN 匹配不同地址空间的 translation。

### 7.3 独立 origin 和 provenance

vBerti 和 STLB prefetch必须有不同 origin、不同 initiator provenance 和不同质量统计状态：

```text
vBerti：L1D_PREFETCH_CROSS_PAGE + tlb_cross_prefetch_* tracker
STLB predictor：STLB_PREFETCH + stlb_prefetch_* tracker
```

MSHR/response/BLOCK 中应增加独立的 STLB-prefetch字段，例如：

```cpp
bool stlb_prefetch_initiated;
bool stlb_prefetch_used;
uint32_t stlb_prefetch_cpu;
uint64_t stlb_prefetch_id;
```

调度身份和最初发起身份必须分离：真实 demand merge 后可以使请求在逻辑上成为 demand，但不能丢失 STLB prefetch initiator，以免漏算 late、fill 和 useful。

### 7.4 同 VPN 合并的 ownership

采用 first-initiator ownership：只有真正建立新 STLB MSHR/page walk 的 prefetcher拥有该 fill 及其后续 usefulness。

#### vBerti 先到，STLB prefetch 后到

```text
vBerti 已有 STLB MSHR；
STLB prefetch merge到该 MSHR。
```

STLB prefetch统计：

```text
prefetch_lookups++
prefetch_miss++
prefetch_mshr_merge++
```

但不获得 `prefetch_fill` 或后续 useful ownership。vBerti保留原有 fill/useful/late统计归属。

#### STLB prefetch先到，vBerti 后到

STLB prefetch保留 page-walk initiator和 fill ownership。vBerti只统计自己的 lookup/miss/MSHR merge，不得抢走 STLB prefetch 的 fill。vBerti不是 real demand，因此不能让 STLB prefetch计为 useful 或 late。

#### STLB prefetch先到，真实 demand 后到

真实 demand merge到尚未完成的 STLB-prefetch translation时：

```text
prefetch_useful++
prefetch_late++
```

第一版遵循现有 Cache late-prefetch语义：如果底层请求已经位于 PTW PQ，则 demand merge后不把该请求迁移到 RQ。功能上只保留一个 walk，但 demand继续等待该 PQ 请求获得服务。

PTW PQ-to-RQ promotion属于未来可独立研究的增强特性，不进入第一版，以免偏离现有 Cache 语义。

## 8. CP-PB 共存规则

现有 STLB CP-PB 仍只重定向 `L1D_PREFETCH_CROSS_PAGE` 发起的 fill。新增加的
STLB-local PB 是另一套独立结构，只接收 `translation_origin::STLB_PREFETCH`，两者
不共享 entry、replacement 或统计。

STLB-local predictor 的算法与目标位置由 infra 解耦。目标位置通过 STLB JSON 配置：

```json
"STLB": {
  "prefetcher": "prefetcher_stlb/atp",
  "stlb_prefetch_destination": "PB",
  "stlb_prefetch_buffer_size": 64,
  "stlb_prefetch_buffer_latency": 2
}
```

`stlb_prefetch_destination` 缺省为 `STLB`，因此所有旧 JSON 继续 direct-fill。只有显式
选择 `PB` 才启用独立 buffer；size 必须大于 0，而且这三个配置键在非 STLB cache 上
会被配置生成器拒绝。

同时开启两套 PB 时：

```text
vBerti cross-page fill                         -> existing CP-PB
STLB-local prefetch fill, no waiting demand    -> STLB-local PB (when destination=PB)
STLB-local prefetch fill, demand already merged -> normal STLB
```

需求访问的次序是串行的：先完成 STLB tag lookup；仅在 STLB miss 后查 STLB-local PB，
等待配置的 latency（论文值为 2 个 STLB cycle）；PB miss 后才进入原有 STLB MSHR/PTW
路径。若既有 CP-PB 同时命中，保留既有 CP-PB 的优先级和零延迟行为，避免新实验改变
旧 CP-PB 语义。

## 9. Too-early 和 pollution

当前工程已有 TLB 专用 shadow 结构，并且 key 已包含 CPU、VPN 和 ASID，可以复用其模板和容量逻辑。

但 vBerti 与 STLB prefetch必须使用独立 shadow，不能共享同一个统计状态：

```text
vBerti：
  tlb_cross_prefetch_too_early_shadow
  tlb_cross_prefetch_pollution_shadow

STLB predictor：
  stlb_prefetch_too_early_shadow
  stlb_prefetch_pollution_shadow
```

### 9.1 Too early

定义：一个尚未被真实 demand 使用的 STLB-prefetched translation 被驱逐，随后在 shadow 生命周期内出现相同 CPU+ASID+VPN 的真实 demand miss。

状态流：

```text
unused STLB-prefetch fill被驱逐
    -> 写入too-early shadow

后续真实demand miss相同key
    -> 消费shadow entry
    -> prefetch_too_early++
```

### 9.2 Pollution

STLB prefetch fill驱逐有效 victim时记录 candidate，并保存 victim 是否为 demand translation。后续真实 demand请求相同 victim key时，分别累计 pollution 指标。

功能状态可以互相影响，但两类 prefetch的统计归属不得因共享 flag 或共享 shadow entry而被覆盖。

## 10. STLB translation prefetch接口

不要直接依赖普通 data-cache `prefetch_line()` 的地址语义。需要增加 TLB 专用接口，例如：

```cpp
struct tlb_prefetch_request {
  champsim::address v_address;
  std::array<uint8_t, 2> asid;
  uint32_t cpu;
  uint32_t metadata;
};

bool prefetch_translation(const tlb_prefetch_request& req);
```

生成的 packet必须满足：

```text
address             = target virtual address/VPN address
v_address           = target virtual address
asid                = 当前请求ASID
cpu                 = 当前CPU
type                = PREFETCH
translation_source  = STLB_PREFETCH
is_translated       = true
response_requested  = true
fill_this_level     = true
```

这里的 `is_translated = true` 表示不需要再经过 Cache 的 `lower_translate` 地址翻译阶段，不表示该 VPN 已经在 STLB 命中。

STLB predictor callback还必须获得足够的 TLB context，至少包括：

```text
CPU
ASID
VPN/virtual address
IP
STLB hit/miss
translation_source
instruction/data属性
```

## 11. 第一版 predictor

第一版使用简单 PC-VPN stride predictor，便于验证框架而不是追求复杂预测算法。

建议每个 load PC 保存：

```text
last_vpn
last_stride
confidence
```

仅真实 data demand更新训练状态。当连续 VPN stride一致且 confidence达到阈值时，预测：

```text
target_vpn = current_vpn + stride
```

第一版可以只发一个 translation prefetch，后续再扩展 degree、距离、过滤和动态节流。

## 12. 必须输出的统计

严格输出以下 STLB-prefetch指标：

```text
requested
issued
pq_drop_rate

prefetch_lookups
prefetch_hit
prefetch_miss
prefetch_mshr_merge
prefetch_fill
prefetch_miss_rate
prefetch_mpki

prefetch_useful
prefetch_useless
prefetch_late

prefetch_too_early
prefetch_too_early_among_fill
prefetch_too_early_among_useless

prefetch_pollution_evict
prefetch_pollution_demand
prefetch_pollution_among_prefetch_fill

prefetch_accuracy
prefetch_coverage
timely_coverage
timely_accuracy
fill_accuracy
```

### 12.1 基础事件定义

```text
requested：predictor请求产生一个translation prefetch候选。

issued：候选成功进入STLB internal_PQ。

prefetch_lookups：STLB-prefetch请求真正执行STLB tag lookup。

prefetch_hit：STLB-prefetch lookup命中STLB。

prefetch_miss：STLB-prefetch lookup未命中STLB。

prefetch_mshr_merge：STLB-prefetch miss与已有STLB MSHR合并。

prefetch_fill：由STLB prefetch最初发起的translation最终fill STLB。

prefetch_useful：真实demand首次使用一个尚未使用的STLB-prefetched translation。

prefetch_late：真实demand在STLB-prefetch translation完成前merge；late是useful的子集。

prefetch_useless：STLB-prefetched translation在真实demand使用前被实际驱逐。ROI结束时仍驻留在STLB或仍处于PQ、tag-check、translation stash、MSHR中的请求属于观测窗口右删失，不强制归类为useless；该语义与普通cache prefetcher一致。
```

### 12.2 派生公式

定义：

```text
timely = prefetch_useful - prefetch_late
```

所有除法必须 zero-safe，分母为 0 时输出 0。

```text
pq_drop_rate
  = (requested - issued) / requested

prefetch_miss_rate
  = prefetch_miss / prefetch_lookups

prefetch_mpki
  = prefetch_lookups * 1000 / ROI retired instructions

prefetch_too_early_among_fill
  = prefetch_too_early / prefetch_fill

prefetch_too_early_among_useless
  = prefetch_too_early / prefetch_useless

prefetch_pollution_among_prefetch_fill
  = prefetch_pollution_evict / prefetch_fill

prefetch_accuracy
  = prefetch_useful / issued

prefetch_coverage
  = prefetch_useful / (prefetch_useful + demand STLB misses)

timely_accuracy
  = timely / issued

timely_coverage
  = timely / (prefetch_useful + demand STLB misses)

fill_accuracy
  = (timely + prefetch_late) / prefetch_fill
```

在 `prefetch_useful = timely + prefetch_late` 不变量成立时：

```text
fill_accuracy = prefetch_useful / prefetch_fill
```

仍应按指定的 timely 加 late 语义实现和说明。

## 13. 实现阶段

### 阶段一：最小可运行且保持基线

1. 新增 `STLB_PREFETCH` origin。
2. 新增 `prefetch_translation()`。
3. 新增简单 PC-VPN stride模块。
4. STLB `internal_PQ` 配置为 16。
5. PTW input PQ配置为16。
6. PTW读取PQ，RQ优先，二者共享 `MAX_READ`。
7. 不改变当前 PTW RQ 的 MSHR准入行为。
8. 只由 `DEMAND_DATA` 训练。
9. 实现 requested、issued、PQ drop、lookup、hit、miss、MSHR merge和fill统计。
10. 完成 `no` 模式与旧 Permit-PGC 的 equivalence test。

### 阶段二：质量与归属统计

1. 增加独立 STLB-prefetch ID和 initiator provenance。
2. 实现 timely、late、useful、useless。
3. 复用并隔离 too-early shadow。
4. 复用并隔离 pollution shadow。
5. 输出全部指定的accuracy、coverage和fill accuracy。
6. 验证与 vBerti 同 VPN merge时的 first-initiator ownership。

### 阶段三：资源控制和扩展

在不改变第一版定义的前提下，可以单独实验：

```text
duplicate filter
STLB/PTW occupancy throttling
动态accuracy feedback
prefetch degree和distance
PQ aging/starvation protection
demand merge后的PTW PQ-to-RQ promotion
真正启用PTW MSHR_SIZE限制
多核/多ASID验证
```

这些增强特性必须作为独立开关或独立配置，不能静默改变 `STLB prefetcher=no` 的 Permit-PGC 基线。

## 14. 必须覆盖的测试矩阵

功能配置至少包括：

```text
No L1D prefetch + STLB no
vBerti Permit-PGC + STLB no
No L1D prefetch + STLB prefetch
vBerti Permit-PGC + STLB prefetch
vBerti Permit-PGC + CP-PB + STLB prefetch
```

定向单元/集成测试至少验证：

1. PTW RQ优先，PQ只使用剩余 `MAX_READ`。
2. RQ+PQ每周期合计不超过2。
3. `MAX_FILL=2` 对所有walk共享。
4. STLB internal_PQ满时requested增加、issued不增加。
5. PTW channel PQ满时请求保留并重试。
6. 相同 CPU+ASID+VPN优先merge，不重复启动walk。
7. 不同ASID的相同VPN不合并。
8. vBerti访问不训练STLB predictor。
9. STLB prefetch不递归训练自身。
10. demand merge到STLB prefetch时记useful和late。
11. vBerti merge到STLB prefetch时不记STLB useful/late。
12. vBerti与STLB prefetch的fill ownership遵循first initiator。
13. 两套too-early/pollution状态互不覆盖。
14. `STLB prefetcher=no` 时已有Permit-PGC指标与旧逻辑一致，新增指标全为0。

## 15. 最终确认的核心约束

```text
STLB demand/vBerti -> PTW RQ -> 高优先级
STLB prefetch      -> PTW PQ -> 低优先级

PTW PQ size = 16
STLB MSHR size = 16
PTW MAX_READ = 2，RQ/PQ共享
PTW MAX_FILL = 2，所有walk共享
PTW MSHR_SIZE=5当前不启用

STLB prefetcher=no必须保持Permit-PGC基线
STLB predictor只由DEMAND_DATA训练
vBerti与STLB prefetch使用独立origin、provenance和质量统计
同VPN合并遵循first-initiator ownership
第一版不做PTW PQ-to-RQ promotion
```
