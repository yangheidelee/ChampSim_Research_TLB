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
BASELINE_SELECT_TAG=${BASELINE_SELECT_TAG:-1core-spec0617_gapligra-TLB-select-trace-compare_jsonnew}
FLOW_TAG=${FLOW_TAG:-select_trace}
SELECT_THRESHOLD=${SELECT_THRESHOLD:-1.0}
SELECT_TRACE_JSON=${SELECT_TRACE_JSON:-${CHAMPSIM_ROOT}/csv_figure/${BASELINE_SELECT_TAG}/${FLOW_TAG}/data_process_for_compare/stlb_mpki_gt_${SELECT_THRESHOLD}_selected_traces.json}
OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/data_process_for_compare"
OUT_JSON="${OUT_DIR}/stlb_mpki_gt_${SELECT_THRESHOLD}_selected_traces.json"

if [ ! -f "$SELECT_TRACE_JSON" ]; then
    echo "[ERROR] Selected trace JSON not found: $SELECT_TRACE_JSON"
    exit 1
fi

mkdir -p "$OUT_DIR"
if [ "$SELECT_TRACE_JSON" != "$OUT_JSON" ]; then
    cp "$SELECT_TRACE_JSON" "$OUT_JSON"
fi

echo "[DONE] reused selected trace json: $SELECT_TRACE_JSON"
echo "[DONE] local selected trace json: $OUT_JSON"
