#!/usr/bin/env python3
"""Helpers for the gcc ideal-STLB prefetch interaction experiment."""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import re
from typing import Dict, Iterable, List, Optional


CONFIGS = [
    {
        "tag": "pref-berti-pythia",
        "label": "pref Berti+Pythia",
        "binary": "tlb-gcc-pref-berti-pythia-1core",
        "ideal_mode": "none",
        "l1d": "berti",
        "l2c": "pythia",
        "options": "--hide-heartbeat",
    },
    {
        "tag": "pref-berti-no",
        "label": "pref Berti+NoL2",
        "binary": "tlb-gcc-pref-berti-no-1core",
        "ideal_mode": "none",
        "l1d": "berti",
        "l2c": "no",
        "options": "--hide-heartbeat",
    },
    {
        "tag": "pref-berti-ip_stride",
        "label": "pref Berti+IPStride",
        "binary": "tlb-gcc-pref-berti-ip_stride-1core",
        "ideal_mode": "none",
        "l1d": "berti",
        "l2c": "ip_stride",
        "options": "--hide-heartbeat",
    },
    {
        "tag": "pref-no-pythia",
        "label": "pref NoL1D+Pythia",
        "binary": "tlb-gcc-pref-no-pythia-1core",
        "ideal_mode": "none",
        "l1d": "no",
        "l2c": "pythia",
        "options": "--hide-heartbeat",
    },
    {
        "tag": "ideal-l1pref-berti-pythia",
        "label": "ideal_l1pref Berti+Pythia",
        "binary": "tlb-gcc-ideal-l1pref-berti-pythia-1core",
        "ideal_mode": "l1pref",
        "l1d": "berti",
        "l2c": "pythia",
        "options": "--hide-heartbeat --stlb-ideal-mode l1pref",
    },
    {
        "tag": "ideal-l1pref-berti-no",
        "label": "ideal_l1pref Berti+NoL2",
        "binary": "tlb-gcc-ideal-l1pref-berti-no-1core",
        "ideal_mode": "l1pref",
        "l1d": "berti",
        "l2c": "no",
        "options": "--hide-heartbeat --stlb-ideal-mode l1pref",
    },
    {
        "tag": "ideal-l1pref-berti-ip_stride",
        "label": "ideal_l1pref Berti+IPStride",
        "binary": "tlb-gcc-ideal-l1pref-berti-ip_stride-1core",
        "ideal_mode": "l1pref",
        "l1d": "berti",
        "l2c": "ip_stride",
        "options": "--hide-heartbeat --stlb-ideal-mode l1pref",
    },
    {
        "tag": "ideal-l1pref-no-pythia",
        "label": "ideal_l1pref NoL1D+Pythia",
        "binary": "tlb-gcc-ideal-l1pref-no-pythia-1core",
        "ideal_mode": "l1pref",
        "l1d": "no",
        "l2c": "pythia",
        "options": "--hide-heartbeat --stlb-ideal-mode l1pref",
    },
    {
        "tag": "ideal-all-berti-pythia",
        "label": "ideal_all Berti+Pythia",
        "binary": "tlb-gcc-ideal-all-berti-pythia-1core",
        "ideal_mode": "all",
        "l1d": "berti",
        "l2c": "pythia",
        "options": "--hide-heartbeat --stlb-ideal-mode all",
    },
    {
        "tag": "ideal-all-berti-no",
        "label": "ideal_all Berti+NoL2",
        "binary": "tlb-gcc-ideal-all-berti-no-1core",
        "ideal_mode": "all",
        "l1d": "berti",
        "l2c": "no",
        "options": "--hide-heartbeat --stlb-ideal-mode all",
    },
    {
        "tag": "ideal-all-berti-ip_stride",
        "label": "ideal_all Berti+IPStride",
        "binary": "tlb-gcc-ideal-all-berti-ip_stride-1core",
        "ideal_mode": "all",
        "l1d": "berti",
        "l2c": "ip_stride",
        "options": "--hide-heartbeat --stlb-ideal-mode all",
    },
    {
        "tag": "ideal-all-no-pythia",
        "label": "ideal_all NoL1D+Pythia",
        "binary": "tlb-gcc-ideal-all-no-pythia-1core",
        "ideal_mode": "all",
        "l1d": "no",
        "l2c": "pythia",
        "options": "--hide-heartbeat --stlb-ideal-mode all",
    },
]


SUMMARY_FIELDS = [
    "config_tag",
    "label",
    "ideal_mode",
    "l1d_prefetcher",
    "l2c_prefetcher",
    "binary",
    "status",
    "log_file",
    "ipc",
    "ipc_speedup_vs_pref",
    "ipc_speedup_vs_same_pref",
    "cycles",
    "instructions",
    "stlb_total_miss",
    "stlb_total_mpki",
    "stlb_l1d_prefetch_miss",
    "stlb_demand_miss",
    "l1d_load_access",
    "l1d_load_hit",
    "l1d_load_miss",
    "l1d_load_mshr_merge",
    "l1d_unique_to_l2c",
    "l1d_prefetch_issued",
    "l1d_prefetch_useful",
    "l1d_prefetch_useless",
    "l1d_prefetch_late",
    "l1d_prefetch_accuracy",
    "l2c_load_access",
    "l2c_load_hit",
    "l2c_load_miss",
    "l2c_load_mshr_merge",
    "l2c_load_hit_rate",
    "l2c_unique_to_llc",
    "l2c_prefetch_issued",
    "l2c_prefetch_useful",
    "l2c_prefetch_useless",
    "l2c_prefetch_late",
    "l2c_prefetch_accuracy",
    "llc_load_access",
    "llc_load_hit",
    "llc_load_miss",
    "l1d_avg_miss_latency",
    "l2c_avg_miss_latency",
    "llc_avg_miss_latency",
]


DELTA_FIELDS = [
    "config_tag",
    "label",
    "baseline_config_tag",
    "ipc_delta",
    "ipc_pct",
    "cycles_delta",
    "stlb_total_miss_delta",
    "stlb_l1d_prefetch_miss_delta",
    "stlb_demand_miss_delta",
    "l1d_load_miss_delta",
    "l1d_load_mshr_merge_delta",
    "l1d_unique_to_l2c_delta",
    "l2c_load_access_delta",
    "l2c_load_hit_delta",
    "l2c_load_miss_delta",
    "l2c_load_mshr_merge_delta",
    "l2c_unique_to_llc_delta",
    "l2c_prefetch_issued_delta",
    "l2c_prefetch_useful_delta",
    "l2c_prefetch_useless_delta",
    "llc_load_miss_delta",
    "l1d_avg_miss_latency_delta",
    "l2c_avg_miss_latency_delta",
    "llc_avg_miss_latency_delta",
]


METRIC_RE_CACHE: Dict[str, re.Pattern[str]] = {}
ROW_RE = re.compile(
    r"(?m)^cpu0->(?P<cache>cpu0_L1D|cpu0_L2C|LLC)\s+"
    r"(?P<kind>LOAD|PREFETCH|TRANSLATION|TOTAL)\s+"
    r"ACCESS:\s+(?P<access>\d+)\s+HIT:\s+(?P<hit>\d+)\s+"
    r"MISS:\s+(?P<miss>\d+)\s+MSHR_MERGE:\s+(?P<merge>\d+)"
)
PF_RE = re.compile(
    r"(?m)^cpu0->(?P<cache>cpu0_L1D|cpu0_L2C|LLC)\s+PREFETCH REQUESTED:\s+"
    r"(?P<requested>\d+)\s+ISSUED:\s+(?P<issued>\d+)\s+USEFUL:\s+"
    r"(?P<useful>\d+)\s+USELESS:\s+(?P<useless>\d+)\s+LATE:\s+(?P<late>\d+)"
)
LAT_RE = re.compile(
    r"(?m)^cpu0->(?P<cache>cpu0_L1D|cpu0_L2C|LLC)\s+"
    r"AVERAGE MISS LATENCY:\s+(?P<lat>[0-9.]+|-) cycles"
)


def metric_re(name: str) -> re.Pattern[str]:
    if name not in METRIC_RE_CACHE:
        METRIC_RE_CACHE[name] = re.compile(rf"(?m)^{re.escape(name)}\s+([-+0-9.eE]+)\b")
    return METRIC_RE_CACHE[name]


def safe_div(num: float, den: float) -> float:
    return num / den if den else math.nan


def fmt_value(value: object) -> object:
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.12g}"
    return value


def config_by_tag(tag: str) -> Dict[str, str]:
    for cfg in CONFIGS:
        if cfg["tag"] == tag:
            return cfg
    raise KeyError(tag)


def update_nested_prefetchers(config: Dict[str, object], cfg: Dict[str, str]) -> Dict[str, object]:
    config["executable_name"] = cfg["binary"]
    config["num_cores"] = 1
    for cache_name, prefetcher in [("L1D", cfg["l1d"]), ("L2C", cfg["l2c"])]:
        section = config.get(cache_name)
        if not isinstance(section, dict):
            raise SystemExit(f"Reference JSON missing {cache_name} section")
        section["prefetcher"] = prefetcher
    return config


def write_configs(args: argparse.Namespace) -> None:
    reference = pathlib.Path(args.reference)
    configs_dir = pathlib.Path(args.configs_dir)
    configs_dir.mkdir(parents=True, exist_ok=True)
    base = json.loads(reference.read_text())
    for cfg in CONFIGS:
        config = json.loads(json.dumps(base))
        update_nested_prefetchers(config, cfg)
        out_path = configs_dir / f"{cfg['tag']}.json"
        out_path.write_text(json.dumps(config, indent=2) + "\n")
        print(out_path)


def print_shell_specs(_: argparse.Namespace) -> None:
    for cfg in CONFIGS:
        fields = [
            cfg["tag"],
            cfg["label"],
            cfg["binary"],
            cfg["ideal_mode"],
            cfg["l1d"],
            cfg["l2c"],
            cfg["options"],
        ]
        print("|".join(fields))


def extract_scalar(metric_text: str, name: str, default: float = math.nan) -> float:
    match = metric_re(name).search(metric_text)
    return float(match.group(1)) if match else default


def find_log(result_root: pathlib.Path, cfg: Dict[str, str]) -> Optional[pathlib.Path]:
    result_dir = result_root / cfg["tag"]
    if not result_dir.is_dir():
        return None
    logs = sorted(result_dir.glob(f"*{cfg['binary']}*.log"))
    if not logs:
        logs = sorted(result_dir.glob("*.log"))
    return logs[-1] if logs else None


def parse_log(path: pathlib.Path) -> Dict[str, object]:
    text = path.read_text(errors="ignore")
    roi_pos = text.find("[ROI Statistics]")
    if roi_pos < 0:
        raise ValueError("missing ROI statistics")
    metric_text = text[roi_pos:]
    rows: Dict[tuple[str, str], Dict[str, int]] = {}
    pfs: Dict[str, Dict[str, int]] = {}
    lats: Dict[str, float] = {}
    for match in ROW_RE.finditer(text):
        rows[(match.group("cache"), match.group("kind"))] = {
            name: int(match.group(name)) for name in ["access", "hit", "miss", "merge"]
        }
    for match in PF_RE.finditer(text):
        pfs[match.group("cache")] = {name: int(match.group(name)) for name in ["issued", "useful", "useless", "late"]}
    for match in LAT_RE.finditer(text):
        lat_text = match.group("lat")
        lats[match.group("cache")] = math.nan if lat_text == "-" else float(lat_text)

    def row(cache: str, kind: str, field: str) -> float:
        return float(rows.get((cache, kind), {}).get(field, 0))

    def pf(cache: str, field: str) -> float:
        return float(pfs.get(cache, {}).get(field, 0))

    instructions = extract_scalar(metric_text, "Core_0_instructions")
    cycles = extract_scalar(metric_text, "Core_0_cycles")
    ipc = extract_scalar(metric_text, "Core_0_IPC")
    if not math.isfinite(ipc):
        ipc = safe_div(instructions, cycles)

    l1d_load_miss = row("cpu0_L1D", "LOAD", "miss")
    l1d_load_merge = row("cpu0_L1D", "LOAD", "merge")
    l2c_load_access = row("cpu0_L2C", "LOAD", "access")
    l2c_load_hit = row("cpu0_L2C", "LOAD", "hit")
    l2c_load_miss = row("cpu0_L2C", "LOAD", "miss")
    l2c_load_merge = row("cpu0_L2C", "LOAD", "merge")
    l2c_pf_issued = pf("cpu0_L2C", "issued")
    l1d_pf_issued = pf("cpu0_L1D", "issued")

    return {
        "ipc": ipc,
        "cycles": cycles,
        "instructions": instructions,
        "stlb_total_miss": extract_scalar(metric_text, "Core_0_STLB_total_miss", 0.0),
        "stlb_total_mpki": extract_scalar(metric_text, "Core_0_STLB_total_MPKI", 0.0),
        "stlb_l1d_prefetch_miss": extract_scalar(metric_text, "Core_0_STLB_L1D_Prefetch_miss", 0.0),
        "stlb_demand_miss": extract_scalar(metric_text, "Core_0_STLB_Demand_miss", 0.0),
        "l1d_load_access": row("cpu0_L1D", "LOAD", "access"),
        "l1d_load_hit": row("cpu0_L1D", "LOAD", "hit"),
        "l1d_load_miss": l1d_load_miss,
        "l1d_load_mshr_merge": l1d_load_merge,
        "l1d_unique_to_l2c": l1d_load_miss - l1d_load_merge,
        "l1d_prefetch_issued": l1d_pf_issued,
        "l1d_prefetch_useful": pf("cpu0_L1D", "useful"),
        "l1d_prefetch_useless": pf("cpu0_L1D", "useless"),
        "l1d_prefetch_late": pf("cpu0_L1D", "late"),
        "l1d_prefetch_accuracy": safe_div(pf("cpu0_L1D", "useful"), l1d_pf_issued),
        "l2c_load_access": l2c_load_access,
        "l2c_load_hit": l2c_load_hit,
        "l2c_load_miss": l2c_load_miss,
        "l2c_load_mshr_merge": l2c_load_merge,
        "l2c_load_hit_rate": safe_div(l2c_load_hit, l2c_load_access),
        "l2c_unique_to_llc": l2c_load_miss - l2c_load_merge,
        "l2c_prefetch_issued": l2c_pf_issued,
        "l2c_prefetch_useful": pf("cpu0_L2C", "useful"),
        "l2c_prefetch_useless": pf("cpu0_L2C", "useless"),
        "l2c_prefetch_late": pf("cpu0_L2C", "late"),
        "l2c_prefetch_accuracy": safe_div(pf("cpu0_L2C", "useful"), l2c_pf_issued),
        "llc_load_access": row("LLC", "LOAD", "access"),
        "llc_load_hit": row("LLC", "LOAD", "hit"),
        "llc_load_miss": row("LLC", "LOAD", "miss"),
        "l1d_avg_miss_latency": lats.get("cpu0_L1D", math.nan),
        "l2c_avg_miss_latency": lats.get("cpu0_L2C", math.nan),
        "llc_avg_miss_latency": lats.get("LLC", math.nan),
    }


def summarize(args: argparse.Namespace) -> None:
    result_root = pathlib.Path(args.result_root)
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, object]] = []
    baseline_ipc = math.nan
    parsed_by_tag: Dict[str, Dict[str, object]] = {}
    pref_by_combo: Dict[tuple[object, object], Dict[str, object]] = {}

    for cfg in CONFIGS:
        row: Dict[str, object] = {
            "config_tag": cfg["tag"],
            "label": cfg["label"],
            "ideal_mode": cfg["ideal_mode"],
            "l1d_prefetcher": cfg["l1d"],
            "l2c_prefetcher": cfg["l2c"],
            "binary": cfg["binary"],
            "status": "missing",
            "log_file": "",
        }
        log_path = find_log(result_root, cfg)
        if log_path is not None:
            row["log_file"] = str(log_path)
            try:
                parsed = parse_log(log_path)
            except ValueError as exc:
                row["status"] = str(exc)
            else:
                row.update(parsed)
                row["status"] = "ok"
                parsed_by_tag[cfg["tag"]] = row
                if cfg["tag"] == "pref-berti-pythia":
                    baseline_ipc = float(row["ipc"])
                if cfg["ideal_mode"] == "none":
                    pref_by_combo[(cfg["l1d"], cfg["l2c"])] = row
        rows.append(row)

    for row in rows:
        ipc = float(row.get("ipc", math.nan)) if row.get("status") == "ok" else math.nan
        row["ipc_speedup_vs_pref"] = safe_div(ipc, baseline_ipc)
        same_pref = pref_by_combo.get((row.get("l1d_prefetcher"), row.get("l2c_prefetcher")))
        same_pref_ipc = float(same_pref["ipc"]) if same_pref is not None and same_pref.get("status") == "ok" else math.nan
        row["ipc_speedup_vs_same_pref"] = safe_div(ipc, same_pref_ipc)

    summary_path = out_dir / "gcc_ideal_prefetch_matrix_summary.csv"
    with summary_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt_value(row.get(field, "")) for field in SUMMARY_FIELDS})

    baseline = parsed_by_tag.get("pref-berti-pythia")
    delta_path = out_dir / "gcc_ideal_prefetch_matrix_delta_vs_pref.csv"
    with delta_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DELTA_FIELDS)
        writer.writeheader()
        if baseline:
            for row in rows:
                if row.get("status") != "ok" or row["config_tag"] == "pref-berti-pythia":
                    continue
                delta_row: Dict[str, object] = {
                    "config_tag": row["config_tag"],
                    "label": row["label"],
                    "baseline_config_tag": "pref-berti-pythia",
                    "ipc_delta": float(row["ipc"]) - float(baseline["ipc"]),
                    "ipc_pct": (float(row["ipc"]) / float(baseline["ipc"]) - 1.0) * 100.0,
                }
                for field in [
                    "cycles",
                    "stlb_total_miss",
                    "stlb_l1d_prefetch_miss",
                    "stlb_demand_miss",
                    "l1d_load_miss",
                    "l1d_load_mshr_merge",
                    "l1d_unique_to_l2c",
                    "l2c_load_access",
                    "l2c_load_hit",
                    "l2c_load_miss",
                    "l2c_load_mshr_merge",
                    "l2c_unique_to_llc",
                    "l2c_prefetch_issued",
                    "l2c_prefetch_useful",
                    "l2c_prefetch_useless",
                    "llc_load_miss",
                    "l1d_avg_miss_latency",
                    "l2c_avg_miss_latency",
                    "llc_avg_miss_latency",
                ]:
                    delta_row[f"{field}_delta"] = float(row.get(field, math.nan)) - float(baseline.get(field, math.nan))
                writer.writerow({field: fmt_value(delta_row.get(field, "")) for field in DELTA_FIELDS})

    same_delta_path = out_dir / "gcc_ideal_prefetch_matrix_delta_vs_same_pref.csv"
    with same_delta_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DELTA_FIELDS)
        writer.writeheader()
        for row in rows:
            if row.get("status") != "ok" or row.get("ideal_mode") == "none":
                continue
            same_pref = pref_by_combo.get((row.get("l1d_prefetcher"), row.get("l2c_prefetcher")))
            if same_pref is None or same_pref.get("status") != "ok":
                continue
            delta_row = {
                "config_tag": row["config_tag"],
                "label": row["label"],
                "baseline_config_tag": same_pref["config_tag"],
                "ipc_delta": float(row["ipc"]) - float(same_pref["ipc"]),
                "ipc_pct": (float(row["ipc"]) / float(same_pref["ipc"]) - 1.0) * 100.0,
            }
            for field in [
                "cycles",
                "stlb_total_miss",
                "stlb_l1d_prefetch_miss",
                "stlb_demand_miss",
                "l1d_load_miss",
                "l1d_load_mshr_merge",
                "l1d_unique_to_l2c",
                "l2c_load_access",
                "l2c_load_hit",
                "l2c_load_miss",
                "l2c_load_mshr_merge",
                "l2c_unique_to_llc",
                "l2c_prefetch_issued",
                "l2c_prefetch_useful",
                "l2c_prefetch_useless",
                "llc_load_miss",
                "l1d_avg_miss_latency",
                "l2c_avg_miss_latency",
                "llc_avg_miss_latency",
            ]:
                delta_row[f"{field}_delta"] = float(row.get(field, math.nan)) - float(same_pref.get(field, math.nan))
            writer.writerow({field: fmt_value(delta_row.get(field, "")) for field in DELTA_FIELDS})

    print(summary_path)
    print(delta_path)
    print(same_delta_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-configs")

    p_write = sub.add_parser("write-configs")
    p_write.add_argument("--reference", required=True)
    p_write.add_argument("--configs-dir", required=True)

    p_sum = sub.add_parser("summarize")
    p_sum.add_argument("--result-root", required=True)
    p_sum.add_argument("--out-dir", required=True)

    args = parser.parse_args()
    if args.cmd == "list-configs":
        print_shell_specs(args)
    elif args.cmd == "write-configs":
        write_configs(args)
    elif args.cmd == "summarize":
        summarize(args)
    else:
        raise AssertionError(args.cmd)


if __name__ == "__main__":
    main()
