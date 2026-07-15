你需要在当前提供的 ChampSim 个人开发版本中，实现一套“Demand Data Load TLB Pattern 采集与可视化分析”功能。

这不是一个简单增加统计计数器的任务。你需要实际阅读当前仓库中的指令、LSQ、地址翻译、L1 DTLB、STLB、命令行解析和构建代码，结合当前版本的真实数据流完成修改。不要假设当前仓库与 ChampSim 官方最新版本的文件结构或接口完全一致。

最终需要完成：

1. ChampSim 仿真器中的 demand-load TLB pattern 日志采集；
2. 一个默认关闭、显式开启的运行时开关；
3. 离线 Python 分析脚本；
4. 四组主要 pattern 图；
5. 正确性测试和 baseline 隔离验证；
6. 简洁、清楚的实现说明文档。

---

# 一、研究目标

本任务只观察：

> OoO core 实际交给数据侧 L1 DTLB 的 demand data load 请求流，在虚拟页 VPN 层面的访问 pattern。

分析对象不是：

* trace 文件中的原始 program-order 地址流；
* 指令 fetch；
* demand store；
* RFO；
* writeback；
* data prefetch；
* instruction prefetch；
* TLB prefetch；
* PTW 内部页表访问；
* PPN 或物理地址 pattern。

主分析序列是：

```text
VPN_0, VPN_1, VPN_2, ...
```

其中每一项代表一个动态 demand data load 实际向 L1 DTLB 发起的地址翻译访问。

研究需要回答：

1. 整个执行过程中访问了哪些虚拟地址 region；
2. 不同 region 在什么时间阶段活跃；
3. region 内部的 4 KB 页面访问是热点、顺序、固定 stride、周期、多流交织，还是不规则访问；
4. 全局页面切换的 `ΔVPN` 有什么特征；
5. 不同静态 load PC 的 VPN pattern 是否具有稳定的 page delta；
6. L1 DTLB hit、L1 DTLB miss + STLB hit、STLB miss 分别出现在什么 pattern 中。

本任务暂时不实现：

* vBerti candidate 记录；
* prefetch pattern；
* PPN 分析；
* VPN→PPN 映射；
* reuse-distance；
* entropy；
* shadow fully associative TLB；
* compulsory/capacity/conflict miss 分类；
* 自动 phase 聚类；
* rescue queue 或 oracle 实验。

不要擅自扩大任务范围。

---

# 二、最重要的事件语义

## 2.1 什么叫“一个 demand data load 事件”

一个事件必须满足：

1. 来源是数据侧 demand load；
2. 不是 store；
3. 不是预取；
4. 不是 instruction fetch；
5. 不是 PTW 内部访问；
6. 该动态 load 第一次成功交给 L1 DTLB 地址翻译输入路径。

这里的“成功交给”是指请求被 L1 DTLB 的输入 channel、queue 或等价接口正式接受。

如果因为输入队列已满而发生 retry：

* retry 失败时不能创建事件；
* 请求真正被接受时才创建事件；
* 同一个动态 load 只能创建一次事件。

如果后续在 TLB MSHR 中发生合并，该动态 load 仍然是一个 demand-load 事件，但需要记录 merge 状态。

## 2.2 主时间轴：`load_tlb_seq`

每个核心维护一个独立、单调递增的：

```text
load_tlb_seq
```

当一个符合条件的 demand load 第一次成功进入 L1 DTLB 请求路径时：

```text
load_tlb_seq++
```

它表示 L1 DTLB 实际面对 demand load 的顺序。

不要使用以下字段替代主时间轴：

* cycle；
* trace instruction order；
* retire order；
* LQ allocation order；
* translation completion order。

日志文件中的行可能按照翻译完成顺序写出，因此离线分析时必须按照：

```text
(cpu, load_tlb_seq)
```

重新排序。

## 2.3 ROI 边界

只记录正式 simulation ROI，不记录 warmup。

在 warmup 结束、simulation ROI 开始时：

* 不得清空正常 Cache、TLB、PTW 或 predictor 状态；
* 只重置 pattern logger；
* 每个核心的 `load_tlb_seq` 从 0 开始；
* 清理 logger 内部由 warmup 产生的 pending bookkeeping；
* warmup 中发起、ROI 中才完成的旧 translation 不应生成 demand-pattern 记录；
* ROI 中新发起但仿真结束时仍未完成的请求，要以 `INCOMPLETE` 状态写出，不能静默丢弃。

---

# 三、动态 load 的唯一身份

当前 ChampSim 中的 `instr_id` 应被理解为动态指令实例 ID，而 `ip` 或 `pc` 是静态指令地址。

同一个动态指令可能具有多个 source-memory operand，因此仅使用 `instr_id` 不足以唯一标识动态 load。

必须使用以下组合身份：

```text
(cpu, instr_id, LOAD, operand_index)
```

不要把这些字段进行算术相加。

建议在日志中分别保存：

```text
cpu
instr_id
operand_index
pc
```

其中：

* `cpu`：核心编号；
* `instr_id`：动态指令实例编号；
* `operand_index`：该动态指令 source-memory 向量中的 load operand 下标；
* `pc`：静态 load 指令地址。

如果当前 LQ、翻译 request 或 channel packet 中没有 `operand_index`，需要从创建 LQ entry 的位置开始增加并向后传播。

例如，原本如果是：

```cpp
for (auto address : instr.source_memory) {
    // create LQ entry
}
```

应改为具有明确下标的形式：

```cpp
for (std::size_t op_idx = 0; op_idx < instr.source_memory.size(); ++op_idx) {
    const auto address = instr.source_memory[op_idx];
    // create LQ entry and store op_idx
}
```

不要依赖地址反推出 operand index，因为同一动态指令的多个 operand 理论上可能访问相同地址。

需要检查当前仓库的实际指令和 LQ 数据结构，选择最小侵入式实现。

---

# 四、运行时开关与 baseline 隔离

增加以下命令行开关：

```text
--demand-tlb-pattern
```

默认没有该参数时：

```text
demand_tlb_pattern = false
```

行为必须与修改前的 ChampSim baseline 完全一致。

开启后：

```text
--demand-tlb-pattern
```

才执行日志采集。

同时增加可选输出目录参数：

```text
--demand-tlb-pattern-output <directory>
```

如果开启 pattern 功能但没有指定目录，默认输出到：

```text
demand_tlb_pattern/
```

可以增加一个只用于短测试的可选参数：

```text
--demand-tlb-pattern-max-events <N>
```

语义为：

* 每个核心最多记录 N 个 demand-load 事件；
* 达到 N 后只停止记录，不停止仿真；
* 默认值 0 表示不限制。

不要自动关闭或改变任何 prefetcher 配置。实验者会使用 no-data-prefetch 的 ChampSim 配置运行。本功能只负责识别并记录 demand data load。

开关关闭时必须满足：

* 不创建日志文件；
* 不创建输出目录；
* 不分配大型 logger 数据结构；
* 不改变任何请求字段的功能语义；
* 不改变 Cache/TLB/PTW 时序；
* 不改变 replacement；
* 不改变统计结果；
* 不改变最终 simulation cycle 和 IPC。

开关开启时，日志操作只消耗宿主机运行时间，不能增加 ChampSim 建模 cycle。

---

# 五、建议的代码组织

请先检查仓库结构，再决定真实文件名。推荐使用以下逻辑组织，但不要为了匹配名称而强行大范围重构。

新增类似：

```text
inc/demand_tlb_pattern.h
src/demand_tlb_pattern.cc
```

提供一个独立 logger，例如：

```cpp
class DemandTlbPatternLogger
```

主要职责：

1. 管理每个核心的 `load_tlb_seq`；
2. 创建 pending demand-load event；
3. 更新 L1 DTLB 结果；
4. 更新 STLB 结果；
5. 更新 merge 和 completion 信息；
6. 完成后缓冲写入 CSV；
7. ROI 结束时刷新 pending 和输出文件；
8. 在功能关闭时快速返回。

不要把大量 CSV 拼接逻辑直接写入 `ooo_cpu.cc` 或 `cache.cc`。

可能涉及的代码位置包括但不限于：

* 命令行参数解析；
* ChampSim 顶层初始化与结束处理；
* trace instruction 到 `ooo_model_instr` 的转换；
* LQ entry 创建；
* data load 地址翻译请求生成；
* channel/request/packet 元数据结构；
* L1 DTLB lookup hit/miss 处理；
* STLB lookup hit/miss 处理；
* MSHR merge 处理；
* translation response 返回；
* warmup/ROI phase 切换；
* CMake、Makefile 或项目构建文件。

必须基于当前仓库的真实调用链完成，不要仅修改表面代码。

---

# 六、日志事件生命周期

推荐实现为“一次 request 创建，一个 pending event，最终一行记录”。

## 6.1 创建事件

在 demand load 第一次成功进入 L1 DTLB 请求路径时：

1. 确认是 data demand load；
2. 检查该 LQ entry 或 memop 是否已经创建过 pattern event；
3. 分配当前核心的 `load_tlb_seq`；
4. 保存初始字段；
5. 将 pattern event ID 或组合 memop key 附加到 translation request；
6. 加入 logger pending map。

需要防止以下情况造成重复记录：

* 输入队列 full 后重复 retry；
* load replay；
* 相同请求被重新构造；
* channel insert 重试；
* MSHR merge 后 callback 重复。

建议在 LQ entry 或等价动态 load 状态中增加：

```text
pattern_event_created
pattern_load_tlb_seq
```

或等价字段。

## 6.2 L1 DTLB 结果

在 L1 DTLB 的权威 hit/miss 判断位置更新：

```text
l1dtlb_result = HIT / MISS
```

如果命中：

```text
stlb_accessed = false
stlb_result = NOT_ACCESSED
```

如果 L1 DTLB miss 并向 STLB 发起请求：

```text
stlb_accessed = true
```

如果 L1 DTLB miss 后直接合并到已存在的 translation/MSHR，且没有产生独立 STLB lookup：

```text
l1dtlb_merged = true
stlb_accessed = false
stlb_result = NOT_ACCESSED
```

不要把“没有访问 STLB”伪造成 STLB hit 或 STLB miss。

## 6.3 STLB 结果

只有真正进入 STLB lookup 的请求才填写：

```text
stlb_result = HIT / MISS
```

如果 STLB tag miss 后与已有 MSHR 合并：

```text
stlb_result = MISS
stlb_merged = true
```

如果当前 ChampSim 的 merge 层次与上述描述不同，应遵循仓库真实语义，但必须在说明文档中解释。

## 6.4 完成事件

当 translation 返回原始 demand load，或者已经获得足够完整的路径结果时，写出该 event。

日志文件中的物理行顺序不需要等于 `load_tlb_seq`，但每行必须保留 `load_tlb_seq`，分析脚本按它重新排序。

为减少宿主机开销：

* 不得每写一行就 `flush()`；
* 使用较大的 `ofstream` buffer 或批量字符串缓冲；
* 在正常结束、异常可控结束和析构时可靠刷新；
* 不引入仓库当前没有的强制外部压缩库依赖。

---

# 七、日志文件和字段

每个核心输出一个文件：

```text
<output_dir>/demand_tlb_pattern_core_<cpu>.csv
```

另外输出：

```text
<output_dir>/metadata.json
<output_dir>/logger_summary.txt
```

## 7.1 CSV 必须包含以下字段

```text
cpu
load_tlb_seq
instr_id
operand_index
pc
dtlb_lookup_cycle
translation_complete_cycle
va
vpn
virtual_region_2m
page_offset_in_region
l1dtlb_result
l1dtlb_merged
stlb_accessed
stlb_result
stlb_merged
completion_state
```

建议枚举使用稳定的文本或整数编码，并在文档中明确。

推荐语义：

```text
l1dtlb_result:
    HIT
    MISS
    UNKNOWN

stlb_result:
    HIT
    MISS
    NOT_ACCESSED
    UNKNOWN

completion_state:
    COMPLETE
    INCOMPLETE
```

所有地址和 ID 在 CSV 中建议输出为无符号十进制整数，分析脚本负责将 PC 和地址格式化为十六进制。这样更方便 Pandas/Polars 读取和运算。

## 7.2 地址计算

不要无条件硬编码 4 KB shift。

从当前 ChampSim 配置或编译期页面大小获得：

```text
page_size
```

计算：

```text
vpn = va / page_size
```

宏观 virtual region 固定使用 2 MiB：

```text
region_size = 2 * 1024 * 1024
virtual_region_2m = va / region_size
page_offset_in_region = (va % region_size) / page_size
```

当前主要实验假定：

```text
page_size = 4096 bytes
```

因此一个 2 MiB region 中有 512 个 4 KB page。

如果页面大小不能整除 2 MiB，必须报错或明确警告，不能静默生成错误数据。

## 7.3 metadata.json

至少记录：

```text
page_size
region_size
num_cores
warmup_instructions
simulation_instructions
trace path or trace name
configuration/executable name
pattern switch enabled
max_events
CSV column definitions
```

如果仓库能够方便获得，还可以记录 git commit hash，但不是强制要求。

## 7.4 logger_summary.txt

至少输出每个核心：

```text
created_events
completed_events
incomplete_events
l1dtlb_hits
l1dtlb_misses
l1dtlb_merges
stlb_accesses
stlb_hits
stlb_misses
stlb_merges
```

该文件主要用于日志正确性验收，不作为论文统计结果。

---

# 八、离线分析脚本

新增：

```text
tools/analyze_demand_tlb_pattern.py
```

建议使用：

* Python 3；
* Pandas 或 Polars；
* NumPy；
* Matplotlib。

不要要求交互式 notebook 才能运行。脚本必须可以从命令行独立执行。

基本命令形式：

```bash
python tools/analyze_demand_tlb_pattern.py \
    --input demand_tlb_pattern/demand_tlb_pattern_core_0.csv \
    --metadata demand_tlb_pattern/metadata.json \
    --output-dir demand_tlb_pattern/figures
```

支持以下参数：

```text
--coarse-bin-size <N>
    默认 50000，表示宏观 heatmap 每个时间 bin 包含多少个 load_tlb_seq

--region-id <R>
    指定局部图观察的 2 MiB virtual region，支持十进制或 0x 十六进制

--seq-start <N>
--seq-end <N>
    指定局部图的 load_tlb_seq 范围

--top-pcs <N>
    默认 32

--pc-rank-by <stlb_miss|stlb_access|load_count>
    默认 stlb_miss

--delta-limit <N>
    默认 16
```

如果没有提供 `region-id` 和序列范围：

1. 首先选择 STLB miss 数最多的 `(region, coarse_time_bin)`；
2. 如果整个日志没有 STLB miss，则选择 demand load 数最多的 cell；
3. 将自动选择结果打印到终端并写入 summary。

分析脚本必须先：

```text
sort_values(["cpu", "load_tlb_seq"])
```

不能假设 CSV 行顺序就是 lookup 顺序。

---

# 九、分析一：宏观 Virtual Region-Time Heatmap

生成：

```text
01_virtual_region_time_heatmap.pdf
01_virtual_region_time_heatmap.png
```

主图：

```text
2 MiB Virtual Region × load_tlb_seq time bin
```

定义：

```text
time_bin = load_tlb_seq // coarse_bin_size
```

每个 cell 的值：

```text
该时间 bin 中访问该 virtual region 的 demand load 数
```

颜色建议使用：

```text
log1p(access_count)
```

避免高频热点遮蔽低频 region。

Y 轴按真实 virtual region 数值顺序排列。

可以只显示真正被访问过的 region，但：

* Y 轴标签必须显示真实 region ID；
* 不得把 region 排名伪装成连续地址；
* 图注需要说明只显示 active regions。

在主 heatmap 下方使用共享 X 轴增加两个窄曲线或柱状图：

```text
每个 time bin 的 L1 DTLB miss 数
每个 time bin 的 STLB miss 数
```

STLB miss 只统计真正访问 STLB 且 `stlb_result=MISS` 的事件。

该图回答：

* 哪些虚拟地址 region 在什么时候活跃；
* 是否存在 footprint 迁移；
* 哪些阶段 TLB miss 较集中。

---

# 十、分析二：局部 Page-Offset Raster

生成：

```text
02_local_page_offset_raster.pdf
02_local_page_offset_raster.png
```

选定：

```text
virtual_region_2m = R
load_tlb_seq ∈ [seq_start, seq_end)
```

Y 轴使用：

```text
page_offset_in_region
```

对于 4 KB 页面，范围为 0～511。

X 轴使用：

```text
load_tlb_seq
```

每一个动态 demand load 画一个点。

统一使用以下视觉语义：

```text
浅灰小圆点：
    L1 DTLB hit

橙色圆点：
    L1 DTLB miss、真正访问 STLB、STLB hit

红色圆点：
    真正访问 STLB、STLB miss

紫色空心点或单独 marker：
    L1 DTLB miss，但在进入独立 STLB lookup 前发生 translation merge
```

不得把 merge 请求错误归入 STLB hit/miss。

图中增加一个简洁指标框，至少显示：

```text
selected region
load_tlb_seq range
total demand loads
unique VPNs
L1 DTLB misses
STLB accesses
STLB misses
```

局部窗口不要默认跨越整条长 trace。自动选择时使用一个 coarse bin，以保证 raster 可读。

该图用于观察：

* 水平带：热点页；
* 斜线：顺序 page stream 或固定 stride；
* 多条斜线：多个 page stream 交织；
* 周期条带：固定页面集合反复切换；
* 散点云：不规则页面访问；
* TLB miss 出现在 pattern 的什么位置。

---

# 十一、分析三：Global Page-Transition Pattern

生成：

```text
03_global_page_delta.pdf
03_global_page_delta.png
03_global_page_delta_summary.csv
```

首先按 `load_tlb_seq` 排序。

原始 VPN 流例如：

```text
A, A, A, B, B, C, C, A
```

构造连续相同 VPN 去重后的 page-transition stream：

```text
A, B, C, A
```

仅对该压缩流计算：

```text
delta_vpn = current_vpn - previous_vpn
```

因此 global transition delta 通常不包含 0。

主图显示：

```text
<-delta_limit
-delta_limit ... -1
+1 ... +delta_limit
>+delta_limit
```

Y 轴可以使用次数或比例，优先使用比例。

必须同时输出：

```text
total raw demand loads
total page transitions
same-page continuation ratio
P(|ΔVPN| = 1)
P(|ΔVPN| <= 4)
P(|ΔVPN| <= 16)
P(|ΔVPN| > 16)
```

其中：

```text
same-page continuation ratio
=
相邻 raw demand loads 中 VPN 相同的次数
/
全部相邻 raw demand load pair 数
```

不要把 raw stream 与 compressed transition stream 的定义混在一起。

---

# 十二、分析四：Per-PC VPN Pattern

生成：

```text
04_per_pc_delta_heatmap.pdf
04_per_pc_delta_heatmap.png
04_per_pc_topk.csv
```

## 12.1 PC 流定义

对于每个静态 load PC：

1. 从全局事件中筛选 `pc == target_pc`；
2. 按 `load_tlb_seq` 排序；
3. 对该 PC 相邻动态实例计算：

```text
delta_vpn_pc = vpn[i] - vpn[i - 1]
```

这里不能使用 global page-transition stream。

Per-PC delta 必须保留 0，因为同一个 load PC 的相邻实例可能访问相同 VPN。

## 12.2 PC 选择

默认选择：

```text
Top-32 PCs by STLB miss count
```

如果某个 PC 的动态实例少于合理最小值，例如 32 次，则不进入 heatmap，避免极少量样本产生误导。

命令行参数允许按：

```text
stlb_miss
stlb_access
load_count
```

排序。

## 12.3 Heatmap

* Y 轴：Top PCs；
* X 轴：

```text
<-delta_limit
-delta_limit ... 0 ... +delta_limit
>+delta_limit
```

* 每一行独立归一化为 100%；
* 颜色表示该 PC 的 delta 分布比例；
* Y 轴 PC 标签使用十六进制；
* PC 顺序与 `04_per_pc_topk.csv` 一致。

## 12.4 Top-k coverage

对每个 PC 计算：

```text
Top-1 coverage
Top-2 coverage
```

定义：

```text
TopKCoverage(PC)
=
该 PC 出现次数最多的 K 个 ΔVPN 的次数
/
该 PC 全部有效 ΔVPN 次数
```

输出 CSV 至少包含：

```text
pc
load_count
unique_vpn_count
l1dtlb_miss_count
stlb_access_count
stlb_miss_count
top1_delta
top1_coverage
top2_deltas
top2_coverage
```

同时计算 workload-level weighted coverage：

```text
WeightedTopK
=
sum(valid_delta_count_pc * TopKCoverage(pc))
/
sum(valid_delta_count_pc)
```

需要在分析 summary 中输出：

```text
Global Top-1/Top-2 transition-delta coverage
Weighted per-PC Top-1/Top-2 delta coverage
```

注意：

* global coverage 基于 compressed page-transition stream；
* per-PC coverage 基于每个 PC 的原始动态实例流；
* 两者定义不同，必须在文档中说明，不能直接伪装成完全同口径指标。

---

# 十三、统一图形规范

所有图保持一致的视觉语义：

```text
L1 DTLB hit：浅灰
L1 DTLB miss + STLB hit：橙色
STLB miss：红色
translation merge：紫色空心 marker
选中区域：蓝色边框或标记
```

要求：

* 使用 Matplotlib；
* 输出 PDF 矢量图；
* 同时输出至少 300 DPI PNG；
* 不使用 notebook 截图；
* 标题、坐标轴、图例完整；
* 默认字体大小适合论文或组会 PPT；
* 图标题尽量包含实际结论信息或清楚的图义；
* 不使用过度复杂的颜色或装饰；
* 大图采用 `tight_layout` 或等价布局；
* 对数颜色必须明确标注；
* 地址和 PC 在图中使用十六进制显示；
* 分析计算中仍使用整数，不要用字符串地址参与排序。

---

# 十四、分析结果 summary

脚本需要生成：

```text
analysis_summary.txt
```

至少包含：

```text
total completed demand-load events
incomplete events
unique VPNs
unique 2 MiB virtual regions
L1 DTLB hit count/rate
L1 DTLB miss count/rate
STLB access count
STLB hit count/rate
STLB miss count/rate
translation merge count
same-page continuation ratio
page-transition count
P(|ΔVPN| = 1)
P(|ΔVPN| <= 4)
P(|ΔVPN| <= 16)
P(|ΔVPN| > 16)
global Top-1/Top-2 delta coverage
weighted per-PC Top-1/Top-2 coverage
auto-selected region and sequence interval
```

---

# 十五、正确性和测试要求

必须实际完成编译和测试，不能只写代码不运行。

## 15.1 Baseline 隔离测试

使用同一个短 trace 和同一个配置运行：

```text
A. 修改后的 binary，不带 --demand-tlb-pattern
B. 修改后的 binary，带 --demand-tlb-pattern
```

验证除日志文件和宿主机运行时间外：

* simulation instructions 完全一致；
* simulation cycle 完全一致；
* IPC 完全一致；
* L1D、L2C、LLC statistics 完全一致；
* L1 DTLB、STLB、PTW statistics 完全一致；
* DRAM statistics 完全一致。

开启 logger 不能改变建模结果。

不带开关时必须确认：

* 不创建 pattern 输出目录；
* 不创建 CSV；
* 不打印 logger summary。

## 15.2 日志结构测试

在短仿真中检查：

1. 每个核心 `load_tlb_seq` 唯一；
2. `load_tlb_seq` 从 0 开始连续递增；
3. `(cpu, instr_id, operand_index)` 对 demand load 唯一；
4. `vpn == va / page_size`；
5. `virtual_region_2m == va / 2MiB`；
6. `page_offset_in_region == (va % 2MiB) / page_size`；
7. `l1dtlb_result == HIT` 时，`stlb_accessed == false`；
8. `stlb_accessed == true` 时，`l1dtlb_result == MISS`；
9. `stlb_result != NOT_ACCESSED` 时，`stlb_accessed == true`；
10. CSV 记录数等于 logger summary 中 completed + incomplete 事件数；
11. 不存在 retry 导致的重复 event。

如果当前 ChampSim 内部语义使某条 invariant 不成立，必须给出准确原因并修改字段语义或测试，不能忽略。

## 15.3 离线算法自测

为 Python 脚本增加一个小型 synthetic CSV 测试。

例如全局 VPN 流：

```text
10, 10, 11, 11, 15, 14
```

应得到：

```text
compressed transition stream:
10, 11, 15, 14

global deltas:
+1, +4, -1
```

某个 PC 的 VPN 流：

```text
20, 20, 21, 21, 25
```

应得到 per-PC deltas：

```text
0, +1, 0, +4
```

该测试必须证明：

* global delta 使用连续 VPN 去重；
* per-PC delta 不做这种全局压缩；
* per-PC delta 保留 0；
* Top-1/Top-2 coverage 计算正确。

## 15.4 Smoke test

至少完成一次短仿真，例如：

```text
较短 warmup
较短 simulation instructions
单核 trace
无 data prefetcher 配置
```

然后运行分析脚本，确认生成：

```text
01_virtual_region_time_heatmap.pdf/png
02_local_page_offset_raster.pdf/png
03_global_page_delta.pdf/png
03_global_page_delta_summary.csv
04_per_pc_delta_heatmap.pdf/png
04_per_pc_topk.csv
analysis_summary.txt
```

需要人工检查图片不是空图、坐标轴正常、颜色语义正确。

---

# 十六、性能与数据量注意事项

完整 ROI 可能包含大量 demand load，CSV 可能较大。

必须做到：

* 不在每条记录后 flush；
* 不将整个 ROI 的所有事件永久保存在 C++ 内存中；
* pending map 只保存尚未完成的 translation；
* 已完成事件及时进行缓冲写出；
* Python 脚本读取大文件时避免不必要的字符串列；
* 必要时明确指定 Pandas/Polars dtype；
* 图形聚合优先使用 groupby，而不是逐事件 Python 循环；
* 局部 raster 只画选定窗口，不默认画完整 trace 的全部点。

不得为了减少日志量而默认抽样或丢弃普通 L1 DTLB hit。完整 demand load stream 是本实验的重要组成部分。

---

# 十七、最终交付物

完成后提供：

## 17.1 修改后的源码

包括：

* simulator logging；
* CLI 开关；
* logger 生命周期；
* 构建文件修改；
* Python 分析脚本。

## 17.2 实现说明

新增：

```text
docs/demand_tlb_pattern_analysis.md
```

必须说明：

1. 研究目标；
2. 事件定义；
3. `load_tlb_seq` 定义；
4. 动态 load 唯一身份；
5. 日志字段；
6. L1 DTLB/STLB/merge 分类语义；
7. warmup/ROI 边界；
8. 命令行使用方法；
9. Python 脚本参数；
10. 四类图的含义；
11. 已执行的测试；
12. 当前实现限制。

## 17.3 最终修改总结

任务完成时清楚列出：

```text
修改了哪些文件
每个文件修改了什么
为什么选择这些 hook point
如何运行带开关的 binary
如何运行分析脚本
测试结果是什么
是否存在未解决问题
```

不要只给 diff。必须解释完整数据流：

```text
dynamic load
→ LQ
→ L1 DTLB request
→ pattern event creation
→ L1 DTLB result
→ STLB result/merge
→ translation completion
→ CSV
→ Python figures
```

---

# 十八、严格禁止事项

1. 不要把静态 PC 当成动态指令 ID；
2. 不要把 operand index 当成动态实例 ID；
3. 不要用 `instr_id + operand_index` 的算术和作为 UID；
4. 不要在请求 retry 时重复分配 `load_tlb_seq`；
5. 不要在 LQ allocation 时直接把它当作实际 DTLB lookup；
6. 不要使用 completion order 作为 pattern 时间轴；
7. 不要把 data prefetch 请求记录为 demand load；
8. 不要把 store 记录为 demand load；
9. 不要把 instruction-side TLB 请求混入日志；
10. 不要把 PTW 页表访问混入 demand VPN stream；
11. 不要将 merge 伪装为 STLB hit 或 STLB miss；
12. 不要在关闭开关时改变 baseline 行为；
13. 不要硬编码只适用于某一个绝对文件路径；
14. 不要依赖 notebook 手工执行；
15. 不要只写统计计数器而不输出逐事件日志；
16. 不要擅自加入 PPN、vBerti、reuse distance 等当前范围外功能。

---

# 十九、验收标准

只有满足以下条件，任务才算完成：

* `--demand-tlb-pattern` 默认关闭；
* 关闭时 baseline 行为和统计完全不变；
* 开启时能够记录实际 L1 DTLB-facing demand data load；
* 每个动态 load 只有一条事件；
* `load_tlb_seq` 正确反映实际 L1 DTLB 请求顺序；
* 能够区分 L1 hit、STLB hit、STLB miss 和 merge；
* 只记录 ROI；
* 日志字段完整；
* Python 脚本能够自动运行；
* 四组核心图全部成功生成；
* global delta 和 per-PC delta 定义正确且不混淆；
* 完成 smoke test、baseline equivalence test 和 synthetic test；
* 提供实现文档和测试结果；
* 没有未说明的行为改变。
