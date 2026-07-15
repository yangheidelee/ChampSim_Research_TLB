# ChampSim 对 CISC 指令的建模方式

## 1. 核心结论

ChampSim 使用动态架构指令粒度的 trace。对于工程自带的 Pin tracer，一条 Pin `INS`（一条完整的动态 x86 CISC 指令）生成一条 ChampSim trace record。

ChampSim 不会将这条 CISC 指令完整拆成真实处理器中的多个 uop。它为每条 trace 指令建立一个 `instr_id` 和一个 ROB entry，但会将该指令中的多个显式 memory operand 分别展开为 LQ/SQ entry。

因此，它的基本模型是：

```text
一条动态 x86 CISC 指令
    -> 一条 trace record
    -> 一个 instr_id
    -> 一个 ROB entry
    -> 若干个 LQ/SQ memory operation
```

## 2. trace 本身已经是动态指令流

原始 trace 中的记录顺序已经表示程序的动态执行顺序。循环中同一条静态指令多次执行时，会在 trace 中多次出现：

```text
trace 顺序    IP/PC       动态实例
1             0x1000      第一次执行
2             0x1004      另一条指令
3             0x1000      循环后再次执行
```

`IP/PC` 标识静态指令地址，所以同一条指令多次执行时 IP 可以相同。

## 3. instr_id 的含义

trace record 本身不需要保存显式的动态编号。ChampSim 每读取一条 trace record，就用全局递增计数器分配 `instr_id`：

```cpp
retval.instr_id = instr_unique_id++;
```

所以：

- `instr_id` 是一条动态架构指令实例的身份标识。
- 单核时，它基本就是 trace record 的读取顺序号。
- 它在 trace reader 读取指令时分配，而不是在执行或退休时分配。
- 多核时使用全局计数器，各核读取可能交错；每核内部仍保持程序顺序，但编号可能不连续。
- `instr_id` 不是 uop ID，也不是单次 memory access ID。

ChampSim 利用 `instr_id` 维护 ROB 程序、寄存器依赖、LQ/SQ 关联、Cache 返回匹配和指令退休。

## 4. Pin tracer 的指令粒度

工程中的 Pin tracer 会对每条 Pin `INS` 进行一次插桩。它会收集：

- 指令 IP；
- 分支信息；
- 输入和输出寄存器；
- 该指令所有 memory operand 的有效地址。

最后每条 `INS` 只调用一次 `WriteCurrentInstruction()`，因此一条完整的 x86 架构指令只生成一条 trace record。

这意味着 ChampSim 并没有在仿真时重新执行完整的 x86 译码，trace 格式也没有提供每个硬件 uop 的信息。

## 5. 一个 instr_id 可以包含多个内存操作

`input_instr` 中保留了 memory operand 数组。普通 trace 格式最多可以记录：

- 4 个 `source_memory`；
- 2 个 `destination_memory`。

ChampSim 将每个非零 `source_memory` 地址建立为一个 LQ entry，将每个非零 `destination_memory` 地址建立为一个 SQ entry。这些 entry 都继承父指令的同一个 `instr_id`。

```text
instr_id = 100

ROB entry:
  动态架构指令 100

LQ entries:
  load address A, instr_id = 100
  load address B, instr_id = 100

SQ entry:
  store address C, instr_id = 100
```

这不表示一个 `instr_id` 包含了多条独立的动态指令，而是表示同一条动态架构指令具有多个 memory operand/access。

## 6. ROB、LQ 和 SQ 的关系

一条 CISC 指令无论包含多少个 memory operand，在当前 ChampSim 中都只占用一个 ROB entry。

它的内存操作分别占用 LQ/SQ 资源：

```text
每个 source_memory      -> 一个 LQ entry
每个 destination_memory -> 一个 SQ entry
整条父指令          -> 一个 ROB entry
```

每完成一个 LSQ 内存操作，ChampSim 都会增加父 ROB entry 的 `completed_mem_ops`。指令总内存操作数为：

```cpp
num_mem_ops() = source_memory.size() + destination_memory.size();
```

只有当：

```text
completed_mem_ops == num_mem_ops()
```

并且指令的其他执行条件已完成时，ROB entry 才会被标记为 completed，然后按程序顺序退休。

## 7. 内存操作展开不等于完整 uop 拆分

真实 x86 处理器可能将一条 CISC 指令拆成多个 uop，例如地址生成、load、ALU 计算和 store 等。当前 ChampSim 不会建立这些独立 uop，也没有 `uop_id`。

它仅对 memory operand 做 LSQ 粒度的展开，不会显式建模：

- 独立的 AGU uop；
- 每个 uop 的 scheduler entry；
- 不同执行端口之间的竞争；
- 微码指令的内部序列；
- uop fusion 或 micro-fusion；
- 真实硬件中的每 uop 延时。

因此，memory operand 展开是一种为了建模内存系统而使用的简化，不是通用的 CISC-to-uop 译码模型。

## 8. 内存指令相对建模得更细

对于实际会拆成多个 uop 的非内存 CISC 指令，ChampSim 通常仍然将其视为一条普通指令：

- 占用一个 ROB entry；
- 消耗一个指令粒度的 decode/dispatch/execute 带宽；
- 使用配置中的通用流水线延时；
- 不根据真实 uop 数增加 ROB、scheduler 或执行端口占用。

但是，显式内存操作会分别经历：

- LQ/SQ 容量和 issue 带宽；
- load/store 依赖和 store-to-load forwarding；
- DTLB、STLB 和 PTW；
- L1D、L2C、LLC 和 DRAM；
- Cache queue、MSHR、fill 和返回延时。

所以 ChampSim 对内存行为的建模比对通用 uop 执行的建模更细，也更适合用于 Cache、TLB、PTW、prefetcher 和 DRAM 研究。

## 9. instr_id 不能唯一标识内存访问

由于多个 LQ/SQ entry 可以共享同一个 `instr_id`，因此不能只用 `instr_id` 区分每次内存访问。

需要区分同一条指令的多个 memory operand 时，可以使用：

```text
(instr_id, operand_type, operand_index)
```

如果要记录 Cache/TLB 端口看到的严格访问顺序，更合适的方式是额外分配全局或每结构递增的 `access_id`。LQ index 会被循环复用，不适合当作长期唯一身份。

此外，prefetch 不是 trace 中的动态指令。当前 `prefetch_line()` 创建的预取请求没有独立的动态指令身份，不应使用其 `instr_id` 作为唯一 prefetch ID。

## 10. 当前模型的主要限制

1. JSON 中的 decode/dispatch/execute width 更接近“每周期 trace 指令数”，不能严格解释为真实 x86 处理器的 uop/cycle。
2. 一条真实会产生多个 uop 的复杂非内存指令，在 ChampSim 中可能被过度简化。
3. trace 格式主要保存内存地址，没有完整的访问长度和 uop 描述；ChampSim 不会在这一层自动将跨 Cache line 的访问拆成多个请求。
4. 这些简化对 Cache/TLB/prefetcher 研究通常是可接受的，但不适合直接用来精确复现真实 x86 核心的 uop 级前端和执行端口行为。

## 11. 关键源码位置

- `tracer/pin/champsim_tracer.cpp`：按 Pin `INS` 粒度生成 trace record，收集寄存器和 memory operand。
- `inc/trace_instruction.h`：定义 trace record 中的寄存器和内存操作数组。
- `inc/tracereader.h`：为每条读取到的动态指令分配 `instr_id`。
- `inc/instruction.h`：定义 `ooo_model_instr`、memory operand 列表和 `num_mem_ops()`。
- `src/ooo_cpu.cc`：建立 ROB/LQ/SQ entry，追踪 `completed_mem_ops`，完成并退休指令。

