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
BASE_CONFIG="${SCRIPT_DIR}/base_config.json"
OLD_COMPARE_TAG=${OLD_COMPARE_TAG:-1core-spec0617_gapligra-idealTLB-select-trace-compare_jsonnew}
N_WARM=${N_WARM:-20}
N_SIM=${N_SIM:-50}
SKIP_EXISTING=${SKIP_EXISTING:-1}
MAX_PARALLEL=${MAX_PARALLEL:-1}
TRACE_FILTER=${TRACE_FILTER:-}

CONFIG_TAGS=(pref ideal-demand ideal-l1pref ideal-all)
BINARY_NAMES=(tlb-rand4-mshr4-pref-1core tlb-rand4-mshr4-ideal-demand-1core tlb-rand4-mshr4-ideal-l1pref-1core tlb-rand4-mshr4-ideal-all-1core)
IDEAL_MODES=(off demand l1pref all)

TRACE_PATHS=(
    /data0/tzh/champsim_traces/SPEC17/602.gcc_s-2226B.champsimtrace.xz
    /data0/tzh/champsim_traces/Ligra/ligra_Radii.com-lj.ungraph.gcc_6.3.0_O3.drop_36000M.length_250M.champsimtrace.xz
    /data0/tzh/champsim_traces/SPEC06/429.mcf-192B.champsimtrace.xz
    /data0/tzh/champsim_traces/SPEC17/620.omnetpp_s-874B.champsimtrace.xz
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

result_dir() {
    echo "${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/$1"
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
data["ITLB"]["mshr_size"] = 4
data["DTLB"]["mshr_size"] = 4
data["STLB"]["mshr_size"] = 4
data["PTW"]["max_read"] = 1

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
    local tag="$1"
    local binary="$2"
    local mode="$3"
    local trace_path="$4"
    local out_dir out_file options

    out_dir=$(result_dir "$tag")
    mkdir -p "$out_dir"
    out_file="${out_dir}/$(trace_tag "$trace_path")-${binary}-w${N_WARM}_s${N_SIM}.log"

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

    echo "[RUN] $tag $(basename "$trace_path")"
    echo "[CMD] bin/${binary} --warmup-instructions ${N_WARM}000000 --simulation-instructions ${N_SIM}000000 ${options[*]} $trace_path"
    "${CHAMPSIM_ROOT}/bin/${binary}" \
        --warmup-instructions "${N_WARM}000000" \
        --simulation-instructions "${N_SIM}000000" \
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

run_all() {
    ensure_inputs
    validate_parallel
    local i trace_path running_jobs
    for i in "${!CONFIG_TAGS[@]}"; do
        if [ ! -x "${CHAMPSIM_ROOT}/bin/${BINARY_NAMES[$i]}" ]; then
            echo "[ERROR] Missing binary bin/${BINARY_NAMES[$i]}; run build first."
            exit 1
        fi
    done
    echo "[INFO] MAX_PARALLEL=$MAX_PARALLEL"
    running_jobs=0
    for trace_path in "${TRACE_PATHS[@]}"; do
        if [ -n "$TRACE_FILTER" ] && [[ "$(basename "$trace_path")" != *"$TRACE_FILTER"* ]]; then
            continue
        fi
        for i in "${!CONFIG_TAGS[@]}"; do
            run_one "${CONFIG_TAGS[$i]}" "${BINARY_NAMES[$i]}" "${IDEAL_MODES[$i]}" "$trace_path" &
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

summarize() {
    python3 - "$CHAMPSIM_ROOT" "$COMPARE_TAG" "$OLD_COMPARE_TAG" <<'PY'
import csv
import math
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
compare_tag = sys.argv[2]
old_compare_tag = sys.argv[3]
result_root = root / "results" / compare_tag
out_dir = root / "csv_figure" / compare_tag
out_dir.mkdir(parents=True, exist_ok=True)
old_csv_root = root / "csv_figure" / old_compare_tag / "select_trace"

configs = [
    ("pref", "baseline", "tlb-rand4-mshr4-pref-1core"),
    ("ideal-demand", "ideal_demand", "tlb-rand4-mshr4-ideal-demand-1core"),
    ("ideal-l1pref", "ideal_l1pref", "tlb-rand4-mshr4-ideal-l1pref-1core"),
    ("ideal-all", "ideal_all", "tlb-rand4-mshr4-ideal-all-1core"),
]

def extract_metric(text, key):
    m = re.search(rf"^{re.escape(key)}\s+([-.+0-9A-Za-z]+)$", text, flags=re.MULTILINE)
    return float(m.group(1)) if m else math.nan

def trace_from_log(path, binary):
    suffix = f"-{binary}-w20_s50.log"
    name = path.name
    if name.endswith(suffix):
        return name[:-len(suffix)]
    m = re.match(rf"(.+)-{re.escape(binary)}-w\d+_s\d+\.log$", name)
    if m:
        return m.group(1)
    return path.stem

def gmean(values):
    vals = [v for v in values if math.isfinite(v) and v > 0]
    if not vals:
        return math.nan
    return math.exp(sum(math.log(v) for v in vals) / len(vals))

def amean(values):
    vals = [v for v in values if math.isfinite(v)]
    return sum(vals) / len(vals) if vals else math.nan

def read_old_ipc(path):
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as rfp:
        return {row["trace_tag"]: float(row["ipc"]) for row in csv.DictReader(rfp)}

old_baseline = read_old_ipc(old_csv_root / "pref-workload-sweep" / "baseline_trace_level.csv")
old_demand = read_old_ipc(old_csv_root / "ideal-demand-workload-sweep" / "ideal_demand_trace_level.csv")
old_l1pref = read_old_ipc(old_csv_root / "ideal-l1pref-workload-sweep" / "ideal_l1pref_trace_level.csv")
old_all = read_old_ipc(old_csv_root / "ideal-all-workload-sweep" / "ideal_all_trace_level.csv")

data = {}
for tag, label, binary in configs:
    cfg_dir = result_root / tag
    for path in sorted(cfg_dir.glob("*.log")):
        text = path.read_text(errors="ignore")
        if "[ROI Statistics]" not in text:
            continue
        trace = trace_from_log(path, binary)
        data.setdefault(trace, {})[label] = {
            "ipc": extract_metric(text, "Core_0_IPC"),
            "stlb_mpki": extract_metric(text, "Core_0_STLB_total_MPKI"),
            "stlb_miss_rate": extract_metric(text, "Core_0_STLB_total_miss_rate"),
        }

rows = []
for trace in sorted(data):
    rec = data[trace]
    if "baseline" not in rec:
        continue
    base_ipc = rec["baseline"]["ipc"]
    old_base_ipc = old_baseline.get(trace, math.nan)

    def old_speedup(old_ipc):
        return old_ipc / old_base_ipc if old_base_ipc and math.isfinite(old_ipc) else math.nan

    row = {
        "trace": trace,
        "old_baseline_ipc": old_base_ipc,
        "new_baseline_ipc": base_ipc,
        "new_baseline_stlb_mpki": rec["baseline"]["stlb_mpki"],
        "new_baseline_stlb_miss_rate": rec["baseline"]["stlb_miss_rate"],
        "old_ideal_demand_speedup": old_speedup(old_demand.get(trace, math.nan)),
        "old_ideal_l1pref_speedup": old_speedup(old_l1pref.get(trace, math.nan)),
        "old_ideal_all_speedup": old_speedup(old_all.get(trace, math.nan)),
    }
    for label in ["ideal_demand", "ideal_l1pref", "ideal_all"]:
        ipc = rec.get(label, {}).get("ipc", math.nan)
        speedup = ipc / base_ipc if base_ipc and math.isfinite(ipc) else math.nan
        row[f"new_{label}_ipc"] = ipc
        row[f"new_{label}_speedup"] = speedup
        old_key = f"old_{label}_speedup"
        row[f"delta_{label}_speedup"] = speedup - row[old_key] if math.isfinite(speedup) and math.isfinite(row[old_key]) else math.nan
    rows.append(row)

trace_fields = [
    "trace",
    "old_baseline_ipc",
    "new_baseline_ipc",
    "new_baseline_stlb_mpki",
    "new_baseline_stlb_miss_rate",
    "old_ideal_demand_speedup",
    "new_ideal_demand_ipc",
    "new_ideal_demand_speedup",
    "delta_ideal_demand_speedup",
    "old_ideal_l1pref_speedup",
    "new_ideal_l1pref_ipc",
    "new_ideal_l1pref_speedup",
    "delta_ideal_l1pref_speedup",
    "old_ideal_all_speedup",
    "new_ideal_all_ipc",
    "new_ideal_all_speedup",
    "delta_ideal_all_speedup",
]
trace_csv = out_dir / "tlb_mshr_ptw_maxread_trace_compare.csv"
with trace_csv.open("w", newline="", encoding="utf-8") as wfp:
    writer = csv.DictWriter(wfp, fieldnames=trace_fields)
    writer.writeheader()
    writer.writerows(rows)

summary = {
    "num_complete_traces": len(rows),
    "old_baseline_ipc_gmean": gmean(row["old_baseline_ipc"] for row in rows),
    "new_baseline_ipc_gmean": gmean(row["new_baseline_ipc"] for row in rows),
    "new_baseline_stlb_mpki_amean": amean(row["new_baseline_stlb_mpki"] for row in rows),
    "old_ideal_demand_speedup_gmean": gmean(row["old_ideal_demand_speedup"] for row in rows),
    "new_ideal_demand_speedup_gmean": gmean(row["new_ideal_demand_speedup"] for row in rows),
    "delta_ideal_demand_speedup_gmean": math.nan,
    "old_ideal_l1pref_speedup_gmean": gmean(row["old_ideal_l1pref_speedup"] for row in rows),
    "new_ideal_l1pref_speedup_gmean": gmean(row["new_ideal_l1pref_speedup"] for row in rows),
    "delta_ideal_l1pref_speedup_gmean": math.nan,
    "old_ideal_all_speedup_gmean": gmean(row["old_ideal_all_speedup"] for row in rows),
    "new_ideal_all_speedup_gmean": gmean(row["new_ideal_all_speedup"] for row in rows),
    "delta_ideal_all_speedup_gmean": math.nan,
}
summary["delta_ideal_demand_speedup_gmean"] = summary["new_ideal_demand_speedup_gmean"] - summary["old_ideal_demand_speedup_gmean"]
summary["delta_ideal_l1pref_speedup_gmean"] = summary["new_ideal_l1pref_speedup_gmean"] - summary["old_ideal_l1pref_speedup_gmean"]
summary["delta_ideal_all_speedup_gmean"] = summary["new_ideal_all_speedup_gmean"] - summary["old_ideal_all_speedup_gmean"]

summary_csv = out_dir / "tlb_mshr_ptw_maxread_summary_compare.csv"
with summary_csv.open("w", newline="", encoding="utf-8") as wfp:
    writer = csv.DictWriter(wfp, fieldnames=list(summary))
    writer.writeheader()
    writer.writerow(summary)

print(f"[INFO] wrote {trace_csv}")
print(f"[INFO] wrote {summary_csv}")
print(
    "summary: "
    f"traces={summary['num_complete_traces']}, "
    f"old_demand={summary['old_ideal_demand_speedup_gmean']:.4g}x, "
    f"new_demand={summary['new_ideal_demand_speedup_gmean']:.4g}x, "
    f"old_l1pref={summary['old_ideal_l1pref_speedup_gmean']:.4g}x, "
    f"new_l1pref={summary['new_ideal_l1pref_speedup_gmean']:.4g}x, "
    f"old_all={summary['old_ideal_all_speedup_gmean']:.4g}x, "
    f"new_all={summary['new_ideal_all_speedup_gmean']:.4g}x"
)
for row in rows:
    print(
        f"{row['trace']}: "
        f"new_base={row['new_baseline_ipc']:.6g}, "
        f"demand={row['new_ideal_demand_speedup']:.4g}x "
        f"(old {row['old_ideal_demand_speedup']:.4g}x), "
        f"l1pref={row['new_ideal_l1pref_speedup']:.4g}x "
        f"(old {row['old_ideal_l1pref_speedup']:.4g}x), "
        f"all={row['new_ideal_all_speedup']:.4g}x "
        f"(old {row['old_ideal_all_speedup']:.4g}x)"
    )
PY
}

status() {
    echo "CHAMPSIM_ROOT : $CHAMPSIM_ROOT"
    echo "BASE_CONFIG   : $BASE_CONFIG"
    echo "OLD_COMPARE   : $OLD_COMPARE_TAG"
    echo "COMPARE_TAG   : $COMPARE_TAG"
    echo "N_WARM        : $N_WARM"
    echo "N_SIM         : $N_SIM"
    echo "SKIP_EXISTING : $SKIP_EXISTING"
    echo "MAX_PARALLEL  : $MAX_PARALLEL"
    echo "TRACE_FILTER  : $TRACE_FILTER"
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
