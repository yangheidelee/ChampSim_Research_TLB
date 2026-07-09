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
    "stlb_demand_access",
    "stlb_demand_hit",
    "stlb_demand_miss",
    "stlb_demand_mpki",
    "stlb_demand_miss_rate",
    "stlb_raw_demand_miss",
    "stlb_raw_demand_mpki",
    "cp_pb_demand_hit",
    "cp_pb_demand_hit_mpki",
    "stlb_pb_demand_miss",
    "stlb_pb_demand_mpki",
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
    "stlb_demand_mpki",
    "stlb_demand_miss_rate",
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

CPPB_TRACE_COMPARE_FIELDS = [
    "dataset",
    "workload",
    "trace_tag",
    "permit_ipc",
    "cppb_ipc",
    "cppb_ipc_speedup",
    "cppb_ipc_speedup_pct",
    "permit_stlb_demand_mpki",
    "cppb_stlb_demand_mpki",
    "cppb_stlb_pb_demand_mpki",
    "stlb_demand_mpki_reduction",
    "stlb_demand_mpki_reduction_pct",
    "stlb_pb_demand_mpki_reduction",
    "stlb_pb_demand_mpki_reduction_pct",
]

CPPB_COMPARE_FIELDS = [
    "dataset",
    "workload",
    "num_traces",
    "permit_ipc",
    "cppb_ipc",
    "cppb_ipc_speedup",
    "cppb_ipc_speedup_pct",
    "permit_stlb_demand_mpki",
    "cppb_stlb_demand_mpki",
    "cppb_stlb_pb_demand_mpki",
    "stlb_demand_mpki_reduction",
    "stlb_demand_mpki_reduction_pct",
    "stlb_pb_demand_mpki_reduction",
    "stlb_pb_demand_mpki_reduction_pct",
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
        qmm_workload = {"compute_fp": "qmm_fp", "compute_int": "qmm_int", "srv": "qmm_srv"}[qmm.group(1)]
        return "qmm", qmm_workload
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
        elif text in DATASET_ORDER:
            dataset, workload = text, text
        else:
            dataset, workload = "unknown", text
    if workload.startswith("gmean_"):
        return len(DATASET_ORDER) + 1, dataset_rank(dataset), workload
    return dataset_rank(dataset), 0, workload


def parse_trace_tag_from_result_filename(path: pathlib.Path) -> Optional[str]:
    stem = path.name[:-4] if path.name.endswith(".log") else path.name
    for binary_tag in ["tlb-nopref-1core", "tlb-pref-cppb-1core", "tlb-pref-1core"]:
        marker = f"-{binary_tag}-"
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
    if "[ROI Statistics]" not in text:
        log_warn(f"skip incomplete result without [ROI Statistics]: {path.name}")
        return None
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
        "stlb_demand_access": extract_metric(metric_text, "Core_0_STLB_demand_access", 0.0),
        "stlb_demand_hit": extract_metric(metric_text, "Core_0_STLB_demand_hit", 0.0),
        "stlb_demand_miss": extract_metric(metric_text, "Core_0_STLB_demand_miss", 0.0),
        "stlb_demand_mpki": extract_metric(metric_text, "Core_0_STLB_demand_MPKI", math.nan),
        "stlb_demand_miss_rate": extract_metric(metric_text, "Core_0_STLB_demand_miss_rate", math.nan),
        "stlb_raw_demand_miss": extract_metric(metric_text, "Core_0_STLB_raw_demand_miss", math.nan),
        "stlb_raw_demand_mpki": extract_metric(metric_text, "Core_0_STLB_raw_demand_mpki", math.nan),
        "cp_pb_demand_hit": extract_metric(metric_text, "Core_0_CP_PB_demand_hit", math.nan),
        "cp_pb_demand_hit_mpki": extract_metric(metric_text, "Core_0_CP_PB_demand_hit_mpki", math.nan),
        "stlb_pb_demand_miss": extract_metric(metric_text, "Core_0_STLB_PB_demand_miss", math.nan),
        "stlb_pb_demand_mpki": extract_metric(metric_text, "Core_0_STLB_PB_demand_mpki", math.nan),
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
    if not finite(float(row["stlb_demand_mpki"])):
        row["stlb_demand_mpki"] = safe_div(float(row["stlb_demand_miss"]) * 1000.0, float(row["instructions"]))
    if not finite(float(row["stlb_demand_miss_rate"])):
        row["stlb_demand_miss_rate"] = safe_div(float(row["stlb_demand_miss"]), float(row["stlb_demand_access"]))
    if not finite(float(row["stlb_raw_demand_mpki"])):
        row["stlb_raw_demand_mpki"] = safe_div(float(row["stlb_raw_demand_miss"]) * 1000.0, float(row["instructions"]))
    if not finite(float(row["cp_pb_demand_hit_mpki"])):
        row["cp_pb_demand_hit_mpki"] = safe_div(float(row["cp_pb_demand_hit"]) * 1000.0, float(row["instructions"]))
    if not finite(float(row["stlb_pb_demand_mpki"])):
        row["stlb_pb_demand_mpki"] = safe_div(float(row["stlb_pb_demand_miss"]) * 1000.0, float(row["instructions"]))

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
    if selected_tags is not None:
        found = {str(row["trace_tag"]) for row in rows}
        missing = sorted(selected_tags - found)
        if missing:
            preview = ", ".join(missing[:20])
            suffix = " ..." if len(missing) > 20 else ""
            raise SystemExit(f"Missing complete selected result logs in {result_dir}: {len(missing)} traces: {preview}{suffix}")
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
    out["stlb_demand_mpki"] = amean([float(r["stlb_demand_mpki"]) for r in rows])
    out["stlb_demand_miss_rate"] = amean([float(r["stlb_demand_miss_rate"]) for r in rows])
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
    rows = [aggregate_workload(v) for _, v in sorted(grouped.items(), key=lambda item: workload_sort_key({"dataset": item[0][0], "workload": item[0][1]}))]
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
    if args.mpki_fig_png:
        plot_single_stlb_mpki(workload_rows, pathlib.Path(args.mpki_fig_png), pathlib.Path(args.mpki_fig_pdf), args.mpki_figure_title)
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


def read_trace_csv(path: pathlib.Path) -> Dict[str, Dict[str, object]]:
    with path.open(newline="") as f:
        return {r["trace_tag"]: r for r in csv.DictReader(f)}


def make_cppb_trace_compare_rows(permit: Dict[str, Dict[str, object]], cppb: Dict[str, Dict[str, object]]) -> List[Dict[str, object]]:
    permit_tags = set(permit)
    cppb_tags = set(cppb)
    if permit_tags != cppb_tags:
        missing_cppb = sorted(permit_tags - cppb_tags)
        missing_permit = sorted(cppb_tags - permit_tags)
        detail = []
        if missing_cppb:
            detail.append(f"missing in cppb: {len(missing_cppb)} ({', '.join(missing_cppb[:12])}{' ...' if len(missing_cppb) > 12 else ''})")
        if missing_permit:
            detail.append(f"missing in permit: {len(missing_permit)} ({', '.join(missing_permit[:12])}{' ...' if len(missing_permit) > 12 else ''})")
        raise SystemExit("Trace set mismatch between permit and cppb CSVs: " + "; ".join(detail))

    rows: List[Dict[str, object]] = []
    for trace_tag in sorted(permit_tags):
        p = permit[trace_tag]
        c = cppb[trace_tag]
        p_ipc = to_float(p.get("ipc"))
        c_ipc = to_float(c.get("ipc"))
        speedup = safe_div(c_ipc, p_ipc)
        p_mpki = to_float(p.get("stlb_demand_mpki"))
        c_mpki = to_float(c.get("stlb_demand_mpki"))
        c_pb_mpki = to_float(c.get("stlb_pb_demand_mpki"))
        reduction = p_mpki - c_mpki if finite(p_mpki) and finite(c_mpki) else math.nan
        reduction_ratio = safe_div(c_mpki, p_mpki)
        reduction_pct = (1.0 - reduction_ratio) * 100.0 if finite(reduction_ratio) else math.nan
        pb_reduction = p_mpki - c_pb_mpki if finite(p_mpki) and finite(c_pb_mpki) else math.nan
        pb_reduction_ratio = safe_div(c_pb_mpki, p_mpki)
        pb_reduction_pct = (1.0 - pb_reduction_ratio) * 100.0 if finite(pb_reduction_ratio) else math.nan
        rows.append({
            "dataset": p.get("dataset", "unknown"),
            "workload": p.get("workload", trace_tag),
            "trace_tag": trace_tag,
            "permit_ipc": p_ipc,
            "cppb_ipc": c_ipc,
            "cppb_ipc_speedup": speedup,
            "cppb_ipc_speedup_pct": (speedup - 1.0) * 100.0 if finite(speedup) else math.nan,
            "permit_stlb_demand_mpki": p_mpki,
            "cppb_stlb_demand_mpki": c_mpki,
            "cppb_stlb_pb_demand_mpki": c_pb_mpki,
            "stlb_demand_mpki_reduction": reduction,
            "stlb_demand_mpki_reduction_pct": reduction_pct,
            "stlb_pb_demand_mpki_reduction": pb_reduction,
            "stlb_pb_demand_mpki_reduction_pct": pb_reduction_pct,
        })
    rows.sort(key=trace_sort_key)
    return rows


def aggregate_cppb_compare_rows(dataset: str, workload: str, rows: List[Dict[str, object]]) -> Dict[str, object]:
    permit_ipc = geomean([float(r["permit_ipc"]) for r in rows])
    cppb_ipc = geomean([float(r["cppb_ipc"]) for r in rows])
    speedup = geomean([float(r["cppb_ipc_speedup"]) for r in rows])
    permit_mpki = amean([float(r["permit_stlb_demand_mpki"]) for r in rows])
    cppb_mpki = amean([float(r["cppb_stlb_demand_mpki"]) for r in rows])
    cppb_pb_mpki = amean([float(r["cppb_stlb_pb_demand_mpki"]) for r in rows])
    reduction = permit_mpki - cppb_mpki if finite(permit_mpki) and finite(cppb_mpki) else math.nan
    ratio = safe_div(cppb_mpki, permit_mpki)
    pb_reduction = permit_mpki - cppb_pb_mpki if finite(permit_mpki) and finite(cppb_pb_mpki) else math.nan
    pb_ratio = safe_div(cppb_pb_mpki, permit_mpki)
    return {
        "dataset": dataset,
        "workload": workload,
        "num_traces": len(rows),
        "permit_ipc": permit_ipc,
        "cppb_ipc": cppb_ipc,
        "cppb_ipc_speedup": speedup,
        "cppb_ipc_speedup_pct": (speedup - 1.0) * 100.0 if finite(speedup) else math.nan,
        "permit_stlb_demand_mpki": permit_mpki,
        "cppb_stlb_demand_mpki": cppb_mpki,
        "cppb_stlb_pb_demand_mpki": cppb_pb_mpki,
        "stlb_demand_mpki_reduction": reduction,
        "stlb_demand_mpki_reduction_pct": (1.0 - ratio) * 100.0 if finite(ratio) else math.nan,
        "stlb_pb_demand_mpki_reduction": pb_reduction,
        "stlb_pb_demand_mpki_reduction_pct": (1.0 - pb_ratio) * 100.0 if finite(pb_ratio) else math.nan,
    }


def make_cppb_workload_compare_rows(trace_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
    for row in trace_rows:
        grouped[(str(row["dataset"]), str(row["workload"]))].append(row)
    rows = [
        aggregate_cppb_compare_rows(k[0], k[1], v)
        for k, v in sorted(grouped.items(), key=lambda item: workload_sort_key({"dataset": item[0][0], "workload": item[0][1]}))
    ]
    final_rows = list(rows)
    for dataset in DATASET_ORDER:
        subset = [r for r in trace_rows if r["dataset"] == dataset]
        if subset:
            final_rows.append(aggregate_cppb_compare_rows(dataset, f"gmean_{dataset}", subset))
    final_rows.append(aggregate_cppb_compare_rows("all", "gmean_all", trace_rows))
    return final_rows


def compare_permit_cppb(args: argparse.Namespace) -> None:
    permit = read_trace_csv(pathlib.Path(args.permit_trace_csv))
    cppb = read_trace_csv(pathlib.Path(args.cppb_trace_csv))
    trace_rows = make_cppb_trace_compare_rows(permit, cppb)
    rows = make_cppb_workload_compare_rows(trace_rows)
    write_csv(pathlib.Path(args.trace_out_csv), CPPB_TRACE_COMPARE_FIELDS, trace_rows)
    write_csv(pathlib.Path(args.out_csv), CPPB_COMPARE_FIELDS, rows)
    if args.ipc_fig_png:
        plot_cppb_ipc_compare(rows, pathlib.Path(args.ipc_fig_png), pathlib.Path(args.ipc_fig_pdf))
    if args.stlb_fig_png:
        plot_cppb_stlb_demand_reduction(rows, pathlib.Path(args.stlb_fig_png), pathlib.Path(args.stlb_fig_pdf))
    log_info(f"trace compare csv: {args.trace_out_csv}")
    log_info(f"compare csv: {args.out_csv}")


def finite_rows(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return [r for r in rows if not str(r["workload"]).startswith("gmean_")]


def plot_label(row: Dict[str, object], summary_prefix: str = "gmean") -> str:
    workload = str(row["workload"])
    if workload.startswith("gmean_"):
        return f"{summary_prefix}_{workload[len('gmean_'):]}"
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
    fig, axes = plt.subplots(2, 1, figsize=(max(12, len(rows) * 0.52), 9.8), dpi=220, gridspec_kw={"height_ratios": [1, 1.35], "hspace": 0.62})

    axes[0].bar(x, [float(r["stlb_miss_rate"]) for r in rows], color="#1f77b4", width=0.68)
    axes[0].set_title("STLB total miss rate", pad=8)
    axes[0].set_ylabel("Miss rate")
    style_axis(axes[0])

    bottom = [0.0] * len(rows)
    for key, label, _, _, color in CAUSES:
        vals = [100.0 * float(r[f"{key}_share"]) for r in rows]
        axes[1].bar(x, vals, bottom=bottom, label=label, color=color, width=0.68)
        bottom = [b + v for b, v in zip(bottom, vals)]
    axes[1].set_title("STLB miss-cause share", pad=8)
    axes[1].set_ylabel("Share of STLB misses (%)")
    axes[1].set_ylim(0, 100)
    style_axis(axes[1])

    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")
    axes[1].set_xlabel("Benchmark")
    axes[1].legend(loc="lower left", ncols=1, frameon=True, edgecolor="#b0b0b0")
    fig.suptitle(title, fontsize=15)
    fig.subplots_adjust(left=0.07, right=0.99, bottom=0.13, top=0.91, hspace=0.64)
    fig_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_png, bbox_inches="tight")
    if fig_pdf:
        fig.savefig(fig_pdf, bbox_inches="tight")


def plot_single_stlb_mpki(rows: List[Dict[str, object]], fig_png: pathlib.Path, fig_pdf: pathlib.Path, title: str) -> None:
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
    raw_vals = [float(r["stlb_mpki"]) for r in rows]
    cap = 20.0
    vals = [min(v, cap) for v in raw_vals]
    colors = ["#d62728" if 0.8 < v < 1.0 else "#1f77b4" for v in raw_vals]

    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.5), 5.2), dpi=220)
    ax.bar(x, vals, color=colors, width=0.68)
    ax.axhline(1.0, color="black", linewidth=0.9, linestyle="--", alpha=0.75, label="MPKI = 1.0")
    ax.axhline(0.8, color="#d62728", linewidth=0.9, linestyle="--", alpha=0.65, label="MPKI = 0.8")
    ax.axhline(cap, color="#666666", linewidth=0.8, linestyle=":", alpha=0.75, label="Display cap = 20")
    ax.set_ylim(0, cap)
    for idx, raw in enumerate(raw_vals):
        if raw > cap:
            ax.text(
                idx,
                cap * 0.985,
                f"{raw:.1f}",
                ha="center",
                va="top",
                rotation=90,
                fontsize=8,
                color="black",
                bbox={"boxstyle": "round,pad=0.12", "facecolor": "white", "edgecolor": "none", "alpha": 0.82},
            )
    ax.set_title(title)
    ax.set_ylabel("STLB MPKI")
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
    raw_vals = [float(r["ipc_speedup_pct"]) for r in rows]
    display_cap = 100.0
    vals = [min(v, display_cap) for v in raw_vals]
    colors = ["#1f77b4" if v >= 0.0 else "#d62728" for v in raw_vals]
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.5), 5.2), dpi=220)
    ax.bar(x, vals, color=colors, width=0.68)
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.axhline(display_cap, color="#666666", linewidth=0.8, linestyle=":", alpha=0.75, label="Display cap = 100%")
    ax.set_ylim(bottom=min(0.0, min(vals, default=0.0)), top=display_cap)
    for idx, raw in enumerate(raw_vals):
        if raw > display_cap:
            ax.text(
                idx,
                display_cap * 0.985,
                f"{raw:.1f}%",
                ha="center",
                va="top",
                rotation=90,
                fontsize=8,
                color="black",
                bbox={"boxstyle": "round,pad=0.12", "facecolor": "white", "edgecolor": "none", "alpha": 0.82},
            )
    ax.set_title(title)
    ax.set_ylabel("IPC speedup over nopref (%)")
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


def plot_cppb_ipc_compare(rows: List[Dict[str, object]], fig_png: pathlib.Path, fig_pdf: pathlib.Path) -> None:
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
    vals = [float(r["cppb_ipc_speedup_pct"]) for r in rows]
    colors = ["#4C78A8" if v >= 0.0 else "#C44E52" for v in vals]
    ymin = min(-5.0, min(vals, default=0.0) * 1.15)
    ymax = max(5.0, max(vals, default=0.0) * 1.15)
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.5), 5.2), dpi=220)
    ax.bar(x, vals, color=colors, width=0.68)
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_ylim(ymin, ymax)
    ax.set_title("Permit PGC + CP-PB IPC speedup over Permit PGC")
    ax.set_ylabel("IPC speedup (%)")
    ax.set_xlabel("Benchmark")
    style_axis(ax)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    fig_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_png, bbox_inches="tight")
    if fig_pdf:
        fig.savefig(fig_pdf, bbox_inches="tight")


def plot_cppb_stlb_demand_reduction(rows: List[Dict[str, object]], fig_png: pathlib.Path, fig_pdf: pathlib.Path) -> None:
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
    raw_vals = [float(r["stlb_demand_mpki_reduction_pct"]) for r in rows]
    residual_vals = [float(r["stlb_pb_demand_mpki_reduction_pct"]) for r in rows]
    all_vals = raw_vals + residual_vals
    ymin = min(-5.0, min(all_vals, default=0.0) * 1.15)
    ymax = max(5.0, max(all_vals, default=0.0) * 1.15)
    width = 0.36
    fig, ax = plt.subplots(figsize=(max(12, len(rows) * 0.58), 5.4), dpi=220)
    ax.bar(
        [idx - width / 2 for idx in x],
        raw_vals,
        color="#F4A261",
        width=width,
        label="Raw STLB demand miss (CP-PB hits counted)",
    )
    ax.bar(
        [idx + width / 2 for idx in x],
        residual_vals,
        color="#D95F02",
        width=width,
        label="Residual after CP-PB hit (hits removed)",
    )
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_ylim(ymin, ymax)
    ax.set_title("Permit PGC + CP-PB STLB demand MPKI reduction over Permit PGC")
    ax.set_ylabel("Reduction vs Permit PGC baseline (%)")
    ax.set_xlabel("Benchmark")
    style_axis(ax)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.legend(loc="lower left", ncols=1, frameon=True, edgecolor="#b0b0b0")
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
    p_single.add_argument("--mpki-fig-png", default="")
    p_single.add_argument("--mpki-fig-pdf", default="")
    p_single.add_argument("--mpki-figure-title", default="STLB MPKI")
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

    p_cppb = sub.add_parser("compare-permit-cppb")
    p_cppb.add_argument("--permit-trace-csv", required=True)
    p_cppb.add_argument("--cppb-trace-csv", required=True)
    p_cppb.add_argument("--out-csv", required=True)
    p_cppb.add_argument("--trace-out-csv", required=True)
    p_cppb.add_argument("--ipc-fig-png", default="")
    p_cppb.add_argument("--ipc-fig-pdf", default="")
    p_cppb.add_argument("--stlb-fig-png", default="")
    p_cppb.add_argument("--stlb-fig-pdf", default="")
    p_cppb.set_defaults(func=compare_permit_cppb)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
