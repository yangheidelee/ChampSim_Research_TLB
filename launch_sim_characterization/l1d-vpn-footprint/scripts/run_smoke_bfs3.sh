#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
CHAMPSIM_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)

BINARY="${CHAMPSIM_ROOT}/bin/tlb-pref-1core"
TRACE="${TRACE:-/data2/zcq/gap_dpc/bfs-3.trace.gz}"
N_WARM="${N_WARM:-1}"
N_SIM="${N_SIM:-1}"
RESULT_DIR="${CASE_DIR}/result"
LOG_FILE="${RESULT_DIR}/bfs-3.trace-tlb-pref-1core-vpn-footprint.log"
VPN_CSV="${RESULT_DIR}/bfs-3.trace.l1d_vpn_trace.csv"

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

echo "[CMD] DUMP_L1D_VPN=1 DUMP_L1D_VPN_FILE=${VPN_CSV} ${BINARY} --warmup-instructions ${N_WARM}000000 --simulation-instructions ${N_SIM}000000 --hide-heartbeat ${TRACE}"
DUMP_L1D_VPN=1 DUMP_L1D_VPN_FILE="$VPN_CSV" "$BINARY" \
    --warmup-instructions "${N_WARM}000000" \
    --simulation-instructions "${N_SIM}000000" \
    --hide-heartbeat \
    "$TRACE" \
    > "$LOG_FILE"

if ! grep -q "^\[ROI Statistics\]" "$LOG_FILE"; then
    echo "[ERROR] Simulation log has no [ROI Statistics]: $LOG_FILE" >&2
    exit 1
fi
if [ ! -s "$VPN_CSV" ]; then
    echo "[ERROR] VPN trace CSV was not produced: $VPN_CSV" >&2
    exit 1
fi

echo "[INFO] Log: $LOG_FILE"
echo "[INFO] VPN CSV: $VPN_CSV"
