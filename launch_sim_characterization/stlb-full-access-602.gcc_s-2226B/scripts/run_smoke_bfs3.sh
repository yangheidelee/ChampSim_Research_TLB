#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
CHAMPSIM_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)

BINARY="${CHAMPSIM_ROOT}/bin/tlb-pref-1core"
TRACE="${TRACE:-/data0/tzh/champsim_traces/SPEC17/602.gcc_s-2226B.champsimtrace.xz}"
N_WARM="${N_WARM:-1}"
N_SIM="${N_SIM:-1}"
RESULT_DIR="${CASE_DIR}/result"
TRACE_TAG="602.gcc_s-2226B"
LOG_FILE="${RESULT_DIR}/${TRACE_TAG}-tlb-pref-1core-stlb-access.log"
STLB_CSV="${RESULT_DIR}/${TRACE_TAG}.stlb_access_trace.csv"

if [ ! -x "$BINARY" ]; then
    echo "[ERROR] Missing binary: $BINARY" >&2
    echo "[HINT] Run ${SCRIPT_DIR}/build.sh first, or run run_all_smoke.sh." >&2
    exit 1
fi
if [ ! -f "$TRACE" ]; then
    echo "[ERROR] Missing trace: $TRACE" >&2
    exit 1
fi

mkdir -p "$RESULT_DIR"

echo "[CMD] DUMP_STLB_ACCESS=1 DUMP_STLB_ACCESS_FILE=${STLB_CSV} ${BINARY} --warmup-instructions ${N_WARM}000000 --simulation-instructions ${N_SIM}000000 --hide-heartbeat ${TRACE}"
DUMP_STLB_ACCESS=1 DUMP_STLB_ACCESS_FILE="$STLB_CSV" "$BINARY" \
    --warmup-instructions "${N_WARM}000000" \
    --simulation-instructions "${N_SIM}000000" \
    --hide-heartbeat \
    "$TRACE" \
    > "$LOG_FILE"

if ! grep -q "^\[ROI Statistics\]" "$LOG_FILE"; then
    echo "[ERROR] Simulation log has no [ROI Statistics]: $LOG_FILE" >&2
    exit 1
fi
if [ ! -s "$STLB_CSV" ]; then
    echo "[ERROR] STLB access trace CSV was not produced: $STLB_CSV" >&2
    exit 1
fi

echo "[INFO] Log: $LOG_FILE"
echo "[INFO] STLB CSV: $STLB_CSV"
