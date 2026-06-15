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
CONFIG_TAG=$(basename "$SCRIPT_DIR")
RESULT_DIR="${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${CONFIG_TAG}"
OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${CONFIG_TAG}"
COMPARE_OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/data_process_for_compare"
WEIGHT_MAP_CSV="${COMPARE_OUT_DIR}/spec17_trace_weight_map.csv"
TOOL_PY="${CHAMPSIM_ROOT}/launch_sim/${COMPARE_TAG}/data_process_for_compare/spec17_fulltrace_tools.py"
MAP_SCRIPT="${CHAMPSIM_ROOT}/launch_sim/${COMPARE_TAG}/data_process_for_compare/generate_spec17_trace_weight_map.sh"

TRACE_LEVEL_CSV="${OUT_DIR}/nol2pref_trace_level.csv"
BENCHMARK_AGG_CSV="${OUT_DIR}/nol2pref_benchmark_agg.csv"
FIG_PNG="${OUT_DIR}/nol2pref_benchmark_agg.png"
FIG_PDF="${OUT_DIR}/nol2pref_benchmark_agg.pdf"

if [ ! -d "$RESULT_DIR" ]; then
    echo "[ERROR] Result directory not found: $RESULT_DIR"
    exit 1
fi

mkdir -p "$OUT_DIR" "$COMPARE_OUT_DIR"

if [ ! -f "$WEIGHT_MAP_CSV" ]; then
    echo "[INFO] weight map not found, generating first: $WEIGHT_MAP_CSV"
    "$MAP_SCRIPT"
fi

python3 "$TOOL_PY" single-config \
    --result-dir "$RESULT_DIR" \
    --weight-map-csv "$WEIGHT_MAP_CSV" \
    --trace-level-csv "$TRACE_LEVEL_CSV" \
    --benchmark-agg-csv "$BENCHMARK_AGG_CSV" \
    --fig-png "$FIG_PNG" \
    --fig-pdf "$FIG_PDF" \
    --figure-title "noL2Pref benchmark-level aggregated metrics"

echo "[DONE] Base fulltrace CSV + figures generated under: $OUT_DIR"
