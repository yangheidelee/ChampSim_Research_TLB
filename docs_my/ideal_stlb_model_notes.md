# Ideal STLB IPC Upper-Bound 建模笔记

本文单独说明本仓库中 ideal STLB 实验的架构建模方式。对应工程路径：

```text
/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound
```

相关源码和脚本主要包括：

- `inc/stlb_ideal.h`
- `src/stlb_ideal.cc`
- `src/main.cc`
- `src/cache.cc`
- `inc/cache.h`
- `inc/cache_builder.h`
- `config/instantiation_file.py`
- `launch_sim/1core-spec17_gap-idealTLB-select-trace-compare`

## 1. 实验目标

这个实验想回答的问题是：

```text
如果 STLB 能把某些来源的 STLB miss 完全解决掉，
那么 IPC 相对 baseline 的收益上限是多少？
```

这里的 baseline 是：

```text
launch_sim/1core-spec17_gap-idealTLB-select-trace-compare/pref-workload-sweep
```

也就是原始 prefetch 配置，不开启 ideal STLB。

三种 ideal STLB 设计分别是：

1. `ideal-demand-workload-sweep`
   - STLB 解决 Demand Data 和 Demand Instruction 引发的 STLB miss。

2. `ideal-l1pref-workload-sweep`
   - STLB 解决 L1D Prefetch 和 L1I Prefetch 引发的 STLB miss。

3. `ideal-all-workload-sweep`
   - STLB 解决所有来源的 STLB miss。

## 2. ideal STLB hit 的定义

本实验中的 ideal hit 不是“PTW 更快”，也不是“STLB miss penalty 变小”，而是：

```text
在 STLB tag lookup 真实 miss 后，
如果该 miss 来源属于当前 ideal mode，
则把这次访问建模成 STLB 直接命中。
```

因此 ideal hit 的语义是：

- 不计 STLB miss。
- 不分配 STLB MSHR。
- 不访问 PTW。
- 不访问 PSC。
- 不发起 PTE memory access。
- 不访问 L1D/L2C/LLC/DRAM。
- 不引入 page walk latency。
- 不使用 `minor_fault_penalty`。
- 在 STLB 统计中按 hit 计数。
- 直接返回 translation response。

这个模型是一个激进的 upper-bound 模型，用于估计完全消除某类 STLB miss 后最多能带来的 IPC 收益。

## 3. 运行时参数

新增运行时参数：

```text
--stlb-ideal-mode
```

支持的值包括：

```text
off
none
0
demand
demand-only
l1pref
l1-prefetch
prefetch
pref
all
ideal
```

主要使用：

```text
--stlb-ideal-mode off
--stlb-ideal-mode demand
--stlb-ideal-mode l1pref
--stlb-ideal-mode all
```

参数注册在 `src/main.cc`：

```cpp
std::string stlb_ideal_mode_text{"off"};

app.add_option("--stlb-ideal-mode", stlb_ideal_mode_text,
               "Resolve selected STLB misses as ideal STLB hits. Choices: off, demand, l1pref, all")
    ->check(CLI::IsMember({"off", "none", "0", "demand", "demand-only",
                           "l1pref", "l1-prefetch", "prefetch", "pref",
                           "all", "ideal"}));
```

CLI parse 后转换为全局枚举：

```cpp
champsim_stlb_ideal_mode = parse_stlb_ideal_mode(stlb_ideal_mode_text);
```

并在仿真开始时打印：

```cpp
fmt::print("STLB ideal mode: {}\n", stlb_ideal_mode_name(champsim_stlb_ideal_mode));
```

因此每个 result log 开头都会包含当前 ideal mode。

## 4. mode 到 miss 来源的映射

mode 定义在 `inc/stlb_ideal.h`：

```cpp
enum class stlb_ideal_mode : unsigned {
  OFF = 0,
  DEMAND,
  L1_PREFETCH,
  ALL,
};
```

实际判断在 `src/stlb_ideal.cc`：

```cpp
bool stlb_ideal_resolves(stlb_ideal_mode mode, translation_origin origin)
{
  switch (mode) {
  case stlb_ideal_mode::OFF:
    return false;
  case stlb_ideal_mode::DEMAND:
    return origin == translation_origin::DEMAND_DATA
        || origin == translation_origin::DEMAND_INSTRUCTION;
  case stlb_ideal_mode::L1_PREFETCH:
    return origin == translation_origin::L1D_PREFETCH
        || origin == translation_origin::L1I_PREFETCH;
  case stlb_ideal_mode::ALL:
    return true;
  }
  return false;
}
```

所以：

```text
demand  -> Demand Data + Demand Instruction
l1pref  -> L1D Prefetch + L1I Prefetch
all     -> 所有 STLB miss source
off     -> 不做 ideal 化
```

## 5. miss 来源从哪里来

每个 translation request 都带有 `translation_source`。

在 cache translation 逻辑中，会调用：

```cpp
classify_translation_origin(q_entry)
```

这个函数根据请求类型和 cache 名字判断来源：

- 普通 load/store demand data -> `DEMAND_DATA`
- 指令取指 demand instruction -> `DEMAND_INSTRUCTION`
- L1D prefetcher 触发的 translation -> `L1D_PREFETCH`
- L1I prefetcher 触发的 translation -> `L1I_PREFETCH`
- 其他无法归类的 translation -> `OTHER`

STLB 的 hit/miss 统计也基于这个来源记录：

```cpp
record_stlb_origin_hit(...)
record_stlb_origin_miss(...)
```

ideal STLB 复用同一套来源分类，因此它和之前 STLB miss cause 统计是一致的。

## 6. STLB hit 路径中的修改点

核心修改在 `src/cache.cc` 的 `CACHE::try_hit()`。

原始逻辑是：

```text
查 tag
如果 hit，返回数据
如果 miss，后面进入 handle_miss()
```

ideal STLB 修改后，在真实 tag miss 后额外判断：

```cpp
const auto ideal_hit =
    !hit
    && is_stlb()
    && vmem != nullptr
    && stlb_ideal_resolves(champsim_stlb_ideal_mode, handle_pkt.translation_source);
```

条件含义：

- `!hit`
  - 只有真实 STLB miss 才需要 ideal 化。
- `is_stlb()`
  - 只对 STLB 生效，不影响 L1D/L1I/L2C/LLC，也不影响 DTLB/ITLB。
- `vmem != nullptr`
  - 需要能访问 `VirtualMemory`，用于得到正确 PPN。
- `stlb_ideal_resolves(...)`
  - 当前 mode 是否解决这类来源的 STLB miss。

最后返回：

```cpp
return hit || (ideal_hit && try_stlb_ideal_hit(handle_pkt));
```

如果 `ideal_hit == true`，`try_hit()` 返回 true，因此该请求不会进入 `handle_miss()`。

这正是“没有后续 STLB miss/PTW 处理”的关键。

## 7. 为什么 ideal hit 跳过 replacement 更新

真实 STLB miss 时，查找结果 `way == set_end`，因此：

```cpp
way_idx == NUM_WAY
```

这个 way 不是真实存在的 cache way。

如果把 ideal miss 当成普通 hit 传给 replacement，例如：

```cpp
impl_update_replacement_state(..., way_idx, ..., hit = true)
```

replacement policy 可能会用不存在的 way index 更新状态，导致越界或错误。

因此当前实现为：

```cpp
if (!ideal_hit) {
  impl_update_replacement_state(..., hit);
}
```

也就是说：

- 真实 STLB hit：正常更新 replacement。
- 真实 STLB miss：正常按 miss 更新 replacement。
- ideal STLB hit：跳过 replacement 更新。

跳过 replacement 更新的原因是：ideal hit 没有真实 STLB block/way，也没有真实 fill，因此不应该污染真实 STLB replacement state。

## 8. ideal hit 如何生成 translation response

核心函数是：

```cpp
bool CACHE::try_stlb_ideal_hit(const tag_lookup_type& handle_pkt)
```

其中调用：

```cpp
auto [ppage, penalty] =
    vmem->va_to_pa(handle_pkt.cpu, champsim::page_number{handle_pkt.v_address});
(void)penalty;
```

含义：

1. 用 `VirtualMemory` 得到当前 VPN 对应的 PPN。
2. 如果该 VPN 之前没有映射，`va_to_pa()` 会按需建立 VPN->PPN 映射。
3. `va_to_pa()` 返回的 `minor_fault_penalty` 被显式忽略。

随后按 STLB hit 统计：

```cpp
sim_stats.hits.increment(std::pair{handle_pkt.type, handle_pkt.cpu});
record_stlb_origin_hit(handle_pkt);
```

最后构造 response：

```cpp
response_type response{
  handle_pkt.address,
  handle_pkt.v_address,
  champsim::address{ppage},
  handle_pkt.pf_metadata,
  handle_pkt.instr_depend_on_me
};

for (auto* ret : handle_pkt.to_return) {
  ret->push_back(response);
}
```

注意：这里返回给上层 cache 的 `data` 是 PPN。上层 cache 的 `finish_translation()` 会把 PPN 与虚拟地址 page offset 拼成完整物理地址：

```cpp
entry.address = champsim::address{
  champsim::splice(p_page, champsim::page_offset{entry.v_address})
};
entry.is_translated = true;
```

所以 ideal STLB path 保持了 ChampSim 原有 translation response 的接口语义。

## 9. 为什么需要给 CACHE 传入 VirtualMemory

原始 ChampSim 中，`VirtualMemory` 主要由 PTW 使用。STLB 本身通常不需要直接查询 `VirtualMemory`。

但是 ideal STLB 绕过 PTW，需要 STLB 自己得到正确 PPN。因此给 `CACHE` 增加了一个：

```cpp
VirtualMemory* vmem;
```

对应 builder 中也增加：

```cpp
VirtualMemory* m_vmem{nullptr};
self_type& virtual_memory(VirtualMemory* vmem_);
```

配置生成器中为每个 cache builder 加上：

```python
'.virtual_memory(&vmem)'
```

因此 `./config.sh` 生成的 `.csconfig/core_inst.cc.inc` 中，每个 cache builder 都会有：

```cpp
.virtual_memory(&vmem)
```

虽然每个 cache 都保存了 `vmem` 指针，但 ideal 逻辑有 `is_stlb()` 限制，因此只有 STLB 会使用它。

## 10. 参数从脚本传到底层的路径

每个 ideal 配置的 `build_champsim.sh` 中设置默认参数。

`ideal-demand-workload-sweep/build_champsim.sh`：

```bash
DEFAULT_OPTION="--hide-heartbeat --stlb-ideal-mode demand"
BINARY_NAME="tlb-ideal-demand-${NUM_CORE}core"
```

`ideal-l1pref-workload-sweep/build_champsim.sh`：

```bash
DEFAULT_OPTION="--hide-heartbeat --stlb-ideal-mode l1pref"
BINARY_NAME="tlb-ideal-l1pref-${NUM_CORE}core"
```

`ideal-all-workload-sweep/build_champsim.sh`：

```bash
DEFAULT_OPTION="--hide-heartbeat --stlb-ideal-mode all"
BINARY_NAME="tlb-ideal-all-${NUM_CORE}core"
```

`launch_workload_sweep.sh` 读取 `build_info.env` 后，把 `DEFAULT_OPTION` 拆成数组：

```bash
read -r -a DEFAULT_OPTIONS <<< "$DEFAULT_OPTION"
```

然后传给 `run_1core.sh`：

```bash
"${RUN_SCRIPT}" "${BINARY_NAME}" "${RUN_N_WARM}" "${RUN_N_SIM}" "${trace_path}" "${DEFAULT_OPTIONS[@]}"
```

`run_1core.sh` 最终执行 bin：

```bash
"$BINARY" \
    --warmup-instructions "${N_WARM}000000" \
    --simulation-instructions "${N_SIM}000000" \
    "${OPTIONS[@]}" \
    "$TRACE_PATH" \
    > "$OUTFILE"
```

因此实际命令类似：

```bash
bin/tlb-ideal-demand-1core \
  --warmup-instructions 50000000 \
  --simulation-instructions 200000000 \
  --hide-heartbeat \
  --stlb-ideal-mode demand \
  trace.champsimtrace.xz
```

## 11. launch 脚本中的四种配置

总控脚本：

```text
launch_sim/1core-spec17_gap-idealTLB-select-trace-compare/run_tlb_select_compare.sh
```

定义了：

```bash
BASELINE_TAG="pref-workload-sweep"
IDEAL_DEMAND_TAG="ideal-demand-workload-sweep"
IDEAL_L1PREF_TAG="ideal-l1pref-workload-sweep"
IDEAL_ALL_TAG="ideal-all-workload-sweep"
```

`build-only` 会构建四个 bin：

```bash
do_build_config "$BASELINE_TAG"
do_build_config "$IDEAL_DEMAND_TAG"
do_build_config "$IDEAL_L1PREF_TAG"
do_build_config "$IDEAL_ALL_TAG"
```

`run-only` 会运行四个配置：

```bash
do_run_config "$BASELINE_TAG"
do_run_config "$IDEAL_DEMAND_TAG"
do_run_config "$IDEAL_L1PREF_TAG"
do_run_config "$IDEAL_ALL_TAG"
```

也支持单独运行：

```bash
run-baseline
run-demand
run-l1pref
run-allideal
```

## 12. select_trace 和 full_trace

脚本保留两套后处理流程：

1. `select_trace`
   - 根据 baseline `pref-workload-sweep` 的 STLB MPKI 筛选 trace。
   - 默认阈值是：

```bash
SELECT_THRESHOLD=1.0
```

2. `full_trace`
   - 不做 trace 筛选。
   - 使用所有可解析 result log。

两套流程都对 baseline 和三种 ideal 配置做同样的后处理。

## 13. IPC upper-bound 对比

后处理脚本会生成：

```text
ideal_stlb_ipc_upperbound_compare.csv
ideal_stlb_ipc_upperbound_compare.png
ideal_stlb_ipc_upperbound_compare.pdf
```

核心对比是：

```text
ideal_demand IPC / baseline IPC
ideal_l1pref IPC / baseline IPC
ideal_all IPC / baseline IPC
```

图是分组柱状图，用于展示不同 workload 下三种 ideal STLB 设计的 IPC speedup upper bound。

## 14. 与正常 PTW 路径的区别

正常 STLB miss 路径：

```text
STLB tag lookup miss
  -> 计 STLB miss
  -> 分配 STLB MSHR
  -> 发 request 到 PTW
  -> PTW 查 PSC
  -> PTW 串行发起 PTE memory access
  -> PTE access 走 L1D/L2C/LLC/DRAM
  -> 首次建立 PTE/VPN->PPN 时加入 minor_fault_penalty
  -> PTW 返回 PPN
  -> STLB 完成 translation
```

ideal STLB 路径：

```text
STLB tag lookup miss
  -> 来源匹配 ideal mode
  -> 直接调用 VirtualMemory 得到 PPN
  -> 忽略 minor_fault_penalty
  -> 不分配 STLB MSHR
  -> 不访问 PTW/PSC/page table
  -> 不访问 cache/DRAM
  -> 按 STLB hit 返回
```

所以 ideal STLB 不是 PTW 加速模型，而是 STLB 命中上限模型。

## 15. 首次 VPN 建立映射时的语义

即使当前 VPN 第一次出现，ideal STLB 也会直接调用：

```cpp
vmem->va_to_pa(...)
```

这会建立 VPN->PPN 映射，并返回一个 `minor_fault_penalty`。

但是 ideal STLB path 中：

```cpp
(void)penalty;
```

所以首次建立映射也没有额外延迟。

这个假设非常理想化，含义是：

```text
ideal STLB 甚至在第一次看到某个 VPN 时也能直接给出 PPN。
```

这不是现实硬件行为，而是 upper-bound。

如果想做更保守的模型，可以改成：

```text
首次 VPN 仍然走 PTW；
只有已经建立过 VPN->PPN 映射的后续 STLB miss 才 ideal hit。
```

但那会变成另一个实验问题，不是当前“所有指定来源 STLB miss 都被解决”的上限模型。

## 16. 对 STLB 统计的影响

对于被 ideal 解决的 STLB miss：

- `total_hit` 增加。
- `total_miss` 不增加。
- 对应 cause 的 miss 不增加。
- `record_stlb_origin_hit()` 会记录对应来源的 hit。

例如 smoke test 中观察到：

```text
--stlb-ideal-mode demand:
  Demand_Data_miss = 0
  Demand_Instruction_miss = 0

--stlb-ideal-mode l1pref:
  L1D_Prefetch_miss = 0
  L1I_Prefetch_miss = 0

--stlb-ideal-mode all:
  STLB_total_miss = 0
```

这符合实验预期。

## 17. 对 cache/DRAM traffic 的影响

被 ideal 解决的 STLB miss 不会触发 PTW，因此也不会产生 PTE memory access。

因此它会减少：

- PTW request 数量。
- page walk 访问 L1D 的请求。
- page walk 访问 L2C/LLC/DRAM 的请求。
- page walk 造成的 cache/DRAM queue pressure。
- page walk 对普通 demand/prefetch memory traffic 的干扰。

这也是它比“只减少 PTW 延迟”更激进的原因。

## 18. 对 replacement/cache state 的影响

ideal STLB hit 不填充 STLB，也不更新 STLB replacement state。

原因是：真实 tag lookup miss 时没有真实命中的 way。为了避免用不存在的 way 更新 replacement，ideal hit 直接跳过 replacement update。

这意味着：

- 它不会改变 STLB 内容。
- 它不会污染 STLB replacement policy。
- 如果同一个 VPN 后续再次被访问，仍然可能真实 STLB miss，然后再次被 ideal 解决。

这符合“外部 oracle/理想 STLB 直接回答”的 upper-bound 语义。

## 19. 已验证内容

已经验证：

1. 四个 bin 可以成功构建：

```text
bin/tlb-pref-1core
bin/tlb-ideal-demand-1core
bin/tlb-ideal-l1pref-1core
bin/tlb-ideal-all-1core
```

2. `--help` 中能看到：

```text
--stlb-ideal-mode
```

3. 用一个小 trace 做 1M warmup + 1M ROI smoke test：

```text
600.perlbench_s-1273B
```

观察结果：

```text
demand 模式：Demand Data / Demand Instruction STLB miss 为 0
l1pref 模式：L1D/L1I Prefetch STLB miss 为 0
all 模式：STLB total miss 为 0
```

smoke test 产生的小 log 已删除，避免污染正式实验。

## 20. 常用命令

进入仓库：

```bash
cd /home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound
```

构建四个 bin：

```bash
./launch_sim/1core-spec17_gap-idealTLB-select-trace-compare/run_tlb_select_compare.sh build-only
```

完整流程：

```bash
MAX_PARALLEL=15 N_WARM=50 N_SIM=200 \
./launch_sim/1core-spec17_gap-idealTLB-select-trace-compare/run_tlb_select_compare.sh all 15
```

只运行某个 ideal 配置：

```bash
MAX_PARALLEL=15 N_WARM=50 N_SIM=200 \
./launch_sim/1core-spec17_gap-idealTLB-select-trace-compare/run_tlb_select_compare.sh run-demand 15

MAX_PARALLEL=15 N_WARM=50 N_SIM=200 \
./launch_sim/1core-spec17_gap-idealTLB-select-trace-compare/run_tlb_select_compare.sh run-l1pref 15

MAX_PARALLEL=15 N_WARM=50 N_SIM=200 \
./launch_sim/1core-spec17_gap-idealTLB-select-trace-compare/run_tlb_select_compare.sh run-allideal 15
```

只做后处理：

```bash
SELECT_THRESHOLD=1.0 \
./launch_sim/1core-spec17_gap-idealTLB-select-trace-compare/run_tlb_select_compare.sh backend-all
```
