#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

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

COMPARE_TAG=$(basename "$(dirname "$SCRIPT_DIR")")
FLOW_TAG=${FLOW_TAG:-select_trace}
SELECT_THRESHOLD=${SELECT_THRESHOLD:-1.0}
RESULT_DIR="${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/nopref-workload-sweep"
OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/data_process_for_compare"
OUT_JSON="${OUT_DIR}/stlb_mpki_gt_${SELECT_THRESHOLD}_selected_traces.json"
TOOL_PY="${SCRIPT_DIR}/tlb_select_tools.py"

if [ ! -d "$RESULT_DIR" ]; then
    echo "[ERROR] nopref result directory not found: $RESULT_DIR"
    exit 1
fi

mkdir -p "$OUT_DIR"

python3 "$TOOL_PY" select-trace-json \
    --result-dir "$RESULT_DIR" \
    --out-json "$OUT_JSON" \
    --threshold "$SELECT_THRESHOLD"

echo "[DONE] selected trace json: $OUT_JSON"
