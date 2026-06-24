# ChampSim JSON 配置逐项说明

参考配置：

`/home/zcq/git_prj/champsim_ideal_stlb_ipc_upperbound/launch_sim/1core-spec0617_gapligra-idealTLB-select-trace-compare/ideal-all-workload-sweep/1C.fullBW.stlb.stats.json`

说明：下面使用 `#` 写注释，便于阅读；这不是合法 JSON 格式，不能直接作为 ChampSim 输入配置。真正用于 `./config.sh` 的文件仍然必须是不带 `#` 注释的标准 JSON。

```text
{
  "executable_name": "tlb-ideal-all-1core", # 最终生成的 ChampSim binary 名字，通常对应 bin/<executable_name>
  "block_size": 64, # cache line 大小，单位 byte；本配置中一个 cache block 为 64B
  "page_size": 4096, # 虚拟内存页大小，单位 byte；4096 表示 4KB page
  "heartbeat_frequency": 100000, # heartbeat 打印间隔，单位通常是 retired instruction 数
  "num_cores": 1, # 模拟的 CPU core 数量

  "ooo_cpu": [ # OoO CPU core 配置数组；多核时可以配置多个 core，单核时只有一个对象
    {
      "frequency": 4000, # CPU 频率，单位 MHz；4000 表示 4GHz
      "ifetch_buffer_size": 64,         # instruction fetch buffer,取指队列，类似于FDIP的Queue
      "decode_buffer_size": 32,         # decode buffer，存放已经取好的指令，等待解码
      "dispatch_buffer_size": 32,       # 存放已经解码完的指令，等待dispatch
      "register_file_size": 288,        # 物理寄存器文件大小
      "rob_size": 352,                  # reorder buffer 项数，决定最多在飞指令窗口大小
      "lq_size": 240, # load queue 项数
      "sq_size": 112, # store queue 项数
      "fetch_width": 6, # 每周期最多 fetch 的指令数
      "decode_width": 6, # 每周期最多 decode 的指令数
      "dispatch_width": 6, # 每周期最多 dispatch/rename 的指令数
      "execute_width": 6, # 每周期最多 issue/execute 的指令数
      "lq_width": 2, # 每周期 load queue 可处理的 load 数或 load 带宽
      "sq_width": 2, # 每周期 store queue 可处理的 store 数或 store 带宽
      "retire_width": 6, # 每周期最多 retire/commit 的指令数
      "mispredict_penalty": 1, # 分支预测错误额外惩罚周期；1 表示非常低的恢复惩罚
      "scheduler_size": 160, # scheduler / issue queue 项数
      "decode_latency": 1, # decode 阶段延迟，单位 cycle
      "dispatch_latency": 1, # dispatch/rename 阶段延迟，单位 cycle
      "schedule_latency": 0, # schedule 阶段额外延迟，单位 cycle
      "execute_latency": 0, # execute 阶段额外基础延迟，单位 cycle
      "branch_predictor": "perceptron", # 分支预测器模块名，对应 branch/ 目录下的模块
      "btb": "basic_btb" # BTB 模块名，对应 btb/ 目录下的模块
    }
  ],

  "DIB": {                  # Decoded Instruction Buffer，保存已解码指令，前端uopCache
    "window_size": 16, # DIB 查找或管理窗口大小
    "sets": 512, # DIB set 数
    "ways": 8 # DIB 组相联路数
  },

  "L1I": { # 一级指令 cache
    "sets": 64, # L1I set 数；容量 = sets * ways * block_size = 64*8*64B = 32KB
    "ways": 8, # L1I 组相联路数
    "rq_size": 64, # read queue/request queue 大小
    "wq_size": 64, # write queue 大小；I-cache 一般写请求很少，但接口仍有该队列
    "pq_size": 32, # prefetch queue 大小
    "mshr_size": 8, # MSHR 项数，决定可同时挂起的 miss 数
    "latency": 4, # 命中访问延迟，单位 cycle
    "max_tag_check": 2, # 每周期最多进行 tag lookup/check 的请求数
    "max_fill": 2, # 每周期最多从下层 fill 回来的 cache line 数
    "prefetch_as_load": false, # prefetch 请求是否按 load 统计/处理；false 表示保持 prefetch 类型
    "virtual_prefetch": true, # prefetcher 产生的地址是否可使用虚拟地址；true 表示 L1I prefetch 可先基于 VA 工作
    "prefetch_activate": "LOAD,PREFETCH", # 哪些访问类型触发 prefetcher
    "prefetcher": "next_line", # L1I 使用 next_line 预取器
    "replacement": "lru" # L1I 替换策略为 LRU
  },

  "L1D": { # 一级数据 cache
    "sets": 64, # L1D set 数；容量 = 64*12*64B = 48KB
    "ways": 12, # L1D 组相联路数
    "rq_size": 64, # read/request queue 大小
    "wq_size": 64, # write queue 大小
    "pq_size": 8, # prefetch queue 大小
    "mshr_size": 16, # MSHR 项数
    "latency": 5, # L1D 命中访问延迟，单位 cycle
    "max_tag_check": 2, # 每周期最多 tag lookup/check 数
    "max_fill": 2, # 每周期最多 fill 数
    "prefetch_as_load": false, # prefetch 不当作普通 load 处理
    "virtual_prefetch": true, # L1D prefetcher 可基于虚拟地址产生预取
    "prefetch_activate": "LOAD,PREFETCH", # load 和 prefetch 访问都可触发预取器
    "prefetcher": "berti", # L1D 使用 berti 预取器
    "replacement": "lru" # L1D 替换策略为 LRU
  },

  "L2C": { # 二级 cache
    "sets": 1024, # L2 set 数；容量 = 1024*8*64B = 512KB
    "ways": 8, # L2 组相联路数
    "rq_size": 32, # read/request queue 大小
    "wq_size": 32, # write queue 大小
    "pq_size": 16, # prefetch queue 大小
    "mshr_size": 32, # MSHR 项数
    "latency": 10, # L2 命中访问延迟，单位 cycle
    "max_tag_check": 1, # 每周期最多 tag lookup/check 数
    "max_fill": 1, # 每周期最多 fill 数
    "prefetch_as_load": false, # prefetch 不当作普通 load 处理
    "virtual_prefetch": false, # L2 prefetch 使用物理地址侧信息
    "prefetch_activate": "LOAD,PREFETCH", # load 和 prefetch 访问都可触发预取器
    "prefetcher": "pythia", # L2 使用 pythia 预取器
    "replacement": "lru" # L2 替换策略为 LRU
  },

  "ITLB": { # 一级指令 TLB
    "sets": 16, # ITLB set 数；entry 数 = sets * ways = 64
    "ways": 4, # ITLB 组相联路数
    "rq_size": 16, # read/request queue 大小
    "wq_size": 16, # write queue 大小
    "pq_size": 0, # prefetch queue 大小；0 表示该层不接收 TLB prefetch queue
    "mshr_size": 8, # MSHR 项数，决定可同时挂起的 TLB miss 数
    "latency": 1, # ITLB 命中延迟，单位 cycle
    "max_tag_check": 2, # 每周期最多 TLB tag lookup/check 数
    "max_fill": 2, # 每周期最多 fill 的翻译项数
    "prefetch_as_load": false # prefetch 不按 load 处理
  },

  "DTLB": { # 一级数据 TLB
    "sets": 16, # DTLB set 数；entry 数 = 16*4 = 64
    "ways": 4, # DTLB 组相联路数
    "rq_size": 16, # read/request queue 大小
    "wq_size": 16, # write queue 大小
    "pq_size": 0, # prefetch queue 大小
    "mshr_size": 8, # MSHR 项数
    "latency": 1, # DTLB 命中延迟，单位 cycle
    "max_tag_check": 2, # 每周期最多 tag lookup/check 数
    "max_fill": 2, # 每周期最多 fill 的翻译项数
    "prefetch_as_load": false # prefetch 不按 load 处理
  },

  "STLB": { # 二级 unified TLB / shared TLB
    "sets": 128, # STLB set 数；entry 数 = 128*12 = 1536
    "ways": 12, # STLB 组相联路数
    "rq_size": 32, # read/request queue 大小
    "wq_size": 32, # write queue 大小
    "pq_size": 0, # prefetch queue 大小
    "mshr_size": 16, # MSHR 项数，决定可并行等待 PTW 的 STLB miss 数
    "latency": 8, # STLB 命中延迟，单位 cycle
    "max_tag_check": 1, # 每周期最多 STLB tag lookup/check 数
    "max_fill": 1, # 每周期最多 fill 的翻译项数
    "prefetch_as_load": false # prefetch 不按 load 处理
  },

  "PTW": { # Page Table Walker 和 Page Structure Cache 配置
    "pscl5_set": 1, # L5 page-structure cache set 数
    "pscl5_way": 2, # L5 page-structure cache 路数
    "pscl4_set": 1, # L4 page-structure cache set 数
    "pscl4_way": 4, # L4 page-structure cache 路数
    "pscl3_set": 2, # L3 page-structure cache set 数
    "pscl3_way": 4, # L3 page-structure cache 路数
    "pscl2_set": 4, # L2 page-structure cache set 数
    "pscl2_way": 8, # L2 page-structure cache 路数
    "rq_size": 16, # PTW request queue 大小
    "mshr_size": 5, # PTW MSHR 项数，限制可并行处理的 page walk 数量
    "max_read": 2, # PTW 每周期最多发出的读请求数量
    "max_write": 2 # PTW 每周期最多处理/发出的写类请求数量
  },

  "LLC": { # Last-Level Cache，单核配置中通常就是该 core 的 LLC slice
    "frequency": 4000, # LLC 频率，单位 MHz
    "sets": 2048, # LLC set 数；容量 = 2048*16*64B = 2MB
    "ways": 16, # LLC 组相联路数
    "rq_size": 32, # read/request queue 大小
    "wq_size": 32, # write queue 大小
    "pq_size": 32, # prefetch queue 大小
    "mshr_size": 64, # MSHR 项数
    "latency": 20, # LLC 命中访问延迟，单位 cycle
    "max_tag_check": 1, # 每周期最多 tag lookup/check 数
    "max_fill": 1, # 每周期最多 fill 数
    "prefetch_as_load": false, # prefetch 不按普通 load 处理
    "virtual_prefetch": false, # LLC prefetch 使用物理地址侧信息
    "prefetch_activate": "LOAD,PREFETCH", # load 和 prefetch 访问都可触发 LLC prefetcher
    "prefetcher": "no", # LLC 不启用预取器
    "replacement": "drrip" # LLC 替换策略为 DRRIP
  },

  "physical_memory": { # DRAM/物理内存模型配置
    "data_rate": 3200, # DRAM 数据传输率，单位 MT/s；3200 表示 DDR4-3200 级别的数据率
    "channels": 1, # DRAM channel 数
    "ranks": 1, # 每个 channel 的 rank 数
    "bankgroups": 8, # 每个 rank 的 bank group 数
    "banks": 4, # 每个 bank group 的 bank 数；总 bank 数 = channels*ranks*bankgroups*banks
    "bank_rows": 16384, # 每个 bank 的 row 数
    "bank_columns": 1024, # 每个 row 的 column 数
    "channel_width": 8, # channel 数据宽度，单位 byte；8 表示 64-bit data bus
    "wq_size": 64, # memory controller write queue 大小
    "rq_size": 64, # memory controller read queue 大小
    "tCAS": 24, # DRAM CAS latency，单位 memory clock cycle
    "tRCD": 24, # row activate 到 column access 的延迟，单位 memory clock cycle
    "tRP": 24, # precharge 延迟，单位 memory clock cycle
    "tRAS": 52, # row active 最短保持时间，单位 memory clock cycle
    "refresh_period": 32, # refresh 周期窗口，ChampSim 配置单位按内部 DRAM 模型解释
    "refreshes_per_period": 8192 # 每个 refresh period 内的 refresh 次数/目标刷新粒度
  },

  "virtual_memory": { # 虚拟内存和页表模型配置
    "pte_page_size": 4096, # 页表页大小，单位 byte；通常等于 page_size
    "num_levels": 5, # 页表层级数；5 表示 5-level page walk/5 级页表
    "minor_fault_penalty": 200, # minor page fault 或首次建立虚实映射时的惩罚，单位 cycle
    "randomization": 1 # 虚拟页到物理页映射随机化开关/强度；1 表示启用随机化
  }
}
```

## 常用换算

- Cache 容量：`sets * ways * block_size`。
- TLB entry 数：`sets * ways`。
- L1I：`64 * 8 * 64B = 32KB`。
- L1D：`64 * 12 * 64B = 48KB`。
- L2C：`1024 * 8 * 64B = 512KB`。
- LLC：`2048 * 16 * 64B = 2MB`。
- ITLB/DTLB：`16 * 4 = 64 entries`。
- STLB：`128 * 12 = 1536 entries`。

## 注意

- `prefetcher` 和 `replacement` 是模块名字，最终由 `config.sh` 根据 JSON 生成配置中间文件，并由 Makefile 编译/链接对应模块。
- `latency`、`max_tag_check`、`max_fill`、`mshr_size` 共同决定 cache/TLB 的命中延迟、端口带宽、fill 带宽和 miss 并发度。
- 这份 `ideal-all` 配置本身只描述硬件结构和模块选择；ideal STLB 的行为还依赖本工程额外加入的 `stlb_ideal_mode` 相关构建/运行配置与源码逻辑。
