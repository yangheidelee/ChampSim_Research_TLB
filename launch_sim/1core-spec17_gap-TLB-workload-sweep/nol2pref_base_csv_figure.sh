#!/usr/bin/env bash
set -euo pipefail

export MPLBACKEND=Agg

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
EXP_TAG=$(basename "${SCRIPT_DIR}")
CHAMPSIM_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
RESULT_DIR="${CHAMPSIM_ROOT}/results/${EXP_TAG}"
OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${EXP_TAG}"
BUILD_INFO_FILE="${SCRIPT_DIR}/build_info.env"
CSV_PATH="${OUT_DIR}/nol2pref_base_workload.csv"
FIG_PNG="${OUT_DIR}/nol2pref_base_workload.png"
FIG_PDF="${OUT_DIR}/nol2pref_base_workload.pdf"

if [ ! -d "${RESULT_DIR}" ]; then
    echo "[ERROR] Result directory not found: ${RESULT_DIR}"
    exit 1
fi

if [ ! -f "${BUILD_INFO_FILE}" ]; then
    echo "[ERROR] Build info file not found: ${BUILD_INFO_FILE}"
    exit 1
fi

mkdir -p "${OUT_DIR}"

python3 - "${RESULT_DIR}" "${BUILD_INFO_FILE}" "${CSV_PATH}" "${FIG_PNG}" "${FIG_PDF}" <<'PY'
import csv
import math
import pathlib
import re
import sys

result_dir = pathlib.Path(sys.argv[1])
build_info_path = pathlib.Path(sys.argv[2])
csv_path = pathlib.Path(sys.argv[3])
fig_png = pathlib.Path(sys.argv[4])
fig_pdf = pathlib.Path(sys.argv[5])


def load_build_info(path: pathlib.Path) -> dict[str, str]:
    info: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        info[key] = value.strip().strip('"')
    return info


def parse_float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return math.nan


def extract_metric(text: str, key: str, default: float | None = None) -> float:
    pattern = rf"^{re.escape(key)}\s+([-.0-9A-Za-z]+)$"
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        if default is not None:
            return default
        raise ValueError(f"Missing metric {key}")
    return parse_float(match.group(1))


def finite(value: object) -> bool:
    return isinstance(value, float) and math.isfinite(value)


def finite_values(rows: list[dict[str, object]], key: str) -> list[float]:
    return [row[key] for row in rows if finite(row[key])]


def arithmetic_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else math.nan


def geometric_mean(values: list[float]) -> float:
    vals = [value for value in values if math.isfinite(value) and value > 0]
    return math.exp(sum(math.log(value) for value in vals) / len(vals)) if vals else math.nan


def workload_sort_key(workload: str) -> tuple[int, str]:
    match = re.match(r"^(\d+)", workload)
    return (int(match.group(1)), workload) if match else (10**9, workload)


build_info = load_build_info(build_info_path)
binary_name = build_info.get("BINARY_NAME", "")
default_option = build_info.get("DEFAULT_OPTION", "")
option_tag = re.sub(r"[^A-Za-z0-9_.=-]", "", default_option.replace(" ", "_")) if default_option else "no_option"
result_suffix = f"-{binary_name}-{option_tag}.log" if binary_name else None

result_files = sorted(result_dir.glob("*.log"))
if not result_files:
    raise SystemExit(f"No .log result files found in {result_dir}")

rows: list[dict[str, object]] = []
for file_path in result_files:
    name = file_path.name
    if result_suffix and not name.endswith(result_suffix):
        continue

    workload = name[:-len(result_suffix)] if result_suffix else name.rsplit(".log", 1)[0]
    if not workload.startswith("6"):
        continue

    text = file_path.read_text(errors="ignore")
    roi_pos = text.find("[ROI Statistics]")
    metric_text = text[roi_pos:] if roi_pos != -1 else text

    try:
        row = {
            "workload": workload,
            "ipc": extract_metric(metric_text, "Core_0_IPC"),
            "l1d_demand_access": extract_metric(metric_text, "Core_0_L1D_demand_access"),
            "l1d_demand_miss": extract_metric(metric_text, "Core_0_L1D_demand_miss"),
            "l1d_demand_miss_rate": extract_metric(metric_text, "Core_0_L1D_demand_miss_rate"),
            "l2c_demand_access": extract_metric(metric_text, "Core_0_L2C_demand_access"),
            "l2c_demand_miss": extract_metric(metric_text, "Core_0_L2C_demand_miss"),
            "l2c_demand_miss_rate": extract_metric(metric_text, "Core_0_L2C_demand_miss_rate"),
            "llc_demand_access": extract_metric(metric_text, "Core_0_LLC_demand_access", 0.0),
            "llc_demand_miss": extract_metric(metric_text, "Core_0_LLC_demand_miss", 0.0),
            "llc_demand_miss_rate": extract_metric(metric_text, "Core_0_LLC_demand_miss_rate", 0.0),
            "l1d_prefetch_issued": extract_metric(metric_text, "Core_0_L1D_prefetch_issued"),
            "l1d_prefetch_accuracy": extract_metric(metric_text, "Core_0_L1D_prefetch_accuracy"),
            "l1d_prefetch_coverage": extract_metric(metric_text, "Core_0_L1D_prefetch_coverage"),
            "l2c_prefetch_issued": extract_metric(metric_text, "Core_0_L2C_prefetch_issued"),
            "l2c_prefetch_accuracy": extract_metric(metric_text, "Core_0_L2C_prefetch_accuracy"),
            "l2c_prefetch_coverage": extract_metric(metric_text, "Core_0_L2C_prefetch_coverage"),
        }
    except ValueError as exc:
        raise SystemExit(f"{file_path}: {exc}") from exc

    rows.append(row)

rows.sort(key=lambda row: workload_sort_key(str(row["workload"])))
if not rows:
    raise SystemExit(f"No matching SPEC17 6xx result files found in {result_dir}")

fieldnames = [
    "workload",
    "ipc",
    "l1d_demand_access",
    "l1d_demand_miss",
    "l1d_demand_miss_rate",
    "l2c_demand_access",
    "l2c_demand_miss",
    "l2c_demand_miss_rate",
    "llc_demand_access",
    "llc_demand_miss",
    "llc_demand_miss_rate",
    "l1d_prefetch_issued",
    "l1d_prefetch_accuracy",
    "l1d_prefetch_coverage",
    "l2c_prefetch_issued",
    "l2c_prefetch_accuracy",
    "l2c_prefetch_coverage",
]

avg_row: dict[str, object] = {"workload": "AVG"}
for key in fieldnames:
    if key == "workload":
        continue
    values = finite_values(rows, key)
    avg_row[key] = geometric_mean(values) if key == "ipc" else arithmetic_mean(values)

with csv_path.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows + [avg_row]:
        writer.writerow({
            key: row[key] if key == "workload" else (f"{row[key]:.6f}" if finite(row[key]) else "nan")
            for key in fieldnames
        })

try:
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit("matplotlib is required for plotting. Install it with: pip install --user matplotlib") from exc

rows_for_plot = rows + [avg_row]
workloads = [str(row["workload"]) for row in rows_for_plot]
x_positions = list(range(len(rows_for_plot)))
avg_index = len(rows_for_plot) - 1

plots = [
    ("ipc", "IPC", "IPC", "#1f77b4"),
    ("l1d_demand_miss_rate", "L1D demand miss rate", "Rate", "#d62728"),
    ("l2c_demand_miss_rate", "L2C demand miss rate", "Rate", "#ff7f0e"),
    ("llc_demand_miss_rate", "LLC demand miss rate", "Rate", "#2ca02c"),
    ("l1d_demand_miss", "L1D demand miss", "Count", "#9467bd"),
    ("l2c_demand_miss", "L2C demand miss", "Count", "#8c564b"),
    ("llc_demand_miss", "LLC demand miss", "Count", "#17becf"),
    ("l1d_prefetch_issued", "L1D prefetch issued", "Count", "#bcbd22"),
    ("l1d_prefetch_accuracy", "L1D prefetch accuracy", "Ratio", "#7f7f7f"),
    ("l1d_prefetch_coverage", "L1D prefetch coverage", "Ratio", "#e377c2"),
    ("l2c_prefetch_issued", "L2C prefetch issued", "Count", "#1f77b4"),
    ("l2c_prefetch_accuracy", "L2C prefetch accuracy", "Ratio", "#ff7f0e"),
]

fig, axes = plt.subplots(3, 4, figsize=(30.0, 14.0), dpi=300)
axes = axes.ravel()

for ax, (key, title, ylabel, color) in zip(axes, plots):
    values = [row[key] for row in rows_for_plot]
    colors = [color] * len(values)
    colors[avg_index] = "#333333"
    ax.bar(x_positions, values, color=colors, width=0.72)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.6)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(workloads, rotation=45, ha="right", fontsize=8)

fig.tight_layout()
fig.savefig(fig_png, bbox_inches="tight")
fig.savefig(fig_pdf, bbox_inches="tight")

print(f"CSV written to: {csv_path}")
print(f"Figure written to: {fig_png}")
print(f"Figure written to: {fig_pdf}")
PY

echo "[DONE] CSV + figure generated under: ${OUT_DIR}"
