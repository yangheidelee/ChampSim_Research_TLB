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

DATASET_ORDER = ["spec06", "spec17", "gap", "ligra", "qmm", "parsec", "xsbench"]
SUMMARY_ONLY_DATASETS = {"xsbench"}

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

IDEAL_TRACE_COMPARE_FIELDS = [
    "dataset",
    "workload",
    "trace_tag",
    "baseline_ipc",
    "ideal_demand_ipc",
    "ideal_demand_speedup",
    "ideal_l1pref_ipc",
    "ideal_l1pref_speedup",
    "ideal_all_ipc",
    "ideal_all_speedup",
]

DISCARD_BASELINE_COMPARE_FIELDS = [
    "dataset",
    "workload",
    "discard_pgc_ipc",
    "pref_ipc",
    "pref_speedup",
    "ideal_demand_ipc",
    "ideal_demand_speedup",
    "ideal_l1pref_ipc",
    "ideal_l1pref_speedup",
    "ideal_all_ipc",
    "ideal_all_speedup",
]

DISCARD_BASELINE_TRACE_COMPARE_FIELDS = [
    "dataset",
    "workload",
    "trace_tag",
    "discard_pgc_ipc",
    "pref_ipc",
    "pref_speedup",
    "ideal_demand_ipc",
    "ideal_demand_speedup",
    "ideal_l1pref_ipc",
    "ideal_l1pref_speedup",
    "ideal_all_ipc",
    "ideal_all_speedup",
]

PREF_OVER_DISCARD_FIELDS = [
    "dataset",
    "workload",
    "discard_pgc_ipc",
    "pref_ipc",
    "pref_speedup",
]

STLB_REDUCTION_COMPARE_FIELDS = [
    "dataset",
    "workload",
    "discard_pgc_stlb_mpki",
    "pref_stlb_mpki",
    "pref_stlb_mpki_reduction",
    "pref_stlb_mpki_reduction_pct",
    "ideal_demand_stlb_mpki",
    "ideal_demand_stlb_mpki_reduction",
    "ideal_demand_stlb_mpki_reduction_pct",
    "ideal_l1pref_stlb_mpki",
    "ideal_l1pref_stlb_mpki_reduction",
    "ideal_l1pref_stlb_mpki_reduction_pct",
    "ideal_all_stlb_mpki",
    "ideal_all_stlb_mpki_reduction",
    "ideal_all_stlb_mpki_reduction_pct",
]

STLB_REDUCTION_TRACE_COMPARE_FIELDS = [
    "dataset",
    "workload",
    "trace_tag",
    *STLB_REDUCTION_COMPARE_FIELDS[2:],
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
    for suffix in [".champsimtrace.xz", ".champsimtrace.gz", ".champsimtrace", ".xz", ".gz"]:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def trace_info_from_tag(trace_tag: str) -> Tuple[str, str]:
    spec06 = re.match(r"^(4\d\d\.[A-Za-z0-9_]+)-\d+B$", trace_tag)
    if spec06:
        return "spec06", spec06.group(1)
    spec = re.match(r"^(6\d\d\.[A-Za-z0-9_]+)-\d+B$", trace_tag)
    if spec:
        return "spec17", spec.group(1)
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
        qmm_workload = {"compute_fp": "fp", "compute_int": "int", "srv": "srv"}[qmm.group(1)]
        return "qmm", qmm_workload
    parsec = re.match(r"^parsec_[^.]+\.[^.]+\.([^.]+)\.", trace_tag)
    if parsec:
        return "parsec", parsec.group(1)
    xsbench = re.match(r"^xs\.([A-Za-z0-9_]+)-\d+B$", trace_tag)
    if xsbench:
        return "xsbench", f"xsbench_{xsbench.group(1)}"
    return "unknown", trace_tag


def dataset_rank(dataset: str) -> int:
    try:
        return DATASET_ORDER.index(dataset)
    except ValueError:
        return len(DATASET_ORDER)


def trace_sort_key(row: Dict[str, object]) -> Tuple[int, str, str]:
    dataset = str(row["dataset"])
    return dataset_rank(dataset), str(row["workload"]), str(row["trace_tag"])


def workload_sort_key(row_or_name: object) -> Tuple[int, int, str]:
    if isinstance(row_or_name, dict):
        dataset = str(row_or_name["dataset"])
        workload = str(row_or_name["workload"])
    else:
        text = str(row_or_name)
        if text.startswith("gmean_"):
            dataset, workload = text[len("gmean_"):], text
        elif text.startswith("amean_"):
            dataset, workload = text[len("amean_"):], text
        elif text in DATASET_ORDER:
            dataset, workload = text, text
        else:
            dataset, workload = "unknown", text
    if workload.startswith("gmean_") or workload.startswith("amean_"):
        return len(DATASET_ORDER) + 1, dataset_rank(dataset), workload
    return dataset_rank(dataset), 0, workload


def parse_trace_tag_from_result_filename(path: pathlib.Path) -> Optional[str]:
    stem = path.name[:-4] if path.name.endswith(".log") else path.name
    for marker in ["-tlb-nopref-", "-tlb-pref-discard-pgc-", "-tlb-pref-", "-tlb-ideal-demand-", "-tlb-ideal-l1pref-", "-tlb-ideal-all-"]:
        if marker in stem:
            return stem.split(marker, 1)[0]
    for option_tag in ["---hide-heartbeat", "--hide-heartbeat"]:
        suffix = f"-{option_tag}"
        if stem.endswith(suffix):
            return stem[: -len(suffix)].rsplit("-", 1)[0]
    return stem.rsplit("-", 1)[0] if "-" in stem else None


def extract_metrics_from_result(path: pathlib.Path) -> Optional[Dict[str, object]]:
    trace_tag = parse_trace_tag_from_result_filename(path)
    if not trace_tag:
        log_warn(f"skip unrecognized result filename: {path.name}")
        return None

    text = path.read_text(errors="ignore")
    roi_pos = text.find("[ROI Statistics]")
    if roi_pos < 0:
        log_warn(f"skip incomplete result without ROI statistics: {path.name}")
        return None
    metric_text = text[roi_pos:]
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


def trace_cause_share(row: Dict[str, object], key: str) -> float:
    return safe_div(float(row[f"{key}_miss"]), float(row["stlb_miss"]), 0.0)


def aggregate_trace_values(dataset: str, workload: str, rows: List[Dict[str, object]]) -> Dict[str, object]:
    out: Dict[str, object] = {"dataset": dataset, "workload": workload, "num_traces": len(rows)}
    out["ipc"] = geomean([float(r["ipc"]) for r in rows])
    out["stlb_mpki"] = amean([float(r["stlb_mpki"]) for r in rows])
    out["stlb_miss_rate"] = amean([float(r["stlb_miss_rate"]) for r in rows])
    for key, _, _, _, _ in CAUSES:
        out[f"{key}_miss_rate"] = amean([float(r[f"{key}_miss_rate"]) for r in rows])
        out[f"{key}_share"] = amean([trace_cause_share(r, key) for r in rows])
    return out


def aggregate_workload(rows: List[Dict[str, object]]) -> Dict[str, object]:
    return aggregate_trace_values(str(rows[0]["dataset"]), str(rows[0]["workload"]), rows)


def summary_row_from_traces(dataset: str, rows: List[Dict[str, object]]) -> Dict[str, object]:
    return aggregate_trace_values(dataset, f"gmean_{dataset}", rows)


def aggregate_rows(trace_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
    for row in trace_rows:
        grouped[(str(row["dataset"]), str(row["workload"]))].append(row)
    rows = [
        aggregate_workload(v)
        for (dataset, workload), v in sorted(grouped.items(), key=lambda item: workload_sort_key({"dataset": item[0][0], "workload": item[0][1]}))
        if dataset not in SUMMARY_ONLY_DATASETS
    ]
    final_rows = list(rows)
    for dataset in DATASET_ORDER:
        subset = [r for r in trace_rows if r["dataset"] == dataset]
        if subset:
            final_rows.append(summary_row_from_traces(dataset, subset))
    final_rows.append(summary_row_from_traces("all", trace_rows))
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
            dataset: [str(row["trace_tag"]) for row in selected if row["dataset"] == dataset]
            for dataset in DATASET_ORDER
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


def read_trace_csv(path: pathlib.Path) -> Dict[str, Dict[str, object]]:
    with path.open(newline="") as f:
        return {str(r["trace_tag"]): r for r in csv.DictReader(f)}


def ideal_trace_compare_rows(
    baseline_csv: pathlib.Path,
    ideal_demand_csv: pathlib.Path,
    ideal_l1pref_csv: pathlib.Path,
    ideal_all_csv: pathlib.Path,
) -> List[Dict[str, object]]:
    baseline = read_trace_csv(baseline_csv)
    ideal_demand = read_trace_csv(ideal_demand_csv)
    ideal_l1pref = read_trace_csv(ideal_l1pref_csv)
    ideal_all = read_trace_csv(ideal_all_csv)
    common = sorted(
        set(baseline) & set(ideal_demand) & set(ideal_l1pref) & set(ideal_all),
        key=lambda tag: trace_sort_key({"dataset": trace_info_from_tag(tag)[0], "workload": trace_info_from_tag(tag)[1], "trace_tag": tag}),
    )
    dropped = len(set(baseline) | set(ideal_demand) | set(ideal_l1pref) | set(ideal_all)) - len(common)
    if dropped:
        log_warn(f"ideal compare uses {len(common)} common trace(s); {dropped} trace tag(s) are not present in all four configs")

    rows: List[Dict[str, object]] = []
    for tag in common:
        dataset, workload = trace_info_from_tag(tag)
        base_ipc = to_float(baseline[tag].get("ipc"))
        demand_ipc = to_float(ideal_demand[tag].get("ipc"))
        l1pref_ipc = to_float(ideal_l1pref[tag].get("ipc"))
        all_ipc = to_float(ideal_all[tag].get("ipc"))
        rows.append({
            "dataset": dataset,
            "workload": workload,
            "trace_tag": tag,
            "baseline_ipc": base_ipc,
            "ideal_demand_ipc": demand_ipc,
            "ideal_demand_speedup": safe_div(demand_ipc, base_ipc),
            "ideal_l1pref_ipc": l1pref_ipc,
            "ideal_l1pref_speedup": safe_div(l1pref_ipc, base_ipc),
            "ideal_all_ipc": all_ipc,
            "ideal_all_speedup": safe_div(all_ipc, base_ipc),
        })
    return rows


def aggregate_ideal_compare_group(dataset: str, workload: str, rows: List[Dict[str, object]]) -> Dict[str, object]:
    return {
        "dataset": dataset,
        "workload": workload,
        "baseline_ipc": geomean([float(r["baseline_ipc"]) for r in rows]),
        "ideal_demand_ipc": geomean([float(r["ideal_demand_ipc"]) for r in rows]),
        "ideal_demand_speedup": geomean([float(r["ideal_demand_speedup"]) for r in rows]),
        "ideal_l1pref_ipc": geomean([float(r["ideal_l1pref_ipc"]) for r in rows]),
        "ideal_l1pref_speedup": geomean([float(r["ideal_l1pref_speedup"]) for r in rows]),
        "ideal_all_ipc": geomean([float(r["ideal_all_ipc"]) for r in rows]),
        "ideal_all_speedup": geomean([float(r["ideal_all_speedup"]) for r in rows]),
    }


def aggregate_ideal_trace_compare(
    trace_rows: List[Dict[str, object]],
    include_datasets: Optional[set[str]] = None,
    expand_summary_only: bool = False,
) -> List[Dict[str, object]]:
    selected = [r for r in trace_rows if include_datasets is None or str(r["dataset"]) in include_datasets]
    grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
    for row in selected:
        grouped[(str(row["dataset"]), str(row["workload"]))].append(row)

    rows = [
        aggregate_ideal_compare_group(dataset, workload, group_rows)
        for (dataset, workload), group_rows in sorted(grouped.items(), key=lambda item: workload_sort_key({"dataset": item[0][0], "workload": item[0][1]}))
        if expand_summary_only or dataset not in SUMMARY_ONLY_DATASETS
    ]
    final_rows = list(rows)
    for dataset in DATASET_ORDER:
        subset = [r for r in selected if str(r["dataset"]) == dataset]
        if subset:
            final_rows.append(aggregate_ideal_compare_group(dataset, f"gmean_{dataset}", subset))
    if selected:
        final_rows.append(aggregate_ideal_compare_group("all", "gmean_all", selected))
    return final_rows


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
    trace_csvs = [
        getattr(args, "baseline_trace_csv", ""),
        getattr(args, "ideal_demand_trace_csv", ""),
        getattr(args, "ideal_l1pref_trace_csv", ""),
        getattr(args, "ideal_all_trace_csv", ""),
    ]
    if all(trace_csvs):
        trace_rows = ideal_trace_compare_rows(
            pathlib.Path(args.baseline_trace_csv),
            pathlib.Path(args.ideal_demand_trace_csv),
            pathlib.Path(args.ideal_l1pref_trace_csv),
            pathlib.Path(args.ideal_all_trace_csv),
        )
        rows = aggregate_ideal_trace_compare(trace_rows, expand_summary_only=False)
        write_csv(pathlib.Path(args.out_csv), IDEAL_COMPARE_FIELDS, rows)
        if getattr(args, "trace_out_csv", ""):
            write_csv(pathlib.Path(args.trace_out_csv), IDEAL_TRACE_COMPARE_FIELDS, trace_rows)
        if args.fig_png:
            plot_ideal_compare(rows, pathlib.Path(args.fig_png), pathlib.Path(args.fig_pdf), args.figure_title)

        if getattr(args, "focus_out_csv", ""):
            focus_datasets = {x.strip() for x in str(args.focus_datasets).split(",") if x.strip()}
            focus_rows = aggregate_ideal_trace_compare(trace_rows, include_datasets=focus_datasets, expand_summary_only=True)
            present = {str(r["dataset"]) for r in focus_rows}
            missing = sorted(focus_datasets - present)
            if missing:
                log_warn(f"focus ideal compare has no common trace for dataset(s): {', '.join(missing)}")
            write_csv(pathlib.Path(args.focus_out_csv), IDEAL_COMPARE_FIELDS, focus_rows)
            if getattr(args, "focus_fig_png", ""):
                plot_ideal_compare(focus_rows, pathlib.Path(args.focus_fig_png), pathlib.Path(args.focus_fig_pdf), args.focus_figure_title)

        log_info(f"ideal compare csv: {args.out_csv}")
        return

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


def discard_baseline_trace_compare_rows(
    discard_trace_csv: pathlib.Path,
    pref_trace_csv: pathlib.Path,
    ideal_demand_trace_csv: pathlib.Path,
    ideal_l1pref_trace_csv: pathlib.Path,
    ideal_all_trace_csv: pathlib.Path,
) -> List[Dict[str, object]]:
    discard = read_trace_csv(discard_trace_csv)
    pref = read_trace_csv(pref_trace_csv)
    ideal_demand = read_trace_csv(ideal_demand_trace_csv)
    ideal_l1pref = read_trace_csv(ideal_l1pref_trace_csv)
    ideal_all = read_trace_csv(ideal_all_trace_csv)
    common = sorted(
        set(discard) & set(pref) & set(ideal_demand) & set(ideal_l1pref) & set(ideal_all),
        key=lambda tag: trace_sort_key({"dataset": trace_info_from_tag(tag)[0], "workload": trace_info_from_tag(tag)[1], "trace_tag": tag}),
    )
    dropped = len(set(discard) | set(pref) | set(ideal_demand) | set(ideal_l1pref) | set(ideal_all)) - len(common)
    if dropped:
        log_warn(f"discard-baseline compare uses {len(common)} common trace(s); {dropped} trace tag(s) are not present in all five configs")

    rows: List[Dict[str, object]] = []
    for tag in common:
        dataset, workload = trace_info_from_tag(tag)
        discard_ipc = to_float(discard[tag].get("ipc"))
        pref_ipc = to_float(pref[tag].get("ipc"))
        demand_ipc = to_float(ideal_demand[tag].get("ipc"))
        l1pref_ipc = to_float(ideal_l1pref[tag].get("ipc"))
        all_ipc = to_float(ideal_all[tag].get("ipc"))
        rows.append({
            "dataset": dataset,
            "workload": workload,
            "trace_tag": tag,
            "discard_pgc_ipc": discard_ipc,
            "pref_ipc": pref_ipc,
            "pref_speedup": safe_div(pref_ipc, discard_ipc),
            "ideal_demand_ipc": demand_ipc,
            "ideal_demand_speedup": safe_div(demand_ipc, discard_ipc),
            "ideal_l1pref_ipc": l1pref_ipc,
            "ideal_l1pref_speedup": safe_div(l1pref_ipc, discard_ipc),
            "ideal_all_ipc": all_ipc,
            "ideal_all_speedup": safe_div(all_ipc, discard_ipc),
        })
    return rows


def aggregate_discard_baseline_group(dataset: str, workload: str, rows: List[Dict[str, object]]) -> Dict[str, object]:
    return {
        "dataset": dataset,
        "workload": workload,
        "discard_pgc_ipc": geomean([float(r["discard_pgc_ipc"]) for r in rows]),
        "pref_ipc": geomean([float(r["pref_ipc"]) for r in rows]),
        "pref_speedup": geomean([float(r["pref_speedup"]) for r in rows]),
        "ideal_demand_ipc": geomean([float(r["ideal_demand_ipc"]) for r in rows]),
        "ideal_demand_speedup": geomean([float(r["ideal_demand_speedup"]) for r in rows]),
        "ideal_l1pref_ipc": geomean([float(r["ideal_l1pref_ipc"]) for r in rows]),
        "ideal_l1pref_speedup": geomean([float(r["ideal_l1pref_speedup"]) for r in rows]),
        "ideal_all_ipc": geomean([float(r["ideal_all_ipc"]) for r in rows]),
        "ideal_all_speedup": geomean([float(r["ideal_all_speedup"]) for r in rows]),
    }


def aggregate_discard_baseline_trace_compare(trace_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
    for row in trace_rows:
        grouped[(str(row["dataset"]), str(row["workload"]))].append(row)

    rows = [
        aggregate_discard_baseline_group(dataset, workload, group_rows)
        for (dataset, workload), group_rows in sorted(grouped.items(), key=lambda item: workload_sort_key({"dataset": item[0][0], "workload": item[0][1]}))
        if dataset not in SUMMARY_ONLY_DATASETS
    ]
    final_rows = list(rows)
    for dataset in DATASET_ORDER:
        subset = [r for r in trace_rows if str(r["dataset"]) == dataset]
        if subset:
            final_rows.append(aggregate_discard_baseline_group(dataset, f"gmean_{dataset}", subset))
    if trace_rows:
        final_rows.append(aggregate_discard_baseline_group("all", "gmean_all", trace_rows))
    return final_rows


def compare_discard_baseline_configs(args: argparse.Namespace) -> None:
    trace_rows = discard_baseline_trace_compare_rows(
        pathlib.Path(args.discard_trace_csv),
        pathlib.Path(args.pref_trace_csv),
        pathlib.Path(args.ideal_demand_trace_csv),
        pathlib.Path(args.ideal_l1pref_trace_csv),
        pathlib.Path(args.ideal_all_trace_csv),
    )
    rows = aggregate_discard_baseline_trace_compare(trace_rows)
    write_csv(pathlib.Path(args.out_csv), DISCARD_BASELINE_COMPARE_FIELDS, rows)
    if getattr(args, "trace_out_csv", ""):
        write_csv(pathlib.Path(args.trace_out_csv), DISCARD_BASELINE_TRACE_COMPARE_FIELDS, trace_rows)
    if getattr(args, "pref_only_out_csv", ""):
        write_csv(pathlib.Path(args.pref_only_out_csv), PREF_OVER_DISCARD_FIELDS, rows)
    if args.fig_png:
        plot_discard_baseline_compare(rows, pathlib.Path(args.fig_png), pathlib.Path(args.fig_pdf), args.figure_title)
    if getattr(args, "pref_only_fig_png", ""):
        plot_pref_over_discard(rows, pathlib.Path(args.pref_only_fig_png), pathlib.Path(args.pref_only_fig_pdf), args.pref_only_figure_title)
    log_info(f"discard-baseline compare csv: {args.out_csv}")


def stlb_reduction_values(prefix: str, cfg_mpki: float, discard_mpki: float) -> Dict[str, object]:
    norm = safe_div(cfg_mpki, discard_mpki)
    reduction = discard_mpki - cfg_mpki if finite(discard_mpki) and finite(cfg_mpki) else math.nan
    reduction_pct = (1.0 - norm) * 100.0 if finite(norm) else math.nan
    return {
        f"{prefix}_stlb_mpki": cfg_mpki,
        f"{prefix}_stlb_mpki_reduction": reduction,
        f"{prefix}_stlb_mpki_reduction_pct": reduction_pct,
    }


def discard_baseline_stlb_reduction_trace_rows(
    discard_trace_csv: pathlib.Path,
    pref_trace_csv: pathlib.Path,
    ideal_demand_trace_csv: pathlib.Path,
    ideal_l1pref_trace_csv: pathlib.Path,
    ideal_all_trace_csv: pathlib.Path,
) -> List[Dict[str, object]]:
    discard = read_trace_csv(discard_trace_csv)
    pref = read_trace_csv(pref_trace_csv)
    ideal_demand = read_trace_csv(ideal_demand_trace_csv)
    ideal_l1pref = read_trace_csv(ideal_l1pref_trace_csv)
    ideal_all = read_trace_csv(ideal_all_trace_csv)
    common = sorted(
        set(discard) & set(pref) & set(ideal_demand) & set(ideal_l1pref) & set(ideal_all),
        key=lambda tag: trace_sort_key({"dataset": trace_info_from_tag(tag)[0], "workload": trace_info_from_tag(tag)[1], "trace_tag": tag}),
    )
    dropped = len(set(discard) | set(pref) | set(ideal_demand) | set(ideal_l1pref) | set(ideal_all)) - len(common)
    if dropped:
        log_warn(f"STLB reduction compare uses {len(common)} common trace(s); {dropped} trace tag(s) are not present in all five configs")

    rows: List[Dict[str, object]] = []
    for tag in common:
        dataset, workload = trace_info_from_tag(tag)
        discard_mpki = to_float(discard[tag].get("stlb_mpki"))
        row: Dict[str, object] = {
            "dataset": dataset,
            "workload": workload,
            "trace_tag": tag,
            "discard_pgc_stlb_mpki": discard_mpki,
        }
        row.update(stlb_reduction_values("pref", to_float(pref[tag].get("stlb_mpki")), discard_mpki))
        row.update(stlb_reduction_values("ideal_demand", to_float(ideal_demand[tag].get("stlb_mpki")), discard_mpki))
        row.update(stlb_reduction_values("ideal_l1pref", to_float(ideal_l1pref[tag].get("stlb_mpki")), discard_mpki))
        row.update(stlb_reduction_values("ideal_all", to_float(ideal_all[tag].get("stlb_mpki")), discard_mpki))
        rows.append(row)
    return rows


def aggregate_stlb_reduction_group(dataset: str, workload: str, rows: List[Dict[str, object]]) -> Dict[str, object]:
    out: Dict[str, object] = {
        "dataset": dataset,
        "workload": workload,
        "discard_pgc_stlb_mpki": amean([float(r["discard_pgc_stlb_mpki"]) for r in rows]),
    }
    for prefix in ["pref", "ideal_demand", "ideal_l1pref", "ideal_all"]:
        out[f"{prefix}_stlb_mpki"] = amean([float(r[f"{prefix}_stlb_mpki"]) for r in rows])
        out[f"{prefix}_stlb_mpki_reduction"] = amean([float(r[f"{prefix}_stlb_mpki_reduction"]) for r in rows])
        out[f"{prefix}_stlb_mpki_reduction_pct"] = amean([float(r[f"{prefix}_stlb_mpki_reduction_pct"]) for r in rows])
    return out


def aggregate_stlb_reduction_trace_compare(trace_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
    for row in trace_rows:
        grouped[(str(row["dataset"]), str(row["workload"]))].append(row)

    rows = [
        aggregate_stlb_reduction_group(dataset, workload, group_rows)
        for (dataset, workload), group_rows in sorted(grouped.items(), key=lambda item: workload_sort_key({"dataset": item[0][0], "workload": item[0][1]}))
        if dataset not in SUMMARY_ONLY_DATASETS
    ]
    final_rows = list(rows)
    for dataset in DATASET_ORDER:
        subset = [r for r in trace_rows if str(r["dataset"]) == dataset]
        if subset:
            final_rows.append(aggregate_stlb_reduction_group(dataset, f"amean_{dataset}", subset))
    if trace_rows:
        final_rows.append(aggregate_stlb_reduction_group("all", "amean_all", trace_rows))
    return final_rows


def compare_discard_baseline_stlb_reduction(args: argparse.Namespace) -> None:
    trace_rows = discard_baseline_stlb_reduction_trace_rows(
        pathlib.Path(args.discard_trace_csv),
        pathlib.Path(args.pref_trace_csv),
        pathlib.Path(args.ideal_demand_trace_csv),
        pathlib.Path(args.ideal_l1pref_trace_csv),
        pathlib.Path(args.ideal_all_trace_csv),
    )
    rows = aggregate_stlb_reduction_trace_compare(trace_rows)
    write_csv(pathlib.Path(args.out_csv), STLB_REDUCTION_COMPARE_FIELDS, rows)
    if getattr(args, "trace_out_csv", ""):
        write_csv(pathlib.Path(args.trace_out_csv), STLB_REDUCTION_TRACE_COMPARE_FIELDS, trace_rows)
    if args.fig_png:
        plot_discard_baseline_stlb_reduction(rows, pathlib.Path(args.fig_png), pathlib.Path(args.fig_pdf), args.figure_title)
    log_info(f"discard-baseline STLB reduction csv: {args.out_csv}")


def finite_rows(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return [r for r in rows if not str(r["workload"]).startswith(("gmean_", "amean_"))]


def plot_label(row: Dict[str, object], summary_prefix: str = "gmean") -> str:
    workload = str(row["workload"])
    if workload.startswith("gmean_"):
        return f"{summary_prefix}_{workload[len('gmean_'):]}"
    if workload.startswith("amean_"):
        return f"{summary_prefix}_{workload[len('amean_'):]}"
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
    labels = [plot_label(r, "amean") for r in rows]
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
        ("L1 prefetch", "ideal_l1pref_speedup", "#f58518"),
        ("Demand", "ideal_demand_speedup", "#4c78a8"),
        ("All", "ideal_all_speedup", "#54a24b"),
    ]
    width = 0.24
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.58), 5.6), dpi=220)
    offsets = [-(width), 0.0, width]
    plotted_vals: List[float] = []
    for offset, (label, key, color) in zip(offsets, series):
        vals = [(float(r[key]) - 1.0) * 100.0 for r in rows]
        plotted_vals.extend(vals)
        ax.bar([i + offset for i in x], vals, width=width, label=label, color=color)
    min_val = min(plotted_vals) if plotted_vals else 0.0
    max_val = max(plotted_vals) if plotted_vals else 0.0
    y_min = min(-10.0, math.floor((min_val - 1.0) / 5.0) * 5.0)
    y_max = max(10.0, math.ceil((max_val + 2.0) / 5.0) * 5.0)
    ax.set_ylim(y_min, y_max)
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_title(title)
    ax.set_ylabel("IPC gain over baseline (%)")
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


def plot_discard_baseline_compare(rows: List[Dict[str, object]], fig_png: pathlib.Path, fig_pdf: pathlib.Path, title: str) -> None:
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
        ("Pref", "pref_speedup", "#8e6c8a"),
        ("L1 prefetch", "ideal_l1pref_speedup", "#f58518"),
        ("Demand", "ideal_demand_speedup", "#4c78a8"),
        ("All", "ideal_all_speedup", "#54a24b"),
    ]
    width = 0.2
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.66), 5.8), dpi=220)
    offsets = [-1.5 * width, -0.5 * width, 0.5 * width, 1.5 * width]
    plotted_vals: List[float] = []
    for offset, (label, key, color) in zip(offsets, series):
        vals = [(float(r[key]) - 1.0) * 100.0 for r in rows]
        plotted_vals.extend(vals)
        ax.bar([i + offset for i in x], vals, width=width, label=label, color=color)
    min_val = min(plotted_vals) if plotted_vals else 0.0
    max_val = max(plotted_vals) if plotted_vals else 0.0
    y_min = min(-10.0, math.floor((min_val - 1.0) / 5.0) * 5.0)
    y_max = max(10.0, math.ceil((max_val + 2.0) / 5.0) * 5.0)
    ax.set_ylim(y_min, y_max)
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_title(title)
    ax.set_ylabel("IPC gain over pref_discard_pgc (%)")
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


def plot_discard_baseline_stlb_reduction(rows: List[Dict[str, object]], fig_png: pathlib.Path, fig_pdf: pathlib.Path, title: str) -> None:
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
    series = [
        ("Pref", "pref_stlb_mpki_reduction_pct", "#8e6c8a"),
        ("L1 prefetch", "ideal_l1pref_stlb_mpki_reduction_pct", "#f58518"),
        ("Demand", "ideal_demand_stlb_mpki_reduction_pct", "#4c78a8"),
        ("All", "ideal_all_stlb_mpki_reduction_pct", "#54a24b"),
    ]
    width = 0.2
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.66), 5.8), dpi=220)
    offsets = [-1.5 * width, -0.5 * width, 0.5 * width, 1.5 * width]
    plotted_vals: List[float] = []
    for offset, (label, key, color) in zip(offsets, series):
        vals = [float(r[key]) for r in rows]
        plotted_vals.extend(vals)
        ax.bar([i + offset for i in x], vals, width=width, label=label, color=color)
    min_val = min(plotted_vals) if plotted_vals else 0.0
    max_val = max(plotted_vals) if plotted_vals else 0.0
    y_min = min(-10.0, math.floor((min_val - 2.0) / 5.0) * 5.0)
    y_max = max(10.0, math.ceil((max_val + 2.0) / 5.0) * 5.0)
    ax.set_ylim(y_min, y_max)
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_title(title)
    ax.set_ylabel("STLB MPKI reduction over pref_discard_pgc (%)")
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


def plot_pref_over_discard(rows: List[Dict[str, object]], fig_png: pathlib.Path, fig_pdf: pathlib.Path, title: str) -> None:
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
    vals = [(float(r["pref_speedup"]) - 1.0) * 100.0 for r in rows]
    colors = ["#4c78a8" if v >= 0.0 else "#d62728" for v in vals]
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.5), 5.2), dpi=220)
    ax.bar(x, vals, color=colors, width=0.68)
    min_val = min(vals) if vals else 0.0
    max_val = max(vals) if vals else 0.0
    y_min = min(-10.0, math.floor((min_val - 1.0) / 5.0) * 5.0)
    y_max = max(10.0, math.ceil((max_val + 2.0) / 5.0) * 5.0)
    ax.set_ylim(y_min, y_max)
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_title(title)
    ax.set_ylabel("IPC gain over pref_discard_pgc (%)")
    ax.set_xlabel("Benchmark")
    style_axis(ax)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    fig_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_png, bbox_inches="tight")
    if fig_pdf:
        fig.savefig(fig_pdf, bbox_inches="tight")


def main() -> None:
    parser = argparse.ArgumentParser(description="SPEC06+SPEC17+GAP+Ligra+QMM+PARSEC TLB select-trace processing")
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
    p_ideal.add_argument("--baseline-trace-csv", default="")
    p_ideal.add_argument("--ideal-demand-trace-csv", default="")
    p_ideal.add_argument("--ideal-l1pref-trace-csv", default="")
    p_ideal.add_argument("--ideal-all-trace-csv", default="")
    p_ideal.add_argument("--out-csv", required=True)
    p_ideal.add_argument("--trace-out-csv", default="")
    p_ideal.add_argument("--fig-png", default="")
    p_ideal.add_argument("--fig-pdf", default="")
    p_ideal.add_argument("--figure-title", default="Ideal STLB IPC upper bound")
    p_ideal.add_argument("--focus-datasets", default="gap,xsbench")
    p_ideal.add_argument("--focus-out-csv", default="")
    p_ideal.add_argument("--focus-fig-png", default="")
    p_ideal.add_argument("--focus-fig-pdf", default="")
    p_ideal.add_argument("--focus-figure-title", default="Ideal STLB IPC upper bound: GAP + XSBench")
    p_ideal.set_defaults(func=compare_ideal_configs)

    p_discard = sub.add_parser("compare-discard-baseline")
    p_discard.add_argument("--discard-trace-csv", required=True)
    p_discard.add_argument("--pref-trace-csv", required=True)
    p_discard.add_argument("--ideal-demand-trace-csv", required=True)
    p_discard.add_argument("--ideal-l1pref-trace-csv", required=True)
    p_discard.add_argument("--ideal-all-trace-csv", required=True)
    p_discard.add_argument("--out-csv", required=True)
    p_discard.add_argument("--trace-out-csv", default="")
    p_discard.add_argument("--fig-png", default="")
    p_discard.add_argument("--fig-pdf", default="")
    p_discard.add_argument("--figure-title", default="IPC gain over pref_discard_pgc")
    p_discard.add_argument("--pref-only-out-csv", default="")
    p_discard.add_argument("--pref-only-fig-png", default="")
    p_discard.add_argument("--pref-only-fig-pdf", default="")
    p_discard.add_argument("--pref-only-figure-title", default="pref over pref_discard_pgc IPC gain")
    p_discard.set_defaults(func=compare_discard_baseline_configs)

    p_stlb_reduction = sub.add_parser("compare-discard-stlb-reduction")
    p_stlb_reduction.add_argument("--discard-trace-csv", required=True)
    p_stlb_reduction.add_argument("--pref-trace-csv", required=True)
    p_stlb_reduction.add_argument("--ideal-demand-trace-csv", required=True)
    p_stlb_reduction.add_argument("--ideal-l1pref-trace-csv", required=True)
    p_stlb_reduction.add_argument("--ideal-all-trace-csv", required=True)
    p_stlb_reduction.add_argument("--out-csv", required=True)
    p_stlb_reduction.add_argument("--trace-out-csv", default="")
    p_stlb_reduction.add_argument("--fig-png", default="")
    p_stlb_reduction.add_argument("--fig-pdf", default="")
    p_stlb_reduction.add_argument("--figure-title", default="STLB MPKI reduction over pref_discard_pgc")
    p_stlb_reduction.set_defaults(func=compare_discard_baseline_stlb_reduction)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
