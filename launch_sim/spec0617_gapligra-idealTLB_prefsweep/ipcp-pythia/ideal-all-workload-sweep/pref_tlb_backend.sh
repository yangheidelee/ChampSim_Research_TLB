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

compare_tag_from_dir() {
    local dir="$1"
    local name parent grandparent
    name=$(basename "$dir")
    parent=$(basename "$(dirname "$dir")")
    grandparent=$(basename "$(dirname "$(dirname "$dir")")")
    if [ "$parent" = "spec0617_gapligra-idealTLB_prefsweep" ]; then
        echo "${parent}/${name}"
    elif [ "$grandparent" = "spec0617_gapligra-idealTLB_prefsweep" ]; then
        echo "${grandparent}/${parent}"
    else
        echo "$parent"
    fi
}

COMPARE_TAG=${COMPARE_TAG:-$(compare_tag_from_dir "$SCRIPT_DIR")}
CONFIG_TAG=$(basename "$SCRIPT_DIR")
FLOW_TAG=${FLOW_TAG:-select_trace}
RESULT_DIR="${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${CONFIG_TAG}"
OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/${CONFIG_TAG}"
COMPARE_OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/data_process_for_compare"
TOOL_PY="${CHAMPSIM_ROOT}/launch_sim/${COMPARE_TAG}/data_process_for_compare/tlb_select_tools.py"
SELECT_TRACE_JSON="${SELECT_TRACE_JSON:-}"

TRACE_LEVEL_CSV="${OUT_DIR}/pref_trace_level.csv"
WORKLOAD_CSV="${OUT_DIR}/pref_workload_agg.csv"
FIG_PNG="${OUT_DIR}/pref_stlb_miss_causes.png"
FIG_PDF="${OUT_DIR}/pref_stlb_miss_causes.pdf"

if [ ! -d "$RESULT_DIR" ]; then
    echo "[ERROR] Result directory not found: $RESULT_DIR"
    exit 1
fi

mkdir -p "$OUT_DIR" "$COMPARE_OUT_DIR"

if [ -z "$SELECT_TRACE_JSON" ]; then
    SELECT_TRACE_JSON="${COMPARE_OUT_DIR}/stlb_mpki_gt_1.0_selected_traces.json"
fi

FIG_TITLE="pref selected STLB miss causes"
DONE_LABEL="pref selected CSV + figures"
if [ "$SELECT_TRACE_JSON" = "ALL" ] || [ "$SELECT_TRACE_JSON" = "FULL" ] || [ "$SELECT_TRACE_JSON" = "NONE" ]; then
    FIG_TITLE="pref full-trace STLB miss causes"
    DONE_LABEL="pref full-trace CSV + figures"
fi

python3 "$TOOL_PY" single-config \
    --result-dir "$RESULT_DIR" \
    --select-trace-json "$SELECT_TRACE_JSON" \
    --trace-level-csv "$TRACE_LEVEL_CSV" \
    --workload-csv "$WORKLOAD_CSV" \
    --fig-png "$FIG_PNG" \
    --fig-pdf "$FIG_PDF" \
    --figure-title "$FIG_TITLE"

echo "[DONE] $DONE_LABEL generated under: $OUT_DIR"
