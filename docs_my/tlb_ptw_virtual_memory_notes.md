# ChampSim TLB/PTW/VirtualMemory 建模笔记

本文记录当前 ChampSim 工程中 TLB、PTW、页表、虚拟页到物理页映射、物理页 free list 的建模方式。对应源码主要在：

- `inc/vmem.h`
- `src/vmem.cc`
- `inc/ptw.h`
- `src/ptw.cc`
- `src/cache.cc`

## 1. trace 中的地址与虚实地址映射

这类 trace-based simulator 通常不会在 trace 中保存完整 OS 页表状态，也不会保存真实程序运行时所有虚拟地址到物理地址的完整映射。

在 ChampSim 中，trace 中的访存地址主要按虚拟地址使用。仿真过程中，TLB/PTW/VirtualMemory 负责把虚拟页转换成物理页。

因此，ChampSim 不是在仿真开始时就已经拥有所有 VPN 到 PPN 的完整映射，而是按需建立映射。

## 2. VirtualMemory 的作用

`VirtualMemory` 可以理解为 ChampSim 内部维护的“虚拟内存真值表”。它负责：

1. 维护虚拟页 VPN 到物理页 PPN 的映射。
2. 维护页表项 PTE 的物理地址。
3. 管理还未分配出去的物理页 free list。
4. 在首次创建映射时返回一个 `minor_fault_penalty`。

主要数据结构在 `inc/vmem.h`：

```cpp
std::map<std::pair<uint32_t, champsim::page_number>, champsim::page_number> vpage_to_ppage_map;
std::map<std::tuple<uint32_t, uint32_t, champsim::address_slice<champsim::dynamic_extent>>, champsim::address> page_table;
std::deque<champsim::page_number> ppage_free_list;
```

含义分别是：

- `vpage_to_ppage_map`：最终 VPN -> PPN 映射。
- `page_table`：页表项的物理地址映射。
- `ppage_free_list`：尚未分配出去的物理页号队列。

## 3. VPN -> PPN 如何按需建立

最终虚拟页到物理页的映射由 `VirtualMemory::va_to_pa()` 完成。

源码位置：`src/vmem.cc`

```cpp
auto [ppage, fault] = vpage_to_ppage_map.try_emplace({cpu_num, champsim::page_number{vaddr}}, ppage_front());

if (fault) {
  ppage_pop();
}

auto penalty = fault ? minor_fault_penalty : champsim::chrono::clock::duration::zero();
return std::pair{ppage->second, penalty};
```

语义是：

1. 如果当前 `{cpu, VPN}` 已经有映射，直接返回已有 PPN，`penalty = 0`。
2. 如果当前 `{cpu, VPN}` 是第一次出现，就从 `ppage_free_list` 取一个 PPN 建立映射。
3. 首次建立映射时返回 `minor_fault_penalty`。

所以同一个 VPN 后续访问会得到同一个 PPN；不同 VPN 一般会从 free list 得到不同 PPN。

## 4. 页表项 PTE 如何按需建立

PTW 遍历页表时，每一级都需要知道对应 PTE 的物理地址。这个由 `VirtualMemory::get_pte_pa()` 完成。

源码位置：`src/vmem.cc`

```cpp
auto [ppage, fault] =
    page_table.try_emplace({cpu_num, level, champsim::address_slice{pte_table_entry_extent, vaddr}},
                           champsim::splice(active_pte_page, next_pte_page));

if (fault) {
  next_pte_page++;
  if (champsim::page_offset{next_pte_page} == champsim::page_offset{0}) {
    active_pte_page = ppage_front();
    ppage_pop();
  }
}

auto penalty = minor_fault_penalty;
if (!fault) {
  penalty = champsim::chrono::clock::duration::zero();
}
return {paddr, penalty};
```

语义是：

1. 如果某一级页表项之前已经存在，返回已有 PTE 物理地址，`penalty = 0`。
2. 如果该 PTE 第一次出现，就为其分配页表空间。
3. 第一次建立该 PTE 时返回 `minor_fault_penalty`。

因此，中间级页表项第一次不存在时，ChampSim 会建立它，并加一个固定 penalty。

## 5. PTW 如何使用 VirtualMemory

PTW 是 `PageTableWalker`，源码在 `src/ptw.cc`。

PTW 构造时保存 `VirtualMemory* vmem`，并初始化 CR3：

```cpp
PageTableWalker::PageTableWalker(champsim::ptw_builder b)
    : ..., vmem(b.m_vmem),
      CR3_addr(b.m_vmem->get_pte_pa(b.m_cpu, champsim::page_number{}, b.m_vmem->pt_levels).first)
```

正常 STLB miss 后，translation request 会进入 PTW。PTW 对每一级页表执行如下过程：

1. 查询 PSC。
2. 确定当前 level 的 PTE 物理地址。
3. 生成一次 `access_type::TRANSLATION` 的内存访问。
4. 把该请求发往下层 cache/DRAM。
5. 等 memory response 返回后，进入下一层 page table。

发送 PTE memory access 的代码在 `PageTableWalker::step_translation()`：

```cpp
packet.address = source.address;
packet.v_address = source.v_address;
packet.is_translated = true;
packet.type = access_type::TRANSLATION;
lower_level->add_rq(packet);
```

这说明 PTW 的 page walk 访问会进入 cache/DRAM 层次，并产生真实排队和访问延迟。

## 6. 中间级 PTE 不存在时是否有延迟

有。

当 PTW 完成某一级 PTE memory access 后，会调用：

```cpp
auto [ppage, penalty] =
    this->vmem->get_pte_pa(mshr_entry.cpu, champsim::page_number{mshr_entry.v_address}, mshr_entry.translation_level);
```

如果该中间级 PTE 第一次建立，`get_pte_pa()` 返回 `minor_fault_penalty`。

PTW 会把这个 penalty 加入该步完成时间：

```cpp
return champsim::waitable{ppage, this->current_time + penalty + (this->warmup ? champsim::chrono::clock::duration{} : HIT_LATENCY)};
```

所以中间级页表项首次建立时，不仅有 PTE memory access 的 cache/DRAM 延迟，还会额外有固定的 `minor_fault_penalty`。

## 7. 最后一级 VPN->PPN 不存在时是否有延迟

也有。

PTW 走到最后一级时调用：

```cpp
auto [ppage, penalty] =
    this->vmem->va_to_pa(mshr_entry.cpu, champsim::page_number{mshr_entry.v_address});
```

如果这是该 VPN 第一次出现，`va_to_pa()` 会建立 VPN -> PPN 映射，并返回 `minor_fault_penalty`。

PTW 同样把 penalty 加入完成时间：

```cpp
return champsim::waitable{champsim::address{ppage},
                          this->current_time + penalty + (this->warmup ? champsim::chrono::clock::duration{} : HIT_LATENCY)};
```

所以最后一级 VPN->PPN 映射首次建立时，也会有固定的 `minor_fault_penalty`。

## 8. minor_fault_penalty 的含义

`minor_fault_penalty` 是 ChampSim 对“首次建立页表项或首次建立 VPN->PPN 映射”的简化固定代价。

它不是完整 OS page fault 建模，也不是 SSD page-in/page-out 建模。

正常 PTW 路径的延迟可以理解为两部分：

1. PTW 每一级 PTE memory access 经过 cache/DRAM 的真实延迟。
2. 如果该级 PTE 或最终 VPN->PPN 映射第一次建立，再额外加 `minor_fault_penalty`。

## 9. 物理页 free list 是什么

`ppage_free_list` 是 ChampSim 维护的一串“尚未分配出去的物理页号”。

初始化时，ChampSim 根据 DRAM size 和 page size 生成可用物理页：

```cpp
ppage_free_list.resize(((dram.size() - 1_MiB) / PAGE_SIZE).count());
```

因此 free list 中物理页数量约为：

```text
(DRAM size - 1 MiB) / PAGE_SIZE
```

例如：

```text
DRAM size = 4 GiB
PAGE_SIZE = 4 KiB

free pages = (4 GiB - 1 MiB) / 4 KiB
           = 1,048,320 pages
```

首次访问某个新 VPN 时，`va_to_pa()` 从 free list 头部取一个 PPN：

```cpp
ppage_front()
```

随后把它从 free list 中弹出：

```cpp
ppage_pop()
```

## 10. 已经建立好的映射会不会删除

正常情况下不会。

一旦某个 VPN 建立了 VPN -> PPN 映射，它会保存在 `vpage_to_ppage_map` 中，直到仿真结束。

ChampSim 这里没有建模：

- page free
- page unmap
- page eviction
- swap out
- dirty page writeback
- OS page replacement policy

页表项映射 `page_table` 也不会主动删除。

## 11. free list 用完怎么办

如果 free list 用完，`ppage_pop()` 会这样处理：

```cpp
if (available_ppages() == 0) {
  fmt::print("[VMEM] WARNING: Out of physical memory, freeing ppages\n");
  populate_pages();
  shuffle_pages();
}
```

也就是说：

1. 打印 warning。
2. 重新填充 free list。
3. 如果配置了 randomization，再 shuffle。
4. 仿真继续运行。

但是这不是现实 OS 的物理页回收。它不会删除已有 VPN->PPN 映射，也不会选择 victim page，更不会模拟 swap。

因此，如果真的耗尽物理页，后续新的 VPN 可能被分配到已经被旧 VPN 使用过的 PPN。这是 ChampSim 的简化行为，主要目的是让仿真继续运行，而不是建模真实操作系统内存管理。

## 12. 是否建模 DRAM page 和 SSD swap

没有。

ChampSim 不建模 DRAM 中 page 与 SSD/disk swap 空间之间的换入换出。

它没有建模：

- major page fault
- SSD/page-in latency
- page-out
- dirty page 写回 SSD
- swap cache
- OS page replacement
- mmap 文件页按需加载
- NUMA/page migration

所以 `minor_fault_penalty` 只是一个简化固定代价，不是 SSD 访问代价。

## 13. 直接访问 VirtualMemory 和走 PTW 的区别

正常 PTW 路径：

1. STLB miss 被计为 miss。
2. STLB 分配 MSHR。
3. request 发给 PTW。
4. PTW 查询 PSC。
5. 每一级 page table 都发起 PTE memory access。
6. PTE memory access 会访问 cache/DRAM。
7. 首次建立 PTE 或 VPN->PPN 映射时加 `minor_fault_penalty`。
8. 最后 PTW 返回 PPN，STLB 完成 translation。

直接调用 `VirtualMemory::va_to_pa()`：

1. 直接得到 PPN。
2. 如果 VPN 不存在，会直接建立 VPN->PPN 映射。
3. 函数会返回 `minor_fault_penalty`，但调用者可以选择是否使用。
4. 不会自动产生 PTE memory access。
5. 不会经过 PTW/PSC/cache/DRAM。

因此，直接访问 `VirtualMemory` 不是硬件 page walk 建模，而是绕过硬件 page walk 的真值查询。

## 14. 与本仓库 ideal STLB 实验的关系

在本仓库的 ideal STLB 实验中，STLB miss 如果属于指定来源，会被视为 ideal STLB hit。

实现位置在 `src/cache.cc`：

```cpp
auto [ppage, penalty] =
    vmem->va_to_pa(handle_pkt.cpu, champsim::page_number{handle_pkt.v_address});
(void)penalty;
```

这里调用 `va_to_pa()` 只是为了得到正确 PPN。返回的 `penalty` 被显式忽略。

因此 ideal STLB 路径的语义是：

1. 如果 VPN 已存在映射，直接返回已有 PPN。
2. 如果 VPN 首次出现，直接建立 VPN->PPN 映射。
3. 即使首次建立映射，也不产生 `minor_fault_penalty`。
4. 不访问 PTW。
5. 不访问 page table。
6. 不访问 cache/DRAM。
7. 不计 STLB miss。
8. 不分配 STLB MSHR。
9. 按 STLB hit 统计。

这是一个激进的 IPC upper-bound 模型。它回答的是：

```text
如果 STLB 对这些来源的 translation request 总是能直接给出答案，IPC 上限是多少？
```

它不是现实硬件机制，而是用于评估“完全消除某类 STLB miss 后最多可能获得多少收益”。

## 15. load 访问 L1D 与 DTLB 的时序关系

从源码看，ChampSim 不是严格显式建模现代 VIPT L1D 的两阶段过程：

```text
先用 VA page offset/index 定位 L1D set
同时查 DTLB
PPN 回来后再比较 tag/way
```

它采用的是一种近似的 overlapped translation/cache pipeline。

CPU 发 load 时，先把请求发给 L1D bus：

```cpp
bool O3_CPU::execute_load(const LSQ_ENTRY& lq_entry)
{
  CacheBus::request_type data_packet;
  data_packet.v_address = lq_entry.virtual_address;
  data_packet.instr_id = lq_entry.instr_id;
  data_packet.ip = lq_entry.ip;

  return L1D_bus.issue_read(data_packet);
}
```

`CacheBus::issue_read()` 中：

```cpp
data_packet.address = data_packet.v_address;
data_packet.is_translated = false;
data_packet.cpu = cpu;
data_packet.type = access_type::LOAD;

return lower_level->add_rq(data_packet);
```

因此 load 进入 L1D 时：

- `address` 暂时等于虚拟地址。
- `v_address` 保存虚拟地址。
- `is_translated = false`。

L1D 处理请求时，会先把请求放入 `inflight_tag_check`，并设置一个未来的 `event_cycle`：

```cpp
retval.event_cycle = current_time + HIT_LATENCY;
```

随后 L1D 对未翻译请求发起 translation：

```cpp
std::for_each(std::begin(inflight_tag_check), std::end(inflight_tag_check),
              [this](auto& x) { this->issue_translation(x); });
```

translation 返回后，L1D 调用 `finish_translation()`，把物理页号和虚拟页内 offset 拼成完整物理地址：

```cpp
entry.address = champsim::address{
  champsim::splice(p_page, champsim::page_offset{entry.v_address})
};
entry.is_translated = true;
```

真正 cache tag hit/miss 判断只处理：

```cpp
is_ready(pkt) && is_translated(pkt)
```

也就是说，ChampSim 的语义更准确地说是：

```text
load 进入 L1D
L1D hit latency 计时开始
L1D 同时发起 DTLB translation
真正 L1D hit/miss 判断必须等 translation 完成
最终 L1D tag lookup 使用翻译后的 PA
```

所以它不是显式建模“VA index 后等 PPN 比 way”，而是让 L1D latency 和 translation latency 可以重叠，但最终 cache lookup 使用 PA。

## 16. 当前配置下 L1D/DTLB/STLB/PTW 的连接关系

当前生成文件 `.csconfig/core_inst.cc.inc` 中可以看到连接关系。

L1D：

```cpp
.name("cpu0_L1D")
.lower_translate(&channels.at(8))
.lower_level(&channels.at(4))
```

DTLB：

```cpp
.name("cpu0_DTLB")
.lower_level(&channels.at(2))
```

STLB：

```cpp
.name("cpu0_STLB")
.upper_levels({{&channels.at(2), &channels.at(3), &channels.at(10)}})
.lower_level(&channels.at(7))
```

PTW：

```cpp
.name("cpu0_PTW")
.upper_levels({&channels.at(7)})
.lower_level(&channels.at(0))
```

所以 demand load 的 translation 路径是：

```text
L1D lower_translate
  -> DTLB
  -> STLB
  -> PTW
```

普通 data cache miss 路径是：

```text
L1D lower_level
  -> L2C
  -> LLC
  -> DRAM
```

## 17. PTW 是否先访问 PSC

是。

PTW 收到 STLB miss 后，在 `PageTableWalker::handle_read()` 中先检查 PSC：

```cpp
pscl_entry walk_init = {handle_pkt.v_address, CR3_addr, std::size(pscl)};
std::vector<std::optional<pscl_entry>> pscl_hits;

std::transform(std::begin(pscl), std::end(pscl),
               std::back_inserter(pscl_hits),
               [walk_init](auto& x) { return x.check_hit(walk_init); });

walk_init =
    std::accumulate(std::begin(pscl_hits), std::end(pscl_hits),
                    std::optional<pscl_entry>(walk_init),
                    [](auto x, auto& y) { return y.value_or(*x); }).value();
```

这段代码表示 PTW 会对所有 PSC structure 做 `check_hit()`。

从建模上看：

- PSC lookup 没有单独建模访问延迟。
- PSC lookup 没有单独建模端口冲突。
- 所有 PSC 在同一个 PTW 操作阶段内被检查。

因此可以理解为：PSC 是并行/组合式检查；如果某一级 PSC 命中，page walk 就从更低一级继续。

默认 PSC 配置来自 `inc/defaults.hpp`：

```cpp
const auto default_ptw =
  champsim::ptw_builder{}
    .bandwidth_factor(2)
    .mshr_factor(5)
    .add_pscl(5, 1, 2)
    .add_pscl(4, 1, 4)
    .add_pscl(3, 2, 4)
    .add_pscl(2, 4, 8);
```

当前生成配置中也是：

```cpp
.add_pscl(5, 1, 2)
.add_pscl(4, 1, 4)
.add_pscl(3, 2, 4)
.add_pscl(2, 4, 8)
```

## 18. PSC 后 page walk memory access 是否串行

是串行的。

PSC 检查后，PTW 发起当前 level 的 PTE memory access：

```cpp
packet.address = source.address;
packet.v_address = source.v_address;
packet.is_translated = true;
packet.type = access_type::TRANSLATION;

bool success = lower_level->add_rq(packet);
```

该请求返回后，PTW 在 `handle_fill()` 中填充 PSC，并把 translation level 减 1：

```cpp
const auto pscl_idx = std::size(pscl) - fill_mshr.translation_level;
pscl.at(pscl_idx).fill({fill_mshr.v_address, *fill_mshr.data, fill_mshr.translation_level});

mshr_type fwd_mshr = fill_mshr;
fwd_mshr.address = *fill_mshr.data;
fwd_mshr.translation_level = fill_mshr.translation_level - 1;

return step_translation(fwd_mshr);
```

所以 page walk 是：

```text
发当前级 PTE memory access
等待返回
填 PSC
发下一级 PTE memory access
等待返回
...
最后得到 PPN
```

它不是一次性并行发出所有级别的 PTE memory request。

## 19. PTW 的 memory access 访问 L1I、L1D 还是 L2C

按当前 ChampSim 默认配置和当前生成配置，PTW 的 PTE memory access 从 L1D 开始。

默认配置在 `config/defaults.py`：

```python
def ptw_core_defaults(cpu):
    yield { 'name': cpu.get('PTW'), 'lower_level': cpu.get('L1D') }
```

当前生成文件中 PTW 为：

```cpp
.name("cpu0_PTW")
.lower_level(&channels.at(0))
```

而 L1D 的 upper levels 包含这个 PTW channel：

```cpp
.name("cpu0_L1D")
.upper_levels({{&channels.at(0), &channels.at(12)}})
```

因此 page walk 的 PTE memory access 路径是：

```text
PTW
  -> L1D
  -> L2C
  -> LLC
  -> DRAM
```

它不是：

```text
PTW -> L1I
```

也不是：

```text
PTW -> L1I and L1D 同时访问
```

也不是默认：

```text
PTW -> L2C
```

也就是说，ChampSim 默认把 PTW 的页表项访问建模成一种 data-side memory access，它进入 L1D RQ，然后继续走普通数据 cache hierarchy。

这和一些研究模型中“PTW 直接从 L2C 开始访问”的设定不同。若要让 PTW 从 L2C 开始，需要改配置连接，而不是当前默认行为。

## 20. 小结：源码中的 translation/cache 建模

当前 ChampSim 源码中的整体建模可以总结为：

```text
load/store 进入 L1D，初始 address = VA，is_translated = false
L1D 开始 hit latency 计时，同时发 translation 到 DTLB
DTLB miss -> STLB
STLB miss -> PTW
PTW 先并行/无额外延迟地检查所有 PSC
PSC 后 page table memory access 串行发起
PTE memory access 默认走 PTW -> L1D -> L2C -> LLC -> DRAM
translation 完成后，L1D 把 PPN 和 VA page offset 拼成 PA
L1D 真正 tag hit/miss 判断等 PA ready 后执行
```

因此，按源码说，不能简单写成“L1D 先用 VA 得到 set，然后 TLB 回来后再看 way”。更准确的说法是：

```text
ChampSim 让 L1D hit latency 和 TLB translation 可以重叠，
但最终 cache lookup 使用翻译后的 PA，
没有显式拆分 VA-index 与 PA-tag 的 L1D 两阶段 lookup。
```
