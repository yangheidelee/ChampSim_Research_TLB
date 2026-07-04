#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
CHAMPSIM_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)

TRACE="${TRACE:-/data0/tzh/champsim_traces/Ligra/ligra_CF.com-lj.ungraph.gcc_6.3.0_O3.drop_184750M.length_250M.champsimtrace.xz}"
TRACE_TAG="${TRACE_TAG:-ligra_CF.com-lj.ungraph.gcc_6.3.0_O3.drop_184750M.length_250M}"
N_WARM="${N_WARM:-1}"
N_SIM="${N_SIM:-1}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"
DO_BUILD="${DO_BUILD:-1}"

NOL1PREF_CONFIG="${SCRIPT_DIR}/1C.nol1pref.ligra-cf-footprint.json"
L1PREF_CONFIG="${SCRIPT_DIR}/1C.l1pref.ligra-cf-footprint.json"
NOL1PREF_BIN="ligra-cf-footprint-nol1pref-1core"
L1PREF_BIN="ligra-cf-footprint-l1pref-1core"

if [ ! -f "$TRACE" ]; then
    echo "[ERROR] Missing trace: $TRACE" >&2
    exit 1
fi

if ! [[ "$N_WARM" =~ ^[0-9]+$ ]] || ! [[ "$N_SIM" =~ ^[0-9]+$ ]]; then
    echo "[ERROR] N_WARM and N_SIM must be integer million-instruction counts." >&2
    exit 1
fi

mkdir -p "${CASE_DIR}/result/nol1pref" "${CASE_DIR}/result/l1pref" "${CASE_DIR}/csv_figure"

is_complete() {
    local log_file="$1"
    shift
    [ -s "$log_file" ] || return 1
    grep -q "^\[ROI Statistics\]" "$log_file" || return 1
    for csv_file in "$@"; do
        [ -s "$csv_file" ] || return 1
    done
}

run_nol1pref() {
    local binary="${CHAMPSIM_ROOT}/bin/${NOL1PREF_BIN}"
    local result_dir="${CASE_DIR}/result/nol1pref"
    local log_file="${result_dir}/${TRACE_TAG}-${NOL1PREF_BIN}.log"
    local l1d_csv="${result_dir}/${TRACE_TAG}.l1d_access.csv"
    local stlb_csv="${result_dir}/${TRACE_TAG}.stlb_full_access.csv"
    local stlb_miss_csv="${result_dir}/${TRACE_TAG}.stlb_full_miss.csv"

    if [ "$SKIP_EXISTING" = "1" ] && is_complete "$log_file" "$l1d_csv" "$stlb_csv" "$stlb_miss_csv"; then
        echo "[SKIP] nol1pref result already complete: ${log_file}"
        return
    fi

    echo "[RUN] nol1pref: L1D access + STLB full access + STLB full miss"
    echo "[CMD] ${binary} --warmup-instructions ${N_WARM}000000 --simulation-instructions ${N_SIM}000000 --hide-heartbeat ${TRACE}"
    DUMP_L1D_VPN=1 DUMP_L1D_VPN_FILE="$l1d_csv" \
    DUMP_STLB_ACCESS=1 DUMP_STLB_ACCESS_FILE="$stlb_csv" \
    DUMP_STLB_MISS_ACCESS=1 DUMP_STLB_MISS_ACCESS_FILE="$stlb_miss_csv" \
    "$binary" \
        --warmup-instructions "${N_WARM}000000" \
        --simulation-instructions "${N_SIM}000000" \
        --hide-heartbeat \
        "$TRACE" \
        > "$log_file"
}

run_l1pref() {
    local binary="${CHAMPSIM_ROOT}/bin/${L1PREF_BIN}"
    local result_dir="${CASE_DIR}/result/l1pref"
    local log_file="${result_dir}/${TRACE_TAG}-${L1PREF_BIN}.log"
    local demand_csv="${result_dir}/${TRACE_TAG}.stlb_demand_access.csv"
    local l1d_prefetch_csv="${result_dir}/${TRACE_TAG}.stlb_l1d_prefetch_access.csv"
    local stlb_miss_csv="${result_dir}/${TRACE_TAG}.stlb_full_miss.csv"
    local dtlb_demand_csv="${result_dir}/${TRACE_TAG}.dtlb_demand_access.csv"
    local dtlb_l1d_prefetch_csv="${result_dir}/${TRACE_TAG}.dtlb_l1d_prefetch_access.csv"

    if [ "$SKIP_EXISTING" = "1" ] && is_complete "$log_file" "$demand_csv" "$l1d_prefetch_csv" "$stlb_miss_csv" "$dtlb_demand_csv" "$dtlb_l1d_prefetch_csv"; then
        echo "[SKIP] l1pref result already complete: ${log_file}"
        return
    fi

    echo "[RUN] l1pref: STLB demand + STLB L1D-prefetch + STLB full miss + DTLB demand + DTLB L1D-prefetch"
    echo "[CMD] ${binary} --warmup-instructions ${N_WARM}000000 --simulation-instructions ${N_SIM}000000 --hide-heartbeat ${TRACE}"
    DUMP_STLB_DEMAND_ACCESS=1 DUMP_STLB_DEMAND_ACCESS_FILE="$demand_csv" \
    DUMP_STLB_L1D_PREFETCH_ACCESS=1 DUMP_STLB_L1D_PREFETCH_ACCESS_FILE="$l1d_prefetch_csv" \
    DUMP_STLB_MISS_ACCESS=1 DUMP_STLB_MISS_ACCESS_FILE="$stlb_miss_csv" \
    DUMP_DTLB_DEMAND_ACCESS=1 DUMP_DTLB_DEMAND_ACCESS_FILE="$dtlb_demand_csv" \
    DUMP_DTLB_L1D_PREFETCH_ACCESS=1 DUMP_DTLB_L1D_PREFETCH_ACCESS_FILE="$dtlb_l1d_prefetch_csv" \
    "$binary" \
        --warmup-instructions "${N_WARM}000000" \
        --simulation-instructions "${N_SIM}000000" \
        --hide-heartbeat \
        "$TRACE" \
        > "$log_file"
}

if [ "$DO_BUILD" = "1" ]; then
    "${SCRIPT_DIR}/build_one.sh" "$NOL1PREF_CONFIG" "$NOL1PREF_BIN"
    "${SCRIPT_DIR}/build_one.sh" "$L1PREF_CONFIG" "$L1PREF_BIN"
fi

run_nol1pref
run_l1pref
"${SCRIPT_DIR}/postprocess.sh"

echo "[DONE] result: ${CASE_DIR}/result"
echo "[DONE] csv_figure: ${CASE_DIR}/csv_figure"
