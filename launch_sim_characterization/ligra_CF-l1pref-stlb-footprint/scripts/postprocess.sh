#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)

TRACE_TAG="${TRACE_TAG:-ligra_CF.com-lj.ungraph.gcc_6.3.0_O3.drop_184750M.length_250M}"
L1D_WINDOW="${L1D_WINDOW:-10000}"
STLB_WINDOW="${STLB_WINDOW:-100}"
STLB_FULL_WINDOW="${STLB_FULL_WINDOW:-500}"
STLB_MISS_WINDOW="${STLB_MISS_WINDOW:-500}"
STLB_L1D_PREFETCH_WINDOW="${STLB_L1D_PREFETCH_WINDOW:-500}"
DTLB_WINDOW="${DTLB_WINDOW:-10000}"
DELTA_CLIP="${DELTA_CLIP:-64}"

run_l1d_plot() {
    local input="$1"
    local outdir="$2"
    local label="$3"

    if [ ! -s "$input" ]; then
        echo "[ERROR] Missing or empty input for ${label}: ${input}" >&2
        exit 1
    fi

    echo "[POST] ${label}"
    python3 "${SCRIPT_DIR}/plot_l1d_vpn_patterns.py" \
        --input "$input" \
        --outdir "$outdir" \
        --window "$L1D_WINDOW" \
        --delta-clip "$DELTA_CLIP"
}

run_stlb_plot() {
    local input="$1"
    local outdir="$2"
    local label="$3"
    local window="${4:-$STLB_WINDOW}"
    local stream_label="${5:-STLB}"

    if [ ! -s "$input" ]; then
        echo "[ERROR] Missing or empty input for ${label}: ${input}" >&2
        exit 1
    fi

    echo "[POST] ${label}"
    python3 "${SCRIPT_DIR}/plot_stlb_access_patterns.py" \
        --input "$input" \
        --outdir "$outdir" \
        --window "$window" \
        --delta-clip "$DELTA_CLIP" \
        --stream-label "$stream_label"
}

run_l1d_plot \
    "${CASE_DIR}/result/nol1pref/${TRACE_TAG}.l1d_access.csv" \
    "${CASE_DIR}/csv_figure/01_nol1pref_l1d_access" \
    "nol1pref L1D demand access"

run_stlb_plot \
    "${CASE_DIR}/result/nol1pref/${TRACE_TAG}.stlb_full_access.csv" \
    "${CASE_DIR}/csv_figure/02_nol1pref_stlb_full_access" \
    "nol1pref STLB full access" \
    "$STLB_FULL_WINDOW"

run_stlb_plot \
    "${CASE_DIR}/result/nol1pref/${TRACE_TAG}.stlb_full_miss.csv" \
    "${CASE_DIR}/csv_figure/03_nol1pref_stlb_full_miss" \
    "nol1pref STLB full miss" \
    "$STLB_MISS_WINDOW"

run_stlb_plot \
    "${CASE_DIR}/result/l1pref/${TRACE_TAG}.stlb_demand_access.csv" \
    "${CASE_DIR}/csv_figure/04_l1pref_stlb_demand_access" \
    "l1pref STLB demand access"

run_stlb_plot \
    "${CASE_DIR}/result/l1pref/${TRACE_TAG}.stlb_l1d_prefetch_access.csv" \
    "${CASE_DIR}/csv_figure/05_l1pref_stlb_l1d_prefetch_access" \
    "l1pref STLB L1D-prefetch access" \
    "$STLB_L1D_PREFETCH_WINDOW"

run_stlb_plot \
    "${CASE_DIR}/result/l1pref/${TRACE_TAG}.stlb_full_miss.csv" \
    "${CASE_DIR}/csv_figure/06_l1pref_stlb_full_miss" \
    "l1pref STLB full miss" \
    "$STLB_MISS_WINDOW"

run_stlb_plot \
    "${CASE_DIR}/result/l1pref/${TRACE_TAG}.dtlb_demand_access.csv" \
    "${CASE_DIR}/csv_figure/07_l1pref_dtlb_demand_access" \
    "l1pref DTLB demand access" \
    "$DTLB_WINDOW" \
    "DTLB"

run_stlb_plot \
    "${CASE_DIR}/result/l1pref/${TRACE_TAG}.dtlb_l1d_prefetch_access.csv" \
    "${CASE_DIR}/csv_figure/08_l1pref_dtlb_l1d_prefetch_access" \
    "l1pref DTLB L1D-prefetch access" \
    "$DTLB_WINDOW" \
    "DTLB"

echo "[DONE] Postprocess outputs: ${CASE_DIR}/csv_figure"
