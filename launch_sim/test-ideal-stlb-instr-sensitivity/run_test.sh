#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

find_champsim_root() {
    local dir="$1"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/Makefile" ] && [ -d "$dir/src" ] && [ -d "$dir/launch_sim" ]; then
            echo "$dir"
            return 0
        fi
        dir=$(dirname "$dir")
    done
    return 1
}

CHAMPSIM_ROOT=$(find_champsim_root "$SCRIPT_DIR") || {
    echo "[ERROR] Cannot locate ChampSim root from $SCRIPT_DIR"
    exit 1
}

COMPARE_TAG=$(basename "$SCRIPT_DIR")
BASE_CONFIG="${CHAMPSIM_ROOT}/champsim_config.json"
SKIP_EXISTING=${SKIP_EXISTING:-1}
MAX_PARALLEL=${MAX_PARALLEL:-1}
LENGTH_CASES=${LENGTH_CASES:-"20:50 50:100 100:200"}
TRACE_FILTER=${TRACE_FILTER:-}

CONFIG_TAGS=(pref ideal-demand ideal-l1pref ideal-all)
BINARY_NAMES=(tlb-lensens-pref-1core tlb-lensens-ideal-demand-1core tlb-lensens-ideal-l1pref-1core tlb-lensens-ideal-all-1core)
IDEAL_MODES=(off demand l1pref all)

TRACE_PATHS=(
    /data0/tzh/champsim_traces/Ligra/ligra_CF.com-lj.ungraph.gcc_6.3.0_O3.drop_184750M.length_250M.champsimtrace.xz
    /data0/tzh/champsim_traces/Ligra/ligra_Components.com-lj.ungraph.gcc_6.3.0_O3.drop_6250M.length_250M.champsimtrace.xz
    /data0/tzh/champsim_traces/SPEC17/620.omnetpp_s-141B.champsimtrace.xz
    /data0/tzh/champsim_traces/SPEC06/483.xalancbmk-716B.champsimtrace.xz
    /data0/tzh/champsim_traces/GAP/gap.cc.twitter-10B.champsimtrace.xz
)

ensure_inputs() {
    if [ ! -f "$BASE_CONFIG" ]; then
        echo "[ERROR] Cannot find base config: $BASE_CONFIG"
        exit 1
    fi
    for trace_path in "${TRACE_PATHS[@]}"; do
        if [ -n "$TRACE_FILTER" ] && [[ "$(basename "$trace_path")" != *"$TRACE_FILTER"* ]]; then
            continue
        fi
        if [ ! -f "$trace_path" ]; then
            echo "[ERROR] Cannot find trace: $trace_path"
            exit 1
        fi
    done
}

config_path() {
    echo "${SCRIPT_DIR}/$1/config.json"
}

length_tag() {
    local warm="$1"
    local sim="$2"
    echo "w${warm}_s${sim}"
}

result_dir() {
    local case_tag="$1"
    local config_tag="$2"
    echo "${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${case_tag}/${config_tag}"
}

trace_tag() {
    local trace_name
    trace_name=$(basename "$1")
    trace_name=${trace_name%.xz}
    trace_name=${trace_name%.gz}
    trace_name=${trace_name%.champsimtrace}
    echo "$trace_name"
}

prepare_config() {
    local tag="$1"
    local binary="$2"
    local cfg
    cfg=$(config_path "$tag")
    mkdir -p "$(dirname "$cfg")"
    cp "$BASE_CONFIG" "$cfg"
    python3 - "$cfg" "$binary" <<'PY'
import json
import sys

cfg, binary = sys.argv[1:]
with open(cfg, encoding="utf-8") as rfp:
    data = json.load(rfp)
data["executable_name"] = binary
data["num_cores"] = 1
with open(cfg, "w", encoding="utf-8") as wfp:
    json.dump(data, wfp, indent=2)
    wfp.write("\n")
PY
}

build_one() {
    local tag="$1"
    local binary="$2"
    local cfg
    cfg=$(config_path "$tag")
    prepare_config "$tag" "$binary"
    cd "$CHAMPSIM_ROOT"
    echo "[BUILD] $tag from $cfg"
    ./config.sh "$cfg"
    make
    if [ ! -x "${CHAMPSIM_ROOT}/bin/${binary}" ]; then
        echo "[ERROR] Build failed, missing bin/${binary}"
        exit 1
    fi
}

build_all() {
    ensure_inputs
    local i
    for i in "${!CONFIG_TAGS[@]}"; do
        build_one "${CONFIG_TAGS[$i]}" "${BINARY_NAMES[$i]}"
    done
}

run_one() {
    local warm="$1"
    local sim="$2"
    local tag="$3"
    local binary="$4"
    local mode="$5"
    local trace_path="$6"
    local case_tag out_dir out_file options

    case_tag=$(length_tag "$warm" "$sim")
    out_dir=$(result_dir "$case_tag" "$tag")
    mkdir -p "$out_dir"
    out_file="${out_dir}/$(trace_tag "$trace_path")-${binary}-${case_tag}.log"

    if [ -f "$out_file" ] && [ "$SKIP_EXISTING" = "1" ]; then
        if grep -q "^\[ROI Statistics\]" "$out_file"; then
            echo "[SKIP] complete output: $out_file"
            return 0
        fi
        echo "[RERUN] incomplete output: $out_file"
    fi

    options=(--hide-heartbeat)
    if [ "$mode" != "off" ]; then
        options+=(--stlb-ideal-mode "$mode")
    fi

    echo "[RUN] ${case_tag} ${tag} $(basename "$trace_path")"
    echo "[CMD] bin/${binary} --warmup-instructions ${warm}000000 --simulation-instructions ${sim}000000 ${options[*]} $trace_path"
    "${CHAMPSIM_ROOT}/bin/${binary}" \
        --warmup-instructions "${warm}000000" \
        --simulation-instructions "${sim}000000" \
        "${options[@]}" \
        "$trace_path" \
        > "$out_file"
    echo "[INFO] Simulation output: $out_file"
}

validate_parallel() {
    if ! [[ "$MAX_PARALLEL" =~ ^[0-9]+$ ]] || [ "$MAX_PARALLEL" -lt 1 ]; then
        echo "[ERROR] MAX_PARALLEL must be a positive integer, got: $MAX_PARALLEL"
        exit 1
    fi
}

run_case() {
    local warm="$1"
    local sim="$2"
    local i trace_path running_jobs
    validate_parallel
    for i in "${!CONFIG_TAGS[@]}"; do
        if [ ! -x "${CHAMPSIM_ROOT}/bin/${BINARY_NAMES[$i]}" ]; then
            echo "[ERROR] Missing binary bin/${BINARY_NAMES[$i]}; run build first."
            exit 1
        fi
    done
    running_jobs=0
    for trace_path in "${TRACE_PATHS[@]}"; do
        if [ -n "$TRACE_FILTER" ] && [[ "$(basename "$trace_path")" != *"$TRACE_FILTER"* ]]; then
            continue
        fi
        for i in "${!CONFIG_TAGS[@]}"; do
            run_one "$warm" "$sim" "${CONFIG_TAGS[$i]}" "${BINARY_NAMES[$i]}" "${IDEAL_MODES[$i]}" "$trace_path" &
            running_jobs=$((running_jobs + 1))
            if [ "$running_jobs" -ge "$MAX_PARALLEL" ]; then
                wait -n
                running_jobs=$((running_jobs - 1))
            fi
        done
    done
    while [ "$running_jobs" -gt 0 ]; do
        wait -n
        running_jobs=$((running_jobs - 1))
    done
}

run_all() {
    ensure_inputs
    local case_spec warm sim
    echo "[INFO] MAX_PARALLEL=$MAX_PARALLEL"
    for case_spec in $LENGTH_CASES; do
        IFS=: read -r warm sim <<< "$case_spec"
        if [ -z "$warm" ] || [ -z "$sim" ]; then
            echo "[ERROR] Bad LENGTH_CASES entry: $case_spec, expected warm:sim"
            exit 1
        fi
        echo "[STEP] run length case $(length_tag "$warm" "$sim")"
        run_case "$warm" "$sim"
    done
}

summarize() {
    python3 - "$CHAMPSIM_ROOT" "$COMPARE_TAG" "$LENGTH_CASES" <<'PY'
import csv
import math
import pathlib
import re
import statistics
import sys

root = pathlib.Path(sys.argv[1])
compare_tag = sys.argv[2]
case_specs = sys.argv[3].split()
result_root = root / "results" / compare_tag
out_dir = root / "csv_figure" / compare_tag
out_dir.mkdir(parents=True, exist_ok=True)

configs = [
    ("pref", "baseline", "tlb-lensens-pref-1core"),
    ("ideal-demand", "ideal_demand", "tlb-lensens-ideal-demand-1core"),
    ("ideal-l1pref", "ideal_l1pref", "tlb-lensens-ideal-l1pref-1core"),
    ("ideal-all", "ideal_all", "tlb-lensens-ideal-all-1core"),
]

def case_tag(spec):
    warm, sim = spec.split(":", 1)
    return f"w{warm}_s{sim}"

def extract_metric(text, key):
    m = re.search(rf"^{re.escape(key)}\s+([-.+0-9A-Za-z]+)$", text, flags=re.MULTILINE)
    return float(m.group(1)) if m else math.nan

def trace_from_log(path, binary, case):
    suffix = f"-{binary}-{case}.log"
    name = path.name
    if name.endswith(suffix):
        return name[:-len(suffix)]
    return path.stem

def gmean(values):
    vals = [v for v in values if math.isfinite(v) and v > 0]
    if not vals:
        return math.nan
    return math.exp(sum(math.log(v) for v in vals) / len(vals))

rows = []
for spec in case_specs:
    case = case_tag(spec)
    data = {}
    for tag, label, binary in configs:
        cfg_dir = result_root / case / tag
        for path in sorted(cfg_dir.glob("*.log")):
            text = path.read_text(errors="ignore")
            if "[ROI Statistics]" not in text:
                continue
            trace = trace_from_log(path, binary, case)
            data.setdefault(trace, {})[label] = {
                "ipc": extract_metric(text, "Core_0_IPC"),
                "stlb_mpki": extract_metric(text, "Core_0_STLB_total_MPKI"),
                "stlb_miss_rate": extract_metric(text, "Core_0_STLB_total_miss_rate"),
            }

    for trace in sorted(data):
        rec = data[trace]
        if "baseline" not in rec:
            continue
        base_ipc = rec["baseline"]["ipc"]
        row = {
            "case": case,
            "warmup_m": spec.split(":", 1)[0],
            "roi_m": spec.split(":", 1)[1],
            "trace": trace,
            "baseline_ipc": base_ipc,
            "baseline_stlb_mpki": rec["baseline"]["stlb_mpki"],
            "baseline_stlb_miss_rate": rec["baseline"]["stlb_miss_rate"],
        }
        for label in ["ideal_demand", "ideal_l1pref", "ideal_all"]:
            ipc = rec.get(label, {}).get("ipc", math.nan)
            row[f"{label}_ipc"] = ipc
            row[f"{label}_speedup"] = ipc / base_ipc if base_ipc and math.isfinite(ipc) else math.nan
        rows.append(row)

trace_fields = [
    "case",
    "warmup_m",
    "roi_m",
    "trace",
    "baseline_ipc",
    "baseline_stlb_mpki",
    "baseline_stlb_miss_rate",
    "ideal_demand_ipc",
    "ideal_demand_speedup",
    "ideal_l1pref_ipc",
    "ideal_l1pref_speedup",
    "ideal_all_ipc",
    "ideal_all_speedup",
]
trace_csv = out_dir / "ideal_stlb_instr_sensitivity_trace.csv"
with trace_csv.open("w", newline="", encoding="utf-8") as wfp:
    writer = csv.DictWriter(wfp, fieldnames=trace_fields)
    writer.writeheader()
    writer.writerows(rows)

summary_rows = []
for spec in case_specs:
    case = case_tag(spec)
    case_rows = [r for r in rows if r["case"] == case]
    summary = {
        "case": case,
        "warmup_m": spec.split(":", 1)[0],
        "roi_m": spec.split(":", 1)[1],
        "num_complete_traces": len(case_rows),
        "baseline_ipc_gmean": gmean([r["baseline_ipc"] for r in case_rows]),
        "baseline_stlb_mpki_amean": statistics.fmean([r["baseline_stlb_mpki"] for r in case_rows if math.isfinite(r["baseline_stlb_mpki"])]) if case_rows else math.nan,
    }
    for label in ["ideal_demand", "ideal_l1pref", "ideal_all"]:
        summary[f"{label}_speedup_gmean"] = gmean([r[f"{label}_speedup"] for r in case_rows])
    summary_rows.append(summary)

summary_fields = [
    "case",
    "warmup_m",
    "roi_m",
    "num_complete_traces",
    "baseline_ipc_gmean",
    "baseline_stlb_mpki_amean",
    "ideal_demand_speedup_gmean",
    "ideal_l1pref_speedup_gmean",
    "ideal_all_speedup_gmean",
]
summary_csv = out_dir / "ideal_stlb_instr_sensitivity_summary.csv"
with summary_csv.open("w", newline="", encoding="utf-8") as wfp:
    writer = csv.DictWriter(wfp, fieldnames=summary_fields)
    writer.writeheader()
    writer.writerows(summary_rows)

print(f"[INFO] wrote {trace_csv}")
print(f"[INFO] wrote {summary_csv}")
for row in summary_rows:
    print(
        f"{row['case']}: traces={row['num_complete_traces']}, "
        f"demand={row['ideal_demand_speedup_gmean']:.4g}x, "
        f"l1pref={row['ideal_l1pref_speedup_gmean']:.4g}x, "
        f"all={row['ideal_all_speedup_gmean']:.4g}x"
    )

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception as exc:
    print(f"[WARN] matplotlib unavailable, skip figures: {exc}")
else:
    labels = [r["case"] for r in summary_rows]
    x = list(range(len(labels)))
    width = 0.24
    series = [
        ("Ideal demand", "ideal_demand_speedup_gmean", "#4C78A8"),
        ("Ideal L1-pref", "ideal_l1pref_speedup_gmean", "#F58518"),
        ("Ideal all", "ideal_all_speedup_gmean", "#54A24B"),
    ]
    fig, ax = plt.subplots(figsize=(max(6.5, 1.5 * len(labels)), 3.8))
    for idx, (name, key, color) in enumerate(series):
        vals = [r[key] for r in summary_rows]
        offs = [pos + (idx - 1) * width for pos in x]
        ax.bar(offs, vals, width=width, label=name, color=color)
    ax.axhline(1.0, color="0.25", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=0)
    ax.set_ylabel("IPC speedup over pref")
    ax.set_xlabel("Warmup / ROI case")
    ax.set_title("Ideal STLB instruction-count sensitivity")
    ax.grid(axis="y", color="0.85", linewidth=0.8)
    ax.legend(frameon=True, fontsize=9)
    fig.tight_layout()
    for suffix in ("png", "pdf"):
        out = out_dir / f"ideal_stlb_instr_sensitivity_summary.{suffix}"
        fig.savefig(out, dpi=220 if suffix == "png" else None)
        print(f"[INFO] wrote {out}")
PY
}

status() {
    echo "CHAMPSIM_ROOT : $CHAMPSIM_ROOT"
    echo "BASE_CONFIG   : $BASE_CONFIG"
    echo "COMPARE_TAG   : $COMPARE_TAG"
    echo "LENGTH_CASES  : $LENGTH_CASES"
    echo "TRACE_FILTER  : ${TRACE_FILTER:-<none>}"
    echo "SKIP_EXISTING : $SKIP_EXISTING"
    echo "MAX_PARALLEL  : $MAX_PARALLEL"
    echo "TRACE_PATHS:"
    printf '  %s\n' "${TRACE_PATHS[@]}"
}

cmd=${1:-all}
case "$cmd" in
    all)
        status
        build_all
        run_all
        summarize
        ;;
    build)
        status
        build_all
        ;;
    run)
        status
        run_all
        ;;
    summary|summarize)
        summarize
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {all|build|run|summary|status}"
        exit 1
        ;;
esac

echo "[DONE] $cmd"
