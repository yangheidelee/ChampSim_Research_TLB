# VPN Characterization 记录说明

本文记录当前 ChampSim 中为了观察 L1D / STLB 的虚拟页访问 footprint 所做的源码修改、控制方式和数据口径。

## 1. 源码修改范围

当前功能主要修改/新增以下文件：

- `inc/vpn_pattern_tracker.h`
- `src/vpn_pattern_tracker.cc`
- `src/cache.cc`

核心设计是：在 cache 的 tag-check ready 阶段记录访问流。这样记录的是 cache/TLB 结构实际看到的访问顺序，而不是 CPU 原始发射顺序。

## 2. 统一记录点

记录点位于 `src/cache.cc` 的 `CACHE::operate()` 中，在 ready tag-check range 取出之后、hit/miss 分组之前：

```cpp
auto [tag_check_ready_begin, tag_check_ready_end] =
    champsim::get_span_p(std::begin(inflight_tag_check), std::end(inflight_tag_check), tag_check_bw,
                         [is_ready, is_translated](const auto& pkt) { return is_ready(pkt) && is_translated(pkt); });

for (auto it = tag_check_ready_begin; it != tag_check_ready_end; ++it) {
  champsim::instrumentation::record_l1d_vpn_access(...);
  champsim::instrumentation::record_stlb_vpn_access(...);
}

auto hits_end = std::stable_partition(tag_check_ready_begin, tag_check_ready_end, [this](const auto& pkt) { return this->try_hit(pkt); });
```

这个位置的含义：

- 访问已经 ready，可以进入 tag check。
- 记录发生在 `stable_partition(... try_hit ...)` 之前。
- 因此 `access_id` 保留的是当前结构看到的严格 tag-check ready access 顺序。
- 当前记录的是 access attempt stream，不记录 hit/miss 结果。

## 3. L1D VPN footprint tracer

### 控制方式

L1D tracer 默认关闭，通过环境变量打开：

```bash
DUMP_L1D_VPN=1
DUMP_L1D_VPN_FILE=/path/to/l1d_vpn_trace.csv
```

如果不设置 `DUMP_L1D_VPN_FILE`，默认输出到当前运行目录下：

```text
l1d_vpn_trace.csv
```

### 记录口径

L1D tracer 在 `record_l1d_vpn_access()` 内部过滤：

- 只记录 cache 名以 `_L1D` 结尾的结构。
- 不记录 warmup 阶段。
- 不记录 instruction-side access。
- 不记录本地 prefetcher 发出的请求。
- 不记录 `PREFETCH` / `TRANSLATION` 类型。
- 只保留 `LOAD`、`RFO`、`WRITE` 类型的 demand data access。

因此 L1D CSV 表示：

```text
ROI 阶段 L1D translated tag-check ready demand data access attempt stream
```

它不是 CPU 原始 load/store 发射顺序，也不是 TLB lookup 顺序；它是地址翻译完成后，L1D tag-check 阶段看到的访问流。

### CSV 字段

L1D CSV header：

```text
access_id,cycle,ip,vaddr,vpn,offset,type,cpu,instr_id
```

字段含义：

- `access_id`：从 0 开始的 ROI 内 L1D access 流序号。
- `cycle`：该访问进入 L1D tag-check ready 阶段时的 ChampSim cycle。
- `ip`：产生该数据访问的动态指令对应的静态 instruction pointer。
- `vaddr`：原始虚拟数据地址。
- `vpn`：原始虚拟页号，计算方式为 `vaddr >> LOG2_PAGE_SIZE`。
- `offset`：虚拟页内部的 cache-line offset，计算方式为 `(vaddr >> LOG2_BLOCK_SIZE) & ((1 << (LOG2_PAGE_SIZE - LOG2_BLOCK_SIZE)) - 1)`。
- `type`：ChampSim access type，正常为 `LOAD`、`RFO` 或 `WRITE`。
- `cpu`：CPU/core id。
- `instr_id`：ChampSim 内部动态指令 id，全局动态指令流顺序编号。

## 4. STLB full access tracer

### 控制方式

STLB tracer 默认关闭，通过环境变量打开：

```bash
DUMP_STLB_ACCESS=1
DUMP_STLB_ACCESS_FILE=/path/to/stlb_access_trace.csv
```

如果不设置 `DUMP_STLB_ACCESS_FILE`，默认输出到当前运行目录下：

```text
stlb_access_trace.csv
```

### 记录口径

STLB tracer 在 `record_stlb_vpn_access()` 内部过滤：

- 只记录 cache/TLB 名以 `_STLB` 结尾的结构。
- 不记录 warmup 阶段。
- 只记录进入 STLB 的 translation lookup request。

当前 ChampSim 中，`issue_translation()` 将发往下级 TLB/STLB 的 translation lookup 包装成：

```cpp
fwd_pkt.type = access_type::LOAD;
fwd_pkt.translation_source = classify_translation_origin(q_entry);
```

因此 STLB CSV 里的 `type` 通常是 `LOAD`。这里的 `LOAD` 不是指程序里的 load 指令，而是 ChampSim 内部用于 TLB lookup request 的类型编码。真正区分来源需要看 `origin` 字段。

STLB CSV 表示：

```text
ROI 阶段 STLB tag-check ready access attempt stream
```

它记录的是 STLB 的 full access attempt stream，也就是 STLB hit 和 miss 都会进入这个 trace；当前不记录 hit/miss 结果本身。

### CSV 字段

STLB CSV header：

```text
access_id,cycle,ip,vaddr,vpn,offset,type,origin,cpu,instr_id,is_instr,prefetch_from_this
```

字段含义：

- `access_id`：从 0 开始的 ROI 内 STLB access 流序号。
- `cycle`：该访问进入 STLB tag-check ready 阶段时的 ChampSim cycle。
- `ip`：产生该 translation 请求的动态指令对应的 instruction pointer。
- `vaddr`：原始虚拟地址。
- `vpn`：原始虚拟页号，计算方式为 `vaddr >> LOG2_PAGE_SIZE`。
- `offset`：虚拟页内部的 cache-line offset。
- `type`：ChampSim request type。对 STLB translation lookup，当前通常为 `LOAD`。
- `origin`：translation 来源。
- `cpu`：CPU/core id。
- `instr_id`：ChampSim 内部动态指令 id。
- `is_instr`：该请求是否来自 instruction-side access。
- `prefetch_from_this`：该请求是否由当前 cache level 的本地 prefetcher 发出；对 STLB 分析通常优先看 `origin`。

### origin 分类

`origin` 来自 `translation_origin`，可能值包括：

- `Demand_Data`
- `Demand_Instruction`
- `L1D_Prefetch`
- `L1I_Prefetch`
- `Other`

分类逻辑位于 `CACHE::classify_translation_origin()`：

```cpp
if (q_entry.type == access_type::PREFETCH && q_entry.prefetch_from_this) {
  if (NAME ... "_L1D")
    return translation_origin::L1D_PREFETCH;
  if (NAME ... "_L1I")
    return translation_origin::L1I_PREFETCH;
  return translation_origin::OTHER;
}

if (q_entry.type == access_type::PREFETCH)
  return q_entry.translation_source;

return q_entry.is_instr ? translation_origin::DEMAND_INSTRUCTION : translation_origin::DEMAND_DATA;
```

## 5. 与原有 STLB miss share 指标的区别

已有日志中的 STLB miss cause/share 指标使用的是 `stlb_origin_misses`，只统计 STLB miss，并按 `origin` 分类：

```cpp
sim_stats.stlb_origin_misses.increment(std::pair{handle_pkt.translation_source, handle_pkt.cpu});
```

因此原有指标回答的是：

```text
STLB miss 里面，Demand_Data / Demand_Instruction / L1D_Prefetch / L1I_Prefetch / Other 各占多少？
```

本次新增的 `DUMP_STLB_ACCESS` trace 回答的是：

```text
所有进入 STLB tag-check ready 阶段的 access attempt 的 VPN 访问流是什么？
```

也就是说：

- 原有 STLB miss share：只看 miss，按 origin 聚合计数。
- 新增 STLB full access trace：看 full access stream，hit/miss 都包括，逐 access 输出 VPN、cycle、origin 等字段。

## 6. 脚本目录

当前已有两个 characterization 脚本目录：

- `launch_sim_characterization/l1d-vpn-footprint`
- `launch_sim_characterization/stlb-full-access`

`l1d-vpn-footprint` 用于 L1D VPN footprint dump。

`stlb-full-access` 用于 STLB full access dump。这个目录中的 JSON 已经将 L1D prefetcher 关闭：

```json
"L1D": {
  "prefetcher": "no"
}
```

两个目录的默认 smoke trace 都是：

```text
/data2/zcq/gap_dpc/bfs-3.trace.gz
```

## 7. 同时打开两个 tracer

两个 tracer 的环境变量互相独立，可以单独打开，也可以同时打开：

```bash
DUMP_L1D_VPN=1 DUMP_L1D_VPN_FILE=/path/to/l1d.csv \
DUMP_STLB_ACCESS=1 DUMP_STLB_ACCESS_FILE=/path/to/stlb.csv \
/home/zcq/git_prj/ChampSim/bin/tlb-pref-1core ...
```

同时打开时会写两个 CSV，I/O 开销更大。
