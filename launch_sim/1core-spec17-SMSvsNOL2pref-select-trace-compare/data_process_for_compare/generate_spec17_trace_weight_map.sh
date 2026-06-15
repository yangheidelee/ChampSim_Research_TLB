#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

find_champsim_root() {
    local dir="$1"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/Makefile" ] && [ -d "$dir/bin" ] && [ -d "$dir/src" ] && [ -d "$dir/launch_sim" ]; then
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
FLOW_TAG=${FLOW_TAG:-full_trace}
TRACE_DIR=${TRACE_DIR:-/data0/tzh/champsim_traces/SPEC17}
WEIGHT_DIR=${WEIGHT_DIR:-${CHAMPSIM_ROOT}/simpoint_weight}

OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/data_process_for_compare"
OUT_CSV="${OUT_DIR}/spec17_trace_weight_map.csv"
TOOL_PY="${SCRIPT_DIR}/spec17_fulltrace_tools.py"

if [ ! -d "$TRACE_DIR" ]; then
    echo "[ERROR] TRACE_DIR not found: $TRACE_DIR"
    exit 1
fi

if [ ! -d "$WEIGHT_DIR" ]; then
    echo "[ERROR] WEIGHT_DIR not found: $WEIGHT_DIR"
    exit 1
fi

mkdir -p "$OUT_DIR"

python3 "$TOOL_PY" weight-map \
    --trace-dir "$TRACE_DIR" \
    --weight-dir "$WEIGHT_DIR" \
    --out-csv "$OUT_CSV"

echo "[DONE] spec17 trace weight map: $OUT_CSV"
