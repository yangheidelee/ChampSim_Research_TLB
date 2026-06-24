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
N_WARM=${N_WARM:-20}
N_SIM=${N_SIM:-50}
SKIP_EXISTING=${SKIP_EXISTING:-1}
MAX_PARALLEL=${MAX_PARALLEL:-1}

CONFIG_TAGS=(pref ideal-demand ideal-l1pref ideal-all)
BINARY_NAMES=(tlb-test-pref-1core tlb-test-ideal-demand-1core tlb-test-ideal-l1pref-1core tlb-test-ideal-all-1core)
IDEAL_MODES=(off demand l1pref all)

TRACE_PATHS=(
    /data0/tzh/champsim_traces/Ligra/ligra_CF.com-lj.ungraph.gcc_6.3.0_O3.drop_184750M.length_250M.champsimtrace.xz
    /data0/tzh/champsim_traces/Ligra/ligra_Components.com-lj.ungraph.gcc_6.3.0_O3.drop_6250M.length_250M.champsimtrace.xz
    /data0/tzh/champsim_traces/SPEC17/620.omnetpp_s-141B.champsimtrace.xz
    /data0/tzh/champsim_traces/SPEC06/483.xalancbmk-716B.champsimtrace.xz
    /data0/tzh/champsim_traces/GAP/gap.cc.twitter-10B.champsimtrace.xz
    /data0/tzh/champsim_traces/GAP/gap.pr.twitter-10B.champsimtrace.xz
)

ensure_inputs() {
    if [ ! -f "$BASE_CONFIG" ]; then
        echo "[ERROR] Cannot find base config: $BASE_CONFIG"
        exit 1
    fi
    for trace_path in "${TRACE_PATHS[@]}"; do
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
    out_file="${out_dir}/$(trace_tag "$trace_path")-${binary}.log"

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

run_all() {
    ensure_inputs
    local i trace_path running_jobs
    for i in "${!CONFIG_TAGS[@]}"; do
        if [ ! -x "${CHAMPSIM_ROOT}/bin/${BINARY_NAMES[$i]}" ]; then
            echo "[ERROR] Missing binary bin/${BINARY_NAMES[$i]}; run build first."
            exit 1
        fi
    done
    if ! [[ "$MAX_PARALLEL" =~ ^[0-9]+$ ]] || [ "$MAX_PARALLEL" -lt 1 ]; then
        echo "[ERROR] MAX_PARALLEL must be a positive integer, got: $MAX_PARALLEL"
        exit 1
    fi
    echo "[INFO] MAX_PARALLEL=$MAX_PARALLEL"
    running_jobs=0
    for trace_path in "${TRACE_PATHS[@]}"; do
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
    python3 - "$CHAMPSIM_ROOT" "$COMPARE_TAG" <<'PY'
import csv
import math
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
compare_tag = sys.argv[2]
result_root = root / "results" / compare_tag
out_dir = root / "csv_figure" / compare_tag
out_dir.mkdir(parents=True, exist_ok=True)
old_csv_root = root / "csv_figure" / "1core-spec0617_gapligra-idealTLB-select-trace-compare" / "select_trace"

configs = [
    ("pref", "baseline"),
    ("ideal-demand", "ideal_demand"),
    ("ideal-l1pref", "ideal_l1pref"),
    ("ideal-all", "ideal_all"),
]

def extract_metric(text, key):
    m = re.search(rf"^{re.escape(key)}\s+([-.+0-9A-Za-z]+)$", text, flags=re.MULTILINE)
    return float(m.group(1)) if m else math.nan

def trace_from_log(path):
    name = path.name
    for marker in [
        "-tlb-test-pref-1core.log",
        "-tlb-test-ideal-demand-1core.log",
        "-tlb-test-ideal-l1pref-1core.log",
        "-tlb-test-ideal-all-1core.log",
    ]:
        if name.endswith(marker):
            return name[: -len(marker)]
    return path.stem

def load_old_trace_level():
    baseline_path = old_csv_root / "pref-workload-sweep" / "baseline_trace_level.csv"
    demand_path = old_csv_root / "ideal-demand-workload-sweep" / "ideal_demand_trace_level.csv"
    l1pref_path = old_csv_root / "ideal-l1pref-workload-sweep" / "ideal_l1pref_trace_level.csv"
    all_path = old_csv_root / "ideal-all-workload-sweep" / "ideal_all_trace_level.csv"
    if not all(p.exists() for p in [baseline_path, demand_path, l1pref_path, all_path]):
        return {}

    def read_ipc(path):
        with path.open(newline="", encoding="utf-8") as rfp:
            return {row["trace_tag"]: float(row["ipc"]) for row in csv.DictReader(rfp)}

    baseline = read_ipc(baseline_path)
    demand = read_ipc(demand_path)
    l1pref = read_ipc(l1pref_path)
    all_ideal = read_ipc(all_path)
    old = {}
    for trace, base_ipc in baseline.items():
        if not base_ipc:
            continue
        old[trace] = {
            "old_baseline_ipc": base_ipc,
            "old_ideal_demand_speedup": demand.get(trace, math.nan) / base_ipc if trace in demand else math.nan,
            "old_ideal_l1pref_speedup": l1pref.get(trace, math.nan) / base_ipc if trace in l1pref else math.nan,
            "old_ideal_all_speedup": all_ideal.get(trace, math.nan) / base_ipc if trace in all_ideal else math.nan,
        }
    return old

old_trace_level = load_old_trace_level()

data = {}
for tag, label in configs:
    cfg_dir = result_root / tag
    for path in sorted(cfg_dir.glob("*.log")):
        text = path.read_text(errors="ignore")
        if "[ROI Statistics]" not in text:
            continue
        trace = trace_from_log(path)
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
    row = {
        "trace": trace,
        "old_baseline_ipc": math.nan,
        "old_ideal_demand_speedup": math.nan,
        "old_ideal_l1pref_speedup": math.nan,
        "old_ideal_all_speedup": math.nan,
        "baseline_ipc": base_ipc,
        "baseline_stlb_mpki": rec["baseline"]["stlb_mpki"],
        "baseline_stlb_miss_rate": rec["baseline"]["stlb_miss_rate"],
    }
    row.update(old_trace_level.get(trace, {}))
    for label in ["ideal_demand", "ideal_l1pref", "ideal_all"]:
        ipc = rec.get(label, {}).get("ipc", math.nan)
        row[f"{label}_ipc"] = ipc
        row[f"{label}_speedup"] = ipc / base_ipc if base_ipc and math.isfinite(ipc) else math.nan
    rows.append(row)

fields = [
    "trace",
    "old_baseline_ipc",
    "old_ideal_demand_speedup",
    "old_ideal_l1pref_speedup",
    "old_ideal_all_speedup",
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
out_csv = out_dir / "ideal_stlb_config_sanity_ipc.csv"
with out_csv.open("w", newline="", encoding="utf-8") as wfp:
    writer = csv.DictWriter(wfp, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

print(f"[INFO] wrote {out_csv}")
for row in rows:
    print(
        f"{row['trace']}: "
        f"base={row['baseline_ipc']:.6g}, "
        f"demand={row['ideal_demand_speedup']:.4g}x, "
        f"l1pref={row['ideal_l1pref_speedup']:.4g}x, "
        f"all={row['ideal_all_speedup']:.4g}x, "
        f"base_stlb_mpki={row['baseline_stlb_mpki']:.4g}"
    )
PY
}

status() {
    echo "CHAMPSIM_ROOT : $CHAMPSIM_ROOT"
    echo "BASE_CONFIG   : $BASE_CONFIG"
    echo "COMPARE_TAG   : $COMPARE_TAG"
    echo "N_WARM        : $N_WARM"
    echo "N_SIM         : $N_SIM"
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
