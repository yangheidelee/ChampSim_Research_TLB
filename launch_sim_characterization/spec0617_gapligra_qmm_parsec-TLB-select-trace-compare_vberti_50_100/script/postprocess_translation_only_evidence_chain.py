#!/usr/bin/env python3
"""Build a trace-level evidence chain from translation-only and discard logs.

This script is intentionally post-processing only.  It never launches ChampSim and
does not read permit or nopref logs.  It isolates the implemented cross-page
translation-prefetch mechanism from cross-page data-cache prefetch effects.
"""

from __future__ import annotations

import csv
import argparse
import math
import re
import shutil
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.lines import Line2D
from scipy.stats import spearmanr


SCRIPT_DIR = Path(__file__).resolve().parent
CASE_DIR = SCRIPT_DIR.parent
RESULT_DIR = CASE_DIR / "result"
OUT_DIR = CASE_DIR / "csv_figure" / "vberti_tlb_translation_only_evidence_chain"

CONFIG_SUFFIX = {
    "translation_only": "-pgc-translation-only-1core---hide-heartbeat.log",
    "discard": "-pgc-discard-1core---hide-heartbeat.log",
}

CONFIG_DIR = {
    "translation_only": RESULT_DIR / "translation_only",
    "discard": RESULT_DIR / "discard_pgc",
}

COLORS = {
    "spec06": "#4c78a8",
    "spec17": "#f58518",
    "gap": "#e45756",
    "ligra": "#72b7b2",
    "qmm": "#54a24b",
    "parsec": "#b279a2",
    "xsbench": "#ff9da6",
    "unknown": "#9d9d9d",
}

KEYS = [
    "CPU 0 cumulative IPC",
    "Core_0_instructions",
    "Core_0_IPC",
    "Core_0_DTLB_demand_mpki",
    "Core_0_STLB_demand_access",
    "Core_0_STLB_demand_hit",
    "Core_0_STLB_demand_miss",
    "Core_0_STLB_demand_mpki",
    "Core_0_STLB_cause_Demand_Data_miss",
    "Core_0_STLB_cause_Demand_Instruction_miss",
    "Core_0_vBerti_Requested",
    "Core_0_vBerti_Cross_page_prefetch_in_Requested",
    "Core_0_vBerti_InPQ_Cross_page_prefetch",
    "Core_0_vBerti_InPQ_Cross_page_prefetch_of_Requested",
    "Core_0_vBerti_PQ_Drop_Rate",
    "Core_0_vBerti_Cross_page_PQ_Drop_rate",
    "Core_0_vBerti_end_to_end_issued",
    "Core_0_vBerti_end_to_end_useful",
    "Core_0_vBerti_end_to_end_accuracy",
    "Core_0_DTLB_cross_page_prefetch_lookups",
    "Core_0_DTLB_vberti_cross_page_prefetch_miss",
    "Core_0_DTLB_vberti_cross_page_prefetch_fill",
    "Core_0_DTLB_cross_page_prefetch_useful",
    "Core_0_DTLB_cross_page_prefetch_late",
    "Core_0_DTLB_cross_page_prefetch_pollution_evict",
    "Core_0_STLB_cross_page_prefetch_lookups",
    "Core_0_STLB_vberti_cross_page_prefetch_miss",
    "Core_0_STLB_vberti_cross_page_prefetch_fill",
    "Core_0_STLB_cross_page_prefetch_useful",
    "Core_0_STLB_cross_page_prefetch_useless",
    "Core_0_STLB_cross_page_prefetch_late",
    "Core_0_STLB_cross_page_prefetch_too_early",
    "Core_0_STLB_cross_page_prefetch_pollution_evict",
    "Core_0_STLB_cross_page_prefetch_pollution_demand",
    "Core_0_STLB_cross_page_prefetch_accuracy",
    "Core_0_STLB_cross_page_prefetch_coverage",
    "Core_0_TLB_cross_page_prefetch_useful",
    "Core_0_TLB_cross_page_prefetch_useless",
    "Core_0_TLB_cross_page_prefetch_late",
    "Core_0_TLB_cross_page_prefetch_too_early",
    "Core_0_TLB_cross_page_prefetch_accuracy",
    "Core_0_TLB_cross_page_prefetch_coverage",
    "Core_0_L1D_cross_page_pf_translation_only_requested",
    "Core_0_L1D_cross_page_pf_translation_only_issued",
    "Core_0_L1D_cross_page_pf_translation_only_dropped",
]


def safe_div(a: float, b: float) -> float:
    return a / b if np.isfinite(a) and np.isfinite(b) and b != 0 else np.nan


def pct(a: float, b: float) -> float:
    return 100.0 * safe_div(a, b)


def parse_log(path: Path) -> dict[str, float]:
    wanted = set(KEYS)
    result: dict[str, float] = {}
    ipc_re = re.compile(r"CPU 0 cumulative IPC:\s*([-+0-9.eE]+)")
    kv_re = re.compile(r"^([A-Za-z0-9_.]+)\s*(?:=\s*)?([-+0-9.eE]+)%?$")
    text = path.read_text(errors="replace")
    result["__complete__"] = float("ChampSim completed all CPUs" in text)
    for raw in text.splitlines():
        line = raw.strip()
        match = ipc_re.search(line)
        if match:
            result["CPU 0 cumulative IPC"] = float(match.group(1))
            continue
        match = kv_re.match(line)
        if match and match.group(1) in wanted:
            result[match.group(1)] = float(match.group(2))
    return result


def trace_info(tag: str) -> tuple[str, str]:
    match = re.match(r"^(4\d\d\.[A-Za-z0-9_]+)-\d+B$", tag)
    if match:
        return "spec06", match.group(1)
    match = re.match(r"^(6\d\d\.[A-Za-z0-9_]+)-\d+B$", tag)
    if match:
        return "spec17", match.group(1)
    match = re.match(r"^(bc|bfs|cc|pr|sssp|tc)\.[A-Za-z0-9_]+-\d+B$", tag)
    if match:
        return "gap", match.group(1)
    match = re.match(r"^(ligra_[^.]+)\.", tag)
    if match:
        return "ligra", match.group(1)
    match = re.match(r"^(srv|compute_int|compute_fp)_\d+_new$", tag)
    if match:
        return "qmm", {"srv": "qmm_srv", "compute_int": "qmm_int", "compute_fp": "qmm_fp"}[match.group(1)]
    match = re.match(r"^parsec_[^.]+\.[^.]+\.([^.]+)\.", tag)
    if match:
        return "parsec", f"parsec_{match.group(1)}"
    match = re.match(r"^xs\.([A-Za-z0-9_]+)-\d+B$", tag)
    if match:
        return "xsbench", f"xsbench_{match.group(1)}"
    return "unknown", tag


def value(d: dict[str, float], key: str, default: float = np.nan) -> float:
    return d.get(key, default)


REQUIRED_TRANSLATION_KEYS = {
    "Core_0_instructions",
    "Core_0_STLB_cause_Demand_Data_miss",
    "Core_0_vBerti_Cross_page_prefetch_in_Requested",
    "Core_0_vBerti_PQ_Drop_Rate",
    "Core_0_DTLB_cross_page_prefetch_lookups",
    "Core_0_DTLB_vberti_cross_page_prefetch_miss",
    "Core_0_DTLB_vberti_cross_page_prefetch_fill",
    "Core_0_DTLB_cross_page_prefetch_useful",
    "Core_0_DTLB_cross_page_prefetch_late",
    "Core_0_DTLB_cross_page_prefetch_pollution_evict",
    "Core_0_STLB_cross_page_prefetch_lookups",
    "Core_0_STLB_vberti_cross_page_prefetch_miss",
    "Core_0_STLB_vberti_cross_page_prefetch_fill",
    "Core_0_STLB_cross_page_prefetch_useful",
    "Core_0_STLB_cross_page_prefetch_useless",
    "Core_0_STLB_cross_page_prefetch_late",
    "Core_0_STLB_cross_page_prefetch_too_early",
    "Core_0_STLB_cross_page_prefetch_pollution_evict",
    "Core_0_TLB_cross_page_prefetch_useful",
    "Core_0_TLB_cross_page_prefetch_useless",
    "Core_0_TLB_cross_page_prefetch_late",
    "Core_0_TLB_cross_page_prefetch_too_early",
}


def log_issues(metrics: dict[str, float], config: str) -> list[str]:
    issues: list[str] = []
    if not metrics.get("__complete__", 0.0):
        issues.append("incomplete_log")
    required = REQUIRED_TRANSLATION_KEYS if config == "translation_only" else {
        "Core_0_STLB_cause_Demand_Data_miss"
    }
    issues.extend(f"missing_metric:{key}" for key in sorted(required - metrics.keys()))
    if config == "translation_only" and not any(key in metrics for key in (
        "Core_0_vBerti_InPQ_Cross_page_prefetch",
        "Core_0_vBerti_Cross_page_PQ_Drop_rate",
        "Core_0_vBerti_InPQ_Cross_page_prefetch_of_Requested",
    )):
        issues.append("missing_metric:cross_page_PQ_survival")
    if "CPU 0 cumulative IPC" not in metrics and "Core_0_IPC" not in metrics:
        issues.append("missing_metric:IPC")
    return issues


def collect() -> tuple[pd.DataFrame, pd.DataFrame]:
    config_paths: dict[str, dict[str, Path]] = {}
    for cfg, suffix in CONFIG_SUFFIX.items():
        paths: dict[str, Path] = {}
        for path in sorted(CONFIG_DIR[cfg].glob("*.log")):
            if path.name.endswith(suffix):
                paths[path.name[: -len(suffix)]] = path
        config_paths[cfg] = paths

    all_tags = sorted(set().union(*(set(x) for x in config_paths.values())))
    common_tags = sorted(set.intersection(*(set(x) for x in config_paths.values())))
    missing_rows = []
    for tag in all_tags:
        for cfg in CONFIG_SUFFIX:
            if tag not in config_paths[cfg]:
                missing_rows.append({"trace_tag": tag, "config": cfg, "issue": "missing_log"})

    rows: list[dict[str, object]] = []
    for tag in common_tags:
        logs = {cfg: parse_log(config_paths[cfg][tag]) for cfg in CONFIG_SUFFIX}
        issues = {cfg: log_issues(logs[cfg], cfg) for cfg in CONFIG_SUFFIX}
        if any(issues.values()):
            for cfg, cfg_issues in issues.items():
                for issue in cfg_issues:
                    missing_rows.append({"trace_tag": tag, "config": cfg, "issue": issue})
            continue
        t, d = logs["translation_only"], logs["discard"]
        dataset, workload = trace_info(tag)
        instr = value(t, "Core_0_instructions", np.nan)
        if not np.isfinite(instr) or instr <= 0:
            missing_rows.append({"trace_tag": tag, "config": "translation_only", "issue": "invalid_metric:Core_0_instructions"})
            continue

        cross_req = value(t, "Core_0_vBerti_Cross_page_prefetch_in_Requested")
        # Newer logs print the absolute InPQ cross-page count.  Older logs only
        # print the official cross-page drop ratio.  Reconstruct the count from
        # that ratio instead of silently treating a missing field as zero.
        official_drop = value(t, "Core_0_vBerti_Cross_page_PQ_Drop_rate", np.nan)
        if "Core_0_vBerti_InPQ_Cross_page_prefetch" in t:
            cross_pq = t["Core_0_vBerti_InPQ_Cross_page_prefetch"]
        elif np.isfinite(official_drop):
            cross_pq = cross_req * (1.0 - official_drop)
        else:
            in_pq_share = value(t, "Core_0_vBerti_InPQ_Cross_page_prefetch_of_Requested", np.nan)
            cross_pq = value(t, "Core_0_vBerti_Requested") * in_pq_share if np.isfinite(in_pq_share) else np.nan
        dtlb_lookup = value(t, "Core_0_DTLB_cross_page_prefetch_lookups")
        dtlb_miss = value(t, "Core_0_DTLB_vberti_cross_page_prefetch_miss")
        dtlb_fill = value(t, "Core_0_DTLB_vberti_cross_page_prefetch_fill")
        dtlb_useful = value(t, "Core_0_DTLB_cross_page_prefetch_useful")
        dtlb_late = value(t, "Core_0_DTLB_cross_page_prefetch_late")
        dtlb_pollution = value(t, "Core_0_DTLB_cross_page_prefetch_pollution_evict")
        stlb_lookup = value(t, "Core_0_STLB_cross_page_prefetch_lookups")
        stlb_miss = value(t, "Core_0_STLB_vberti_cross_page_prefetch_miss")
        stlb_fill = value(t, "Core_0_STLB_vberti_cross_page_prefetch_fill")
        stlb_useful = value(t, "Core_0_STLB_cross_page_prefetch_useful")
        stlb_useless = value(t, "Core_0_STLB_cross_page_prefetch_useless")
        stlb_late = value(t, "Core_0_STLB_cross_page_prefetch_late")
        stlb_too_early = value(t, "Core_0_STLB_cross_page_prefetch_too_early")
        stlb_pollution = value(t, "Core_0_STLB_cross_page_prefetch_pollution_evict")
        useful = value(t, "Core_0_TLB_cross_page_prefetch_useful")
        useless = value(t, "Core_0_TLB_cross_page_prefetch_useless")
        late = value(t, "Core_0_TLB_cross_page_prefetch_late")
        too_early = value(t, "Core_0_TLB_cross_page_prefetch_too_early")
        system_fill = dtlb_fill + stlb_fill
        pollution = dtlb_pollution + stlb_pollution
        translation_only_miss = value(t, "Core_0_STLB_cause_Demand_Data_miss")
        discard_miss = value(d, "Core_0_STLB_cause_Demand_Data_miss")
        translation_only_mpki = translation_only_miss * 1000.0 / instr
        discard_mpki = discard_miss * 1000.0 / instr
        translation_only_ipc = value(t, "CPU 0 cumulative IPC", value(t, "Core_0_IPC", np.nan))
        discard_ipc = value(d, "CPU 0 cumulative IPC", value(d, "Core_0_IPC", np.nan))
        miss_reduction = discard_miss - translation_only_miss
        e2e_issued = value(t, "Core_0_vBerti_end_to_end_issued")
        e2e_useful = value(t, "Core_0_vBerti_end_to_end_useful")

        rows.append({
            "trace_tag": tag,
            "dataset": dataset,
            "workload": workload,
            "instructions": instr,
            "discard_ipc": discard_ipc,
            "translation_only_ipc": translation_only_ipc,
            "translation_only_vs_discard_ipc_pct": 100.0 * (safe_div(translation_only_ipc, discard_ipc) - 1.0),
            "vberti_end_to_end_issued": e2e_issued,
            "vberti_end_to_end_useful": e2e_useful,
            "vberti_end_to_end_accuracy_pct": pct(e2e_useful, e2e_issued),
            "discard_stlb_data_demand_miss": discard_miss,
            "translation_only_stlb_data_demand_miss": translation_only_miss,
            "discard_stlb_data_demand_mpki": discard_mpki,
            "translation_only_stlb_data_demand_mpki": translation_only_mpki,
            "demand_miss_reduction_count": miss_reduction,
            "demand_miss_reduction_pct": pct(miss_reduction, discard_miss),
            "cross_requested": cross_req,
            "cross_in_pq": cross_pq,
            "pq_drop_rate_pct": 100.0 * value(t, "Core_0_vBerti_PQ_Drop_Rate"),
            "cross_pq_drop_rate_pct": 100.0 * (official_drop if np.isfinite(official_drop) else safe_div(cross_req-cross_pq, cross_req)),
            "dtlb_cross_lookups": dtlb_lookup,
            "dtlb_cross_misses": dtlb_miss,
            "dtlb_cross_fills": dtlb_fill,
            "dtlb_cross_useful": dtlb_useful,
            "dtlb_cross_late": dtlb_late,
            "dtlb_cross_pollution_evict": dtlb_pollution,
            "stlb_cross_lookups": stlb_lookup,
            "stlb_cross_misses": stlb_miss,
            "stlb_cross_fills": stlb_fill,
            "stlb_cross_useful": stlb_useful,
            "stlb_cross_useless": stlb_useless,
            "stlb_cross_late": stlb_late,
            "stlb_cross_too_early": stlb_too_early,
            "stlb_cross_pollution_evict": stlb_pollution,
            "tlb_cross_fills": system_fill,
            "tlb_cross_useful": useful,
            "tlb_cross_useless": useless,
            "tlb_cross_late": late,
            "tlb_cross_too_early": too_early,
            "tlb_cross_pollution_evict_sum": pollution,
            "cross_requested_mpki": cross_req * 1000.0 / instr,
            "stlb_cross_lookup_mpki": stlb_lookup * 1000.0 / instr,
            "stlb_cross_page_walk_mpki": stlb_miss * 1000.0 / instr,
            "stlb_cross_useful_mpki": stlb_useful * 1000.0 / instr,
            "tlb_cross_useful_mpki": useful * 1000.0 / instr,
            "pq_survival_pct": pct(cross_pq, cross_req),
            "reach_dtlb_pct_of_requested": pct(dtlb_lookup, cross_req),
            "reach_stlb_pct_of_requested": pct(stlb_lookup, cross_req),
            "trigger_page_walk_pct_of_requested": pct(stlb_miss, cross_req),
            "useful_pct_of_requested": pct(useful, cross_req),
            "dtlb_miss_pct_of_lookup": pct(dtlb_miss, dtlb_lookup),
            "stlb_miss_pct_of_lookup": pct(stlb_miss, stlb_lookup),
            "combined_fill_productivity_pct": pct(useful, system_fill),
            "translation_only_requested": value(t, "Core_0_L1D_cross_page_pf_translation_only_requested"),
            "translation_only_issued": value(t, "Core_0_L1D_cross_page_pf_translation_only_issued"),
            "translation_only_dropped_after_translation": value(t, "Core_0_L1D_cross_page_pf_translation_only_dropped"),
            "stlb_accuracy_pct": 100.0 * value(t, "Core_0_STLB_cross_page_prefetch_accuracy", safe_div(stlb_useful, stlb_lookup)),
            "stlb_coverage_pct_logged": 100.0 * value(t, "Core_0_STLB_cross_page_prefetch_coverage", safe_div(stlb_useful, stlb_useful + translation_only_miss)),
            "stlb_too_early_among_useless_pct": pct(stlb_too_early, stlb_useless),
            "stlb_late_among_useful_pct": pct(stlb_late, stlb_useful),
            "dtlb_late_among_useful_pct": pct(dtlb_late, dtlb_useful),
            "stlb_pollution_candidate_among_cross_fill_pct": pct(stlb_pollution, stlb_fill),
            "tlb_accuracy_pct": 100.0 * value(t, "Core_0_TLB_cross_page_prefetch_accuracy", safe_div(useful, dtlb_lookup)),
            "tlb_coverage_pct_logged": 100.0 * value(t, "Core_0_TLB_cross_page_prefetch_coverage", safe_div(useful, useful + translation_only_miss)),
            "useful_vs_discard_miss_pct": pct(useful, discard_miss),
            "net_reduction_per_useful_pct": pct(miss_reduction, useful),
            "too_early_among_useless_pct": pct(too_early, useless),
            "combined_local_pollution_candidates_per_fill_pct": pct(pollution, system_fill),
            "late_per_fill_pct": pct(late, system_fill),
        })
    return pd.DataFrame(rows), pd.DataFrame(missing_rows, columns=["trace_tag", "config", "issue"])


SUMMARY_METRICS = [
    "cross_pq_drop_rate_pct",
    "reach_stlb_pct_of_requested",
    "trigger_page_walk_pct_of_requested",
    "useful_pct_of_requested",
    "combined_fill_productivity_pct",
    "useful_vs_discard_miss_pct",
    "demand_miss_reduction_pct",
    "too_early_among_useless_pct",
    "combined_local_pollution_candidates_per_fill_pct",
]


def evidence_summary(group: pd.DataFrame) -> pd.Series:
    sums = group.select_dtypes(include=[np.number]).sum(min_count=1)
    req = sums["cross_requested"]
    fills = sums["tlb_cross_fills"]
    useful = sums["tlb_cross_useful"]
    discard_miss = sums["discard_stlb_data_demand_miss"]
    reduction = sums["demand_miss_reduction_count"]
    result = {
        "num_traces": len(group),
        "discard_stlb_data_demand_mpki_amean": group["discard_stlb_data_demand_mpki"].mean(),
        "translation_only_stlb_data_demand_mpki_amean": group["translation_only_stlb_data_demand_mpki"].mean(),
        "translation_only_vs_discard_ipc_pct_geomean": 100.0 * (
            np.exp(np.log1p(group["translation_only_vs_discard_ipc_pct"] / 100.0).mean()) - 1.0
        ),
        "cross_requested_mpki_amean": group["cross_requested_mpki"].mean(),
        "pq_drop_rate_pct_weighted": pct(req - sums["cross_in_pq"], req),
        "reach_stlb_pct_of_requested_weighted": pct(sums["stlb_cross_lookups"], req),
        "trigger_page_walk_pct_of_requested_weighted": pct(sums["stlb_cross_misses"], req),
        "useful_pct_of_requested_weighted": pct(useful, req),
        "combined_fill_productivity_pct_weighted": pct(useful, fills),
        "useful_vs_discard_miss_pct_weighted": pct(useful, discard_miss),
        "demand_miss_reduction_pct_weighted": pct(reduction, discard_miss),
        "too_early_among_useless_pct_weighted": pct(sums["tlb_cross_too_early"], sums["tlb_cross_useless"]),
        "combined_local_pollution_candidates_per_fill_pct_weighted": pct(sums["tlb_cross_pollution_evict_sum"], fills),
    }
    # DPC4-style diagnostic aggregation: form every ratio per trace first and
    # then give every trace equal weight.  Median and IQR expose long tails.
    for metric in SUMMARY_METRICS:
        values = group[metric].replace([np.inf, -np.inf], np.nan).dropna()
        result[f"{metric}_n"] = len(values)
        result[f"{metric}_amean"] = values.mean()
        result[f"{metric}_median"] = values.median()
        result[f"{metric}_p25"] = values.quantile(0.25)
        result[f"{metric}_p75"] = values.quantile(0.75)
    return pd.Series(result)


def savefig(fig: plt.Figure, stem: str) -> None:
    fig.savefig(OUT_DIR / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(OUT_DIR / f"{stem}.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


PQ_DATASET_ORDER = ["spec06", "spec17", "gap", "ligra", "qmm", "parsec", "xsbench", "unknown"]


def pq_dataset_order(df: pd.DataFrame) -> list[str]:
    present = set(df["dataset"].astype(str))
    return [dataset for dataset in PQ_DATASET_ORDER if dataset in present] + sorted(present - set(PQ_DATASET_ORDER))


def pq_workload_label(dataset: str, workload: str) -> str:
    for prefix in ("qmm_", "parsec_", "xsbench_"):
        if workload.startswith(prefix):
            return workload.removeprefix(prefix)
    return workload


def pq_drop_aggregate_rows(df: pd.DataFrame, include_workloads: bool) -> pd.DataFrame:
    metrics = ["pq_drop_rate_pct", "cross_pq_drop_rate_pct"]
    rows: list[dict[str, object]] = []
    if include_workloads:
        for dataset in pq_dataset_order(df):
            dataset_group = df[df["dataset"] == dataset]
            for workload, group in dataset_group.groupby("workload", sort=True):
                rows.append({
                    "level": "workload", "dataset": dataset, "workload": workload,
                    "label": pq_workload_label(dataset, str(workload)),
                    "aggregation": "trace_equal_amean", "num_traces": len(group),
                    **{metric: group[metric].mean() for metric in metrics},
                })
    for dataset in pq_dataset_order(df):
        group = df[df["dataset"] == dataset]
        rows.append({
            "level": "benchmark", "dataset": dataset, "workload": "",
            "label": f"amean_{dataset}",
            "aggregation": "trace_equal_amean", "num_traces": len(group),
            **{metric: group[metric].mean() for metric in metrics},
        })
    rows.append({
        "level": "all", "dataset": "all", "workload": "", "label": "amean_all",
        "aggregation": "trace_equal_amean",
        "num_traces": len(df), **{metric: df[metric].mean() for metric in metrics},
    })
    return pd.DataFrame(rows)


def plot_pq_drop_bars(table: pd.DataFrame, stem: str, title: str) -> None:
    count = len(table)
    fig, ax = plt.subplots(figsize=(max(13, 0.46 * count), 7.2))
    x = np.arange(count)
    width = 0.38
    bars_all = ax.bar(x - width / 2, table["pq_drop_rate_pct"], width,
                      label="All vBerti PQ drop rate", color="#4c78a8")
    bars_cross = ax.bar(x + width / 2, table["cross_pq_drop_rate_pct"], width,
                        label="Cross-page PQ drop rate", color="#e45756")
    for bars, color in ((bars_all, "#4c78a8"), (bars_cross, "#e45756")):
        for bar in bars:
            if np.isfinite(bar.get_height()) and bar.get_height() == 0:
                ax.text(bar.get_x() + bar.get_width() / 2, 0.8, "0", ha="center", va="bottom",
                        fontsize=8, color=color, fontweight="bold")
    ax.set_xticks(x, table["label"], rotation=70, ha="right", fontsize=8)
    ax.set_ylabel("PQ drop rate (%)")
    ax.set_ylim(0, 100)
    ax.set_title(title)
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.25)
    levels = table["level"].tolist()
    for idx in range(1, count):
        if levels[idx] != levels[idx - 1]:
            ax.axvline(idx - 0.5, color="0.35", lw=1.0, ls="--")
    fig.tight_layout()
    savefig(fig, stem)


def make_pq_drop_figures(df: pd.DataFrame) -> None:
    detailed = pq_drop_aggregate_rows(df, include_workloads=True)
    benchmark = pq_drop_aggregate_rows(df, include_workloads=False)
    detailed.to_csv(OUT_DIR / "09_pq_drop_rate_workload_benchmark_all.csv", index=False)
    benchmark.to_csv(OUT_DIR / "10_pq_drop_rate_benchmark_all.csv", index=False)
    plot_pq_drop_bars(
        detailed, "09_pq_drop_rate_workload_benchmark_all",
        "PQ drop rates: workload, benchmark, and amean_all (trace-equal)",
    )
    plot_pq_drop_bars(
        benchmark, "10_pq_drop_rate_benchmark_all",
        "PQ drop rates: benchmark and amean_all (trace-equal)",
    )


def stlb_metric_aggregate_rows(df: pd.DataFrame, columns: list[str], include_workloads: bool) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def append_row(level: str, dataset: str, workload: str, label: str, group: pd.DataFrame) -> None:
        row: dict[str, object] = {
            "level": level, "dataset": dataset, "workload": workload, "label": label,
            "aggregation": "trace_equal_amean", "num_traces": len(group),
        }
        for column in columns:
            values = group[column].replace([np.inf, -np.inf], np.nan).dropna()
            row[column] = values.mean()
            row[f"{column}_n"] = len(values)
        rows.append(row)

    if include_workloads:
        for dataset in pq_dataset_order(df):
            dataset_group = df[df["dataset"] == dataset]
            for workload, group in dataset_group.groupby("workload", sort=True):
                append_row("workload", dataset, str(workload), pq_workload_label(dataset, str(workload)), group)
    for dataset in pq_dataset_order(df):
        append_row("benchmark", dataset, "", f"amean_{dataset}", df[df["dataset"] == dataset])
    append_row("all", "all", "", "amean_all", df)
    return pd.DataFrame(rows)


def plot_stlb_metric_axis(ax, table: pd.DataFrame, column: str, ylabel: str, title: str,
                          color: str, is_rate: bool) -> None:
    x = np.arange(len(table))
    bars = ax.bar(x, table[column], color=color, width=0.72)
    ax.set_xticks(x, table["label"], rotation=68, ha="right", fontsize=8)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.25)
    max_value = np.nanmax(table[column].to_numpy(dtype=float))
    if is_rate:
        ax.set_ylim(0, 100)
    elif max_value == 0:
        ax.set_ylim(0, 1)
    elif max_value >= 1e6:
        ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
    for bar in bars:
        if np.isfinite(bar.get_height()) and bar.get_height() == 0:
            ax.text(bar.get_x() + bar.get_width() / 2, 0, "0", ha="center", va="bottom",
                    fontsize=7, color=color, fontweight="bold")
    levels = table["level"].tolist()
    for idx in range(1, len(table)):
        if levels[idx] != levels[idx - 1]:
            ax.axvline(idx - 0.5, color="0.35", lw=0.9, ls="--")


def make_one_stlb_quality_figure(df: pd.DataFrame, stem: str, page_title: str,
                                 rate_column: str, rate_ylabel: str,
                                 count_column: str | None = None, count_ylabel: str = "") -> None:
    columns = [rate_column] + ([count_column] if count_column else [])
    detailed = stlb_metric_aggregate_rows(df, columns, include_workloads=True)
    summary = stlb_metric_aggregate_rows(df, columns, include_workloads=False)
    detailed.to_csv(OUT_DIR / f"{stem}.csv", index=False)

    if count_column is None:
        fig, axes = plt.subplots(1, 2, figsize=(28, 7.5), gridspec_kw={"width_ratios": [3.2, 1.2]})
        plot_stlb_metric_axis(axes[0], detailed, rate_column, rate_ylabel,
                              "All workloads + suite amean + amean_all", "#4c78a8", True)
        plot_stlb_metric_axis(axes[1], summary, rate_column, rate_ylabel,
                              "Suite amean + amean_all", "#4c78a8", True)
    else:
        fig, axes = plt.subplots(2, 2, figsize=(28, 14), gridspec_kw={"width_ratios": [3.2, 1.2]})
        plot_stlb_metric_axis(axes[0, 0], detailed, rate_column, rate_ylabel,
                              "Rate: all workloads + suite amean + amean_all", "#4c78a8", True)
        plot_stlb_metric_axis(axes[0, 1], summary, rate_column, rate_ylabel,
                              "Rate: suite amean + amean_all", "#4c78a8", True)
        plot_stlb_metric_axis(axes[1, 0], detailed, count_column, count_ylabel,
                              "Count: all workloads + suite amean + amean_all", "#e45756", False)
        plot_stlb_metric_axis(axes[1, 1], summary, count_column, count_ylabel,
                              "Count: suite amean + amean_all", "#e45756", False)
    fig.suptitle(page_title, fontsize=17)
    if count_column is None:
        fig.tight_layout(rect=[0, 0, 1, 0.97])
    else:
        fig.subplots_adjust(left=0.045, right=0.99, bottom=0.075, top=0.92, wspace=0.14, hspace=0.52)
    savefig(fig, stem)


def make_stlb_quality_figures(df: pd.DataFrame) -> None:
    make_one_stlb_quality_figure(
        df, "11_stlb_cross_page_accuracy", "11. vBerti cross-page prefetch accuracy at STLB",
        "stlb_accuracy_pct", "STLB accuracy (%)",
    )
    make_one_stlb_quality_figure(
        df, "12_stlb_cross_page_coverage", "12. vBerti cross-page prefetch coverage at STLB",
        "stlb_coverage_pct_logged", "STLB coverage (%)",
    )
    make_one_stlb_quality_figure(
        df, "13_stlb_cross_page_too_early", "13. vBerti cross-page prefetch too-early at STLB",
        "stlb_too_early_among_useless_pct", "Too early / useless (%)",
        "stlb_cross_too_early", "Too-early count per trace (amean)",
    )
    make_one_stlb_quality_figure(
        df, "14_stlb_cross_page_too_late", "14. vBerti cross-page prefetch too-late at STLB",
        "stlb_late_among_useful_pct", "Late / useful (%)",
        "stlb_cross_late", "Late count per trace (amean)",
    )
    make_one_stlb_quality_figure(
        df, "15_stlb_cross_page_pollution", "15. vBerti cross-page prefetch pollution candidates at STLB",
        "stlb_pollution_candidate_among_cross_fill_pct", "Pollution candidates / STLB cross-page fills (%)",
        "stlb_cross_pollution_evict", "Pollution-candidate count per trace (amean)",
    )
    make_one_stlb_quality_figure(
        df, "16_vberti_end_to_end_accuracy", "16. vBerti end-to-end data-prefetch accuracy",
        "vberti_end_to_end_accuracy_pct", "End-to-end useful / issued (%)",
    )


def make_dtlb_quality_figures(df: pd.DataFrame) -> None:
    make_one_stlb_quality_figure(
        df, "17_dtlb_cross_page_too_late", "17. vBerti cross-page prefetch too-late at DTLB",
        "dtlb_late_among_useful_pct", "Late / useful (%)",
        "dtlb_cross_late", "Late count per trace (amean)",
    )


def scatter_by_dataset(ax, df: pd.DataFrame, x: str, y: str, xlabel: str, ylabel: str) -> None:
    for dataset, group in df.groupby("dataset", sort=False):
        ax.scatter(group[x], group[y], s=25, alpha=0.72, color=COLORS.get(dataset, COLORS["unknown"]), label=dataset, edgecolors="none")
    ax.axhline(0, color="0.35", lw=0.8, ls="--")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.2)


def annotate_extremes(ax, df: pd.DataFrame, x: str, y: str, n: int = 5) -> None:
    clean = df[[x, y, "trace_tag"]].replace([np.inf, -np.inf], np.nan).dropna()
    chosen = pd.concat([clean.nlargest(n, y), clean.nsmallest(n, y)]).drop_duplicates("trace_tag")
    for _, row in chosen.iterrows():
        ax.annotate(str(row["trace_tag"]), (row[x], row[y]), xytext=(3, 3), textcoords="offset points", fontsize=6, alpha=0.8)


def correlation_table(df: pd.DataFrame) -> pd.DataFrame:
    predictors = [
        "discard_stlb_data_demand_mpki", "cross_requested_mpki", "cross_pq_drop_rate_pct",
        "reach_stlb_pct_of_requested", "trigger_page_walk_pct_of_requested",
        "useful_pct_of_requested", "combined_fill_productivity_pct", "useful_vs_discard_miss_pct",
        "too_early_among_useless_pct", "combined_local_pollution_candidates_per_fill_pct",
    ]
    outcomes = ["demand_miss_reduction_pct", "translation_only_vs_discard_ipc_pct"]
    rows = []
    for y in outcomes:
        for x in predictors:
            pair = df[[x, y]].replace([np.inf, -np.inf], np.nan).dropna()
            rho, pval = spearmanr(pair[x], pair[y]) if len(pair) >= 3 else (np.nan, np.nan)
            rows.append({"outcome": y, "predictor": x, "spearman_rho": rho, "p_value": pval, "n": len(pair)})
    return pd.DataFrame(rows)


def workload_display_name(dataset: str, workload: str) -> str:
    if dataset == "xsbench" and workload.startswith("xsbench_"):
        workload = workload.removeprefix("xsbench_")
    return f"{dataset}:{workload}"


def make_figures(df: pd.DataFrame, workload: pd.DataFrame, corr: pd.DataFrame,
                 focus: pd.DataFrame, focus_label: str, focus_stem: str) -> None:
    sns.set_theme(style="whitegrid", context="notebook")

    # 01: demand-side opportunity and observed net result.
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    scatter_by_dataset(axes[0], df, "discard_stlb_data_demand_mpki", "demand_miss_reduction_pct",
                       "Discard-PGC data-demand STLB MPKI", "Translation-only vs discard data-demand STLB miss reduction (%)")
    annotate_extremes(axes[0], df, "discard_stlb_data_demand_mpki", "demand_miss_reduction_pct", 4)
    scatter_by_dataset(axes[1], df, "demand_miss_reduction_pct", "translation_only_vs_discard_ipc_pct",
                       "Demand STLB miss reduction (%)", "Translation-only vs discard IPC change (%)")
    annotate_extremes(axes[1], df, "demand_miss_reduction_pct", "translation_only_vs_discard_ipc_pct", 4)
    axes[0].set_title("Opportunity does not guarantee coverage")
    axes[1].set_title("Pure translation mechanism: TLB result vs IPC")
    axes[1].legend(ncol=2, fontsize=8, loc="best")
    fig.suptitle("01. Demand-side opportunity and observed outcome", fontsize=15)
    savefig(fig, "01_demand_opportunity_and_outcome")

    # 02: keep the original evidence-chain funnel layout, but use the DPC4-style
    # equal-trace arithmetic mean instead of a ratio of summed counts.
    stages = [
        ("cross_requested", "Requested"), ("cross_in_pq", "Survive PQ"),
        ("dtlb_cross_lookups", "DTLB lookup"), ("stlb_cross_lookups", "Reach STLB"),
        ("stlb_cross_misses", "Trigger walk"), ("stlb_cross_useful", "Useful at STLB"),
    ]
    retention_by_trace = pd.DataFrame({
        label: 100.0 * df[column] / df["cross_requested"].replace(0, np.nan)
        for column, label in stages
    })
    retention_amean = retention_by_trace.mean()
    fig, axes = plt.subplots(1, 2, figsize=(16, 6.5))
    xstage = np.arange(len(stages))
    axes[0].plot(xstage, retention_amean, marker="o", lw=2.5, color="#4c78a8")
    axes[0].fill_between(xstage, retention_amean, alpha=0.15, color="#4c78a8")
    axes[0].set_xticks(range(len(stages)), [label for _, label in stages], rotation=25, ha="right")
    axes[0].set_ylabel("Retained events / cross-page requests (%)")
    axes[0].set_yscale("log")
    axes[0].set_title("All traces: equal-weight amean (DPC4-style)")
    for idx, val in enumerate(retention_amean):
        axes[0].annotate(f"{val:.3g}%", (idx, val), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=9)
    dataset_rows = []
    for dataset, group in df.groupby("dataset"):
        dataset_rows.append({"dataset": dataset,
                             "Reach STLB": group["reach_stlb_pct_of_requested"].mean(),
                             "Trigger walk": group["trigger_page_walk_pct_of_requested"].mean(),
                             "Useful": (100.0 * group["stlb_cross_useful"] / group["cross_requested"].replace(0, np.nan)).mean()})
    ds = pd.DataFrame(dataset_rows).set_index("dataset")
    ds.plot.bar(ax=axes[1], logy=True, color=["#72b7b2", "#f2cf5b", "#e45756"])
    axes[1].set_ylabel("Events / cross-page requests (%) [log scale]")
    axes[1].set_title("Where requests survive, by dataset")
    axes[1].tick_params(axis="x", rotation=25)
    fig.suptitle("02. Cross-page translation evidence funnel", fontsize=15)
    savefig(fig, "02_cross_page_flow_funnel")

    # 03: raw volume vs useful coverage and net demand result.
    fig, axes = plt.subplots(1, 3, figsize=(19, 5.8))
    scatter_by_dataset(axes[0], df, "cross_requested_mpki", "useful_vs_discard_miss_pct",
                       "Cross-page requests per 1K instructions", "Useful TLB-system events / discard data-demand misses (%)")
    scatter_by_dataset(axes[1], df, "trigger_page_walk_pct_of_requested", "useful_pct_of_requested",
                       "Requests missing STLB and triggering PTW (%)", "Useful TLB-system events / requests (%)")
    scatter_by_dataset(axes[2], df, "useful_vs_discard_miss_pct", "demand_miss_reduction_pct",
                       "Useful TLB-system events / discard data-demand misses (%)", "Net data-demand STLB miss reduction (%)")
    annotate_extremes(axes[2], df, "useful_vs_discard_miss_pct", "demand_miss_reduction_pct", 4)
    axes[0].set_title("Quantity is not coverage")
    axes[1].set_title("Translation reach vs useful prediction")
    axes[2].set_title("Useful events vs net reduction")
    axes[2].legend(ncol=2, fontsize=8)
    fig.suptitle("03. Does vBerti generate the right cross-page translations?", fontsize=15)
    savefig(fig, "03_prediction_quality_and_coverage")

    # 04: test whether PQ drop is the dominant explanation.
    fig, axes = plt.subplots(1, 3, figsize=(19, 5.8))
    scatter_by_dataset(axes[0], df, "cross_pq_drop_rate_pct", "useful_pct_of_requested",
                       "Cross-page PQ drop rate (%)", "Useful TLB-system events / requests (%)")
    scatter_by_dataset(axes[1], df, "cross_pq_drop_rate_pct", "demand_miss_reduction_pct",
                       "Cross-page PQ drop rate (%)", "Data-demand STLB miss reduction (%)")
    scatter_by_dataset(axes[2], df, "pq_survival_pct", "trigger_page_walk_pct_of_requested",
                       "Cross-page requests surviving PQ (%)", "Requests missing STLB and triggering PTW (%)")
    axes[0].set_title("PQ pressure vs prediction yield")
    axes[1].set_title("PQ pressure vs net TLB result")
    axes[2].set_title("Surviving PQ still may not need translation")
    axes[2].legend(ncol=2, fontsize=8)
    fig.suptitle("04. Is PQ dropping the main bottleneck?", fontsize=15)
    savefig(fig, "04_pq_bottleneck_test")

    # 05: downstream explanations after a translation is inserted.
    fig, axes = plt.subplots(1, 3, figsize=(19, 5.8))
    scatter_by_dataset(axes[0], df, "combined_fill_productivity_pct", "demand_miss_reduction_pct",
                       "Useful TLB-system events / DTLB+STLB cross-page fills (%)", "Demand STLB miss reduction (%)")
    scatter_by_dataset(axes[1], df, "too_early_among_useless_pct", "demand_miss_reduction_pct",
                       "Too-early / useless STLB prefetches (%)", "Demand STLB miss reduction (%)")
    scatter_by_dataset(axes[2], df, "combined_local_pollution_candidates_per_fill_pct", "demand_miss_reduction_pct",
                       "DTLB+STLB pollution candidates / combined fills (%)", "Demand STLB miss reduction (%)")
    axes[0].set_title("Fill productivity")
    axes[1].set_title("Timeliness symptom")
    axes[2].set_title("Pollution symptom")
    axes[2].legend(ncol=2, fontsize=8)
    fig.suptitle("05. Downstream timeliness and pollution checks", fontsize=15)
    savefig(fig, "05_timeliness_and_pollution")

    # 06: Spearman associations, shown separately for TLB outcome and IPC.
    matrix = corr.pivot(index="predictor", columns="outcome", values="spearman_rho")
    fig, ax = plt.subplots(figsize=(8, 7))
    sns.heatmap(matrix, annot=True, fmt=".2f", center=0, vmin=-1, vmax=1, cmap="vlag", ax=ax, cbar_kws={"label": "Spearman rho"})
    ax.set_title("Trace-level monotonic associations (descriptive, not causal)")
    ax.set_xlabel("Outcome")
    ax.set_ylabel("Candidate explanation")
    savefig(fig, "06_spearman_correlation_map")

    focus = focus.sort_values("demand_miss_reduction_pct_amean")
    labels = [workload_display_name(str(r.dataset), str(r.workload)) for r in focus.itertuples()]
    y = np.arange(len(focus))
    fig, axes = plt.subplots(1, 3, figsize=(19, max(7, 0.42 * len(focus))))
    axes[0].barh(y, focus["discard_stlb_data_demand_mpki_amean"], color="#4c78a8")
    axes[0].set_xlabel("Discard data-demand STLB MPKI (amean)")
    axes[0].set_yticks(y, labels)
    axes[0].set_title("Demand-side opportunity")
    axes[1].barh(y, focus["useful_vs_discard_miss_pct_amean"], color="#e45756")
    axes[1].set_xlabel("Useful / discard data-demand misses (%) [amean]")
    axes[1].set_yticks(y, [])
    axes[1].set_title("Cross-page coverage supply")
    axes[2].barh(y, focus["demand_miss_reduction_pct_amean"], color="#54a24b")
    axes[2].axvline(0, color="0.3", lw=0.8)
    axes[2].set_xlabel("Data-demand miss reduction (%) [amean]")
    axes[2].set_yticks(y, [])
    axes[2].set_title("Observed net TLB result")
    fig.suptitle(f"07. {focus_label}: demand need vs useful cross-page coverage", fontsize=15)
    savefig(fig, focus_stem)

    # 08: the hypothesis in one quadrant plot: high demand need but low supply.
    fig, axes = plt.subplots(1, 2, figsize=(18, 7), gridspec_kw={"width_ratios": [1.45, 1.0]})
    ax = axes[0]
    scatter_by_dataset(ax, df, "discard_stlb_data_demand_mpki", "useful_vs_discard_miss_pct",
                       "Discard-PGC data-demand STLB MPKI", "Useful TLB-system events / discard data-demand misses (%)")
    x_cut = df["discard_stlb_data_demand_mpki"].median()
    y_cut = df["useful_vs_discard_miss_pct"].median()
    ax.axvline(x_cut, color="0.45", lw=0.9, ls=":")
    ax.axhline(y_cut, color="0.45", lw=0.9, ls=":")
    ax.text(0.99, 0.02, "High demand need / low useful coverage", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=10, color="#b22222")
    score = df["discard_stlb_data_demand_mpki"].rank(pct=True) * (1.0 - df["useful_vs_discard_miss_pct"].rank(pct=True))
    top = score.nlargest(12)
    for idx in top.index:
        row = df.loc[idx]
        ax.scatter(row["discard_stlb_data_demand_mpki"], row["useful_vs_discard_miss_pct"],
                   s=85, facecolors="none", edgecolors="black", linewidths=0.9, zorder=4)
    ax.legend(ncol=2, fontsize=8)
    ax.set_title("Trace distribution (outlined points are ranked at right)")
    ranked = df.loc[top.index, ["trace_tag"]].copy()
    ranked["score"] = top.values
    ranked["rank"] = np.arange(1, len(ranked) + 1)
    ranked = ranked.iloc[::-1]
    labels = [f"{r.rank}. {r.trace_tag}" for r in ranked.itertuples()]
    axes[1].barh(np.arange(len(ranked)), ranked["score"], color="#e45756", alpha=0.86)
    axes[1].set_yticks(np.arange(len(ranked)), labels, fontsize=8)
    axes[1].set_xlabel("High-need / low-coverage percentile score")
    axes[1].set_title("Most diagnostic traces")
    axes[1].grid(axis="x", alpha=0.2)
    fig.suptitle("08. Direct test of the high-need / low-coverage hypothesis", fontsize=15)
    savefig(fig, "08_high_need_low_coverage_quadrant")


def write_readme(df: pd.DataFrame, workload: pd.DataFrame, corr: pd.DataFrame,
                 focus: pd.DataFrame, focus_label: str, focus_stem: str,
                 focus_csv: str, scope_label: str, reproduce_command: str) -> None:
    sums = df.select_dtypes(include=[np.number]).sum(min_count=1)
    request_to_page_walk = df["trigger_page_walk_pct_of_requested"].mean()
    request_to_useful = df["useful_pct_of_requested"].mean()
    request_to_stlb_useful = (100.0 * df["stlb_cross_useful"] / df["cross_requested"].replace(0, np.nan)).mean()
    pq_drop = df["cross_pq_drop_rate_pct"].mean()
    useful_vs_miss = df["useful_vs_discard_miss_pct"].mean()
    net_reduction = df["demand_miss_reduction_pct"].mean()
    useful_vs_miss_median = df["useful_vs_discard_miss_pct"].median()
    net_reduction_median = df["demand_miss_reduction_pct"].median()
    survived_to_page_walk = (100.0 * df["stlb_cross_misses"] / df["cross_in_pq"].replace(0, np.nan)).mean()
    survived_to_useful = (100.0 * df["tlb_cross_useful"] / df["cross_in_pq"].replace(0, np.nan)).mean()
    survived_to_stlb_useful = (100.0 * df["stlb_cross_useful"] / df["cross_in_pq"].replace(0, np.nan)).mean()
    weighted_page_walk = pct(sums["stlb_cross_misses"], sums["cross_requested"])
    weighted_useful = pct(sums["tlb_cross_useful"], sums["cross_requested"])
    weighted_useful_vs_miss = pct(sums["tlb_cross_useful"], sums["discard_stlb_data_demand_miss"])
    weighted_net_reduction = pct(sums["demand_miss_reduction_count"], sums["discard_stlb_data_demand_miss"])
    focus_line = ", ".join(
        f"{workload_display_name(str(r.dataset), str(r.workload))}: useful/miss={r.useful_vs_discard_miss_pct_amean:.3g}%, net={r.demand_miss_reduction_pct_amean:.3g}%"
        for r in focus.sort_values("useful_vs_discard_miss_pct_amean").itertuples()
    )
    zero_denominator_lines = "\n".join(
        f"- `{metric}`: 有效 n={int(df[metric].notna().sum())}/{len(df)}"
        for metric in SUMMARY_METRICS if df[metric].isna().any()
    ) or "- 所有主比例的有效 n 均等于纳入 trace 数。"
    best = corr[corr["outcome"] == "demand_miss_reduction_pct"].dropna().sort_values("spearman_rho", key=abs, ascending=False).head(4)
    corr_lines = "\n".join(f"- `{r.predictor}`: rho={r.spearman_rho:.3f}, p={r.p_value:.3g}, n={int(r.n)}" for r in best.itertuples())
    text = f"""# vBerti 跨页 TLB 预取证据链（{scope_label}）

本目录的分析范围为 **{scope_label}**，只使用已经完成的 `translation_only` 和 `discard_pgc` 日志进行后处理，不重新运行模拟器，也不读取 `permit_pgc` 或 `nopref` 日志。共纳入 **{len(df)}** 条两配置齐全的 trace。

## 要回答的问题

目标是利用 `translation_only - discard_pgc` 这组对照，检查下面这个更具体的假设：

> vBerti 可以产生大量跨页 cache-prefetch 候选，但这些候选很少真正需要新的 STLB translation，更少成为后来真实 data demand 使用的 translation，因此它先天能够覆盖的 demand STLB miss 很有限。

## 推荐阅读顺序

如果希望一次顺序浏览全部图，直接打开 `00_all_evidence_chain_figures.pdf`；它按下面的 01–17 顺序合并。

1. `01_demand_opportunity_and_outcome.pdf`：先确认 discard 下的 **data-demand** STLB MPKI，以及 translation-only 是否减少 data-demand miss；右图检查纯跨页 translation 机制的净 IPC 结果。
2. `02_cross_page_flow_funnel.pdf`：版式与原始 permit/discard evidence-chain 图一致。左图完整追踪 Requested → PQ → DTLB → STLB → PTW → Useful at STLB；右图按 dataset 展示 Reach STLB、Trigger walk 和 STLB Useful。每个点和柱都先对单条 trace 计算相对 `cross_requested` 的比例，再做非加权 amean（DPC4-style），不是 ratio-of-sums。PQ drop amean 为 **{pq_drop:.4g}%**；只有 **{request_to_page_walk:.4g}%** 的跨页请求发生 STLB miss 并触发 PTW，最终有 **{request_to_stlb_useful:.4g}%** 成为 STLB useful。已通过 PQ 的候选中，触发 PTW 和最终 STLB useful 的条件比例 amean 为 **{survived_to_page_walk:.4g}% / {survived_to_stlb_useful:.4g}%**。
3. `03_prediction_quality_and_coverage.pdf`：验证“发得多”是否等于“覆盖多”。去重 TLB-system useful 相当于 discard data-demand STLB miss 的 **{useful_vs_miss:.4g}%**，而 translation-only 相对 discard 的净 data-demand miss reduction 为 **{net_reduction:.4g}%**。
4. `04_pq_bottleneck_test.pdf`：检查 PQ drop 与覆盖/净结果的关系。总体 PQ 损失显著，但通过 PQ 后到 translation/useful 的条件保留率仍很低，因此需要把“PQ 压力”和“候选本身的 TLB 价值不足”作为两段损失分别判断。
5. `05_timeliness_and_pollution.pdf`：只在确认预测覆盖供给后，再检查 too-early 和 pollution 等后端损失。
6. `06_spearman_correlation_map.pdf`：跨 trace 的描述性相关性，不能单独作为因果证明；p 值未进行多重比较校正。
7. `{focus_stem}.pdf`：把 {focus_label} 各 workload group 的需求强度、有效覆盖供给、净 miss reduction 并排看。
8. `08_high_need_low_coverage_quadrant.pdf`：最直接地寻找 demand STLB MPKI 高、但 useful/miss 覆盖供给低的 trace；左图圈出、右图列出该象限评分最高的 trace。
9. `09_pq_drop_rate_workload_benchmark_all.pdf`：比较全部 vBerti PQ drop 与跨页 PQ drop，依次给出 workload、benchmark(dataset) 和 `amean_all`。
10. `10_pq_drop_rate_benchmark_all.pdf`：只保留 benchmark(dataset) 和 `amean_all`。PQ drop rate 是比例型诊断指标，所有层级均采用内部 trace 等权 amean，不使用 gmean。
11. `11_stlb_cross_page_accuracy.pdf`：同一页给出全部 workload+suite+All，以及仅 suite+All 的 STLB accuracy。
12. `12_stlb_cross_page_coverage.pdf`：同一页给出两个范围的 STLB coverage。
13. `13_stlb_cross_page_too_early.pdf`：同一页四个面板，分别给出两个范围的 `too_early/useless` 和 too-early 绝对计数 amean。
14. `14_stlb_cross_page_too_late.pdf`：同一页四个面板，分别给出两个范围的 `late/useful` 和 late 绝对计数 amean；useful 已包含 late。
15. `15_stlb_cross_page_pollution.pdf`：同一页四个面板，分别给出两个范围的 `STLB cross-page pollution_evict / STLB cross-page fill` 和 pollution-candidate 绝对计数 amean。
16. `16_vberti_end_to_end_accuracy.pdf`：同一页给出全部 workload+suite+All，以及仅 suite+All 的 vBerti data-prefetch 端到端准确率；由 useful/issued 原始计数重算，零分母保留 NaN。
17. `17_dtlb_cross_page_too_late.pdf`：与 14 的版式和 DPC4 trace 平权方式相同，但使用 DTLB 本级 `late/useful` 和 DTLB late 绝对计数。对同 VPN 的 demand 在跨页翻译返回前到达时，它通常先合并到 DTLB MSHR，因此该口径比 STLB-local late 更能反映真实 demand 观察到的翻译不及时。

## 关键口径

- `discard_pgc` 保留同页 vBerti data prefetch，但丢弃跨页 candidate；`translation_only` 让跨页 candidate 经过 L1D PQ 和 DTLB/STLB/PTW，翻译完成后在 data-cache tag lookup 之前主动删除。
- `cross_requested` 是 vBerti 产生的跨页 cache-prefetch 请求，不等于 TLB prefetch，也不等于可覆盖的 STLB miss。
- `trigger_page_walk_pct_of_requested = STLB cross-page prefetch miss / cross_requested`，表示候选在 STLB miss 并进一步触发 PTW/page walk 的比例。
- `tlb_cross_useful` 使用 `Core_N_TLB_cross_page_prefetch_useful`，在 DTLB+STLB 整体范围内去重；它包含 DTLB useful，不能只用 STLB useful 替代，否则会漏掉后续 demand 直接在 DTLB 命中、因而不再访问 STLB 的覆盖。
- `DTLB late/useful` 使用 `Core_N_DTLB_cross_page_prefetch_late / Core_N_DTLB_cross_page_prefetch_useful`。STLB-local late 在当前层次中可能被上游 DTLB MSHR merge 遮蔽，因此图 17 专门补充 demand 首先观察到的 DTLB timelyness。
- 源码打印的 `TLB_cross_page_prefetch_accuracy = useful / issued`；`coverage = useful / (useful + translation-only system demand miss)`。
- 所有 demand miss 和 demand MPKI 都只使用 `Core_0_STLB_cause_Demand_Data_miss`，明确排除 instruction demand。
- `useful_vs_discard_miss_pct = TLB-system useful / discard data-demand STLB miss`；`demand_miss_reduction_pct` 也只比较 data-demand miss。
- `combined_fill_productivity_pct` 的分母是 DTLB+STLB fill 之和，可能跨层重复计入同一预测，只作为 combined-fill 诊断量，不视为标准 accuracy。
- `combined_local_pollution_candidates_per_fill_pct` 汇总 DTLB 和 STLB 两级本地 pollution candidate，未做系统级去重，也不等于已证明造成性能损失的次数。
- 主汇总采用 trace 等权：每条 trace 先计算比例，再报告 amean，并提供 median/P25/P75 和有效样本数 `n`。IPC speedup 使用 per-trace speedup 的 geomean。
- `_weighted` 列是“计数先求和、再做比值”的 request-weighted 补充结果，不作为主结论。

## 当前数据给出的总体读数

- 跨页候选到 STLB miss/PTW 的等权 amean：**{request_to_page_walk:.6g}%**。
- 跨页候选到去重 TLB-system useful 的保留率：**{request_to_useful:.6g}%**。
- 已通过 PQ 的候选到 STLB miss/PTW 和 TLB-system useful 的等权 amean：**{survived_to_page_walk:.6g}% / {survived_to_useful:.6g}%**。PQ 是显著损失，但不能单独解释剩余候选的低有效覆盖。
- useful/discard data-demand miss：amean **{useful_vs_miss:.6g}%**，median **{useful_vs_miss_median:.6g}%**。
- data-demand STLB miss reduction：amean **{net_reduction:.6g}%**，median **{net_reduction_median:.6g}%**。
- 规模加权补充：PTW/request、useful/request、useful/discard miss、净 miss reduction 分别为 **{weighted_page_walk:.6g}% / {weighted_useful:.6g}% / {weighted_useful_vs_miss:.6g}% / {weighted_net_reduction:.6g}%**。
- 净 miss reduction 不要求与日志直接记录的 STLB useful 数严格相等：TLB replacement/pollution、late、运行时序以及跨页请求占用 L1D PQ 对同页预取的间接影响都会进入配置间净差值。
- {focus_label} workload摘要：{focus_line}

与 demand miss reduction 绝对相关性较高的几个 trace-level 指标为：

{corr_lines}

这些数字应结合图中的离群点和 `00_trace_metrics.csv` 检查，不能只用总体求和替代逐 trace 判断。

## 零分母与有效样本

分母为 0 时比例保留为 NaN，不会静默改成 0；相关性和汇总排除该指标的 NaN，并在 CSV 中记录 `n`：

{zero_denominator_lines}

## 结论边界

这套结果直接衡量当前实现下跨页 translation-only 机制相对 discard 的净 TLB 与 IPC 效果，不包含跨页 data-cache lookup/fill/traffic。仍需注意，translation-only 请求会占用正常 L1D PQ、TLB/PTW 和可能的页表 DRAM 带宽，因此这是可实现机制的净效果，不是无资源代价的理想预测上界。

## 可复算数据

- `00_trace_metrics.csv`：每条 trace 的原始计数和派生比例。
- `00_overall_summary.csv`：当前分析范围的 trace 等权主汇总、分位数以及 request-weighted 补充结果。
- `00_workload_summary.csv`：按 workload 汇总。
- `00_dataset_summary.csv`：按数据集汇总。
- `00_spearman_correlations.csv`：相关系数、p 值和样本数。
- `{focus_csv}`：{focus_label} 各 workload group 的表格版结果。
- `00_high_need_low_coverage_rank.csv`：高 demand 需求、低 useful 覆盖的 trace 排名。
- `09_pq_drop_rate_workload_benchmark_all.csv`、`10_pq_drop_rate_benchmark_all.csv`：两张 PQ drop 分组柱状图的可复算数据。
- `11_stlb_cross_page_accuracy.csv` 至 `15_stlb_cross_page_pollution.csv`：五张 STLB 质量单页图的可复算数据，包含每个指标的有效 trace 数 `n`。
- `16_vberti_end_to_end_accuracy.csv`：vBerti 端到端 data-prefetch accuracy 的可复算数据。
- `17_dtlb_cross_page_too_late.csv`：DTLB 本级 late/useful 和 late 绝对计数的 trace 平权汇总。
- `00_missing_required_logs.csv`：缺失日志、未完成日志和必需指标缺失清单；为空表示所有纳入日志通过完整性检查。

## 复现

在本实验目录执行：

```bash
{reproduce_command}
```

脚本只读取 `result/{{discard_pgc,translation_only}}/*.log`，并覆盖本子目录中的同名后处理文件。
"""
    (OUT_DIR / "README.md").write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post-process the vBerti TLB evidence chain from existing logs only")
    parser.add_argument("--datasets", default="", help="Comma-separated dataset names, e.g. gap,xsbench; empty means all datasets")
    parser.add_argument("--output-subdir", default="", help="Output directory name below csv_figure")
    return parser.parse_args()


def main() -> None:
    global OUT_DIR
    args = parse_args()
    selected_datasets = [x.strip().lower() for x in args.datasets.split(",") if x.strip()]
    output_subdir = args.output_subdir or (
        "vberti_tlb_translation_only_evidence_chain_" + "_".join(selected_datasets)
        if selected_datasets else "vberti_tlb_translation_only_evidence_chain"
    )
    if Path(output_subdir).name != output_subdir:
        raise SystemExit("--output-subdir must be a single directory name below csv_figure")
    OUT_DIR = CASE_DIR / "csv_figure" / output_subdir
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, missing = collect()
    if selected_datasets:
        unknown = sorted(set(selected_datasets) - set(df["dataset"].unique()))
        if unknown:
            raise SystemExit(f"Unknown or unavailable datasets: {', '.join(unknown)}")
        df = df[df["dataset"].isin(selected_datasets)].copy()
        if not missing.empty:
            missing = missing[missing["trace_tag"].map(lambda tag: trace_info(str(tag))[0] in selected_datasets)].copy()
    if df.empty:
        raise SystemExit("No trace has both translation-only and discard logs")
    df = df.sort_values(["dataset", "workload", "trace_tag"]).reset_index(drop=True)
    workload = df.groupby(["dataset", "workload"], sort=True).apply(evidence_summary, include_groups=False).reset_index()
    dataset = df.groupby("dataset", sort=True).apply(evidence_summary, include_groups=False).reset_index()
    corr = correlation_table(df)
    if selected_datasets:
        focus = workload.copy()
        display_names = {"gap": "GAP", "xsbench": "XSBench"}
        focus_label = " + ".join(display_names.get(x, x) for x in selected_datasets)
        focus_stem = "07_" + "_".join(selected_datasets) + "_focus"
        focus_csv = "00_" + "_".join(selected_datasets) + "_focus.csv"
        scope_label = focus_label
    else:
        focus = workload[(workload["dataset"] == "gap") | workload["workload"].str.contains("mcf", case=False, na=False)].copy()
        focus_label = "GAP and mcf"
        focus_stem = "07_gap_mcf_focus"
        focus_csv = "00_gap_mcf_focus.csv"
        scope_label = "全部数据集"
    diagnosis = df[["trace_tag", "dataset", "workload", "discard_stlb_data_demand_mpki", "useful_vs_discard_miss_pct",
                    "demand_miss_reduction_pct", "cross_pq_drop_rate_pct", "trigger_page_walk_pct_of_requested",
                    "too_early_among_useless_pct", "combined_local_pollution_candidates_per_fill_pct"]].copy()
    diagnosis["high_need_low_coverage_score"] = (
        diagnosis["discard_stlb_data_demand_mpki"].rank(pct=True)
        * (1.0 - diagnosis["useful_vs_discard_miss_pct"].rank(pct=True))
    )
    diagnosis = diagnosis.sort_values("high_need_low_coverage_score", ascending=False)

    df.to_csv(OUT_DIR / "00_trace_metrics.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    evidence_summary(df).rename("value").to_csv(OUT_DIR / "00_overall_summary.csv", header=True)
    workload.to_csv(OUT_DIR / "00_workload_summary.csv", index=False)
    dataset.to_csv(OUT_DIR / "00_dataset_summary.csv", index=False)
    corr.to_csv(OUT_DIR / "00_spearman_correlations.csv", index=False)
    focus.to_csv(OUT_DIR / focus_csv, index=False)
    diagnosis.to_csv(OUT_DIR / "00_high_need_low_coverage_rank.csv", index=False)
    missing.to_csv(OUT_DIR / "00_missing_required_logs.csv", index=False)
    make_figures(df, workload, corr, focus, focus_label, focus_stem)
    make_pq_drop_figures(df)
    make_stlb_quality_figures(df)
    make_dtlb_quality_figures(df)
    pdfunite = shutil.which("pdfunite")
    if pdfunite:
        merged = OUT_DIR / "00_all_evidence_chain_figures.pdf"
        merged.unlink(missing_ok=True)
        inputs = [OUT_DIR / f"{index:02d}_{name}.pdf" for index, name in [
            (1, "demand_opportunity_and_outcome"),
            (2, "cross_page_flow_funnel"),
            (3, "prediction_quality_and_coverage"),
            (4, "pq_bottleneck_test"),
            (5, "timeliness_and_pollution"),
            (6, "spearman_correlation_map"),
            (7, focus_stem.removeprefix("07_")),
            (8, "high_need_low_coverage_quadrant"),
            (9, "pq_drop_rate_workload_benchmark_all"),
            (10, "pq_drop_rate_benchmark_all"),
            (11, "stlb_cross_page_accuracy"),
            (12, "stlb_cross_page_coverage"),
            (13, "stlb_cross_page_too_early"),
            (14, "stlb_cross_page_too_late"),
            (15, "stlb_cross_page_pollution"),
            (16, "vberti_end_to_end_accuracy"),
            (17, "dtlb_cross_page_too_late"),
        ]]
        subprocess.run([pdfunite, *map(str, inputs), str(merged)], check=True)
    reproduce_command = "python3 script/postprocess_translation_only_evidence_chain.py"
    if selected_datasets:
        reproduce_command += f" --datasets {','.join(selected_datasets)} --output-subdir {output_subdir}"
    write_readme(df, workload, corr, focus, focus_label, focus_stem, focus_csv, scope_label, reproduce_command)
    print(f"[PASS] Evidence-chain post-processing complete: {OUT_DIR}")
    print(f"[INFO] Traces with translation-only+discard: {len(df)}")
    print(f"[INFO] Datasets: {', '.join(sorted(df['dataset'].unique()))}")


if __name__ == "__main__":
    main()
