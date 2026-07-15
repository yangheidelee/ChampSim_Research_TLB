#!/usr/bin/env python3
"""Build a trace-level evidence chain from existing nopref/permit/discard logs.

This script is intentionally post-processing only.  It never launches ChampSim and
does not require translation-only logs.  All generated files live below
csv_figure/vberti_tlb_evidence_chain in this copied experiment directory.
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
OUT_DIR = CASE_DIR / "csv_figure" / "vberti_tlb_evidence_chain"

CONFIG_SUFFIX = {
    "nopref": "-pgc-nopref-1core---hide-heartbeat.log",
    "permit": "-pgc-permit-1core---hide-heartbeat.log",
    "discard": "-pgc-discard-1core---hide-heartbeat.log",
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
    for raw in path.read_text(errors="replace").splitlines():
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


def value(d: dict[str, float], key: str, default: float = 0.0) -> float:
    return d.get(key, default)


def collect() -> tuple[pd.DataFrame, pd.DataFrame]:
    config_paths: dict[str, dict[str, Path]] = {}
    for cfg, suffix in CONFIG_SUFFIX.items():
        paths: dict[str, Path] = {}
        for path in sorted((RESULT_DIR / ("permit_pgc" if cfg == "permit" else ("discard_pgc" if cfg == "discard" else "nopref"))).glob("*.log")):
            if path.name.endswith(suffix):
                paths[path.name[: -len(suffix)]] = path
        config_paths[cfg] = paths

    all_tags = sorted(set().union(*(set(x) for x in config_paths.values())))
    common_tags = sorted(set.intersection(*(set(x) for x in config_paths.values())))
    missing_rows = []
    for tag in all_tags:
        for cfg in CONFIG_SUFFIX:
            if tag not in config_paths[cfg]:
                missing_rows.append({"trace_tag": tag, "missing_config": cfg})

    rows: list[dict[str, object]] = []
    for tag in common_tags:
        logs = {cfg: parse_log(config_paths[cfg][tag]) for cfg in CONFIG_SUFFIX}
        p, d, n = logs["permit"], logs["discard"], logs["nopref"]
        dataset, workload = trace_info(tag)
        instr = value(p, "Core_0_instructions", np.nan)
        if not np.isfinite(instr) or instr <= 0:
            instr = 100_000_000.0

        cross_req = value(p, "Core_0_vBerti_Cross_page_prefetch_in_Requested")
        # Newer logs print the absolute InPQ cross-page count.  Older logs only
        # print the official cross-page drop ratio.  Reconstruct the count from
        # that ratio instead of silently treating a missing field as zero.
        official_drop = value(p, "Core_0_vBerti_Cross_page_PQ_Drop_rate", np.nan)
        if "Core_0_vBerti_InPQ_Cross_page_prefetch" in p:
            cross_pq = p["Core_0_vBerti_InPQ_Cross_page_prefetch"]
        elif np.isfinite(official_drop):
            cross_pq = cross_req * (1.0 - official_drop)
        else:
            in_pq_share = value(p, "Core_0_vBerti_InPQ_Cross_page_prefetch_of_Requested", np.nan)
            cross_pq = value(p, "Core_0_vBerti_Requested") * in_pq_share if np.isfinite(in_pq_share) else np.nan
        dtlb_lookup = value(p, "Core_0_DTLB_cross_page_prefetch_lookups")
        dtlb_miss = value(p, "Core_0_DTLB_vberti_cross_page_prefetch_miss")
        stlb_lookup = value(p, "Core_0_STLB_cross_page_prefetch_lookups")
        stlb_miss = value(p, "Core_0_STLB_vberti_cross_page_prefetch_miss")
        stlb_fill = value(p, "Core_0_STLB_vberti_cross_page_prefetch_fill")
        useful = value(p, "Core_0_STLB_cross_page_prefetch_useful")
        useless = value(p, "Core_0_STLB_cross_page_prefetch_useless")
        late = value(p, "Core_0_STLB_cross_page_prefetch_late")
        too_early = value(p, "Core_0_STLB_cross_page_prefetch_too_early")
        pollution = value(p, "Core_0_STLB_cross_page_prefetch_pollution_evict")
        permit_miss = value(p, "Core_0_STLB_demand_miss")
        discard_miss = value(d, "Core_0_STLB_demand_miss")
        nopref_miss = value(n, "Core_0_STLB_demand_miss")
        permit_mpki = value(p, "Core_0_STLB_demand_mpki", np.nan)
        discard_mpki = value(d, "Core_0_STLB_demand_mpki", np.nan)
        nopref_mpki = value(n, "Core_0_STLB_demand_mpki", np.nan)
        permit_ipc = value(p, "CPU 0 cumulative IPC", value(p, "Core_0_IPC", np.nan))
        discard_ipc = value(d, "CPU 0 cumulative IPC", value(d, "Core_0_IPC", np.nan))
        nopref_ipc = value(n, "CPU 0 cumulative IPC", value(n, "Core_0_IPC", np.nan))
        miss_reduction = discard_miss - permit_miss
        e2e_issued = value(p, "Core_0_vBerti_end_to_end_issued", np.nan)
        e2e_useful = value(p, "Core_0_vBerti_end_to_end_useful", np.nan)

        rows.append({
            "trace_tag": tag,
            "dataset": dataset,
            "workload": workload,
            "instructions": instr,
            "nopref_ipc": nopref_ipc,
            "discard_ipc": discard_ipc,
            "permit_ipc": permit_ipc,
            "permit_vs_discard_ipc_pct": 100.0 * (safe_div(permit_ipc, discard_ipc) - 1.0),
            "vberti_end_to_end_issued": e2e_issued,
            "vberti_end_to_end_useful": e2e_useful,
            "vberti_end_to_end_accuracy_pct": pct(e2e_useful, e2e_issued),
            "nopref_stlb_demand_miss": nopref_miss,
            "discard_stlb_demand_miss": discard_miss,
            "permit_stlb_demand_miss": permit_miss,
            "nopref_stlb_demand_mpki": nopref_mpki,
            "discard_stlb_demand_mpki": discard_mpki,
            "permit_stlb_demand_mpki": permit_mpki,
            "demand_miss_reduction_count": miss_reduction,
            "demand_miss_reduction_pct": pct(miss_reduction, discard_miss),
            "cross_requested": cross_req,
            "cross_in_pq": cross_pq,
            "pq_drop_rate_pct": 100.0 * value(p, "Core_0_vBerti_PQ_Drop_Rate", np.nan),
            "cross_pq_drop_rate_pct": 100.0 * (official_drop if np.isfinite(official_drop) else safe_div(cross_req-cross_pq, cross_req)),
            "dtlb_cross_lookups": dtlb_lookup,
            "dtlb_cross_misses": dtlb_miss,
            "stlb_cross_lookups": stlb_lookup,
            "stlb_cross_misses": stlb_miss,
            "stlb_cross_fills": stlb_fill,
            "stlb_cross_useful": useful,
            "stlb_cross_useless": useless,
            "stlb_cross_late": late,
            "stlb_cross_too_early": too_early,
            "stlb_cross_pollution_evict": pollution,
            "cross_requested_mpki": cross_req * 1000.0 / instr,
            "stlb_cross_lookup_mpki": stlb_lookup * 1000.0 / instr,
            "stlb_cross_translation_mpki": stlb_miss * 1000.0 / instr,
            "stlb_cross_useful_mpki": useful * 1000.0 / instr,
            "pq_survival_pct": pct(cross_pq, cross_req),
            "reach_dtlb_pct_of_requested": pct(dtlb_lookup, cross_req),
            "reach_stlb_pct_of_requested": pct(stlb_lookup, cross_req),
            "trigger_translation_pct_of_requested": pct(stlb_miss, cross_req),
            "useful_pct_of_requested": pct(useful, cross_req),
            "dtlb_miss_pct_of_lookup": pct(dtlb_miss, dtlb_lookup),
            "stlb_miss_pct_of_lookup": pct(stlb_miss, stlb_lookup),
            "fill_productivity_pct": pct(useful, stlb_fill),
            "stlb_accuracy_pct": 100.0 * value(p, "Core_0_STLB_cross_page_prefetch_accuracy", safe_div(useful, stlb_lookup)),
            "stlb_coverage_pct_logged": 100.0 * value(p, "Core_0_STLB_cross_page_prefetch_coverage", safe_div(useful, useful + permit_miss)),
            "stlb_too_early_among_useless_pct": pct(too_early, useless),
            "stlb_late_among_useful_pct": pct(late, useful),
            "stlb_pollution_candidate_among_cross_fill_pct": pct(pollution, stlb_fill),
            "useful_vs_discard_miss_pct": pct(useful, discard_miss),
            "net_reduction_per_useful_pct": pct(miss_reduction, useful),
            "too_early_among_useless_pct": pct(too_early, useless),
            "pollution_per_fill_pct": pct(pollution, stlb_fill),
            "late_per_fill_pct": pct(late, stlb_fill),
        })
    return pd.DataFrame(rows), pd.DataFrame(missing_rows, columns=["trace_tag", "missing_config"])


def weighted_summary(group: pd.DataFrame) -> pd.Series:
    sums = group.select_dtypes(include=[np.number]).sum(min_count=1)
    req = sums["cross_requested"]
    fills = sums["stlb_cross_fills"]
    useful = sums["stlb_cross_useful"]
    discard_miss = sums["discard_stlb_demand_miss"]
    reduction = sums["demand_miss_reduction_count"]
    return pd.Series({
        "num_traces": len(group),
        "discard_stlb_demand_mpki_mean": group["discard_stlb_demand_mpki"].mean(),
        "permit_stlb_demand_mpki_mean": group["permit_stlb_demand_mpki"].mean(),
        "permit_vs_discard_ipc_pct_geomean": 100.0 * (np.exp(np.log1p(group["permit_vs_discard_ipc_pct"] / 100.0).mean()) - 1.0),
        "cross_requested_mpki_mean": group["cross_requested_mpki"].mean(),
        "pq_drop_rate_pct_weighted": pct(req - sums["cross_in_pq"], req),
        "reach_stlb_pct_of_requested_weighted": pct(sums["stlb_cross_lookups"], req),
        "trigger_translation_pct_of_requested_weighted": pct(sums["stlb_cross_misses"], req),
        "useful_pct_of_requested_weighted": pct(useful, req),
        "fill_productivity_pct_weighted": pct(useful, fills),
        "useful_vs_discard_miss_pct_weighted": pct(useful, discard_miss),
        "demand_miss_reduction_pct_weighted": pct(reduction, discard_miss),
        "too_early_among_useless_pct_weighted": pct(sums["stlb_cross_too_early"], sums["stlb_cross_useless"]),
        "pollution_per_fill_pct_weighted": pct(sums["stlb_cross_pollution_evict"], fills),
    })


def savefig(fig: plt.Figure, stem: str) -> None:
    fig.savefig(OUT_DIR / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(OUT_DIR / f"{stem}.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


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
        "discard_stlb_demand_mpki", "cross_requested_mpki", "cross_pq_drop_rate_pct",
        "reach_stlb_pct_of_requested", "trigger_translation_pct_of_requested",
        "useful_pct_of_requested", "fill_productivity_pct", "useful_vs_discard_miss_pct",
        "too_early_among_useless_pct", "pollution_per_fill_pct",
    ]
    outcomes = ["demand_miss_reduction_pct", "permit_vs_discard_ipc_pct"]
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


def make_figures(df: pd.DataFrame, workload: pd.DataFrame, corr: pd.DataFrame,
                 focus: pd.DataFrame, focus_label: str, focus_stem: str) -> None:
    sns.set_theme(style="whitegrid", context="notebook")

    # 01: demand-side opportunity and observed net result.
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    scatter_by_dataset(axes[0], df, "discard_stlb_demand_mpki", "demand_miss_reduction_pct",
                       "Discard-PGC demand STLB MPKI", "Permit vs discard demand STLB miss reduction (%)")
    annotate_extremes(axes[0], df, "discard_stlb_demand_mpki", "demand_miss_reduction_pct", 4)
    scatter_by_dataset(axes[1], df, "demand_miss_reduction_pct", "permit_vs_discard_ipc_pct",
                       "Demand STLB miss reduction (%)", "Permit vs discard IPC change (%)")
    annotate_extremes(axes[1], df, "demand_miss_reduction_pct", "permit_vs_discard_ipc_pct", 4)
    axes[0].set_title("Opportunity does not guarantee coverage")
    axes[1].set_title("TLB result vs mixed-system IPC result")
    axes[1].legend(ncol=2, fontsize=8, loc="best")
    fig.suptitle("01. Demand-side opportunity and observed outcome", fontsize=15)
    savefig(fig, "01_demand_opportunity_and_outcome")

    # 02: end-to-end flow; ratios are ratio-of-sums, not mean-of-ratios.
    stages = [
        ("cross_requested", "Requested"), ("cross_in_pq", "Survive PQ"),
        ("dtlb_cross_lookups", "DTLB lookup"), ("stlb_cross_lookups", "Reach STLB"),
        ("stlb_cross_misses", "Trigger walk"), ("stlb_cross_useful", "Useful at STLB"),
    ]
    totals = df[[x for x, _ in stages]].sum()
    retention = [100.0 * totals[x] / totals[stages[0][0]] for x, _ in stages]
    fig, axes = plt.subplots(1, 2, figsize=(16, 6.5))
    axes[0].plot(range(len(stages)), retention, marker="o", lw=2.5, color="#4c78a8")
    axes[0].fill_between(range(len(stages)), retention, alpha=0.15, color="#4c78a8")
    axes[0].set_xticks(range(len(stages)), [label for _, label in stages], rotation=25, ha="right")
    axes[0].set_ylabel("Retained events / cross-page requests (%)")
    axes[0].set_yscale("log")
    axes[0].set_title("All traces: ratio of summed counts")
    for idx, val in enumerate(retention):
        axes[0].annotate(f"{val:.3g}%", (idx, val), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=9)
    dataset_rows = []
    for dataset, group in df.groupby("dataset"):
        req = group["cross_requested"].sum()
        dataset_rows.append({"dataset": dataset, "Reach STLB": pct(group["stlb_cross_lookups"].sum(), req),
                             "Trigger walk": pct(group["stlb_cross_misses"].sum(), req),
                             "Useful": pct(group["stlb_cross_useful"].sum(), req)})
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
                       "Cross-page requests per 1K instructions", "Useful STLB events / discard demand misses (%)")
    scatter_by_dataset(axes[1], df, "trigger_translation_pct_of_requested", "useful_pct_of_requested",
                       "Requests triggering STLB translation (%)", "Useful STLB events / requests (%)")
    scatter_by_dataset(axes[2], df, "useful_vs_discard_miss_pct", "demand_miss_reduction_pct",
                       "Useful STLB events / discard demand misses (%)", "Net demand STLB miss reduction (%)")
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
                       "Cross-page PQ drop rate (%)", "Useful STLB events / requests (%)")
    scatter_by_dataset(axes[1], df, "cross_pq_drop_rate_pct", "demand_miss_reduction_pct",
                       "Cross-page PQ drop rate (%)", "Demand STLB miss reduction (%)")
    scatter_by_dataset(axes[2], df, "pq_survival_pct", "trigger_translation_pct_of_requested",
                       "Cross-page requests surviving PQ (%)", "Requests triggering STLB translation (%)")
    axes[0].set_title("PQ pressure vs prediction yield")
    axes[1].set_title("PQ pressure vs net TLB result")
    axes[2].set_title("Surviving PQ still may not need translation")
    axes[2].legend(ncol=2, fontsize=8)
    fig.suptitle("04. Is PQ dropping the main bottleneck?", fontsize=15)
    savefig(fig, "04_pq_bottleneck_test")

    # 05: downstream explanations after a translation is inserted.
    fig, axes = plt.subplots(1, 3, figsize=(19, 5.8))
    scatter_by_dataset(axes[0], df, "fill_productivity_pct", "demand_miss_reduction_pct",
                       "Useful demand hits / STLB cross-page fills (%)", "Demand STLB miss reduction (%)")
    scatter_by_dataset(axes[1], df, "too_early_among_useless_pct", "demand_miss_reduction_pct",
                       "Too-early / useless STLB prefetches (%)", "Demand STLB miss reduction (%)")
    scatter_by_dataset(axes[2], df, "pollution_per_fill_pct", "demand_miss_reduction_pct",
                       "Pollution candidates / STLB cross-page fills (%)", "Demand STLB miss reduction (%)")
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

    focus = focus.sort_values("demand_miss_reduction_pct_weighted")
    labels = [workload_display_name(str(r.dataset), str(r.workload)) for r in focus.itertuples()]
    y = np.arange(len(focus))
    fig, axes = plt.subplots(1, 3, figsize=(19, max(7, 0.42 * len(focus))))
    axes[0].barh(y, focus["discard_stlb_demand_mpki_mean"], color="#4c78a8")
    axes[0].set_xlabel("Discard demand STLB MPKI")
    axes[0].set_yticks(y, labels)
    axes[0].set_title("Demand-side opportunity")
    axes[1].barh(y, focus["useful_vs_discard_miss_pct_weighted"], color="#e45756")
    axes[1].set_xlabel("Useful events / discard demand misses (%)")
    axes[1].set_yticks(y, [])
    axes[1].set_title("Cross-page coverage supply")
    axes[2].barh(y, focus["demand_miss_reduction_pct_weighted"], color="#54a24b")
    axes[2].axvline(0, color="0.3", lw=0.8)
    axes[2].set_xlabel("Permit vs discard demand miss reduction (%)")
    axes[2].set_yticks(y, [])
    axes[2].set_title("Observed net TLB result")
    fig.suptitle(f"07. {focus_label}: demand need vs useful cross-page coverage", fontsize=15)
    savefig(fig, focus_stem)

    # 08: the hypothesis in one quadrant plot: high demand need but low supply.
    fig, axes = plt.subplots(1, 2, figsize=(18, 7), gridspec_kw={"width_ratios": [1.45, 1.0]})
    ax = axes[0]
    scatter_by_dataset(ax, df, "discard_stlb_demand_mpki", "useful_vs_discard_miss_pct",
                       "Discard-PGC demand STLB MPKI", "Useful STLB events / discard demand misses (%)")
    x_cut = df["discard_stlb_demand_mpki"].median()
    y_cut = df["useful_vs_discard_miss_pct"].median()
    ax.axvline(x_cut, color="0.45", lw=0.9, ls=":")
    ax.axhline(y_cut, color="0.45", lw=0.9, ls=":")
    ax.text(0.99, 0.02, "High demand need / low useful coverage", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=10, color="#b22222")
    score = df["discard_stlb_demand_mpki"].rank(pct=True) * (1.0 - df["useful_vs_discard_miss_pct"].rank(pct=True))
    top = score.nlargest(12)
    for idx in top.index:
        row = df.loc[idx]
        ax.scatter(row["discard_stlb_demand_mpki"], row["useful_vs_discard_miss_pct"],
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
    request_to_translation = pct(sums["stlb_cross_misses"], sums["cross_requested"])
    request_to_useful = pct(sums["stlb_cross_useful"], sums["cross_requested"])
    survived_to_translation = pct(sums["stlb_cross_misses"], sums["cross_in_pq"])
    survived_to_useful = pct(sums["stlb_cross_useful"], sums["cross_in_pq"])
    useful_vs_miss = pct(sums["stlb_cross_useful"], sums["discard_stlb_demand_miss"])
    net_reduction = pct(sums["demand_miss_reduction_count"], sums["discard_stlb_demand_miss"])
    pq_drop = pct(sums["cross_requested"] - sums["cross_in_pq"], sums["cross_requested"])
    focus_line = ", ".join(
        f"{workload_display_name(str(r.dataset), str(r.workload))}: useful/miss={r.useful_vs_discard_miss_pct_weighted:.3g}%, net={r.demand_miss_reduction_pct_weighted:.3g}%"
        for r in focus.sort_values("useful_vs_discard_miss_pct_weighted").itertuples()
    )
    best = corr[corr["outcome"] == "demand_miss_reduction_pct"].dropna().sort_values("spearman_rho", key=abs, ascending=False).head(4)
    corr_lines = "\n".join(f"- `{r.predictor}`: rho={r.spearman_rho:.3f}, p={r.p_value:.3g}, n={int(r.n)}" for r in best.itertuples())
    text = f"""# vBerti 跨页 TLB 预取证据链（{scope_label}）

本目录的分析范围为 **{scope_label}**，并使用副本中已经完成的 `nopref`、`discard_pgc` 和 `permit_pgc` 日志进行后处理，不重新运行模拟器，也不读取或依赖 translation-only 日志。共纳入 **{len(df)}** 条三配置齐全的 trace。

## 要回答的问题

目标不是简单证明 `permit_pgc` 的 IPC 不高，而是检查下面这个更具体的假设：

> vBerti 可以产生大量跨页 cache-prefetch 候选，但这些候选很少真正需要新的 STLB translation，更少成为后来真实 data demand 使用的 translation，因此它先天能够覆盖的 demand STLB miss 很有限。

## 推荐阅读顺序

如果希望一次顺序浏览全部图，直接打开 `00_all_evidence_chain_figures.pdf`；它按下面的 01–16 顺序合并。

1. `01_demand_opportunity_and_outcome.pdf`：先确认 discard 下的 demand STLB MPKI，以及 permit 是否真的减少 demand miss。右图 IPC 仅作混合系统结果，不作纯 TLB 因果结论。
2. `02_cross_page_flow_funnel.pdf`：从跨页 request 一直追到 STLB useful。全体 trace 按计数求和后，PQ drop 为 **{pq_drop:.4g}%**；只有 **{request_to_translation:.4g}%** 的跨页请求触发 STLB translation，最终只有 **{request_to_useful:.4g}%** 成为 STLB useful。即使只看已经通过 PQ 的候选，也只有 **{survived_to_translation:.4g}%** 触发 translation、**{survived_to_useful:.4g}%** 最终 useful。
3. `03_prediction_quality_and_coverage.pdf`：验证“发得多”是否等于“覆盖多”。STLB useful 仅相当于 discard demand miss 的 **{useful_vs_miss:.4g}%**，而 permit 相对 discard 的净 demand miss reduction 为 **{net_reduction:.4g}%**。
4. `04_pq_bottleneck_test.pdf`：检查 PQ drop 与覆盖/净结果的关系。总体 PQ 损失显著，但通过 PQ 后到 translation/useful 的条件保留率仍很低，因此需要把“PQ 压力”和“候选本身的 TLB 价值不足”作为两段损失分别判断。
5. `05_timeliness_and_pollution.pdf`：只在确认预测覆盖供给后，再检查 too-early 和 pollution 等后端损失。
6. `06_spearman_correlation_map.pdf`：跨 trace 的描述性相关性，不能单独作为因果证明。
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

## 关键口径

- `discard_pgc` 用作 TLB 行为比较基线：保留同页 vBerti 行为，丢弃跨页 PGC；`permit_pgc` 放行跨页 PGC。
- `cross_requested` 是 vBerti 产生的跨页 cache-prefetch 请求，不等于 TLB prefetch，也不等于可覆盖的 STLB miss。
- `trigger_translation_pct_of_requested = STLB cross-page prefetch miss / cross_requested`，衡量候选中真正需要新 translation 的比例。
- `stlb_cross_useful` 在 STLB 预取项被后续 demand 命中时计数。
- 源码打印的 `STLB_cross_page_prefetch_accuracy = useful / issued`；`coverage = useful / (useful + permit demand miss)`。
- 本分析另外给出 `useful_vs_discard_miss_pct = useful / discard demand miss`，用于表达相对于基线 miss 需求的有效覆盖供给。
- `demand_miss_reduction_pct = (discard demand miss - permit demand miss) / discard demand miss`，它是净结果，允许为负。
- `pollution_per_fill_pct` 的分子是被 STLB 跨页预取填充驱逐的有效项（pollution candidate），不是已经证明造成性能损失的精确次数。
- 所有带 `weighted` 的 workload/dataset 比例均采用“先求和计数、再做比值”，避免小 trace 与大 trace 被等权。

## 当前数据给出的总体读数

- 跨页候选到 STLB translation 的保留率：**{request_to_translation:.6g}%**。
- 跨页候选到 STLB useful 的保留率：**{request_to_useful:.6g}%**。
- 已通过 PQ 的候选到 STLB translation/useful：**{survived_to_translation:.6g}% / {survived_to_useful:.6g}%**。因此 PQ 是显著损失，但不能单独解释剩余候选的低有效覆盖。
- useful 相对于 discard demand miss：**{useful_vs_miss:.6g}%**。
- permit 相对 discard 的净 demand STLB miss reduction：**{net_reduction:.6g}%**。
- 净 miss reduction 大于日志直接记录的 STLB useful 覆盖供给，因此不能把 permit/discard 的全部 miss 差异都解释成 translation prefetch 的直接覆盖；跨页 data-cache prefetch 对访问流和时序的耦合变化也在这个差值里。
- {focus_label} workload摘要：{focus_line}

与 demand miss reduction 绝对相关性较高的几个 trace-level 指标为：

{corr_lines}

这些数字应结合图中的离群点和 `00_trace_metrics.csv` 检查，不能只用总体求和替代逐 trace 判断。

## 结论边界

这套结果可以支持或反驳“vBerti 跨页候选对真实 demand STLB miss 的有效覆盖供给不足”，也能判断 PQ/timeliness/pollution 是否与结果一致。它不能把 `permit_pgc` 与 `discard_pgc` 的 IPC 差异完全归因于 translation，因为 permit 同时放行了跨页 data-cache prefetch。translation-only 完整后，可把纯 translation IPC/MPKI 作为额外因果对照加入，但不影响当前对 TLB 内部事件链的统计。

## 可复算数据

- `00_trace_metrics.csv`：每条 trace 的原始计数和派生比例。
- `00_workload_summary.csv`：按 workload 汇总。
- `00_dataset_summary.csv`：按数据集汇总。
- `00_spearman_correlations.csv`：相关系数、p 值和样本数。
- `{focus_csv}`：{focus_label} 各 workload group 的表格版结果。
- `00_high_need_low_coverage_rank.csv`：高 demand 需求、低 useful 覆盖的 trace 排名。
- `09_pq_drop_rate_workload_benchmark_all.csv`、`10_pq_drop_rate_benchmark_all.csv`：两张 PQ drop 分组柱状图的可复算数据。
- `11_stlb_cross_page_accuracy.csv` 至 `15_stlb_cross_page_pollution.csv`：五张 STLB 质量单页图的可复算数据，包含每个指标的有效 trace 数 `n`。
- `16_vberti_end_to_end_accuracy.csv`：vBerti 端到端 data-prefetch accuracy 的可复算数据。
- `00_missing_required_logs.csv`：三配置缺失清单；为空表示所有纳入配置齐全。

## 复现

在本副本目录执行：

```bash
{reproduce_command}
```

脚本只读取 `result/{{nopref,discard_pgc,permit_pgc}}/*.log`，并覆盖本子目录中的同名后处理文件。
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
        "vberti_tlb_evidence_chain_" + "_".join(selected_datasets) if selected_datasets else "vberti_tlb_evidence_chain"
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
        raise SystemExit("No trace has all three required logs")
    df = df.sort_values(["dataset", "workload", "trace_tag"]).reset_index(drop=True)
    workload = df.groupby(["dataset", "workload"], sort=True).apply(weighted_summary, include_groups=False).reset_index()
    dataset = df.groupby("dataset", sort=True).apply(weighted_summary, include_groups=False).reset_index()
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
    diagnosis = df[["trace_tag", "dataset", "workload", "discard_stlb_demand_mpki", "useful_vs_discard_miss_pct",
                    "demand_miss_reduction_pct", "cross_pq_drop_rate_pct", "trigger_translation_pct_of_requested",
                    "too_early_among_useless_pct", "pollution_per_fill_pct"]].copy()
    diagnosis["high_need_low_coverage_score"] = (
        diagnosis["discard_stlb_demand_mpki"].rank(pct=True)
        * (1.0 - diagnosis["useful_vs_discard_miss_pct"].rank(pct=True))
    )
    diagnosis = diagnosis.sort_values("high_need_low_coverage_score", ascending=False)

    df.to_csv(OUT_DIR / "00_trace_metrics.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    workload.to_csv(OUT_DIR / "00_workload_summary.csv", index=False)
    dataset.to_csv(OUT_DIR / "00_dataset_summary.csv", index=False)
    corr.to_csv(OUT_DIR / "00_spearman_correlations.csv", index=False)
    focus.to_csv(OUT_DIR / focus_csv, index=False)
    diagnosis.to_csv(OUT_DIR / "00_high_need_low_coverage_rank.csv", index=False)
    missing.to_csv(OUT_DIR / "00_missing_required_logs.csv", index=False)
    make_figures(df, workload, corr, focus, focus_label, focus_stem)
    make_pq_drop_figures(df)
    make_stlb_quality_figures(df)
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
        ]]
        subprocess.run([pdfunite, *map(str, inputs), str(merged)], check=True)
    reproduce_command = "python3 script/postprocess_evidence_chain.py"
    if selected_datasets:
        reproduce_command += f" --datasets {','.join(selected_datasets)} --output-subdir {output_subdir}"
    write_readme(df, workload, corr, focus, focus_label, focus_stem, focus_csv, scope_label, reproduce_command)
    print(f"[PASS] Evidence-chain post-processing complete: {OUT_DIR}")
    print(f"[INFO] Traces with nopref+discard+permit: {len(df)}")
    print(f"[INFO] Datasets: {', '.join(sorted(df['dataset'].unique()))}")


if __name__ == "__main__":
    main()
