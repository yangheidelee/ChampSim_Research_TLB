#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
CASE_DIR = SCRIPT_DIR.parent
SELECT_TRACE_JSON = Path(
    os.environ.get(
        "SELECT_TRACE_JSON",
        "/home/zcq/git_prj/ChampSim/csv_figure/spec0617_gapligra_qmm_parsec-TLB-select-trace-compare_vberti_50_100/select_trace/data_process_for_compare/stlb_mpki_gt_1.0_selected_traces.json",
    )
)
SELECT_THRESHOLD = float(os.environ.get("SELECT_THRESHOLD", "1.0"))

CONFIGS = {
    "nopref": {"label": "No L1D Prefetch", "short": "nopref", "binary": "pgc-nopref-1core", "result_dir": CASE_DIR / "result" / "nopref"},
    "permit_pgc": {"label": "Permit PGC", "short": "permit", "binary": "pgc-permit-1core", "result_dir": CASE_DIR / "result" / "permit_pgc"},
    "discard_pgc": {"label": "Discard PGC", "short": "discard", "binary": "pgc-discard-1core", "result_dir": CASE_DIR / "result" / "discard_pgc"},
}
CAUSES = [
    ("demand_data", "Demand Data", "Core_0_STLB_cause_Demand_Data_miss", "Core_0_STLB_cause_Demand_Data_miss_rate", "#1f77b4"),
    ("demand_instruction", "Demand Instruction", "Core_0_STLB_cause_Demand_Instruction_miss", "Core_0_STLB_cause_Demand_Instruction_miss_rate", "#ff7f0e"),
    ("l1d_prefetch", "L1D Prefetch", "Core_0_STLB_cause_L1D_Prefetch_miss", "Core_0_STLB_cause_L1D_Prefetch_miss_rate", "#2ca02c"),
    ("l1i_prefetch", "L1I Prefetch", "Core_0_STLB_cause_L1I_Prefetch_miss", "Core_0_STLB_cause_L1I_Prefetch_miss_rate", "#d62728"),
    ("other", "Other", "Core_0_STLB_cause_Other_miss", "Core_0_STLB_cause_Other_miss_rate", "#9467bd"),
]
DATASET_ORDER = ["spec06", "spec17", "gap", "ligra", "qmm", "parsec", "xsbench"]
TRACE_FIELDS = [
    "dataset",
    "workload",
    "trace_tag",
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
IPC_FIELDS = [
    "dataset",
    "workload",
    "trace_tag",
    "num_traces",
    "nopref_ipc",
    "permit_ipc",
    "discard_ipc",
    "permit_vs_nopref_speedup",
    "permit_vs_nopref_speedup_pct",
    "discard_vs_nopref_speedup",
    "discard_vs_nopref_speedup_pct",
    "permit_vs_discard_speedup",
    "permit_vs_discard_speedup_pct",
]
COMPARE_FIELDS = [
    "dataset",
    "workload",
    "trace_tag",
    "num_traces",
    "base_ipc",
    "other_ipc",
    "ipc_speedup",
    "ipc_speedup_pct",
    "base_stlb_mpki",
    "other_stlb_mpki",
    "stlb_mpki_norm",
    "stlb_mpki_change_pct",
    "base_stlb_miss_rate",
    "other_stlb_miss_rate",
    "stlb_miss_rate_norm",
    "stlb_miss_rate_change_pct",
]
METRIC_ALIASES = {
    "CPU 0 cumulative IPC": ("CPU 0 cumulative IPC", "Core_0_IPC"),
    "DRAM_read_traffic_MPKI": ("dram_rq_read_total_observed.per_1K_instructions",),
}


def finite(value: float) -> bool:
    return math.isfinite(value)


def to_float(value: object, default: float = math.nan) -> float:
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return default


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


def fmt_value(value: object) -> str:
    if isinstance(value, str):
        return value
    val = to_float(value)
    return f"{val:.12g}" if finite(val) else ""


def trace_info_from_tag(trace_tag: str) -> tuple[str, str]:
    spec06 = re.match(r"^(4\d\d\.[A-Za-z0-9_]+)-\d+B$", trace_tag)
    if spec06:
        return "spec06", spec06.group(1)
    spec17 = re.match(r"^(6\d\d\.[A-Za-z0-9_]+)-\d+B$", trace_tag)
    if spec17:
        return "spec17", spec17.group(1)
    old_gap = re.match(r"^gap\.([A-Za-z0-9_]+)\.", trace_tag)
    if old_gap:
        return "gap", old_gap.group(1)
    gap = re.match(r"^(bc|bfs|cc|pr|sssp|tc)\.[A-Za-z0-9_]+-\d+B$", trace_tag)
    if gap:
        return "gap", gap.group(1)
    gap_dpc = re.match(r"^(bc|bfs|cc|pr|sssp|tc)-\d+(?:\.trace)?$", trace_tag)
    if gap_dpc:
        return "gap", gap_dpc.group(1)
    ligra = re.match(r"^(ligra_[^.]+)\.", trace_tag)
    if ligra:
        return "ligra", ligra.group(1)
    qmm = re.match(r"^(srv|compute_int|compute_fp)_\d+_new$", trace_tag)
    if qmm:
        return "qmm", {"compute_fp": "qmm_fp", "compute_int": "qmm_int", "srv": "qmm_srv"}[qmm.group(1)]
    parsec = re.match(r"^parsec_[^.]+\.[^.]+\.([^.]+)\.", trace_tag)
    if parsec:
        return "parsec", f"parsec_{parsec.group(1)}"
    xsbench = re.match(r"^xs\.([A-Za-z0-9_]+)-\d+B$", trace_tag)
    if xsbench:
        return "xsbench", f"xsbench_{xsbench.group(1)}"
    return "unknown", trace_tag


def dataset_rank(dataset: str) -> int:
    try:
        return DATASET_ORDER.index(dataset)
    except ValueError:
        return len(DATASET_ORDER)


def sort_key(row: dict[str, object]) -> tuple[int, int, str, str]:
    workload = str(row["workload"])
    return dataset_rank(str(row["dataset"])), 1 if workload.startswith("gmean_") else 0, workload, str(row.get("trace_tag", ""))


def selected_tags() -> list[str]:
    if not SELECT_TRACE_JSON.exists():
        raise SystemExit(f"[ERROR] Missing selected trace json: {SELECT_TRACE_JSON}")
    payload = json.loads(SELECT_TRACE_JSON.read_text())
    tags = [str(x) for x in payload.get("selected_trace_tags", [])]
    if not tags:
        raise SystemExit(f"[ERROR] Empty selected_trace_tags in {SELECT_TRACE_JSON}")
    return tags


def log_path(config_key: str, trace_tag: str) -> Path:
    cfg = CONFIGS[config_key]
    return Path(cfg["result_dir"]) / f"{trace_tag}-{cfg['binary']}---hide-heartbeat.log"


def log_complete(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    text = path.read_text(errors="replace")
    return "[ROI Statistics]" in text and "Core_0_TLB_cross_page_prefetch_coverage" in text


def parse_key_values(path: Path) -> dict[str, float]:
    data: dict[str, float] = {}
    ipc_re = re.compile(r"CPU 0 cumulative IPC:\s+([-+0-9.eE]+)")
    kv_space_re = re.compile(r"^([A-Za-z0-9_.]+)\s+([-+0-9.eE]+%?)$")
    kv_equal_re = re.compile(r"^([A-Za-z0-9_.]+)\s*=\s*([-+0-9.eE]+%?)$")
    for line in path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if match := ipc_re.search(stripped):
            data["CPU 0 cumulative IPC"] = to_float(match.group(1))
            continue
        match = kv_equal_re.match(stripped) or kv_space_re.match(stripped)
        if match:
            key, value = match.groups()
            data[key] = to_float(value)
    return data


def metric_value(metric: str, data: dict[str, float]) -> float | None:
    for key in METRIC_ALIASES.get(metric, (metric,)):
        if key in data:
            return data[key]
    return None


def parse_trace_row(trace_tag: str, data: dict[str, float]) -> dict[str, object]:
    dataset, workload = trace_info_from_tag(trace_tag)
    row: dict[str, object] = {
        "dataset": dataset,
        "workload": workload,
        "trace_tag": trace_tag,
        "instructions": data.get("Core_0_instructions", math.nan),
        "cycles": data.get("Core_0_cycles", math.nan),
        "ipc": data.get("Core_0_IPC", data.get("CPU 0 cumulative IPC", math.nan)),
        "stlb_access": data.get("Core_0_STLB_total_access", 0.0),
        "stlb_hit": data.get("Core_0_STLB_total_hit", 0.0),
        "stlb_miss": data.get("Core_0_STLB_total_miss", 0.0),
        "stlb_mpki": data.get("Core_0_STLB_total_MPKI", math.nan),
        "stlb_miss_rate": data.get("Core_0_STLB_total_miss_rate", math.nan),
    }
    if not finite(float(row["ipc"])):
        row["ipc"] = safe_div(float(row["instructions"]), float(row["cycles"]))
    if not finite(float(row["stlb_mpki"])):
        row["stlb_mpki"] = safe_div(float(row["stlb_miss"]) * 1000.0, float(row["instructions"]))
    if not finite(float(row["stlb_miss_rate"])):
        row["stlb_miss_rate"] = safe_div(float(row["stlb_miss"]), float(row["stlb_access"]))
    for key, _, miss_key, rate_key, _ in CAUSES:
        row[f"{key}_miss"] = data.get(miss_key, 0.0)
        row[f"{key}_miss_rate"] = data.get(rate_key, 0.0)
    return row


def collect_config(config_key: str, tags: list[str]) -> tuple[list[dict[str, object]], dict[str, dict[str, float]], list[str]]:
    rows: list[dict[str, object]] = []
    raw: dict[str, dict[str, float]] = {}
    missing: list[str] = []
    for trace_tag in tags:
        path = log_path(config_key, trace_tag)
        if not log_complete(path):
            missing.append(trace_tag)
            continue
        data = parse_key_values(path)
        raw[trace_tag] = data
        rows.append(parse_trace_row(trace_tag, data))
    rows.sort(key=sort_key)
    return rows, raw, missing


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt_value(row.get(field, "")) for field in fields})


def cause_share(row: dict[str, object], key: str) -> float:
    return safe_div(float(row[f"{key}_miss"]), float(row["stlb_miss"]), 0.0)


def aggregate_trace_rows(dataset: str, workload: str, rows: list[dict[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {"dataset": dataset, "workload": workload, "num_traces": len(rows)}
    out["ipc"] = geomean(float(r["ipc"]) for r in rows)
    out["stlb_mpki"] = amean(float(r["stlb_mpki"]) for r in rows)
    out["stlb_miss_rate"] = amean(float(r["stlb_miss_rate"]) for r in rows)
    for key, _, _, _, _ in CAUSES:
        out[f"{key}_miss_rate"] = amean(float(r[f"{key}_miss_rate"]) for r in rows)
        out[f"{key}_share"] = amean(cause_share(r, key) for r in rows)
    return out


def aggregate_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    by_dataset: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["dataset"]), str(row["workload"]))].append(row)
        by_dataset[str(row["dataset"])].append(row)

    out = [aggregate_trace_rows(ds, wl, group) for (ds, wl), group in grouped.items()]
    for dataset in DATASET_ORDER:
        if by_dataset.get(dataset):
            out.append(aggregate_trace_rows(dataset, f"gmean_{dataset}", by_dataset[dataset]))
    if rows:
        out.append(aggregate_trace_rows("all", "gmean_all", rows))
    out.sort(key=sort_key)
    return out


def plot_style(plt) -> None:
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "black",
        "axes.linewidth": 0.9,
        "font.size": 10,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def style_axis(ax) -> None:
    ax.grid(True, axis="y", linestyle="--", linewidth=0.55, alpha=0.45, color="#b0b0b0")
    ax.set_axisbelow(True)


def plot_labels(rows: list[dict[str, object]], summary_prefix: str) -> list[str]:
    labels = []
    for row in rows:
        workload = str(row["workload"])
        labels.append(f"{summary_prefix}_{workload[len('gmean_'):]}" if workload.startswith("gmean_") else workload)
    return labels


def save_single_config_plots(config_key: str, workload_rows: list[dict[str, object]]) -> None:
    if not workload_rows:
        return
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"[WARN] matplotlib unavailable: {exc}", file=sys.stderr)
        return
    plot_style(plt)
    cfg = CONFIGS[config_key]
    out_dir = CASE_DIR / "csv_figure" / "select_trace" / config_key
    rows = sorted(workload_rows, key=sort_key)
    labels = plot_labels(rows, "amean")
    x = list(range(len(rows)))

    fig, axes = plt.subplots(2, 1, figsize=(max(12, len(rows) * 0.52), 9.8), dpi=220, gridspec_kw={"height_ratios": [1, 1.35], "hspace": 0.62})
    axes[0].bar(x, [float(r["stlb_miss_rate"]) for r in rows], color="#1f77b4", width=0.68)
    axes[0].set_title(f"{cfg['label']} STLB total miss rate")
    axes[0].set_ylabel("Miss rate")
    style_axis(axes[0])
    bottom = [0.0] * len(rows)
    for key, label, _, _, color in CAUSES:
        vals = [100.0 * float(r[f"{key}_share"]) for r in rows]
        axes[1].bar(x, vals, bottom=bottom, label=label, color=color, width=0.68)
        bottom = [b + v for b, v in zip(bottom, vals)]
    axes[1].set_title(f"{cfg['label']} STLB miss-cause share")
    axes[1].set_ylabel("Share of STLB misses (%)")
    axes[1].set_ylim(0, 100)
    axes[1].legend(loc="lower left", frameon=True)
    style_axis(axes[1])
    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")
    axes[1].set_xlabel("Benchmark")
    fig.tight_layout()
    fig.savefig(out_dir / f"{cfg['short']}_stlb_miss_causes.png", bbox_inches="tight")
    fig.savefig(out_dir / f"{cfg['short']}_stlb_miss_causes.pdf", bbox_inches="tight")
    plt.close(fig)

    raw_vals = [float(r["stlb_mpki"]) for r in rows]
    vals = [min(v, 20.0) for v in raw_vals]
    colors = ["#d62728" if 0.8 < v < 1.0 else "#1f77b4" for v in raw_vals]
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.5), 5.2), dpi=220)
    ax.bar(x, vals, color=colors, width=0.68)
    ax.axhline(1.0, color="black", linewidth=0.9, linestyle="--", label="MPKI = 1.0")
    ax.axhline(0.8, color="#d62728", linewidth=0.9, linestyle="--", label="MPKI = 0.8")
    ax.set_ylim(0, 20.0)
    for idx, raw in enumerate(raw_vals):
        if raw > 20.0:
            ax.text(idx, 19.7, f"{raw:.1f}", ha="center", va="top", rotation=90, fontsize=8, bbox={"boxstyle": "round,pad=0.12", "facecolor": "white", "edgecolor": "none", "alpha": 0.82})
    ax.set_title(f"{cfg['label']} STLB MPKI")
    ax.set_ylabel("STLB MPKI")
    ax.set_xlabel("Benchmark")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.legend(loc="upper left", frameon=True)
    style_axis(ax)
    fig.tight_layout()
    fig.savefig(out_dir / f"{cfg['short']}_stlb_mpki.png", bbox_inches="tight")
    fig.savefig(out_dir / f"{cfg['short']}_stlb_mpki.pdf", bbox_inches="tight")
    plt.close(fig)


def write_single_config_outputs(config_key: str, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    out_dir = CASE_DIR / "csv_figure" / "select_trace" / config_key
    out_dir.mkdir(parents=True, exist_ok=True)
    workload_rows = aggregate_rows(rows)
    short = str(CONFIGS[config_key]["short"])
    write_csv(out_dir / f"{short}_trace_level.csv", TRACE_FIELDS, rows)
    write_csv(out_dir / f"{short}_workload_agg.csv", WORKLOAD_FIELDS, workload_rows)
    save_single_config_plots(config_key, workload_rows)
    return workload_rows


def make_ipc_summary_row(dataset: str, workload: str, rows: list[dict[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {
        "dataset": dataset,
        "workload": workload,
        "num_traces": len(rows),
        "nopref_ipc": geomean(float(r["nopref_ipc"]) for r in rows),
        "permit_ipc": geomean(float(r["permit_ipc"]) for r in rows),
        "discard_ipc": geomean(float(r["discard_ipc"]) for r in rows),
        "permit_vs_nopref_speedup": geomean(float(r["permit_vs_nopref_speedup"]) for r in rows),
        "discard_vs_nopref_speedup": geomean(float(r["discard_vs_nopref_speedup"]) for r in rows),
        "permit_vs_discard_speedup": geomean(float(r["permit_vs_discard_speedup"]) for r in rows),
    }
    out["permit_vs_nopref_speedup_pct"] = (float(out["permit_vs_nopref_speedup"]) - 1.0) * 100.0
    out["discard_vs_nopref_speedup_pct"] = (float(out["discard_vs_nopref_speedup"]) - 1.0) * 100.0
    out["permit_vs_discard_speedup_pct"] = (float(out["permit_vs_discard_speedup"]) - 1.0) * 100.0
    return out


def ipc_rows(raw_by_config: dict[str, dict[str, dict[str, float]]], tags: list[str]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    trace_rows: list[dict[str, object]] = []
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    by_dataset: dict[str, list[dict[str, object]]] = defaultdict(list)
    for trace_tag in tags:
        if not all(trace_tag in raw_by_config[c] for c in CONFIGS):
            continue
        dataset, workload = trace_info_from_tag(trace_tag)
        nopref = metric_value("CPU 0 cumulative IPC", raw_by_config["nopref"][trace_tag])
        permit = metric_value("CPU 0 cumulative IPC", raw_by_config["permit_pgc"][trace_tag])
        discard = metric_value("CPU 0 cumulative IPC", raw_by_config["discard_pgc"][trace_tag])
        if nopref is None or permit is None or discard is None:
            continue
        row: dict[str, object] = {
            "dataset": dataset,
            "workload": workload,
            "trace_tag": trace_tag,
            "nopref_ipc": nopref,
            "permit_ipc": permit,
            "discard_ipc": discard,
            "permit_vs_nopref_speedup": safe_div(permit, nopref),
            "discard_vs_nopref_speedup": safe_div(discard, nopref),
            "permit_vs_discard_speedup": safe_div(permit, discard),
        }
        row["permit_vs_nopref_speedup_pct"] = (float(row["permit_vs_nopref_speedup"]) - 1.0) * 100.0
        row["discard_vs_nopref_speedup_pct"] = (float(row["discard_vs_nopref_speedup"]) - 1.0) * 100.0
        row["permit_vs_discard_speedup_pct"] = (float(row["permit_vs_discard_speedup"]) - 1.0) * 100.0
        trace_rows.append(row)
        grouped[(dataset, workload)].append(row)
        by_dataset[dataset].append(row)

    workload_rows = [make_ipc_summary_row(ds, wl, rows) for (ds, wl), rows in grouped.items()]
    summary_rows = [make_ipc_summary_row(ds, f"gmean_{ds}", by_dataset[ds]) for ds in DATASET_ORDER if by_dataset.get(ds)]
    if trace_rows:
        summary_rows.append(make_ipc_summary_row("all", "gmean_all", trace_rows))
    trace_rows.sort(key=sort_key)
    workload_rows.sort(key=sort_key)
    summary_rows.sort(key=sort_key)
    return trace_rows, workload_rows, summary_rows


def save_ipc_plots(rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception as exc:
        print(f"[WARN] matplotlib unavailable: {exc}", file=sys.stderr)
        return
    plot_style(plt)
    out_dir = CASE_DIR / "csv_figure" / "select_trace" / "data_process_for_compare"
    labels = plot_labels(rows, "gmean")
    x = np.arange(len(rows))

    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.5), 5.4), dpi=220)
    width = 0.38
    ax.bar(x - width / 2, [float(r["permit_vs_nopref_speedup_pct"]) for r in rows], width=width, color="#4C78A8", label="Permit PGC vs No L1D Prefetch")
    ax.bar(x + width / 2, [float(r["discard_vs_nopref_speedup_pct"]) for r in rows], width=width, color="#F58518", label="Discard PGC vs No L1D Prefetch")
    ax.axhline(0, color="black", linewidth=0.9)
    ax.set_title("IPC speedup over No L1D Prefetch")
    ax.set_ylabel("IPC speedup (%)")
    ax.set_xlabel("Benchmark")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.legend(loc="upper left", frameon=True)
    style_axis(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "ipc_speedup_vs_nopref.png", bbox_inches="tight")
    fig.savefig(out_dir / "ipc_speedup_vs_nopref.pdf", bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.5), 5.4), dpi=220)
    ax.bar(x, [float(r["permit_vs_discard_speedup_pct"]) for r in rows], color="#54A24B", width=0.65)
    ax.axhline(0, color="black", linewidth=0.9)
    ax.set_title("Permit PGC IPC speedup over Discard PGC")
    ax.set_ylabel("IPC speedup (%)")
    ax.set_xlabel("Benchmark")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    style_axis(ax)
    fig.tight_layout()
    fig.savefig(out_dir / "permit_vs_discard_ipc_speedup.png", bbox_inches="tight")
    fig.savefig(out_dir / "permit_vs_discard_ipc_speedup.pdf", bbox_inches="tight")
    plt.close(fig)


def pairwise_trace_rows(base_rows: list[dict[str, object]], other_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    base = {str(r["trace_tag"]): r for r in base_rows}
    other = {str(r["trace_tag"]): r for r in other_rows}
    rows: list[dict[str, object]] = []
    for trace_tag in sorted(set(base) & set(other)):
        b = base[trace_tag]
        o = other[trace_tag]
        ipc_speedup = safe_div(float(o["ipc"]), float(b["ipc"]))
        mpki_norm = safe_div(float(o["stlb_mpki"]), float(b["stlb_mpki"]))
        miss_rate_norm = safe_div(float(o["stlb_miss_rate"]), float(b["stlb_miss_rate"]))
        rows.append({
            "dataset": b["dataset"],
            "workload": b["workload"],
            "trace_tag": trace_tag,
            "num_traces": 1,
            "base_ipc": b["ipc"],
            "other_ipc": o["ipc"],
            "ipc_speedup": ipc_speedup,
            "ipc_speedup_pct": (ipc_speedup - 1.0) * 100.0 if finite(ipc_speedup) else math.nan,
            "base_stlb_mpki": b["stlb_mpki"],
            "other_stlb_mpki": o["stlb_mpki"],
            "stlb_mpki_norm": mpki_norm,
            "stlb_mpki_change_pct": (mpki_norm - 1.0) * 100.0 if finite(mpki_norm) else math.nan,
            "base_stlb_miss_rate": b["stlb_miss_rate"],
            "other_stlb_miss_rate": o["stlb_miss_rate"],
            "stlb_miss_rate_norm": miss_rate_norm,
            "stlb_miss_rate_change_pct": (miss_rate_norm - 1.0) * 100.0 if finite(miss_rate_norm) else math.nan,
        })
    rows.sort(key=sort_key)
    return rows


def pairwise_summary_row(dataset: str, workload: str, rows: list[dict[str, object]]) -> dict[str, object]:
    ipc_speedup = geomean(float(r["ipc_speedup"]) for r in rows)
    mpki_norm = amean(float(r["stlb_mpki_norm"]) for r in rows)
    miss_rate_norm = amean(float(r["stlb_miss_rate_norm"]) for r in rows)
    return {
        "dataset": dataset,
        "workload": workload,
        "trace_tag": "",
        "num_traces": len(rows),
        "base_ipc": geomean(float(r["base_ipc"]) for r in rows),
        "other_ipc": geomean(float(r["other_ipc"]) for r in rows),
        "ipc_speedup": ipc_speedup,
        "ipc_speedup_pct": (ipc_speedup - 1.0) * 100.0 if finite(ipc_speedup) else math.nan,
        "base_stlb_mpki": amean(float(r["base_stlb_mpki"]) for r in rows),
        "other_stlb_mpki": amean(float(r["other_stlb_mpki"]) for r in rows),
        "stlb_mpki_norm": mpki_norm,
        "stlb_mpki_change_pct": (mpki_norm - 1.0) * 100.0 if finite(mpki_norm) else math.nan,
        "base_stlb_miss_rate": amean(float(r["base_stlb_miss_rate"]) for r in rows),
        "other_stlb_miss_rate": amean(float(r["other_stlb_miss_rate"]) for r in rows),
        "stlb_miss_rate_norm": miss_rate_norm,
        "stlb_miss_rate_change_pct": (miss_rate_norm - 1.0) * 100.0 if finite(miss_rate_norm) else math.nan,
    }


def aggregate_pairwise_rows(trace_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    by_dataset: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in trace_rows:
        grouped[(str(row["dataset"]), str(row["workload"]))].append(row)
        by_dataset[str(row["dataset"])].append(row)

    rows = [pairwise_summary_row(ds, wl, group) for (ds, wl), group in grouped.items()]
    for dataset in DATASET_ORDER:
        if by_dataset.get(dataset):
            rows.append(pairwise_summary_row(dataset, f"gmean_{dataset}", by_dataset[dataset]))
    if trace_rows:
        rows.append(pairwise_summary_row("all", "gmean_all", trace_rows))
    rows.sort(key=sort_key)
    return rows


def save_pairwise_plots(rows: list[dict[str, object]], prefix: str, title_prefix: str) -> None:
    if not rows:
        return
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"[WARN] matplotlib unavailable: {exc}", file=sys.stderr)
        return
    plot_style(plt)
    out_dir = CASE_DIR / "csv_figure" / "select_trace" / "data_process_for_compare"
    labels = plot_labels(rows, "gmean")
    x = list(range(len(rows)))

    def save_bar(metric: str, ylabel: str, title: str, out_name: str, baseline: float = 0.0) -> None:
        vals = [float(r[metric]) for r in rows]
        colors = ["#1f77b4" if v >= baseline else "#d62728" for v in vals]
        fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.5), 5.2), dpi=220)
        ax.bar(x, vals, color=colors, width=0.68)
        ax.axhline(baseline, color="black", linewidth=0.9)
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_xlabel("Benchmark")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")
        style_axis(ax)
        fig.tight_layout()
        fig.savefig(out_dir / f"{out_name}.png", bbox_inches="tight")
        fig.savefig(out_dir / f"{out_name}.pdf", bbox_inches="tight")
        plt.close(fig)

    save_bar("ipc_speedup_pct", "IPC speedup (%)", f"{title_prefix} IPC compare", f"{prefix}_ipc_compare", 0.0)
    save_bar("stlb_mpki_norm", "Normalized STLB MPKI", f"{title_prefix} STLB MPKI norm", f"{prefix}_stlb_mpki_norm", 1.0)
    save_bar("stlb_miss_rate_norm", "Normalized STLB miss rate", f"{title_prefix} STLB miss rate norm", f"{prefix}_stlb_miss_rate_norm", 1.0)


def write_pairwise_outputs(rows_by_config: dict[str, list[dict[str, object]]]) -> None:
    out_dir = CASE_DIR / "csv_figure" / "select_trace" / "data_process_for_compare"
    pairs = [
        ("pref_vs_nopref", "nopref", "permit_pgc", "Permit PGC vs No L1D Prefetch"),
        ("discard_vs_nopref", "nopref", "discard_pgc", "Discard PGC vs No L1D Prefetch"),
    ]
    for prefix, base, other, title in pairs:
        trace_rows = pairwise_trace_rows(rows_by_config.get(base, []), rows_by_config.get(other, []))
        summary_rows = aggregate_pairwise_rows(trace_rows)
        write_csv(out_dir / f"{prefix}_trace_compare.csv", COMPARE_FIELDS, trace_rows)
        write_csv(out_dir / f"{prefix}_compare.csv", COMPARE_FIELDS, summary_rows)
        save_pairwise_plots(summary_rows, prefix, title)


def write_ipc_outputs(raw_by_config: dict[str, dict[str, dict[str, float]]], tags: list[str]) -> None:
    out_dir = CASE_DIR / "csv_figure" / "select_trace" / "data_process_for_compare"
    trace_rows, workload_rows, summary_rows = ipc_rows(raw_by_config, tags)
    write_csv(out_dir / "ipc_speedup_trace.csv", IPC_FIELDS, trace_rows)
    write_csv(out_dir / "ipc_speedup_workload.csv", IPC_FIELDS, workload_rows)
    write_csv(out_dir / "ipc_speedup_summary.csv", IPC_FIELDS, summary_rows)
    save_ipc_plots(workload_rows + summary_rows)


def delta_pct(new_value: float | None, base_value: float | None) -> str:
    if new_value is None or base_value is None or not finite(new_value) or not finite(base_value) or base_value == 0:
        return ""
    return f"{((new_value - base_value) / base_value * 100.0):.12g}%"


def write_pgc_template_tables(raw_by_config: dict[str, dict[str, dict[str, float]]], tags: list[str]) -> None:
    template = SCRIPT_DIR / "vberti_pgc_tlb_compare_template.csv"
    if not template.exists():
        print(f"[WARN] missing template: {template}", file=sys.stderr)
        return
    with template.open(newline="", encoding="utf-8-sig") as f:
        template_rows = list(csv.reader(f))
    if not template_rows:
        return
    header = template_rows[0]
    col_index = {name: header.index(name) for name in header}
    out_dir = CASE_DIR / "csv_figure" / "pgc_compare"
    per_trace_dir = out_dir / "per_trace_tables"
    per_trace_dir.mkdir(parents=True, exist_ok=True)
    combined_rows: list[list[str]] = [["trace_tag", "dataset", "workload"] + header]
    missing_rows: list[dict[str, object]] = []

    label_to_config = {"Permit PGC": "permit_pgc", "Discard PGC": "discard_pgc", "No L1D Prefetch": "nopref"}
    for trace_tag in tags:
        missing = [label for label, cfg in label_to_config.items() if trace_tag not in raw_by_config[cfg]]
        if missing:
            missing_rows.append({"trace_tag": trace_tag, "missing_configs": ",".join(missing)})
            continue
        rows = [list(row) for row in template_rows]
        for row in rows[1:]:
            while len(row) < len(header):
                row.append("")
            metric = row[col_index["Metric"]].strip()
            if not metric:
                continue
            values: dict[str, float | None] = {}
            for label, cfg in label_to_config.items():
                value = metric_value(metric, raw_by_config[cfg][trace_tag])
                values[label] = value
                row[col_index[label]] = fmt_value(value) if value is not None else ""
            row[col_index["Permit vs Discard Δ%"]] = delta_pct(values["Permit PGC"], values["Discard PGC"])
            row[col_index["Permit vs No L1D Prefetch Δ%"]] = delta_pct(values["Permit PGC"], values["No L1D Prefetch"])
        with (per_trace_dir / f"{trace_tag}.csv").open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows(rows)
        dataset, workload = trace_info_from_tag(trace_tag)
        for row in rows[1:]:
            combined_rows.append([trace_tag, dataset, workload] + row)

    for out_name in ["vberti_pgc_tlb_compare.csv", "vberti_pgc_tlb_compare_all_traces.csv"]:
        with (out_dir / out_name).open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows(combined_rows)
    write_csv(out_dir / "missing_logs.csv", ["trace_tag", "missing_configs"], missing_rows)


def main() -> None:
    tags = selected_tags()
    (CASE_DIR / "csv_figure" / "select_trace" / "data_process_for_compare").mkdir(parents=True, exist_ok=True)
    local_selected = CASE_DIR / "csv_figure" / "select_trace" / "data_process_for_compare" / f"stlb_mpki_gt_{SELECT_THRESHOLD}_selected_traces.json"
    local_selected.write_text(SELECT_TRACE_JSON.read_text())

    rows_by_config: dict[str, list[dict[str, object]]] = {}
    raw_by_config: dict[str, dict[str, dict[str, float]]] = {}
    missing_summary: list[dict[str, object]] = []
    for config_key in CONFIGS:
        rows, raw, missing = collect_config(config_key, tags)
        rows_by_config[config_key] = rows
        raw_by_config[config_key] = raw
        write_single_config_outputs(config_key, rows)
        for trace_tag in missing:
            missing_summary.append({"config": config_key, "trace_tag": trace_tag})
        print(f"[INFO] {config_key}: complete={len(rows)} missing={len(missing)}")

    write_csv(CASE_DIR / "csv_figure" / "select_trace" / "data_process_for_compare" / "missing_logs_by_config.csv", ["config", "trace_tag"], missing_summary)
    write_pairwise_outputs(rows_by_config)
    write_ipc_outputs(raw_by_config, tags)
    write_pgc_template_tables(raw_by_config, tags)
    print(f"[INFO] csv_figure: {CASE_DIR / 'csv_figure'}")


if __name__ == "__main__":
    main()
