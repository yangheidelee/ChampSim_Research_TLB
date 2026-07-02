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
PREF_CSV_LIST=${PREF_CSV_LIST:-}
PREF_LABEL_LIST=${PREF_LABEL_LIST:-}
PREF_CONFIG_LIST=${PREF_CONFIG_LIST:-}

if [ ! -f "$NOPREF_CSV" ]; then
    echo "[ERROR] nopref workload csv not found: $NOPREF_CSV"
    exit 1
fi

OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/data_process_for_compare"
OUT_CSV="${OUT_DIR}/pref_vs_nopref_ipc_compare.csv"
OUT_PNG="${OUT_DIR}/pref_vs_nopref_ipc_compare.png"
OUT_PDF="${OUT_DIR}/pref_vs_nopref_ipc_compare.pdf"
OUT_MPKI_PNG="${OUT_DIR}/pref_vs_nopref_stlb_mpki_norm.png"
OUT_MPKI_PDF="${OUT_DIR}/pref_vs_nopref_stlb_mpki_norm.pdf"
OUT_STLB_PNG="${OUT_DIR}/pref_vs_nopref_stlb_miss_rate_norm.png"
OUT_STLB_PDF="${OUT_DIR}/pref_vs_nopref_stlb_miss_rate_norm.pdf"
OUT_DRAM_PKI_PNG="${OUT_DIR}/pref_vs_nopref_dram_rq_read_pki_norm.png"
OUT_DRAM_PKI_PDF="${OUT_DIR}/pref_vs_nopref_dram_rq_read_pki_norm.pdf"
TOOL_PY="${SCRIPT_DIR}/tlb_select_tools.py"

mkdir -p "$OUT_DIR"

if [ -n "$PREF_CSV_LIST" ]; then
    IFS=':' read -r -a PREF_CSV_ARRAY <<< "$PREF_CSV_LIST"
    IFS=':' read -r -a PREF_LABEL_ARRAY <<< "$PREF_LABEL_LIST"
    IFS=':' read -r -a PREF_CONFIG_ARRAY <<< "$PREF_CONFIG_LIST"
    if [ "${#PREF_CSV_ARRAY[@]}" -eq 0 ]; then
        echo "[ERROR] PREF_CSV_LIST is empty"
        exit 1
    fi

    PY_ARGS=(
        "$TOOL_PY" compare-many
        --nopref-csv "$NOPREF_CSV"
        --out-csv "$OUT_CSV"
        --fig-png "$OUT_PNG"
        --fig-pdf "$OUT_PDF"
        --figure-title "selected trace IPC speedup vs nopref"
        --mpki-fig-png "$OUT_MPKI_PNG"
        --mpki-fig-pdf "$OUT_MPKI_PDF"
        --mpki-figure-title "selected trace STLB MPKI vs nopref"
        --stlb-fig-png "$OUT_STLB_PNG"
        --stlb-fig-pdf "$OUT_STLB_PDF"
        --stlb-figure-title "selected trace STLB miss rate vs nopref"
        --dram-pki-fig-png "$OUT_DRAM_PKI_PNG"
        --dram-pki-fig-pdf "$OUT_DRAM_PKI_PDF"
        --dram-pki-figure-title "selected trace DRAM RQ read PKI vs nopref"
    )

    for idx in "${!PREF_CSV_ARRAY[@]}"; do
        csv_path="${PREF_CSV_ARRAY[$idx]}"
        if [ ! -f "$csv_path" ]; then
            echo "[ERROR] pref workload csv not found: $csv_path"
            exit 1
        fi
        PY_ARGS+=(--pref-csv "$csv_path")
        if [ -n "${PREF_LABEL_ARRAY[$idx]:-}" ]; then
            PY_ARGS+=(--pref-label "${PREF_LABEL_ARRAY[$idx]}")
        fi
        if [ -n "${PREF_CONFIG_ARRAY[$idx]:-}" ]; then
            PY_ARGS+=(--pref-config "${PREF_CONFIG_ARRAY[$idx]}")
        fi
    done

    python3 "${PY_ARGS[@]}"
else
    if [ ! -f "$PREF_CSV" ]; then
        echo "[ERROR] pref workload csv not found: $PREF_CSV"
        exit 1
    fi

    python3 "$TOOL_PY" compare \
        --nopref-csv "$NOPREF_CSV" \
        --pref-csv "$PREF_CSV" \
        --out-csv "$OUT_CSV" \
        --fig-png "$OUT_PNG" \
        --fig-pdf "$OUT_PDF" \
        --figure-title "pref vs nopref IPC compare" \
        --mpki-fig-png "$OUT_MPKI_PNG" \
        --mpki-fig-pdf "$OUT_MPKI_PDF" \
        --mpki-figure-title "pref vs nopref STLB MPKI amean" \
        --stlb-fig-png "$OUT_STLB_PNG" \
        --stlb-fig-pdf "$OUT_STLB_PDF" \
        --stlb-figure-title "pref vs nopref STLB miss rate amean" \
        --dram-pki-fig-png "$OUT_DRAM_PKI_PNG" \
        --dram-pki-fig-pdf "$OUT_DRAM_PKI_PDF" \
        --dram-pki-figure-title "pref vs nopref DRAM RQ read PKI amean"
fi

echo "[DONE] compare outputs generated under: $OUT_DIR"
