# GCC L1D/STLB Footprint Characterization

这个 case 固定跑 SPEC17 `602.gcc_s-2226B` trace，用两个 ChampSim JSON 配置生成两个 bin：

- `nol1pref`：L1D prefetcher = `no`
- `l1pref`：L1D prefetcher = `vberti`

默认 trace：

```text
/data0/tzh/champsim_traces/SPEC17/602.gcc_s-2226B.champsimtrace.xz
```

默认运行长度：

```text
N_WARM=1
N_SIM=1
```

这里的单位是 million instructions，可以在命令行用环境变量覆盖。

## 输出结构

```text
result/nol1pref/
result/l1pref/
csv_figure/01_nol1pref_l1d_access/
csv_figure/02_nol1pref_stlb_full_access/
csv_figure/03_nol1pref_stlb_full_miss/
csv_figure/04_l1pref_stlb_demand_access/
csv_figure/05_l1pref_stlb_l1d_prefetch_access/
csv_figure/06_l1pref_stlb_full_miss/
csv_figure/07_l1pref_dtlb_demand_access/
csv_figure/08_l1pref_dtlb_l1d_prefetch_access/
```

## 八组 footprint

1. `nol1pref` 下的 L1D demand access footprint。
2. `nol1pref` 下的 STLB full access footprint。
3. `nol1pref` 下的 STLB full miss footprint。
4. `l1pref` 下的 STLB demand footprint，即 `Demand_Data + Demand_Instruction`。
5. `l1pref` 下由 L1D prefetch 触发的 STLB footprint。
6. `l1pref` 下的 STLB full miss footprint。
7. `l1pref` 下 DTLB 输入端看到的 demand footprint。
8. `l1pref` 下 DTLB 输入端看到的 L1D prefetch footprint。

## 运行

```bash
cd /home/zcq/git_prj/ChampSim/launch_sim_characterization/gcc-l1pref-stlb-footprint
N_WARM=1 N_SIM=1 ./scripts/run_all.sh
```

只做后处理：

```bash
cd /home/zcq/git_prj/ChampSim/launch_sim_characterization/gcc-l1pref-stlb-footprint
./scripts/postprocess.sh
```

如果已有完整 log 和 CSV，默认会跳过仿真；需要强制重跑：

```bash
SKIP_EXISTING=0 N_WARM=1 N_SIM=1 ./scripts/run_all.sh
```
