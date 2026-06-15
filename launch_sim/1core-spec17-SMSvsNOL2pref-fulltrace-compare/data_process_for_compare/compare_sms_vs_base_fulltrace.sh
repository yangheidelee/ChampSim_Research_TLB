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

BASE_CSV_DEFAULT="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/1core-spec17-nol2pref-workload-sweep/nol2pref_benchmark_agg.csv"
SMS_CSV_DEFAULT="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/1core-spec17-sms-workload-sweep/sms_benchmark_agg.csv"

BASE_CSV=${1:-$BASE_CSV_DEFAULT}
SMS_CSV=${2:-$SMS_CSV_DEFAULT}

if [ ! -f "$BASE_CSV" ]; then
    echo "[ERROR] base benchmark agg csv not found: $BASE_CSV"
    exit 1
fi

if [ ! -f "$SMS_CSV" ]; then
    echo "[ERROR] sms benchmark agg csv not found: $SMS_CSV"
    exit 1
fi

OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/data_process_for_compare"
OUT_CSV="${OUT_DIR}/sms_vs_nol2pref_compare.csv"
OUT_PNG="${OUT_DIR}/sms_vs_nol2pref_compare.png"
OUT_PDF="${OUT_DIR}/sms_vs_nol2pref_compare.pdf"
TOOL_PY="${SCRIPT_DIR}/spec17_fulltrace_tools.py"

mkdir -p "$OUT_DIR"

python3 "$TOOL_PY" compare \
    --base-csv "$BASE_CSV" \
    --sms-csv "$SMS_CSV" \
    --out-csv "$OUT_CSV" \
    --fig-png "$OUT_PNG" \
    --fig-pdf "$OUT_PDF" \
    --figure-title "SMS vs noL2pref fulltrace compare"

echo "[DONE] compare outputs generated under: $OUT_DIR"
