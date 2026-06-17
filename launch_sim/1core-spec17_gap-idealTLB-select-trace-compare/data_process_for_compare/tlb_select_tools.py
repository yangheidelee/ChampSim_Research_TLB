#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import re
import sys
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple


CAUSES = [
    ("demand_data", "Demand Data", "Core_0_STLB_cause_Demand_Data_miss", "Core_0_STLB_cause_Demand_Data_miss_rate", "#1f77b4"),
    ("demand_instruction", "Demand Instruction", "Core_0_STLB_cause_Demand_Instruction_miss", "Core_0_STLB_cause_Demand_Instruction_miss_rate", "#ff7f0e"),
    ("l1d_prefetch", "L1D Prefetch", "Core_0_STLB_cause_L1D_Prefetch_miss", "Core_0_STLB_cause_L1D_Prefetch_miss_rate", "#2ca02c"),
    ("l1i_prefetch", "L1I Prefetch", "Core_0_STLB_cause_L1I_Prefetch_miss", "Core_0_STLB_cause_L1I_Prefetch_miss_rate", "#d62728"),
    ("other", "Other", "Core_0_STLB_cause_Other_miss", "Core_0_STLB_cause_Other_miss_rate", "#9467bd"),
]

TRACE_FIELDS = [
    "dataset",
    "workload",
    "trace_tag",
    "trace_name",
    "instructions",
    "cycles",
    "ipc",
    "stlb_access",
    "stlb_hit",
    "stlb_miss",
    "stlb_mpki",
    "stlb_miss_rate",
    "demand_data_miss",
    "demand_data_miss_rate",
    "demand_instruction_miss",
    "demand_instruction_miss_rate",
    "l1d_prefetch_miss",
    "l1d_prefetch_miss_rate",
    "l1i_prefetch_miss",
    "l1i_prefetch_miss_rate",
    "other_miss",
    "other_miss_rate",
]

WORKLOAD_FIELDS = [
    "dataset",
    "workload",
    "num_traces",
    "ipc",
    "stlb_mpki",
    "stlb_miss_rate",
    "demand_data_miss_rate",
    "demand_instruction_miss_rate",
    "l1d_prefetch_miss_rate",
    "l1i_prefetch_miss_rate",
    "other_miss_rate",
    "demand_data_share",
    "demand_instruction_share",
    "l1d_prefetch_share",
    "l1i_prefetch_share",
    "other_share",
]

COMPARE_FIELDS = [
    "dataset",
    "workload",
    "nopref_ipc",
    "pref_ipc",
    "ipc_speedup",
    "ipc_speedup_pct",
    "nopref_stlb_mpki",
    "pref_stlb_mpki",
    "stlb_mpki_norm",
    "stlb_mpki_change_pct",
    "nopref_stlb_miss_rate",
    "pref_stlb_miss_rate",
    "stlb_miss_rate_norm",
    "stlb_miss_rate_change_pct",
]

IDEAL_COMPARE_FIELDS = [
    "dataset",
    "workload",
    "baseline_ipc",
    "ideal_demand_ipc",
    "ideal_demand_speedup",
    "ideal_l1pref_ipc",
    "ideal_l1pref_speedup",
    "ideal_all_ipc",
    "ideal_all_speedup",
]


def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")


def log_warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def to_float(text: object, default: float = math.nan) -> float:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return default


def finite(value: float) -> bool:
    return math.isfinite(value)


def fmt_float(value: object) -> str:
    if isinstance(value, str):
        return value
    val = to_float(value)
    return f"{val:.17g}" if finite(val) else "nan"


def safe_div(num: float, den: float, default: float = math.nan) -> float:
    if not finite(num) or not finite(den) or den == 0:
        return default
    return num / den


def amean(values: Iterable[float]) -> float:
    vals = [v for v in values if finite(v)]
    return sum(vals) / len(vals) if vals else math.nan


def geomean(values: Iterable[float]) -> float:
    vals = [v for v in values if finite(v) and v > 0]
    return math.exp(sum(math.log(v) for v in vals) / len(vals)) if vals else math.nan


def extract_metric(text: str, key: str, default: float = math.nan) -> float:
    match = re.search(rf"^{re.escape(key)}\s+([-.+0-9A-Za-z]+)$", text, flags=re.MULTILINE)
    return to_float(match.group(1), default) if match else default


def strip_trace_suffix(name: str) -> str:
    for suffix in [".champsimtrace.xz", ".champsimtrace.gz", ".champsimtrace"]:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def trace_info_from_tag(trace_tag: str) -> Tuple[str, str]:
    spec = re.match(r"^(6\d\d\.[A-Za-z0-9_]+)-\d+B$", trace_tag)
    if spec:
        return "spec17", spec.group(1)
    if trace_tag.startswith("gap."):
        return "gap", trace_tag
    return "unknown", trace_tag


def trace_sort_key(row: Dict[str, object]) -> Tuple[int, str, str]:
    dataset = str(row["dataset"])
    dataset_rank = 0 if dataset == "spec17" else 1 if dataset == "gap" else 2
    return dataset_rank, str(row["workload"]), str(row["trace_tag"])


def workload_sort_key(row_or_name: object) -> Tuple[int, int, str]:
    if isinstance(row_or_name, dict):
        dataset = str(row_or_name["dataset"])
        workload = str(row_or_name["workload"])
    else:
        text = str(row_or_name)
        if text.startswith("gmean_spec17") or text == "spec17":
            dataset, workload = "spec17", text
        elif text.startswith("gmean_gap") or text == "gap":
            dataset, workload = "gap", text
        else:
            dataset, workload = "unknown", text
    if workload == "gmean_spec17":
        return 2, 0, workload
    if workload == "gmean_gap":
        return 2, 1, workload
    dataset_rank = 0 if dataset == "spec17" else 1 if dataset == "gap" else 3
    return dataset_rank, 0, workload


def parse_trace_tag_from_result_filename(path: pathlib.Path) -> Optional[str]:
    stem = path.name[:-4] if path.name.endswith(".log") else path.name
    spec = re.match(r"^(6\d\d\.[A-Za-z0-9_]+-\d+B)-", stem)
    if spec:
        return spec.group(1)
    gap = re.match(r"^(gap\.[A-Za-z0-9_.-]+-\d+B)-", stem)
    if gap:
        return gap.group(1)
    return None


def extract_metrics_from_result(path: pathlib.Path) -> Optional[Dict[str, object]]:
    trace_tag = parse_trace_tag_from_result_filename(path)
    if not trace_tag:
        log_warn(f"skip unrecognized result filename: {path.name}")
        return None

    text = path.read_text(errors="ignore")
    roi_pos = text.find("[ROI Statistics]")
    metric_text = text[roi_pos:] if roi_pos >= 0 else text
    dataset, workload = trace_info_from_tag(trace_tag)

    row: Dict[str, object] = {
        "dataset": dataset,
        "workload": workload,
        "trace_tag": trace_tag,
        "trace_name": f"{trace_tag}.champsimtrace.xz",
        "instructions": extract_metric(metric_text, "Core_0_instructions"),
        "cycles": extract_metric(metric_text, "Core_0_cycles"),
        "ipc": extract_metric(metric_text, "Core_0_IPC"),
        "stlb_access": extract_metric(metric_text, "Core_0_STLB_total_access", 0.0),
        "stlb_hit": extract_metric(metric_text, "Core_0_STLB_total_hit", 0.0),
        "stlb_miss": extract_metric(metric_text, "Core_0_STLB_total_miss", 0.0),
        "stlb_mpki": extract_metric(metric_text, "Core_0_STLB_total_MPKI", math.nan),
        "stlb_miss_rate": extract_metric(metric_text, "Core_0_STLB_total_miss_rate", math.nan),
    }
    for key, _, miss_key, rate_key, _ in CAUSES:
        row[f"{key}_miss"] = extract_metric(metric_text, miss_key, 0.0)
        row[f"{key}_miss_rate"] = extract_metric(metric_text, rate_key, 0.0)

    if not finite(float(row["ipc"])):
        row["ipc"] = safe_div(float(row["instructions"]), float(row["cycles"]))
    if not finite(float(row["stlb_mpki"])):
        row["stlb_mpki"] = safe_div(float(row["stlb_miss"]) * 1000.0, float(row["instructions"]))
    if not finite(float(row["stlb_miss_rate"])):
        row["stlb_miss_rate"] = safe_div(float(row["stlb_miss"]), float(row["stlb_access"]))

    return row


def load_selected_tags(path: str) -> Optional[set[str]]:
    if not path or path.upper() in {"ALL", "FULL", "NONE"}:
        return None
    payload = json.loads(pathlib.Path(path).read_text())
    return {str(x) for x in payload.get("selected_trace_tags", [])}


def collect_trace_rows(result_dir: pathlib.Path, selected_tags: Optional[set[str]] = None) -> List[Dict[str, object]]:
    if not result_dir.is_dir():
        raise SystemExit(f"Result directory not found: {result_dir}")
    rows: List[Dict[str, object]] = []
    for path in sorted(result_dir.glob("*.log")):
        row = extract_metrics_from_result(path)
        if row is None:
            continue
        if selected_tags is not None and str(row["trace_tag"]) not in selected_tags:
            continue
        rows.append(row)
    rows.sort(key=trace_sort_key)
    return rows


def write_csv(path: pathlib.Path, fields: List[str], rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt_float(row.get(field, math.nan)) for field in fields})


def aggregate_workload(rows: List[Dict[str, object]]) -> Dict[str, object]:
    dataset = str(rows[0]["dataset"])
    workload = str(rows[0]["workload"])
    out: Dict[str, object] = {"dataset": dataset, "workload": workload, "num_traces": len(rows)}
    out["ipc"] = geomean([float(r["ipc"]) for r in rows])
    total_instr = sum(float(r["instructions"]) for r in rows if finite(float(r["instructions"])))
    total_access = sum(float(r["stlb_access"]) for r in rows if finite(float(r["stlb_access"])))
    total_miss = sum(float(r["stlb_miss"]) for r in rows if finite(float(r["stlb_miss"])))
    out["stlb_mpki"] = safe_div(total_miss * 1000.0, total_instr, 0.0)
    out["stlb_miss_rate"] = safe_div(total_miss, total_access, 0.0)
    for key, _, _, _, _ in CAUSES:
        miss_sum = sum(float(r[f"{key}_miss"]) for r in rows if finite(float(r[f"{key}_miss"])))
        out[f"{key}_miss_rate"] = safe_div(miss_sum, total_access, 0.0)
        out[f"{key}_share"] = safe_div(miss_sum, total_miss, 0.0)
    return out


def summary_row_from_traces(dataset: str, rows: List[Dict[str, object]]) -> Dict[str, object]:
    out: Dict[str, object] = {"dataset": dataset, "workload": f"gmean_{dataset}", "num_traces": len(rows)}
    out["ipc"] = geomean([float(r["ipc"]) for r in rows])
    total_instr = sum(float(r["instructions"]) for r in rows if finite(float(r["instructions"])))
    total_access = sum(float(r["stlb_access"]) for r in rows if finite(float(r["stlb_access"])))
    total_miss = sum(float(r["stlb_miss"]) for r in rows if finite(float(r["stlb_miss"])))
    out["stlb_mpki"] = safe_div(total_miss * 1000.0, total_instr, 0.0)
    out["stlb_miss_rate"] = safe_div(total_miss, total_access, 0.0)
    for key, _, _, _, _ in CAUSES:
        miss_sum = sum(float(r[f"{key}_miss"]) for r in rows if finite(float(r[f"{key}_miss"])))
        out[f"{key}_miss_rate"] = safe_div(miss_sum, total_access, 0.0)
        out[f"{key}_share"] = safe_div(miss_sum, total_miss, 0.0)
    return out


def aggregate_rows(trace_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
    for row in trace_rows:
        grouped[(str(row["dataset"]), str(row["workload"]))].append(row)
    rows = [aggregate_workload(v) for _, v in sorted(grouped.items(), key=lambda item: workload_sort_key({"dataset": item[0][0], "workload": item[0][1]}))]
    final_rows = list(rows)
    for dataset in ["spec17", "gap"]:
        subset = [r for r in trace_rows if r["dataset"] == dataset]
        if subset:
            final_rows.append(summary_row_from_traces(dataset, subset))
    return final_rows


def select_traces(args: argparse.Namespace) -> None:
    rows = collect_trace_rows(pathlib.Path(args.result_dir))
    threshold = float(args.threshold)
    selected = [row for row in rows if finite(float(row["stlb_mpki"])) and float(row["stlb_mpki"]) > threshold]
    payload = {
        "source_result_dir": str(pathlib.Path(args.result_dir).resolve()),
        "threshold": {"metric": "Core_0_STLB_total_MPKI", "operator": ">", "value": threshold},
        "selected_trace_tags": [str(row["trace_tag"]) for row in selected],
        "selected_by_dataset": {
            "spec17": [str(row["trace_tag"]) for row in selected if row["dataset"] == "spec17"],
            "gap": [str(row["trace_tag"]) for row in selected if row["dataset"] == "gap"],
        },
        "trace_metrics": {str(row["trace_tag"]): {"dataset": row["dataset"], "workload": row["workload"], "stlb_mpki": row["stlb_mpki"]} for row in rows},
        "summary": {"total_traces": len(rows), "total_selected_traces": len(selected)},
    }
    out_json = pathlib.Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2) + "\n")
    log_info(f"selected trace json: {out_json}")


def single_config(args: argparse.Namespace) -> None:
    selected = load_selected_tags(args.select_trace_json)
    trace_rows = collect_trace_rows(pathlib.Path(args.result_dir), selected)
    if not trace_rows:
        raise SystemExit("No result .log files found for selected single-config processing")
    workload_rows = aggregate_rows(trace_rows)
    write_csv(pathlib.Path(args.trace_level_csv), TRACE_FIELDS, trace_rows)
    write_csv(pathlib.Path(args.workload_csv), WORKLOAD_FIELDS, workload_rows)
    if args.fig_png:
        plot_single(workload_rows, pathlib.Path(args.fig_png), pathlib.Path(args.fig_pdf), args.figure_title)
    log_info(f"trace-level csv: {args.trace_level_csv}")
    log_info(f"workload csv: {args.workload_csv}")


def read_workload_csv(path: pathlib.Path) -> Dict[Tuple[str, str], Dict[str, object]]:
    with path.open(newline="") as f:
        return {(r["dataset"], r["workload"]): r for r in csv.DictReader(f)}


def compare_configs(args: argparse.Namespace) -> None:
    nopref = read_workload_csv(pathlib.Path(args.nopref_csv))
    pref = read_workload_csv(pathlib.Path(args.pref_csv))
    common = sorted(set(nopref) & set(pref), key=lambda k: workload_sort_key({"dataset": k[0], "workload": k[1]}))
    rows: List[Dict[str, object]] = []
    for key in common:
        n = nopref[key]
        p = pref[key]
        n_ipc = to_float(n.get("ipc"))
        p_ipc = to_float(p.get("ipc"))
        speedup = safe_div(p_ipc, n_ipc)
        n_stlb_mpki = to_float(n.get("stlb_mpki"))
        p_stlb_mpki = to_float(p.get("stlb_mpki"))
        stlb_mpki_norm = safe_div(p_stlb_mpki, n_stlb_mpki)
        n_stlb_miss_rate = to_float(n.get("stlb_miss_rate"))
        p_stlb_miss_rate = to_float(p.get("stlb_miss_rate"))
        stlb_miss_rate_norm = safe_div(p_stlb_miss_rate, n_stlb_miss_rate)
        rows.append({
            "dataset": key[0],
            "workload": key[1],
            "nopref_ipc": n_ipc,
            "pref_ipc": p_ipc,
            "ipc_speedup": speedup,
            "ipc_speedup_pct": (speedup - 1.0) * 100.0 if finite(speedup) else math.nan,
            "nopref_stlb_mpki": n_stlb_mpki,
            "pref_stlb_mpki": p_stlb_mpki,
            "stlb_mpki_norm": stlb_mpki_norm,
            "stlb_mpki_change_pct": (stlb_mpki_norm - 1.0) * 100.0 if finite(stlb_mpki_norm) else math.nan,
            "nopref_stlb_miss_rate": n_stlb_miss_rate,
            "pref_stlb_miss_rate": p_stlb_miss_rate,
            "stlb_miss_rate_norm": stlb_miss_rate_norm,
            "stlb_miss_rate_change_pct": (stlb_miss_rate_norm - 1.0) * 100.0 if finite(stlb_miss_rate_norm) else math.nan,
        })
    write_csv(pathlib.Path(args.out_csv), COMPARE_FIELDS, rows)
    if args.fig_png:
        plot_compare(rows, pathlib.Path(args.fig_png), pathlib.Path(args.fig_pdf), args.figure_title)
    if args.mpki_fig_png:
        plot_stlb_mpki_compare(rows, pathlib.Path(args.mpki_fig_png), pathlib.Path(args.mpki_fig_pdf), args.mpki_figure_title)
    if args.stlb_fig_png:
        plot_stlb_miss_rate_compare(rows, pathlib.Path(args.stlb_fig_png), pathlib.Path(args.stlb_fig_pdf), args.stlb_figure_title)
    log_info(f"compare csv: {args.out_csv}")


def compare_ideal_configs(args: argparse.Namespace) -> None:
    baseline = read_workload_csv(pathlib.Path(args.baseline_csv))
    ideal_demand = read_workload_csv(pathlib.Path(args.ideal_demand_csv))
    ideal_l1pref = read_workload_csv(pathlib.Path(args.ideal_l1pref_csv))
    ideal_all = read_workload_csv(pathlib.Path(args.ideal_all_csv))
    common = sorted(set(baseline) & set(ideal_demand) & set(ideal_l1pref) & set(ideal_all), key=lambda k: workload_sort_key({"dataset": k[0], "workload": k[1]}))
    rows: List[Dict[str, object]] = []
    for key in common:
        base_ipc = to_float(baseline[key].get("ipc"))
        demand_ipc = to_float(ideal_demand[key].get("ipc"))
        l1pref_ipc = to_float(ideal_l1pref[key].get("ipc"))
        all_ipc = to_float(ideal_all[key].get("ipc"))
        rows.append({
            "dataset": key[0],
            "workload": key[1],
            "baseline_ipc": base_ipc,
            "ideal_demand_ipc": demand_ipc,
            "ideal_demand_speedup": safe_div(demand_ipc, base_ipc),
            "ideal_l1pref_ipc": l1pref_ipc,
            "ideal_l1pref_speedup": safe_div(l1pref_ipc, base_ipc),
            "ideal_all_ipc": all_ipc,
            "ideal_all_speedup": safe_div(all_ipc, base_ipc),
        })
    write_csv(pathlib.Path(args.out_csv), IDEAL_COMPARE_FIELDS, rows)
    if args.fig_png:
        plot_ideal_compare(rows, pathlib.Path(args.fig_png), pathlib.Path(args.fig_pdf), args.figure_title)
    log_info(f"ideal compare csv: {args.out_csv}")


def finite_rows(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return [r for r in rows if not str(r["workload"]).startswith("gmean_")]


def plot_label(row: Dict[str, object], summary_prefix: str = "gmean") -> str:
    workload = str(row["workload"])
    if workload == "gmean_spec17":
        return f"{summary_prefix}_spec17"
    if workload == "gmean_gap":
        return f"{summary_prefix}_gap"
    return workload


def apply_plot_style(plt: object) -> None:
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "black",
        "axes.linewidth": 0.9,
        "axes.titlesize": 14,
        "axes.labelsize": 12,
        "xtick.labelsize": 10,
        "ytick.labelsize": 11,
        "legend.fontsize": 10,
        "font.size": 11,
        "savefig.dpi": 300,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def style_axis(ax: object) -> None:
    ax.grid(True, axis="y", linestyle="--", linewidth=0.55, alpha=0.45, color="#b0b0b0")
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color("black")
        spine.set_linewidth(0.9)
    ax.tick_params(axis="both", colors="black", width=0.9, length=4)


def plot_single(rows: List[Dict[str, object]], fig_png: pathlib.Path, fig_pdf: pathlib.Path, title: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception as exc:
        log_warn(f"matplotlib unavailable, skip plotting: {exc}")
        return
    apply_plot_style(plt)
    rows = sorted(rows, key=workload_sort_key)
    labels = [plot_label(r, "amean") for r in rows]
    x = list(range(len(rows)))
    fig, axes = plt.subplots(3, 1, figsize=(max(12, len(rows) * 0.52), 12.4), dpi=220, gridspec_kw={"height_ratios": [1, 1, 1.35], "hspace": 0.72})

    axes[0].bar(x, [float(r["stlb_mpki"]) for r in rows], color="#4c78a8", width=0.68)
    axes[0].set_title("STLB total MPKI", pad=8)
    axes[0].set_ylabel("MPKI")
    style_axis(axes[0])

    axes[1].bar(x, [float(r["stlb_miss_rate"]) for r in rows], color="#1f77b4", width=0.68)
    axes[1].set_title("STLB total miss rate", pad=8)
    axes[1].set_ylabel("Miss rate")
    style_axis(axes[1])

    bottom = [0.0] * len(rows)
    for key, label, _, _, color in CAUSES:
        vals = [100.0 * float(r[f"{key}_share"]) for r in rows]
        axes[2].bar(x, vals, bottom=bottom, label=label, color=color, width=0.68)
        bottom = [b + v for b, v in zip(bottom, vals)]
    axes[2].set_title("STLB miss-cause share", pad=8)
    axes[2].set_ylabel("Share of STLB misses (%)")
    axes[2].set_ylim(0, 100)
    style_axis(axes[2])

    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")
    axes[2].set_xlabel("Benchmark")
    axes[2].legend(loc="lower left", ncols=1, frameon=True, edgecolor="#b0b0b0")
    fig.suptitle(title, fontsize=15)
    fig.subplots_adjust(left=0.07, right=0.99, bottom=0.11, top=0.93, hspace=0.72)
    fig_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_png, bbox_inches="tight")
    if fig_pdf:
        fig.savefig(fig_pdf, bbox_inches="tight")


def plot_compare(rows: List[Dict[str, object]], fig_png: pathlib.Path, fig_pdf: pathlib.Path, title: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception as exc:
        log_warn(f"matplotlib unavailable, skip plotting: {exc}")
        return
    apply_plot_style(plt)
    rows = sorted(rows, key=workload_sort_key)
    labels = [plot_label(r, "gmean") for r in rows]
    x = list(range(len(rows)))
    vals = [float(r["ipc_speedup"]) for r in rows]
    colors = ["#1f77b4" if v >= 1.0 else "#d62728" for v in vals]
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.5), 5.2), dpi=220)
    ax.bar(x, vals, color=colors, width=0.68)
    ax.axhline(1.0, color="black", linewidth=0.9)
    ax.set_title(title)
    ax.set_ylabel("IPC speedup (pref / nopref)")
    ax.set_xlabel("Benchmark")
    style_axis(ax)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    fig_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_png, bbox_inches="tight")
    if fig_pdf:
        fig.savefig(fig_pdf, bbox_inches="tight")


def plot_stlb_mpki_compare(rows: List[Dict[str, object]], fig_png: pathlib.Path, fig_pdf: pathlib.Path, title: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception as exc:
        log_warn(f"matplotlib unavailable, skip plotting: {exc}")
        return
    apply_plot_style(plt)
    rows = sorted(rows, key=workload_sort_key)
    labels = [plot_label(r, "amean") for r in rows]
    x = list(range(len(rows)))
    vals = [float(r["stlb_mpki_norm"]) for r in rows]
    colors = ["#2ca02c" if v <= 1.0 else "#d62728" for v in vals]
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.5), 5.2), dpi=220)
    ax.bar(x, vals, color=colors, width=0.68)
    ax.axhline(1.0, color="black", linewidth=0.9)
    ax.set_title(title)
    ax.set_ylabel("Normalized STLB MPKI (amean, pref / nopref)")
    ax.set_xlabel("Benchmark")
    style_axis(ax)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    fig_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_png, bbox_inches="tight")
    if fig_pdf:
        fig.savefig(fig_pdf, bbox_inches="tight")


def plot_stlb_miss_rate_compare(rows: List[Dict[str, object]], fig_png: pathlib.Path, fig_pdf: pathlib.Path, title: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception as exc:
        log_warn(f"matplotlib unavailable, skip plotting: {exc}")
        return
    apply_plot_style(plt)
    rows = sorted(rows, key=workload_sort_key)
    labels = [plot_label(r, "amean") for r in rows]
    x = list(range(len(rows)))
    vals = [float(r["stlb_miss_rate_norm"]) for r in rows]
    colors = ["#2ca02c" if v <= 1.0 else "#d62728" for v in vals]
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.5), 5.2), dpi=220)
    ax.bar(x, vals, color=colors, width=0.68)
    ax.axhline(1.0, color="black", linewidth=0.9)
    ax.set_title(title)
    ax.set_ylabel("Normalized STLB miss rate (amean, pref / nopref)")
    ax.set_xlabel("Benchmark")
    style_axis(ax)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    fig_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_png, bbox_inches="tight")
    if fig_pdf:
        fig.savefig(fig_pdf, bbox_inches="tight")


def plot_ideal_compare(rows: List[Dict[str, object]], fig_png: pathlib.Path, fig_pdf: pathlib.Path, title: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception as exc:
        log_warn(f"matplotlib unavailable, skip plotting: {exc}")
        return
    apply_plot_style(plt)
    rows = sorted(rows, key=workload_sort_key)
    labels = [plot_label(r, "gmean") for r in rows]
    x = list(range(len(rows)))
    series = [
        ("Demand", "ideal_demand_speedup", "#4c78a8"),
        ("L1 prefetch", "ideal_l1pref_speedup", "#f58518"),
        ("All", "ideal_all_speedup", "#54a24b"),
    ]
    width = 0.24
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.58), 5.6), dpi=220)
    offsets = [-(width), 0.0, width]
    for offset, (label, key, color) in zip(offsets, series):
        ax.bar([i + offset for i in x], [float(r[key]) for r in rows], width=width, label=label, color=color)
    ax.axhline(1.0, color="black", linewidth=0.9)
    ax.set_title(title)
    ax.set_ylabel("IPC speedup over baseline")
    ax.set_xlabel("Benchmark")
    style_axis(ax)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.legend(loc="upper left", ncols=1, frameon=True, edgecolor="#b0b0b0")
    fig.tight_layout()
    fig_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_png, bbox_inches="tight")
    if fig_pdf:
        fig.savefig(fig_pdf, bbox_inches="tight")


def main() -> None:
    parser = argparse.ArgumentParser(description="SPEC17+GAP TLB select-trace processing")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sel = sub.add_parser("select-trace-json")
    p_sel.add_argument("--result-dir", required=True)
    p_sel.add_argument("--out-json", required=True)
    p_sel.add_argument("--threshold", default="1.0")
    p_sel.set_defaults(func=select_traces)

    p_single = sub.add_parser("single-config")
    p_single.add_argument("--result-dir", required=True)
    p_single.add_argument("--select-trace-json", required=True)
    p_single.add_argument("--trace-level-csv", required=True)
    p_single.add_argument("--workload-csv", required=True)
    p_single.add_argument("--fig-png", default="")
    p_single.add_argument("--fig-pdf", default="")
    p_single.add_argument("--figure-title", default="STLB miss causes")
    p_single.set_defaults(func=single_config)

    p_cmp = sub.add_parser("compare")
    p_cmp.add_argument("--nopref-csv", required=True)
    p_cmp.add_argument("--pref-csv", required=True)
    p_cmp.add_argument("--out-csv", required=True)
    p_cmp.add_argument("--fig-png", default="")
    p_cmp.add_argument("--fig-pdf", default="")
    p_cmp.add_argument("--figure-title", default="IPC compare")
    p_cmp.add_argument("--mpki-fig-png", default="")
    p_cmp.add_argument("--mpki-fig-pdf", default="")
    p_cmp.add_argument("--mpki-figure-title", default="STLB MPKI amean compare")
    p_cmp.add_argument("--stlb-fig-png", default="")
    p_cmp.add_argument("--stlb-fig-pdf", default="")
    p_cmp.add_argument("--stlb-figure-title", default="STLB miss rate amean compare")
    p_cmp.set_defaults(func=compare_configs)

    p_ideal = sub.add_parser("compare-ideal")
    p_ideal.add_argument("--baseline-csv", required=True)
    p_ideal.add_argument("--ideal-demand-csv", required=True)
    p_ideal.add_argument("--ideal-l1pref-csv", required=True)
    p_ideal.add_argument("--ideal-all-csv", required=True)
    p_ideal.add_argument("--out-csv", required=True)
    p_ideal.add_argument("--fig-png", default="")
    p_ideal.add_argument("--fig-pdf", default="")
    p_ideal.add_argument("--figure-title", default="Ideal STLB IPC upper bound")
    p_ideal.set_defaults(func=compare_ideal_configs)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
