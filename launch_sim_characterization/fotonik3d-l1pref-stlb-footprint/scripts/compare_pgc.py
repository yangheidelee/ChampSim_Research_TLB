#!/usr/bin/env python3
import csv
import math
import re
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
CASE_DIR = SCRIPT_DIR.parent
TRACE_TAG = "649.fotonik3d_s-10881B"

PERMIT_LOG = CASE_DIR / "result" / "l1pref" / f"{TRACE_TAG}-fotonik3d-footprint-l1pref-1core.log"
DISCARD_LOG = CASE_DIR / "result" / "discard_pgc" / f"{TRACE_TAG}-fotonik3d-footprint-discard-pgc-1core.log"
OUT_DIR = CASE_DIR / "csv_figure" / "pgc_compare"


def parse_log(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit(f"Missing log: {path}")

    data = {}
    ipc_re = re.compile(r"CPU 0 cumulative IPC:\s+([0-9.]+)\s+instructions:\s+([0-9]+)\s+cycles:\s+([0-9]+)")
    kv_re = re.compile(r"^([A-Za-z0-9_]+)\s+([-+0-9.eE]+)$")
    berti_re = re.compile(r"^BERTI CROSS_PAGE\s+([0-9]+)\s+NO_CROSS_PAGE:\s+([0-9]+)")

    for line in path.read_text(errors="replace").splitlines():
        if m := ipc_re.search(line):
            data["ipc"] = float(m.group(1))
            data["instructions"] = int(m.group(2))
            data["cycles"] = int(m.group(3))
            continue
        if m := berti_re.search(line):
            data["berti_cross_page"] = int(m.group(1))
            data["berti_no_cross_page"] = int(m.group(2))
            continue
        if m := kv_re.match(line.strip()):
            key, value = m.groups()
            try:
                data[key] = float(value)
            except ValueError:
                pass

    required = ["ipc", "instructions", "Core_0_DTLB_demand_MPKI", "Core_0_STLB_Demand_miss"]
    missing = [k for k in required if k not in data]
    if missing:
        raise SystemExit(f"Missing keys in {path}: {missing}")

    data["demand_dtlb_mpki"] = data["Core_0_DTLB_demand_MPKI"]
    data["demand_stlb_mpki"] = data["Core_0_STLB_Demand_miss"] / data["instructions"] * 1000.0
    return data


def pct_delta(new: float, base: float) -> float:
    if base == 0:
        return math.nan
    return (new / base - 1.0) * 100.0


def trend_same(ipc_speedup: float, mpki_change_pct: float) -> int:
    ipc_better = ipc_speedup > 1.0
    tlb_better = mpki_change_pct < 0.0
    ipc_worse = ipc_speedup < 1.0
    tlb_worse = mpki_change_pct > 0.0
    return int((ipc_better and tlb_better) or (ipc_worse and tlb_worse) or (ipc_speedup == 1.0 and mpki_change_pct == 0.0))


def fmt(x: float) -> str:
    if math.isnan(x):
        return "nan"
    return f"{x:.6g}"


def pct_str(x: float) -> str:
    return fmt(x) + "%"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    permit = parse_log(PERMIT_LOG)
    discard = parse_log(DISCARD_LOG)

    ipc_speedup = permit["ipc"] / discard["ipc"]
    dtlb_change = pct_delta(permit["demand_dtlb_mpki"], discard["demand_dtlb_mpki"])
    stlb_change = pct_delta(permit["demand_stlb_mpki"], discard["demand_stlb_mpki"])
    dtlb_trend_same = trend_same(ipc_speedup, dtlb_change)
    stlb_trend_same = trend_same(ipc_speedup, stlb_change)

    row = {
        "trace": TRACE_TAG,
        "baseline": "Discard PGC",
        "compare": "Permit PGC",
        "permit_ipc_change_pct": pct_str((ipc_speedup - 1.0) * 100.0),
        "permit_demand_dtlb_mpki_change_pct": pct_str(dtlb_change),
        "demand_dtlb_trend_same": str(dtlb_trend_same),
        "permit_demand_stlb_mpki_change_pct": pct_str(stlb_change),
        "demand_stlb_trend_same": str(stlb_trend_same),
    }

    csv_path = OUT_DIR / "permit_vs_discard_pgc.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)

    md_path = OUT_DIR / "permit_vs_discard_pgc.md"
    with md_path.open("w") as f:
        f.write("# Permit PGC vs Discard PGC\n\n")
        f.write(f"- Trace: `{TRACE_TAG}`\n")
        f.write("- Baseline: `Discard PGC`，即 vberti 禁止跨页预取。\n")
        f.write("- Compare: `Permit PGC`，即 vberti 允许跨页预取。\n")
        f.write("- 所有 change 都是 `Permit PGC` 相对 `Discard PGC` 的变化百分比。\n")
        f.write("- `trend_same=1` 表示 IPC 方向与 TLB MPKI 方向一致：IPC 增长且 MPKI 降低，或 IPC 下降且 MPKI 升高。\n\n")
        f.write("## Summary\n\n")
        f.write("| Baseline | Compare | IPC change |\n")
        f.write("|---|---|---:|\n")
        f.write(f"| Discard PGC | Permit PGC | {row['permit_ipc_change_pct']} |\n\n")
        f.write("## TLB MPKI\n\n")
        f.write("| Metric | Permit change | trend_same |\n")
        f.write("|---|---:|---:|\n")
        f.write(
            f"| demand dTLB MPKI | {row['permit_demand_dtlb_mpki_change_pct']} | {row['demand_dtlb_trend_same']} |\n"
        )
        f.write(
            f"| demand STLB MPKI | {row['permit_demand_stlb_mpki_change_pct']} | {row['demand_stlb_trend_same']} |\n"
        )
        f.write("\n")
        f.write("说明：`demand_stlb_mpki` 由 `Core_0_STLB_Demand_miss / ROI instructions * 1000` 计算，避免把 L1D prefetch 来源的 STLB miss 混入 demand STLB MPKI。\n")

    print(f"[INFO] Wrote {csv_path}")
    print(f"[INFO] Wrote {md_path}")


if __name__ == "__main__":
    main()
