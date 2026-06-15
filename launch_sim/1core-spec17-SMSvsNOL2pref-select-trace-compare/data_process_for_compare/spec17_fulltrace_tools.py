#!/usr/bin/env python3
import argparse
import csv
import json
import math
import pathlib
import re
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


def log_warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")


def to_float(text: str) -> float:
    try:
        return float(str(text).strip())
    except ValueError:
        return math.nan


def to_int(text: str) -> Optional[int]:
    try:
        return int(float(str(text).strip()))
    except ValueError:
        return None


def finite(value: float) -> bool:
    return math.isfinite(value)


def fmt_float(value: float) -> str:
    return f"{value:.17g}" if finite(value) else "nan"


def safe_div(num: float, den: float) -> float:
    if not finite(num) or not finite(den) or den == 0:
        return math.nan
    return num / den


def amean(values: List[float]) -> float:
    vals = [v for v in values if finite(v)]
    return sum(vals) / len(vals) if vals else math.nan


def geomean(values: List[float]) -> float:
    vals = [v for v in values if finite(v) and v > 0]
    return math.exp(sum(math.log(v) for v in vals) / len(vals)) if vals else math.nan


def parse_trace_name(name: str) -> Optional[Tuple[str, str, int]]:
    match = re.match(r"^(6\d\d\.[A-Za-z0-9_]+)-(\d+)B\.champsimtrace\.(?:xz|gz)$", name)
    if not match:
        return None
    bench = match.group(1)
    sid = int(match.group(2))
    return bench, f"{bench}-{sid}B", sid


def parse_trace_tag(trace_tag: str) -> Optional[Tuple[str, int]]:
    match = re.match(r"^(6\d\d\.[A-Za-z0-9_]+)-(\d+)B$", trace_tag)
    if not match:
        return None
    return match.group(1), int(match.group(2))


def read_tokens(path: pathlib.Path) -> List[List[str]]:
    rows = []
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            rows.append(line.split())
    return rows


def build_weight_map(args: argparse.Namespace) -> None:
    trace_dir = pathlib.Path(args.trace_dir)
    weight_dir = pathlib.Path(args.weight_dir)
    out_csv = pathlib.Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    if not trace_dir.is_dir():
        raise SystemExit(f"TRACE_DIR does not exist: {trace_dir}")
    if not weight_dir.is_dir():
        raise SystemExit(f"WEIGHT_DIR does not exist: {weight_dir}")

    available: Dict[str, Dict[int, str]] = defaultdict(dict)
    for path in sorted(trace_dir.glob("6*.champsimtrace.xz")) + sorted(trace_dir.glob("6*.champsimtrace.gz")):
        parsed = parse_trace_name(path.name)
        if parsed:
            bench, trace_tag, sid = parsed
            available[bench][sid] = trace_tag

    rows: List[Dict[str, object]] = []
    all_benchmarks = sorted({p.name for p in weight_dir.iterdir() if p.is_dir() and re.match(r"^6\d\d\.", p.name)} | set(available.keys()))

    for bench in all_benchmarks:
        sim_path = weight_dir / bench / "simpoints.out"
        wt_path = weight_dir / bench / "weights.out"
        avail = available.get(bench, {})
        sid_to_weight: Dict[int, float] = {}

        if sim_path.exists() and wt_path.exists():
            sim_rows = read_tokens(sim_path)
            wt_rows = read_tokens(wt_path)
            if {len(r) for r in sim_rows} == {1} and {len(r) for r in wt_rows} == {1}:
                for sim_row, wt_row in zip(sim_rows, wt_rows):
                    sid = to_int(sim_row[0])
                    if sid is not None:
                        sid_to_weight[sid] = to_float(wt_row[0])
            else:
                cluster_to_sid: Dict[int, int] = {}
                for row in sim_rows:
                    if len(row) >= 2:
                        sid = to_int(row[0])
                        cid = to_int(row[1])
                        if sid is not None and cid is not None:
                            cluster_to_sid[cid] = sid

                cluster_to_weight: Dict[int, float] = {}
                for row in wt_rows:
                    if len(row) >= 2:
                        first_f = to_float(row[0])
                        second_i = to_int(row[1])
                        first_i = to_int(row[0])
                        second_f = to_float(row[1])
                        if finite(first_f) and second_i is not None:
                            cluster_to_weight[second_i] = first_f
                        elif finite(second_f) and first_i is not None:
                            cluster_to_weight[first_i] = second_f

                for cid, sid in cluster_to_sid.items():
                    if cid in cluster_to_weight:
                        sid_to_weight[sid] = cluster_to_weight[cid]
        elif avail:
            log_warn(f"{bench} has traces but missing simpoint files under {weight_dir / bench}; weights will be uniform downstream")

        available_weight_sum = sum(w for sid, w in sid_to_weight.items() if sid in avail and finite(w) and w >= 0)
        for sid in sorted(set(sid_to_weight) | set(avail)):
            trace_tag = avail.get(sid, f"{bench}-{sid}B")
            raw_w = sid_to_weight.get(sid, math.nan)
            norm_w = raw_w / available_weight_sum if sid in avail and finite(raw_w) and available_weight_sum > 0 else math.nan
            rows.append({
                "benchmark": bench,
                "trace_name": f"{trace_tag}.champsimtrace.xz",
                "trace_tag": trace_tag,
                "simpoint_id": sid,
                "raw_weight": raw_w,
                "normalized_weight": norm_w,
                "available_weight_sum": available_weight_sum,
                "is_available": 1 if sid in avail else 0,
            })

    with out_csv.open("w", newline="") as f:
        fieldnames = ["benchmark", "trace_name", "trace_tag", "simpoint_id", "raw_weight", "normalized_weight", "available_weight_sum", "is_available"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (str(r["benchmark"]), int(r["simpoint_id"]))):
            writer.writerow({
                "benchmark": row["benchmark"],
                "trace_name": row["trace_name"],
                "trace_tag": row["trace_tag"],
                "simpoint_id": row["simpoint_id"],
                "raw_weight": fmt_float(float(row["raw_weight"])),
                "normalized_weight": fmt_float(float(row["normalized_weight"])),
                "available_weight_sum": fmt_float(float(row["available_weight_sum"])),
                "is_available": row["is_available"],
            })

    log_info(f"weight map written: {out_csv}")


def extract_metric(text: str, key: str, default: float = math.nan) -> float:
    match = re.search(rf"^{re.escape(key)}\s+([-.+0-9A-Za-z]+)$", text, flags=re.MULTILINE)
    return to_float(match.group(1)) if match else default


def extract_metrics_from_result(path: pathlib.Path) -> Dict[str, float]:
    text = path.read_text(errors="ignore")
    roi_pos = text.find("[ROI Statistics]")
    metric_text = text[roi_pos:] if roi_pos != -1 else text

    metrics = {
        "instructions": extract_metric(metric_text, "Core_0_instructions"),
        "cycles": extract_metric(metric_text, "Core_0_cycles"),
        "ipc": extract_metric(metric_text, "Core_0_IPC"),
        "l1d_demand_access": extract_metric(metric_text, "Core_0_L1D_demand_access", 0.0),
        "l1d_demand_miss": extract_metric(metric_text, "Core_0_L1D_demand_miss", 0.0),
        "l1d_demand_miss_rate": extract_metric(metric_text, "Core_0_L1D_demand_miss_rate", 0.0),
        "l2c_demand_access": extract_metric(metric_text, "Core_0_L2C_demand_access", 0.0),
        "l2c_demand_miss": extract_metric(metric_text, "Core_0_L2C_demand_miss", 0.0),
        "l2c_demand_miss_rate": extract_metric(metric_text, "Core_0_L2C_demand_miss_rate", 0.0),
        "llc_demand_access": extract_metric(metric_text, "Core_0_LLC_demand_access", 0.0),
        "llc_demand_miss": extract_metric(metric_text, "Core_0_LLC_demand_miss", 0.0),
        "llc_demand_miss_rate": extract_metric(metric_text, "Core_0_LLC_demand_miss_rate", 0.0),
        "l2c_prefetch_requested": extract_metric(metric_text, "Core_0_L2C_prefetch_requested", 0.0),
        "l2c_prefetch_issued": extract_metric(metric_text, "Core_0_L2C_prefetch_issued", 0.0),
        "l2c_prefetch_useful": extract_metric(metric_text, "Core_0_L2C_prefetch_useful", 0.0),
        "l2c_prefetch_useless": extract_metric(metric_text, "Core_0_L2C_prefetch_useless", 0.0),
        "l2c_prefetch_late": extract_metric(metric_text, "Core_0_L2C_prefetch_late", 0.0),
        "l2c_prefetch_accuracy": extract_metric(metric_text, "Core_0_L2C_prefetch_accuracy", 0.0),
        "l2c_prefetch_coverage": extract_metric(metric_text, "Core_0_L2C_prefetch_coverage", 0.0),
    }

    if not finite(metrics["ipc"]) and finite(metrics["instructions"]) and finite(metrics["cycles"]):
        metrics["ipc"] = safe_div(metrics["instructions"], metrics["cycles"])
    return metrics


def load_weight_map(path: pathlib.Path) -> Dict[Tuple[str, str], Dict[str, float]]:
    result: Dict[Tuple[str, str], Dict[str, float]] = {}
    if not path.exists():
        return result
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bench = (row.get("benchmark") or "").strip()
            trace_tag = (row.get("trace_tag") or "").strip()
            if bench and trace_tag:
                result[(bench, trace_tag)] = {
                    "simpoint_id": to_float(row.get("simpoint_id", "nan")),
                    "raw_weight": to_float(row.get("raw_weight", "nan")),
                    "normalized_weight": to_float(row.get("normalized_weight", "nan")),
                    "available_weight_sum": to_float(row.get("available_weight_sum", "nan")),
                    "is_available": to_float(row.get("is_available", "nan")),
                }
    return result


def parse_trace_tag_from_result_filename(name: str) -> Optional[str]:
    match = re.match(r"^(6\d\d\.[A-Za-z0-9_]+-\d+B)-.*\.log$", name)
    return match.group(1) if match else None


def collect_trace_rows(args: argparse.Namespace) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, float]]]:
    result_dir = pathlib.Path(args.result_dir)
    if not result_dir.is_dir():
        raise SystemExit(f"Result directory not found: {result_dir}")

    weight_map = load_weight_map(pathlib.Path(args.weight_map_csv))
    select_trace_json = getattr(args, "select_trace_json", "")
    selected_tags = load_selected_trace_tags(pathlib.Path(select_trace_json)) if select_trace_json else None
    rows: List[Dict[str, object]] = []
    bench_weight_sum_hint: Dict[str, float] = {}

    for path in sorted(result_dir.glob("*.log")):
        trace_tag = parse_trace_tag_from_result_filename(path.name)
        if not trace_tag:
            continue
        parsed = parse_trace_tag(trace_tag)
        if not parsed:
            continue
        bench, sid = parsed
        if selected_tags is not None and trace_tag not in selected_tags:
            continue
        metrics = extract_metrics_from_result(path)
        wm = weight_map.get((bench, trace_tag), {})
        norm_w = float(wm.get("normalized_weight", math.nan)) if wm else math.nan
        raw_w = float(wm.get("raw_weight", math.nan)) if wm else math.nan
        av_sum = float(wm.get("available_weight_sum", math.nan)) if wm else math.nan
        if finite(av_sum):
            bench_weight_sum_hint[bench] = av_sum

        row: Dict[str, object] = {
            "benchmark": bench,
            "trace_tag": trace_tag,
            "trace_name": f"{trace_tag}.champsimtrace.xz",
            "simpoint_id": sid,
            "weight": norm_w,
            "raw_weight": raw_w,
        }
        row.update(metrics)

        if not finite(float(row["ipc"])) or not finite(float(row["instructions"])) or not finite(float(row["cycles"])):
            log_warn(f"{path.name} missing critical IPC/instruction/cycle metrics")
        rows.append(row)

    rows.sort(key=lambda r: (str(r["benchmark"]), int(r["simpoint_id"])))
    return rows, {k: {"available_weight_sum": v} for k, v in bench_weight_sum_hint.items()}


def load_selected_trace_tags(path: pathlib.Path) -> Optional[set[str]]:
    if not str(path):
        return None
    if not path.exists():
        raise SystemExit(f"Selected trace JSON not found: {path}")
    payload = json.loads(path.read_text())
    selected: set[str] = set()
    for bench_payload in payload.get("benchmarks", {}).values():
        selected.update(str(tag) for tag in bench_payload.get("selected_trace_tags", []))
    return selected


TRACE_FIELDS = [
    "benchmark",
    "trace_tag",
    "trace_name",
    "simpoint_id",
    "weight",
    "raw_weight",
    "instructions",
    "ipc",
    "cycles",
    "l1d_demand_access_per_kinst",
    "l1d_demand_miss_per_kinst",
    "l1d_demand_miss_rate",
    "l2c_demand_access_per_kinst",
    "l2c_demand_miss_per_kinst",
    "l2c_demand_miss_rate",
    "llc_demand_access_per_kinst",
    "llc_demand_miss_per_kinst",
    "llc_demand_miss_rate",
    "l2c_prefetch_issued_per_kinst",
    "l2c_prefetch_accuracy",
    "l2c_prefetch_coverage",
    "l2c_prefetch_late_per_kinst",
]


def derived_trace_row(row: Dict[str, object]) -> Dict[str, object]:
    inst = float(row.get("instructions", math.nan))
    out = dict(row)
    for level in ["l1d", "l2c", "llc"]:
        out[f"{level}_demand_access_per_kinst"] = safe_div(float(row.get(f"{level}_demand_access", math.nan)), inst) * 1000
        out[f"{level}_demand_miss_per_kinst"] = safe_div(float(row.get(f"{level}_demand_miss", math.nan)), inst) * 1000
    out["l2c_prefetch_issued_per_kinst"] = safe_div(float(row.get("l2c_prefetch_issued", math.nan)), inst) * 1000
    out["l2c_prefetch_late_per_kinst"] = safe_div(float(row.get("l2c_prefetch_late", math.nan)), inst) * 1000
    return out


def write_trace_level_csv(rows: List[Dict[str, object]], out_csv: pathlib.Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRACE_FIELDS)
        writer.writeheader()
        for row in rows:
            drow = derived_trace_row(row)
            writer.writerow({k: drow[k] if not isinstance(drow.get(k), (int, float)) else fmt_float(float(drow[k])) for k in TRACE_FIELDS})


def weighted_sum(items: List[Tuple[float, float]]) -> float:
    vals = [w * x for w, x in items if finite(w) and finite(x)]
    return sum(vals) if vals else math.nan


def aggregate_benchmark(trace_rows: List[Dict[str, object]], available_weight_sum_hint: float) -> Dict[str, object]:
    bench = str(trace_rows[0]["benchmark"])
    valid = [r for r in trace_rows if finite(float(r.get("weight", math.nan))) and float(r["weight"]) >= 0]
    if valid:
        total_w = sum(float(r["weight"]) for r in valid)
        weights = {id(r): (float(r["weight"]) / total_w if total_w > 0 else 0.0) for r in valid}
        for r in trace_rows:
            weights.setdefault(id(r), 0.0)
    else:
        weights = {id(r): 1.0 / len(trace_rows) for r in trace_rows}
        log_warn(f"{bench} has no usable weights; fallback to uniform")

    drows = [derived_trace_row(r) for r in trace_rows]

    def wavg(key: str) -> float:
        return weighted_sum([(weights[id(orig)], float(d.get(key, math.nan))) for orig, d in zip(trace_rows, drows)])

    cpi = weighted_sum([(weights[id(r)], safe_div(float(r["cycles"]), float(r["instructions"]))) for r in trace_rows])
    ipc = safe_div(1.0, cpi)

    return {
        "benchmark": bench,
        "num_traces": len(trace_rows),
        "available_weight_sum": available_weight_sum_hint,
        "ipc": ipc,
        "cpi": cpi,
        "l1d_demand_access_per_kinst": wavg("l1d_demand_access_per_kinst"),
        "l1d_demand_miss_per_kinst": wavg("l1d_demand_miss_per_kinst"),
        "l1d_demand_miss_rate": wavg("l1d_demand_miss_rate"),
        "l2c_demand_access_per_kinst": wavg("l2c_demand_access_per_kinst"),
        "l2c_demand_miss_per_kinst": wavg("l2c_demand_miss_per_kinst"),
        "l2c_demand_miss_rate": wavg("l2c_demand_miss_rate"),
        "llc_demand_access_per_kinst": wavg("llc_demand_access_per_kinst"),
        "llc_demand_miss_per_kinst": wavg("llc_demand_miss_per_kinst"),
        "llc_demand_miss_rate": wavg("llc_demand_miss_rate"),
        "l2c_prefetch_issued_per_kinst": wavg("l2c_prefetch_issued_per_kinst"),
        "l2c_prefetch_accuracy": wavg("l2c_prefetch_accuracy"),
        "l2c_prefetch_coverage": wavg("l2c_prefetch_coverage"),
        "l2c_prefetch_late_per_kinst": wavg("l2c_prefetch_late_per_kinst"),
    }


BENCH_FIELDS = [
    "benchmark",
    "num_traces",
    "available_weight_sum",
    "ipc",
    "cpi",
    "l1d_demand_access_per_kinst",
    "l1d_demand_miss_per_kinst",
    "l1d_demand_miss_rate",
    "l2c_demand_access_per_kinst",
    "l2c_demand_miss_per_kinst",
    "l2c_demand_miss_rate",
    "llc_demand_access_per_kinst",
    "llc_demand_miss_per_kinst",
    "llc_demand_miss_rate",
    "l2c_prefetch_issued_per_kinst",
    "l2c_prefetch_accuracy",
    "l2c_prefetch_coverage",
    "l2c_prefetch_late_per_kinst",
]


def bench_sort_key(bench: str) -> Tuple[int, str]:
    match = re.match(r"^(\d+)", bench)
    return (int(match.group(1)) if match else 10**9, bench)


def summary_row(rows: List[Dict[str, object]]) -> Dict[str, object]:
    out: Dict[str, object] = {
        "benchmark": "SUMMARY",
        "num_traces": sum(int(r["num_traces"]) for r in rows),
        "available_weight_sum": amean([float(r["available_weight_sum"]) for r in rows]),
    }
    for field in BENCH_FIELDS:
        if field in out or field in {"benchmark", "num_traces", "available_weight_sum"}:
            continue
        vals = [float(r[field]) for r in rows]
        out[field] = geomean(vals) if field == "ipc" else amean(vals)
    return out


def write_benchmark_csv(rows: List[Dict[str, object]], out_csv: pathlib.Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: bench_sort_key(str(r["benchmark"])))
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BENCH_FIELDS)
        writer.writeheader()
        for row in rows + [summary_row(rows)]:
            writer.writerow({k: row[k] if not isinstance(row.get(k), (int, float)) else fmt_float(float(row[k])) for k in BENCH_FIELDS})


def plot_single_config(rows: List[Dict[str, object]], fig_png: pathlib.Path, fig_pdf: pathlib.Path, title: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception as exc:
        log_warn(f"matplotlib unavailable, skip plotting: {exc}")
        return

    rows = sorted(rows, key=lambda r: bench_sort_key(str(r["benchmark"])))
    srow = summary_row(rows)
    labels = [str(r["benchmark"]) for r in rows] + ["SUMMARY"]
    x = list(range(len(labels)))
    plots = [
        ("ipc", "IPC", "IPC", "#1f77b4"),
        ("l2c_demand_miss_rate", "L2C demand miss rate", "Rate", "#ff7f0e"),
        ("llc_demand_miss_rate", "LLC demand miss rate", "Rate", "#2ca02c"),
        ("llc_demand_access_per_kinst", "LLC demand access/KInst", "Access/KInst", "#9467bd"),
        ("llc_demand_miss_per_kinst", "LLC demand miss/KInst", "Miss/KInst", "#d62728"),
        ("l2c_prefetch_issued_per_kinst", "L2C prefetch issued/KInst", "Issued/KInst", "#8c564b"),
        ("l2c_prefetch_accuracy", "L2C prefetch accuracy", "Ratio", "#17becf"),
        ("l2c_prefetch_coverage", "L2C prefetch coverage", "Ratio", "#bcbd22"),
    ]

    fig, axes = plt.subplots(2, 4, figsize=(28, 10), dpi=220)
    axes = axes.ravel()
    for ax, (key, ttl, ylabel, color) in zip(axes, plots):
        vals = [float(r[key]) for r in rows] + [float(srow[key])]
        colors = [color] * len(vals)
        colors[-1] = "#222222"
        ax.bar(x, vals, color=colors, width=0.72)
        ax.set_title(ttl)
        ax.set_ylabel(ylabel)
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.55)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)

    fig.suptitle(title)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_png, bbox_inches="tight")
    fig.savefig(fig_pdf, bbox_inches="tight")


def run_single_config(args: argparse.Namespace) -> None:
    trace_rows, bench_hint = collect_trace_rows(args)
    if not trace_rows:
        raise SystemExit("No result .log files found for single-config processing")

    write_trace_level_csv(trace_rows, pathlib.Path(args.trace_level_csv))
    grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for row in trace_rows:
        grouped[str(row["benchmark"])].append(row)

    bench_rows = []
    for bench, rows in grouped.items():
        hint = float(bench_hint.get(bench, {}).get("available_weight_sum", math.nan))
        bench_rows.append(aggregate_benchmark(rows, hint))

    write_benchmark_csv(bench_rows, pathlib.Path(args.benchmark_agg_csv))
    if args.fig_png and args.fig_pdf:
        plot_single_config(bench_rows, pathlib.Path(args.fig_png), pathlib.Path(args.fig_pdf), args.figure_title)

    log_info(f"trace-level csv: {args.trace_level_csv}")
    log_info(f"benchmark-agg csv: {args.benchmark_agg_csv}")


def run_select_trace_json(args: argparse.Namespace) -> None:
    trace_rows, _ = collect_trace_rows(args)
    if not trace_rows:
        raise SystemExit("No result .log files found for selection processing")

    threshold = float(args.threshold)
    grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for row in trace_rows:
        grouped[str(row["benchmark"])].append(row)

    payload: Dict[str, object] = {
        "source_result_dir": str(pathlib.Path(args.result_dir).resolve()),
        "threshold": {
            "metric": "llc_demand_miss_per_kinst",
            "operator": ">",
            "value": threshold,
        },
        "benchmarks": {},
    }

    total_selected = 0
    for bench, rows in sorted(grouped.items(), key=lambda item: bench_sort_key(item[0])):
        all_tags: List[str] = []
        selected_tags: List[str] = []
        trace_metrics: Dict[str, Dict[str, object]] = {}
        for row in sorted(rows, key=lambda r: int(r["simpoint_id"])):
            trace_tag = str(row["trace_tag"])
            drow = derived_trace_row(row)
            llc_mpki = float(drow.get("llc_demand_miss_per_kinst", math.nan))
            l2c_mpki = float(drow.get("l2c_demand_miss_per_kinst", math.nan))
            all_tags.append(trace_tag)
            trace_metrics[trace_tag] = {
                "simpoint_id": int(row["simpoint_id"]),
                "instructions": fmt_float(float(row.get("instructions", math.nan))),
                "llc_demand_miss_per_kinst": fmt_float(llc_mpki),
                "l2c_demand_miss_per_kinst": fmt_float(l2c_mpki),
            }
            if finite(llc_mpki) and llc_mpki > threshold:
                selected_tags.append(trace_tag)
                total_selected += 1

        payload["benchmarks"][bench] = {
            "all_trace_tags": all_tags,
            "selected_trace_tags": selected_tags,
            "trace_metrics": trace_metrics,
        }

    payload["summary"] = {
        "total_benchmarks": len(payload["benchmarks"]),
        "total_selected_traces": total_selected,
    }

    out_json = pathlib.Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    log_info(f"selected trace json: {out_json}")


def load_benchmark_csv(path: pathlib.Path) -> Dict[str, Dict[str, float]]:
    data: Dict[str, Dict[str, float]] = {}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bench = (row.get("benchmark") or "").strip()
            if bench and bench.upper() not in {"SUMMARY", "AVG", "GEOMEAN"}:
                data[bench] = {k: to_float(v) for k, v in row.items() if k != "benchmark"}
    return data


def reduction(new_value: float, base_value: float) -> float:
    return 1.0 - safe_div(new_value, base_value) if finite(base_value) and base_value != 0 else math.nan


COMPARE_FIELDS = [
    "benchmark",
    "base_ipc",
    "sms_ipc",
    "ipc_speedup",
    "ipc_speedup_pct",
    "base_l2c_demand_miss_rate",
    "sms_l2c_demand_miss_rate",
    "l2c_demand_miss_rate_reduction_pct",
    "base_llc_demand_access_per_kinst",
    "sms_llc_demand_access_per_kinst",
    "llc_demand_access_reduction_pct",
    "base_llc_demand_miss_per_kinst",
    "sms_llc_demand_miss_per_kinst",
    "llc_demand_miss_reduction_pct",
    "base_llc_demand_miss_rate",
    "sms_llc_demand_miss_rate",
    "llc_demand_miss_rate_reduction_pct",
    "sms_l2c_prefetch_issued_per_kinst",
    "sms_l2c_prefetch_accuracy",
    "sms_l2c_prefetch_coverage",
]


def compare_summary(rows: List[Dict[str, object]]) -> Dict[str, object]:
    out: Dict[str, object] = {"benchmark": "SUMMARY"}
    for field in COMPARE_FIELDS:
        if field == "benchmark":
            continue
        vals = [float(r[field]) for r in rows]
        out[field] = geomean(vals) if field == "ipc_speedup" else amean(vals)
    if finite(float(out["ipc_speedup"])):
        out["ipc_speedup_pct"] = (float(out["ipc_speedup"]) - 1.0) * 100.0
    return out


def run_compare(args: argparse.Namespace) -> None:
    base = load_benchmark_csv(pathlib.Path(args.base_csv))
    sms = load_benchmark_csv(pathlib.Path(args.sms_csv))
    common = sorted(set(base) & set(sms), key=bench_sort_key)
    if not common:
        raise SystemExit("No common benchmarks between base and sms benchmark_agg.csv")

    rows: List[Dict[str, object]] = []
    for bench in common:
        b = base[bench]
        s = sms[bench]
        speedup = safe_div(s.get("ipc", math.nan), b.get("ipc", math.nan))
        l2_red = reduction(s.get("l2c_demand_miss_rate", math.nan), b.get("l2c_demand_miss_rate", math.nan))
        access_red = reduction(s.get("llc_demand_access_per_kinst", math.nan), b.get("llc_demand_access_per_kinst", math.nan))
        miss_red = reduction(s.get("llc_demand_miss_per_kinst", math.nan), b.get("llc_demand_miss_per_kinst", math.nan))
        mr_red = reduction(s.get("llc_demand_miss_rate", math.nan), b.get("llc_demand_miss_rate", math.nan))
        rows.append({
            "benchmark": bench,
            "base_ipc": b.get("ipc", math.nan),
            "sms_ipc": s.get("ipc", math.nan),
            "ipc_speedup": speedup,
            "ipc_speedup_pct": (speedup - 1.0) * 100.0 if finite(speedup) else math.nan,
            "base_l2c_demand_miss_rate": b.get("l2c_demand_miss_rate", math.nan),
            "sms_l2c_demand_miss_rate": s.get("l2c_demand_miss_rate", math.nan),
            "l2c_demand_miss_rate_reduction_pct": l2_red * 100.0 if finite(l2_red) else math.nan,
            "base_llc_demand_access_per_kinst": b.get("llc_demand_access_per_kinst", math.nan),
            "sms_llc_demand_access_per_kinst": s.get("llc_demand_access_per_kinst", math.nan),
            "llc_demand_access_reduction_pct": access_red * 100.0 if finite(access_red) else math.nan,
            "base_llc_demand_miss_per_kinst": b.get("llc_demand_miss_per_kinst", math.nan),
            "sms_llc_demand_miss_per_kinst": s.get("llc_demand_miss_per_kinst", math.nan),
            "llc_demand_miss_reduction_pct": miss_red * 100.0 if finite(miss_red) else math.nan,
            "base_llc_demand_miss_rate": b.get("llc_demand_miss_rate", math.nan),
            "sms_llc_demand_miss_rate": s.get("llc_demand_miss_rate", math.nan),
            "llc_demand_miss_rate_reduction_pct": mr_red * 100.0 if finite(mr_red) else math.nan,
            "sms_l2c_prefetch_issued_per_kinst": s.get("l2c_prefetch_issued_per_kinst", math.nan),
            "sms_l2c_prefetch_accuracy": s.get("l2c_prefetch_accuracy", math.nan),
            "sms_l2c_prefetch_coverage": s.get("l2c_prefetch_coverage", math.nan),
        })

    out_csv = pathlib.Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    srow = compare_summary(rows)
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COMPARE_FIELDS)
        writer.writeheader()
        for row in rows + [srow]:
            writer.writerow({k: row[k] if not isinstance(row.get(k), (int, float)) else fmt_float(float(row[k])) for k in COMPARE_FIELDS})

    if args.fig_png and args.fig_pdf:
        plot_compare(rows, srow, pathlib.Path(args.fig_png), pathlib.Path(args.fig_pdf), args.figure_title)
    log_info(f"compare csv: {out_csv}")


def plot_compare(rows: List[Dict[str, object]], summary: Dict[str, object], fig_png: pathlib.Path, fig_pdf: pathlib.Path, title: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception as exc:
        log_warn(f"matplotlib unavailable, skip compare plotting: {exc}")
        return

    labels = [str(r["benchmark"]) for r in rows] + ["SUMMARY"]
    x = list(range(len(labels)))
    plots = [
        ("ipc_speedup_pct", "IPC speedup (%)", "Speedup (%)"),
        ("l2c_demand_miss_rate_reduction_pct", "L2C demand miss-rate reduction (%)", "Reduction (%)"),
        ("llc_demand_access_reduction_pct", "LLC demand access reduction (%)", "Reduction (%)"),
        ("llc_demand_miss_reduction_pct", "LLC demand miss reduction (%)", "Reduction (%)"),
        ("llc_demand_miss_rate_reduction_pct", "LLC demand miss-rate reduction (%)", "Reduction (%)"),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(21, 10), dpi=220)
    axes = axes.ravel()
    for ax, (key, ttl, ylabel) in zip(axes, plots):
        vals = [float(r[key]) for r in rows] + [float(summary[key])]
        colors = ["#1f77b4"] * len(vals)
        colors[-1] = "#222222"
        ax.bar(x, vals, color=colors, width=0.72)
        ax.axhline(0.0, color="#444", linewidth=0.8)
        ax.set_title(ttl)
        ax.set_ylabel(ylabel)
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.55)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    for ax in axes[len(plots):]:
        ax.axis("off")

    fig.suptitle(title)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_png, bbox_inches="tight")
    fig.savefig(fig_pdf, bbox_inches="tight")


def main() -> None:
    parser = argparse.ArgumentParser(description="SPEC17 fulltrace processing tools for current ChampSim")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_map = sub.add_parser("weight-map", help="Generate SPEC17 trace-weight map CSV")
    p_map.add_argument("--trace-dir", required=True)
    p_map.add_argument("--weight-dir", required=True)
    p_map.add_argument("--out-csv", required=True)
    p_map.set_defaults(func=build_weight_map)

    p_single = sub.add_parser("single-config", help="Generate trace-level and benchmark-level CSV/figures")
    p_single.add_argument("--result-dir", required=True)
    p_single.add_argument("--weight-map-csv", required=True)
    p_single.add_argument("--trace-level-csv", required=True)
    p_single.add_argument("--benchmark-agg-csv", required=True)
    p_single.add_argument("--fig-png", default="")
    p_single.add_argument("--fig-pdf", default="")
    p_single.add_argument("--figure-title", default="SPEC17 Fulltrace")
    p_single.add_argument("--is-sms", action="store_true")
    p_single.add_argument("--select-trace-json", default="")
    p_single.set_defaults(func=run_single_config)

    p_sel = sub.add_parser("select-trace-json", help="Generate selected trace JSON from baseline result logs")
    p_sel.add_argument("--result-dir", required=True)
    p_sel.add_argument("--weight-map-csv", required=True)
    p_sel.add_argument("--out-json", required=True)
    p_sel.add_argument("--threshold", default="1.0")
    p_sel.set_defaults(func=run_select_trace_json)

    p_cmp = sub.add_parser("compare", help="Compare SMS vs base benchmark-level CSV")
    p_cmp.add_argument("--base-csv", required=True)
    p_cmp.add_argument("--sms-csv", required=True)
    p_cmp.add_argument("--out-csv", required=True)
    p_cmp.add_argument("--fig-png", default="")
    p_cmp.add_argument("--fig-pdf", default="")
    p_cmp.add_argument("--figure-title", default="SMS vs noL2pref Fulltrace")
    p_cmp.set_defaults(func=run_compare)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
