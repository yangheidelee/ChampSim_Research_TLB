# Work Record

## 2026-06-22 PTW/TLB Modeling Notes

本次主要检查工程：

```text
/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound
```

关注脚本目录：

```text
/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/launch_sim/1core-spec0617_gapligra-idealTLB-select-trace-compare_jsonnew
```

这套脚本用于测试不同 ideal STLB 条件下的 IPC 上限，包括 `pref`、`ideal-demand`、`ideal-l1pref`、`ideal-all` 等配置。

### 主要发现

1. 当前 jsonnew 配置中的 TLB/PTW 参数比论文 Table I 更宽松。

   当前配置中，ITLB/DTLB MSHR 为 8，STLB MSHR 为 16，PTW `max_read` 为 2；论文 Table I 中 ITLB/DTLB/L2 TLB MSHR 都是 4，并且是 `1 page walk / cycle`。

2. `PTW.mshr_size` 目前不能严格限制 PTW 并发 page walk。

   JSON 中可以写：

   ```json
   "PTW": {
     "mshr_size": 4
   }
   ```

   配置生成器也会把它传到 `PageTableWalker::MSHR_SIZE`。但是 `src/ptw.cc` 的 `PageTableWalker::operate()` 中没有使用 `MSHR_SIZE` 检查当前在飞 page walk 数量，因此它不是一个真正的 PTW hard limit。

   当前真正限制 PTW 启动新 page walk 速度的是 `PTW.max_read`，同时还会受到下游 L1D/L2/LLC/DRAM 队列反压影响。

3. 当前 PTW 默认下游是 L1D。

   `config/defaults.py` 中默认：

   ```python
   yield { 'name': cpu.get('PTW'), 'lower_level': cpu.get('L1D') }
   ```

   所以 STLB miss 后，PTW 发出的 page-table memory request 会先进入 L1D。这个连接可以通过 JSON 的 `PTW.lower_level` 改成 `cpu0_L2C`，但当前实验先保持 ChampSim 默认行为。

4. Page table level 和 PSC 个数没有完全解耦。

   当前 JSON 中可以设置：

   ```json
   "virtual_memory": {
     "num_levels": 4
   }
   ```

   但是 `src/ptw.cc` 中 PTW 初始 walk level 使用的是 `std::size(pscl)`，不是 `vmem->pt_levels`。因此仅修改 `virtual_memory.num_levels`，不能严格控制 PTW 从第几级开始 walk。

5. PSC 结构不能通过当前 JSON 干净表达论文配置。

   论文 Table I 是 4-level page table + 3-level split PSC。当前 ChampSim 默认 PTW 里有 `pscl5/pscl4/pscl3/pscl2` 四组 PSC。JSON 可以改每组大小，但没有清晰机制删除某一级 PSC，因而不能严格表达“4-level page table 但只有 3-level PSC”。

### 对后续实验的影响

如果只是粗略收窄配置，可以直接在 JSON 中改：

```json
"ITLB": { "mshr_size": 4 },
"DTLB": { "mshr_size": 4 },
"STLB": { "mshr_size": 4 },
"PTW": {
  "max_read": 1,
  "max_write": 1
},
"virtual_memory": {
  "num_levels": 4
}
```

但如果要严格复现论文 Table I 的 PTW/TLB 建模，需要修改源码：

- 在 `src/ptw.cc` 中让 `PTW.mshr_size` 真正限制并发 page walk。
- 解耦 `virtual_memory.num_levels` 和 PSC 个数，让 PTW 起始 walk level 由 page-table levels 决定。
- 修改 PSC 配置生成方式，让 JSON 能明确描述 PSC list，并支持 3-level PSC。

当前结论：现有 ChampSim 对 PTW/TLB 的部分建模偏简化，JSON 配置不能完全严格控制 PTW concurrency、PSC 个数、PSC 层级和 PTW walk 起始层级。
