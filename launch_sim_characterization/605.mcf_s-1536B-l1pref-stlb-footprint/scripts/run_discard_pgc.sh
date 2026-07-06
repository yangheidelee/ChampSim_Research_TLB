#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
CHAMPSIM_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)

TRACE="${TRACE:-/data0/tzh/champsim_traces/SPEC17/605.mcf_s-1536B.champsimtrace.xz}"
TRACE_TAG="${TRACE_TAG:-605.mcf_s-1536B}"
N_WARM="${N_WARM:-20}"
N_SIM="${N_SIM:-50}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"
DO_BUILD="${DO_BUILD:-1}"

CONFIG="${SCRIPT_DIR}/1C.l1pref-discard-pgc.mcf-footprint.json"
BINARY_NAME="mcf-footprint-discard-pgc-1core"

is_complete() {
    local log_file="$1"
    [ -s "$log_file" ] || return 1
    grep -q "^\[ROI Statistics\]" "$log_file" || return 1
    grep -q "^BERTI CROSS_PAGE" "$log_file" || return 1
}

mkdir -p "${CASE_DIR}/result/discard_pgc" "${CASE_DIR}/csv_figure/pgc_compare"

if [ "$DO_BUILD" = "1" ]; then
    "${SCRIPT_DIR}/build_one.sh" "$CONFIG" "$BINARY_NAME"
fi

binary="${CHAMPSIM_ROOT}/bin/${BINARY_NAME}"
log_file="${CASE_DIR}/result/discard_pgc/${TRACE_TAG}-${BINARY_NAME}.log"

if [ "$SKIP_EXISTING" = "1" ] && is_complete "$log_file"; then
    echo "[SKIP] Discard PGC result already complete: ${log_file}"
else
    echo "[RUN] Discard PGC: vberti_nocross, no cross-page prefetch"
    echo "[CMD] ${binary} --warmup-instructions ${N_WARM}000000 --simulation-instructions ${N_SIM}000000 --hide-heartbeat ${TRACE}"
    "$binary" \
        --warmup-instructions "${N_WARM}000000" \
        --simulation-instructions "${N_SIM}000000" \
        --hide-heartbeat \
        "$TRACE" \
        > "$log_file"
fi

"${SCRIPT_DIR}/compare_pgc.py"

echo "[DONE] Discard PGC log: ${log_file}"
echo "[DONE] Compare table: ${CASE_DIR}/csv_figure/pgc_compare"
