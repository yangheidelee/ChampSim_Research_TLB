#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: ./script/run_config.sh CONFIG_NAME BINARY_NAME [MAX_PARALLEL]" >&2
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)

find_champsim_root() {
    local dir="$1"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/Makefile" ] && [ -d "$dir/bin" ] && [ -d "$dir/src" ]; then
            echo "$dir"
            return 0
        fi
        dir=$(dirname "$dir")
    done
    return 1
}

CHAMPSIM_ROOT=$(find_champsim_root "$SCRIPT_DIR") || {
    echo "[ERROR] Cannot locate ChampSim root from $SCRIPT_DIR" >&2
    exit 1
}

CONFIG_NAME="$1"
BINARY_NAME="$2"
MAX_PARALLEL="${3:-${MAX_PARALLEL:-1}}"
N_WARM="${N_WARM:-50}"
N_SIM="${N_SIM:-100}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"
TRACE_DIRS="${TRACE_DIRS:-/data0/tzh/champsim_traces/SPEC06:/data0/tzh/champsim_traces/SPEC17:/data2/zcq/champsim_traces_gap:/data0/tzh/champsim_traces/Ligra:/data0/tzh/champsim_traces/QMM:/data0/tzh/champsim_traces/PARSEC:/data2/zcq/champsim_traces_xsbench}"
SELECT_TRACE_JSON="${SELECT_TRACE_JSON:-/home/zcq/git_prj/ChampSim/csv_figure/spec0617_gapligra_qmm_parsec-TLB-select-trace-compare_vberti_50_100/select_trace/data_process_for_compare/stlb_mpki_gt_1.0_selected_traces.json}"
TRACE_FILTER="${TRACE_FILTER:-}"

if ! [[ "$MAX_PARALLEL" =~ ^[0-9]+$ ]] || [ "$MAX_PARALLEL" -lt 1 ]; then
    echo "[ERROR] MAX_PARALLEL must be a positive integer: $MAX_PARALLEL" >&2
    exit 1
fi
if [ ! -f "$SELECT_TRACE_JSON" ]; then
    echo "[ERROR] Missing selected trace json: $SELECT_TRACE_JSON" >&2
    exit 1
fi

BINARY="${CHAMPSIM_ROOT}/bin/${BINARY_NAME}"
if [ ! -x "$BINARY" ]; then
    echo "[ERROR] Missing binary: $BINARY" >&2
    exit 1
fi

RESULT_DIR="${CASE_DIR}/result/${CONFIG_NAME}"
mkdir -p "$RESULT_DIR"
STATUS_DIR=$(mktemp -d "${TMPDIR:-/tmp}/champsim-${CONFIG_NAME}.XXXXXX")
FAILED_LIST="${STATUS_DIR}/failed_traces.txt"

cleanup() {
    local code=$?
    if [ "$code" -ne 0 ]; then
        for pid in $(jobs -pr); do
            kill "$pid" 2>/dev/null || true
        done
        wait 2>/dev/null || true
    fi
    rm -rf "$STATUS_DIR"
}
trap cleanup EXIT
trap 'echo "[ERROR] Interrupted, terminating active simulations..." >&2; exit 130' INT
trap 'echo "[ERROR] Terminated, stopping active simulations..." >&2; exit 143' TERM

shopt -s nullglob
IFS=':' read -r -a TRACE_DIR_ARRAY <<< "$TRACE_DIRS"
TRACE_FILES=()
for trace_dir in "${TRACE_DIR_ARRAY[@]}"; do
    if [ ! -d "$trace_dir" ]; then
        echo "[ERROR] Trace directory not found: $trace_dir" >&2
        exit 1
    fi
    if [ -n "$TRACE_FILTER" ]; then
        TRACE_FILES+=("${trace_dir}/${TRACE_FILTER}"*.champsimtrace.xz)
        TRACE_FILES+=("${trace_dir}/${TRACE_FILTER}"*.champsimtrace.gz)
        TRACE_FILES+=("${trace_dir}/${TRACE_FILTER}"*.xz)
        TRACE_FILES+=("${trace_dir}/${TRACE_FILTER}"*.gz)
    else
        TRACE_FILES+=("${trace_dir}"/*.champsimtrace.xz)
        TRACE_FILES+=("${trace_dir}"/*.champsimtrace.gz)
        TRACE_FILES+=("${trace_dir}"/*.xz)
        TRACE_FILES+=("${trace_dir}"/*.gz)
    fi
done
shopt -u nullglob

mapfile -t TRACE_ROWS < <(python3 - "$SELECT_TRACE_JSON" "${TRACE_FILES[@]}" <<'PY'
import json
import pathlib
import sys

selected_json = pathlib.Path(sys.argv[1])
candidates = sys.argv[2:]
payload = json.loads(selected_json.read_text())
selected = [str(x) for x in payload.get("selected_trace_tags", [])]

def trace_tag(path_text: str) -> str:
    name = pathlib.Path(path_text).name
    for suffix in [".xz", ".gz"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    if name.endswith(".champsimtrace"):
        name = name[: -len(".champsimtrace")]
    return name

by_tag = {}
for path_text in candidates:
    by_tag.setdefault(trace_tag(path_text), path_text)

missing = []
for tag in selected:
    path = by_tag.get(tag)
    if path:
        print(f"{tag}\t{path}")
    else:
        missing.append(tag)

if missing:
    print("[WARN] Missing selected traces:", file=sys.stderr)
    for tag in missing:
        print(f"[WARN]   {tag}", file=sys.stderr)
PY
)

if [ "${#TRACE_ROWS[@]}" -eq 0 ]; then
    echo "[ERROR] No selected trace files found." >&2
    exit 1
fi

is_complete() {
    local log_file="$1"
    [ -s "$log_file" ] || return 1
    grep -q "^\[ROI Statistics\]" "$log_file" || return 1
    grep -q "^Core_0_TLB_cross_page_prefetch_coverage" "$log_file" || return 1
}

run_one() {
    local trace_tag="$1"
    local trace_path="$2"
    local log_file="${RESULT_DIR}/${trace_tag}-${BINARY_NAME}---hide-heartbeat.log"

    if [ "$SKIP_EXISTING" = "1" ] && is_complete "$log_file"; then
        echo "[SKIP] ${CONFIG_NAME}: ${trace_tag}"
        return
    fi

    echo "[RUN] ${CONFIG_NAME}: ${trace_tag}"
    "$BINARY" \
        --warmup-instructions "${N_WARM}000000" \
        --simulation-instructions "${N_SIM}000000" \
        --hide-heartbeat \
        "$trace_path" \
        > "$log_file"
    echo "[INFO] Simulation output: ${log_file}"
}

run_one_wrapped() {
    local trace_tag="$1"
    local trace_path="$2"
    if ! run_one "$trace_tag" "$trace_path"; then
        printf "%s\n" "$trace_tag" >> "$FAILED_LIST"
        return 1
    fi
}

echo "[INFO] config=${CONFIG_NAME} binary=${BINARY_NAME}"
echo "[INFO] selected_json=${SELECT_TRACE_JSON}"
echo "[INFO] trace_count=${#TRACE_ROWS[@]} parallel=${MAX_PARALLEL} warm=${N_WARM}M sim=${N_SIM}M skip=${SKIP_EXISTING}"

running_jobs=0
failed_jobs=0
for row in "${TRACE_ROWS[@]}"; do
    IFS=$'\t' read -r trace_tag trace_path <<< "$row"
    run_one_wrapped "$trace_tag" "$trace_path" &
    running_jobs=$((running_jobs + 1))
    if [ "$running_jobs" -ge "$MAX_PARALLEL" ]; then
        if ! wait -n; then
            failed_jobs=1
            echo "[ERROR] A simulation job failed; continuing to collect remaining jobs." >&2
        fi
        running_jobs=$((running_jobs - 1))
    fi
done

while [ "$running_jobs" -gt 0 ]; do
    if ! wait -n; then
        failed_jobs=1
        echo "[ERROR] A simulation job failed; continuing to collect remaining jobs." >&2
    fi
    running_jobs=$((running_jobs - 1))
done

if [ "$failed_jobs" -ne 0 ] || [ -s "$FAILED_LIST" ]; then
    echo "[ERROR] Failed traces for ${CONFIG_NAME}:" >&2
    if [ -s "$FAILED_LIST" ]; then
        sort -u "$FAILED_LIST" >&2
    fi
    exit 1
fi

echo "[DONE] ${CONFIG_NAME}: ${RESULT_DIR}"
