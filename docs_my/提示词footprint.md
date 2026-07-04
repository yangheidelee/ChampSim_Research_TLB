我正在基于 ChampSim DPC-4 版本的修改版本做 CPU 微架构实验。现在需要实现一个 L1D virtual-page access pattern characterization 功能，用来分析程序在 L1D demand data access 流上的虚拟页访问轨迹。

任务目标：
在 ChampSim 中全量 dump ROI 阶段每一次 L1D demand data access 的虚拟页信息，然后提供一个 Python 后处理脚本，画出四张图：
1. Raw VPN trajectory
2. First-touch VPN ID trajectory
3. Adjacent raw-VPN delta sequence
4. Windowed VPN-delta predictability / coverage

请你直接检查当前 ChampSim 工程结构的源码，找到正确插桩点并实现。要求保持对 ChampSim 主体代码的侵入最小，不改变原始champsim的功能，能够通过环境变量打开/关闭 dump 功能，默认关闭，不影响普通仿真。

========================
一、背景和实验定义
========================

我要分析的是 L1D 侧的程序 data demand access 的 VPN pattern。

每次 L1D demand data access 定义为：
- 程序真实 load / store / RFO 等 demand data request 到达 L1D 的事件；
- 不包括 L1D prefetch request；
- 不包括 page-table walk / PTE translation access；
- 不包括 instruction fetch；
- 不包括 L1D fill 事件，因为 fill 只能看到 miss，不能看到 hit；
- 需要尽量在 L1D 处理 demand request 的入口处记录，这样能包含 L1D hit 和 miss。

最关键的是：必须使用 virtual address 计算 VPN，而不是 physical address。
定义如下：
- raw VPN = virtual_address >> LOG2_PAGE_SIZE
- page offset = (virtual_address >> LOG2_BLOCK_SIZE) & ((1 << (LOG2_PAGE_SIZE - LOG2_BLOCK_SIZE)) - 1)
在 4KB page + 64B cache line 下，page offset 是 0~63。

请不要把 PPN 当成 VPN。不要从 physical address 计算页号。

========================
二、需要 dump 的 CSV
========================

请新增一个全量 dump 文件，默认关闭，通过环境变量开启。

推荐环境变量：
- DUMP_L1D_VPN=1 开启功能
- DUMP_L1D_VPN_FILE=/path/to/l1d_vpn_trace.csv 指定输出文件
如果没有指定文件名，默认输出到当前目录：l1d_vpn_trace.csv

CSV header 至少包含以下字段：

access_id,cycle,ip,vaddr,vpn,offset,type

字段含义：
- access_id：ROI 阶段第几次 L1D demand data access，从 0 开始递增
- cycle：当前 core cycle
- ip：触发该 data access 的 instruction PC / IP
- vaddr：该 data access 的 virtual address
- vpn：vaddr >> LOG2_PAGE_SIZE
- offset：page 内 cache-line offset
- type：访问类型，例如 LOAD / RFO / WRITE，使用 ChampSim 里已有 access type 的数值或字符串均可，但要保持 CSV 可解析

如果当前插桩点拿不到 vaddr 或 ip，请继续向上游 packet/request 结构查找，不要退而求其次使用 paddr。这个实验必须基于 virtual address。

如果很容易拿到额外字段，可以额外加入：
- cpu
- instr_id
- l1d_hit
- is_prefetch
但这些不是强制要求。强制要求是上面 7 个基本字段。

========================
三、ROI 要求
========================

请只 dump ROI / simulation phase 的访问，不要 dump warmup 阶段。

原因：
first-touch VPN ID 后处理时需要从 ROI 开始编号。如果 warmup 也 dump，会污染 ROI 的 first-touch 顺序。

请检查当前 DPC-4 ChampSim 中如何判断 warmup 是否结束，尽量使用已有的 warmup/ROI 状态变量。如果当前代码结构不容易判断，也请说明你使用的 gate 条件，并保证 CSV 中 access_id 从 ROI 第一条 L1D demand data access 开始。

========================
四、插桩点要求
========================

请在 L1D demand request 被处理时记录，而不是 fill 时记录。

伪代码语义如下：

if this cache is L1D:
    if request is demand data access:
        if request is not prefetch and not translation/page-walk:
            vaddr = request.virtual_address
            dump_l1d_vpn_access(cycle, ip, vaddr, type)

需要你根据当前 ChampSim DPC-4 的真实代码确定：
- 哪个类 / 文件处理 cache request；
- 如何判断当前 cache 是 L1D；
- packet/request 中 virtual address 字段叫什么；
- packet/request 中 ip 字段叫什么；
- 如何判断 prefetch request；
- 如何排除 page walk / translation request；
- 如何判断 ROI。

请不要只凭猜测修改。如果字段名不确定，请在代码中搜索 packet 结构、access_type、v_address、virtual_address、ip、pf_origin 等相关字段。

========================
五、实现方式建议
========================

建议新增一个小的 tracker / dumper 模块，避免把大量逻辑散落在 cache.cc 里。例如可以新增：
- src/vpn_pattern_tracker.h
- src/vpn_pattern_tracker.cc

也可以如果工程结构不方便，先在 cache.cc 里实现一个局部 static dumper，但要保证代码清晰。

功能要求：
1. 使用 std::ofstream 输出 CSV。
2. 默认关闭，只有 DUMP_L1D_VPN=1 时才打开。
3. 首次打开文件时写 header。
4. 每条 L1D demand data access 写一行。
5. access_id 从 0 开始递增。
6. 输出要尽量 buffered，不要每行 flush，否则会严重拖慢模拟。
7. 仿真结束时正常 close 文件。
8. 多核如果暂时不考虑，可以先支持单核；但代码不要写死崩溃。至少可以输出 cpu 字段，或者在单核实验中正常工作。

可以参考这种函数接口：

void dump_l1d_vpn_access(uint64_t cycle,
                         uint64_t ip,
                         uint64_t vaddr,
                         uint64_t type);

内部计算：
uint64_t vpn = vaddr >> LOG2_PAGE_SIZE;
uint64_t offset = (vaddr >> LOG2_BLOCK_SIZE) &
                  ((1ULL << (LOG2_PAGE_SIZE - LOG2_BLOCK_SIZE)) - 1);

========================
六、Python 后处理脚本
========================

请新增一个 Python 脚本，例如：
scripts/plot_l1d_vpn_patterns.py

使用方式示例：
python3 scripts/plot_l1d_vpn_patterns.py \
    --input l1d_vpn_trace.csv \
    --outdir vpn_figs \
    --window 100000 \
    --delta-clip 32

脚本功能：
读取 CSV，使用全量数据，不采样，生成四张图和一个 windowed stats CSV。

图 1：Raw VPN trajectory
- x-axis = access_id
- y-axis = raw VPN
- 文件名：fig_a_raw_vpn_trajectory.png
- 目的：展示原始虚拟地址空间中的 VPN 访问位置。这个图可能很稀疏、很难看清局部 pattern，但它是 raw VPN 的真实展示，用作对比。

图 2：First-touch VPN ID trajectory
- 对每个 raw VPN 按首次出现顺序重编号：
  if vpn not seen before:
      vpn_to_ftid[vpn] = next_id++
- x-axis = access_id
- y-axis = first-touch VPN ID
- 文件名：fig_b_first_touch_vpn_id_trajectory.png
- 注意：first-touch ID 只用于展示 page discovery / reuse / phase behavior，不保留真实 VPN 空间距离。

图 3：Adjacent raw-VPN delta sequence
- delta_t = raw_vpn_t - raw_vpn_{t-1}
- 必须用 raw VPN 计算 delta，不要用 first-touch ID。
- x-axis = access_id
- y-axis = clipped delta
- clipping 参数由 --delta-clip 控制，例如默认 32：
  clipped_delta = max(-32, min(32, delta))
- 加一条 y=0 的参考线。
- 文件名：fig_c_adjacent_raw_vpn_delta_sequence.png
- 图注里说明：for readability, VPN deltas are clipped to [-clip, +clip].

图 4：Windowed VPN-delta predictability / coverage
- 按 access_id 分 window，例如每 100000 次 L1D demand access 一个 window。
- 每个窗口内基于 raw VPN delta 统计：
  same-page ratio: delta == 0
  +1 ratio: delta == +1
  -1 ratio: delta == -1
  small-delta ratio: |delta| <= 4
  medium-delta ratio: 4 < |delta| <= 16
  large-jump ratio: |delta| > 16
  top-1 delta coverage
  top-2 delta coverage
  top-4 delta coverage
  entropy of delta distribution
  unique_vpn count
- 输出一个 CSV：
  vpn_delta_window_stats.csv
- 图可以优先画：
  top1/top2/top4 coverage 随 window_id 变化的曲线
- 文件名：fig_d_windowed_vpn_delta_coverage.png
- 如果时间允许，也可以额外画 stacked ratio 图：
  same / +1 / -1 / small / medium / large
  文件名：fig_d2_windowed_vpn_delta_breakdown.png

Python 脚本要求：
1. 使用 pandas + matplotlib。
2. 能处理较大的 CSV。读取时尽量指定 dtype。
3. 不要使用 seaborn。
4. 输出 PNG，dpi=300。
5. 如果数据点非常多，scatter 可以设置 s 很小，并使用 rasterized=True。
6. 如果 scatter 太慢，可以使用 matplotlib hist2d / hexbin 做 density plot，但必须使用全量数据参与统计，不能采样。
7. 脚本运行结束打印：
   total accesses
   unique VPNs
   output directory
   window size
   delta clip

========================
七、四张图的解释逻辑
========================

请在 Python 脚本或 README 中简要写明四张图各自作用：

(a) Raw VPN trajectory:
展示原始虚拟地址空间中的 VPN 访问位置。它保留真实 VPN，但可能受地址空间布局、segment gap、ASLR/randomization 影响，局部 pattern 不容易看清。

(b) First-touch VPN ID trajectory:
把每个 VPN 按首次出现顺序重编号，去掉绝对虚拟地址基址的视觉干扰，用于观察 page discovery、page reuse、working-set evolution 和 phase behavior。

(c) Adjacent raw-VPN delta sequence:
展示相邻 L1D demand access 之间的真实 VPN 跳转。该图保留真实空间关系，能直观看到 delta=0、+1、-1、小跳转、大跳转、周期性跳转等局部行为。

(d) Windowed VPN-delta coverage:
定量说明 VPN transition 是否具有稳定 pattern。top-k coverage 越高，说明少数 VPN delta 能覆盖更多相邻访问转移；entropy 越低，说明 delta 分布越集中。

========================
八、验证要求
========================

实现完成后，请做以下检查：

1. 工程能够正常编译。
2. 默认不设置 DUMP_L1D_VPN 时，仿真不生成 CSV，行为和原来一致。
3. 设置 DUMP_L1D_VPN=1 后，ROI 内生成 CSV。
4. CSV header 正确。
5. access_id 从 0 开始递增。
6. vpn 字段等于 vaddr >> LOG2_PAGE_SIZE。
7. offset 字段在 4KB page / 64B line 下应为 0~63。
8. CSV 不包含 warmup 阶段访问。
9. CSV 不包含明显的 prefetch request 或 PTW/PTE translation access。
10. Python 脚本能从 CSV 生成四张图和 windowed stats CSV。

请先用短仿真验证，例如：
1M warmup + 5M ROI
确认 CSV 和图都正常；
然后再跑正式：
20M warmup + 50M ROI。

========================
九、运行示例
========================

仿真示例：

DUMP_L1D_VPN=1 \
DUMP_L1D_VPN_FILE=./l1d_vpn_trace.csv \
./bin/<your_binary> \
  --warmup_instructions 1000000 \
  --simulation_instructions 5000000 \
  -traces <your_trace>.champsimtrace.xz

后处理示例：

python3 scripts/plot_l1d_vpn_patterns.py \
  --input ./l1d_vpn_trace.csv \
  --outdir ./vpn_figs \
  --window 100000 \
  --delta-clip 32

========================
十、最终交付内容
========================

请交付：
1. 修改过的 ChampSim 源码。
2. 新增的 VPN dump 模块或相关函数。
3. 新增 Python 后处理脚本 scripts/plot_l1d_vpn_patterns.py。
4. 简短 README 或注释，说明如何开启 dump、如何画图、每张图是什么意思。
5. 如果某些字段名或 ROI 判断在当前 DPC-4 代码中有特殊处理，请明确说明你用了哪个变量/函数作为依据。

重要提醒：
- 这个任务不是实现新的 prefetcher。
- 这个任务是做 L1D demand virtual-page access pattern characterization。
- 核心要求是 full dump 单 trace ROI 内 L1D demand VPN stream，并离线画四张图。
- 必须使用 virtual address，不要使用 physical address。
- 必须排除 prefetch 和 page-walk/PTE translation access。
- 必须只记录 ROI，避免 warmup 污染 first-touch ID。