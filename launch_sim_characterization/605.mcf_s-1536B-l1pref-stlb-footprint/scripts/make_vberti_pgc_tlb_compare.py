#!/usr/bin/env python3
import csv
import os
import re
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
CASE_DIR = SCRIPT_DIR.parent
TRACE_TAG = os.environ.get("TRACE_TAG", "605.mcf_s-1536B")

TEMPLATE = CASE_DIR / "vberti_pgc_tlb_compare_template.csv"
OUT_DIR = CASE_DIR / "csv_figure" / "pgc_compare"
OUT_CSV = OUT_DIR / "vberti_pgc_tlb_compare.csv"

LOGS = {
    "Permit PGC": CASE_DIR / "result" / "l1pref" / f"{TRACE_TAG}-mcf-footprint-l1pref-1core.log",
    "Discard PGC": CASE_DIR / "result" / "discard_pgc" / f"{TRACE_TAG}-mcf-footprint-discard-pgc-1core.log",
    "No L1Pref": CASE_DIR / "result" / "nol1pref" / f"{TRACE_TAG}-mcf-footprint-nol1pref-1core.log",
}

ALIASES = {
    "CPU 0 cumulative IPC": "CPU 0 cumulative IPC",
    "DRAM_read_traffic_MPKI": "dram_rq_read_total_observed.per_1K_instructions",
}


def parse_number(text: str) -> float:
    return float(text.rstrip("%"))


def parse_log(path: Path) -> dict[str, float]:
    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit(f"[ERROR] Missing or empty log: {path}")

    data: dict[str, float] = {}
    ipc_re = re.compile(r"CPU 0 cumulative IPC:\s+([-+0-9.eE]+)")
    kv_space_re = re.compile(r"^([A-Za-z0-9_.]+)\s+([-+0-9.eE]+%?)$")
    kv_equal_re = re.compile(r"^([A-Za-z0-9_.]+)\s*=\s*([-+0-9.eE]+%?)$")

    for line in path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if match := ipc_re.search(stripped):
            data["CPU 0 cumulative IPC"] = parse_number(match.group(1))
            continue

        match = kv_equal_re.match(stripped) or kv_space_re.match(stripped)
        if not match:
            continue

        key, value = match.groups()
        try:
            data[key] = parse_number(value)
        except ValueError:
            continue

    if "CPU 0 cumulative IPC" not in data:
        raise SystemExit(f"[ERROR] Missing CPU IPC in log: {path}")

    return data


def format_value(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.12g}"


def format_delta_pct(new_value: float | None, base_value: float | None) -> str:
    if new_value is None or base_value is None or base_value == 0:
        return ""
    return f"{((new_value - base_value) / base_value * 100.0):.12g}%"


def metric_value(metric: str, data: dict[str, float]) -> float | None:
    key = ALIASES.get(metric, metric)
    return data.get(key)


def main() -> None:
    if not TEMPLATE.exists():
        raise SystemExit(f"[ERROR] Missing template: {TEMPLATE}")

    logs = {name: parse_log(path) for name, path in LOGS.items()}

    with TEMPLATE.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    if not rows:
        raise SystemExit(f"[ERROR] Empty template: {TEMPLATE}")

    header = rows[0]
    required_columns = ["Metric", "Permit PGC", "Discard PGC", "No L1Pref", "Permit vs Discard Δ%", "Permit vs NoL1Pref Δ%"]
    missing_columns = [col for col in required_columns if col not in header]
    if missing_columns:
        raise SystemExit(f"[ERROR] Missing columns in template: {missing_columns}")

    col_index = {name: header.index(name) for name in header}
    missing_metrics: list[str] = []

    for row in rows[1:]:
        if not row:
            continue
        while len(row) < len(header):
            row.append("")

        metric = row[col_index["Metric"]].strip()
        if not metric:
            continue

        values: dict[str, float | None] = {}
        found_any = False
        for config_name in ["Permit PGC", "Discard PGC", "No L1Pref"]:
            value = metric_value(metric, logs[config_name])
            values[config_name] = value
            row[col_index[config_name]] = format_value(value)
            found_any = found_any or value is not None

        row[col_index["Permit vs Discard Δ%"]] = format_delta_pct(values["Permit PGC"], values["Discard PGC"])
        row[col_index["Permit vs NoL1Pref Δ%"]] = format_delta_pct(values["Permit PGC"], values["No L1Pref"])

        if not found_any:
            missing_metrics.append(metric)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    print(f"[INFO] Wrote {OUT_CSV}")
    if missing_metrics:
        print("[WARN] Metrics not found in any log:")
        for metric in missing_metrics:
            print(f"[WARN]   {metric}")


if __name__ == "__main__":
    main()
