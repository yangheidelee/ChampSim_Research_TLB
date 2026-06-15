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
FLOW_TAG=${FLOW_TAG:-select_trace}

NOPREF_CSV_DEFAULT="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/nopref-workload-sweep/nopref_workload_agg.csv"
PREF_CSV_DEFAULT="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/pref-workload-sweep/pref_workload_agg.csv"

NOPREF_CSV=${1:-$NOPREF_CSV_DEFAULT}
PREF_CSV=${2:-$PREF_CSV_DEFAULT}

if [ ! -f "$NOPREF_CSV" ]; then
    echo "[ERROR] nopref workload csv not found: $NOPREF_CSV"
    exit 1
fi

if [ ! -f "$PREF_CSV" ]; then
    echo "[ERROR] pref workload csv not found: $PREF_CSV"
    exit 1
fi

OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/data_process_for_compare"
OUT_CSV="${OUT_DIR}/pref_vs_nopref_ipc_compare.csv"
OUT_PNG="${OUT_DIR}/pref_vs_nopref_ipc_compare.png"
OUT_PDF="${OUT_DIR}/pref_vs_nopref_ipc_compare.pdf"
OUT_STLB_PNG="${OUT_DIR}/pref_vs_nopref_stlb_miss_rate_norm.png"
OUT_STLB_PDF="${OUT_DIR}/pref_vs_nopref_stlb_miss_rate_norm.pdf"
TOOL_PY="${SCRIPT_DIR}/tlb_select_tools.py"

mkdir -p "$OUT_DIR"

python3 "$TOOL_PY" compare \
    --nopref-csv "$NOPREF_CSV" \
    --pref-csv "$PREF_CSV" \
    --out-csv "$OUT_CSV" \
    --fig-png "$OUT_PNG" \
    --fig-pdf "$OUT_PDF" \
    --figure-title "pref vs nopref IPC compare" \
    --stlb-fig-png "$OUT_STLB_PNG" \
    --stlb-fig-pdf "$OUT_STLB_PDF" \
    --stlb-figure-title "pref vs nopref STLB miss rate amean"

echo "[DONE] compare outputs generated under: $OUT_DIR"
