#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
CHAMPSIM_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)

TRACE="${TRACE:-/data0/tzh/champsim_traces/SPEC17/605.mcf_s-1536B.champsimtrace.xz}"
TRACE_TAG="${TRACE_TAG:-605.mcf_s-1536B}"
N_WARM="${N_WARM:-50}"
N_SIM="${N_SIM:-100}"
MAX_EVENTS="${MAX_EVENTS:-0}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"
BINARY_NAME="605.mcf_s-1536B-demand-tlb-pattern-1core"
BINARY="${CHAMPSIM_ROOT}/bin/${BINARY_NAME}"
RESULT_DIR="${CASE_DIR}/result"
PATTERN_DIR="${RESULT_DIR}/dtlb_access"
LOG_DIR="${RESULT_DIR}/simulation_log"
LOG_FILE="${LOG_DIR}/${TRACE_TAG}-${BINARY_NAME}.log"

for value in "$N_WARM" "$N_SIM" "$MAX_EVENTS"; do
    if ! [[ "$value" =~ ^[0-9]+$ ]]; then
        echo "[ERROR] N_WARM, N_SIM, and MAX_EVENTS must be non-negative integers." >&2
        exit 1
    fi
done

if [ ! -f "$TRACE" ]; then
    echo "[ERROR] Missing trace: $TRACE" >&2
    exit 1
fi
if [ ! -x "$BINARY" ]; then
    echo "[ERROR] Missing binary: $BINARY" >&2
    echo "[HINT] Run scripts/run_all.sh build first." >&2
    exit 1
fi

mkdir -p "$LOG_DIR" "$PATTERN_DIR"

is_complete() {
    [ -s "$LOG_FILE" ] || return 1
    [ -s "${PATTERN_DIR}/demand_tlb_pattern_core_0.csv" ] || return 1
    [ -s "${PATTERN_DIR}/metadata.json" ] || return 1
    [ -s "${PATTERN_DIR}/logger_summary.txt" ] || return 1
    grep -q "^Simulation complete CPU 0" "$LOG_FILE" || return 1
    grep -q "^\[ROI Statistics\]" "$LOG_FILE" || return 1
}

if [ "$SKIP_EXISTING" = "1" ] && is_complete; then
    echo "[SKIP] Complete pattern result already exists: $LOG_FILE"
    exit 0
fi

max_event_args=()
if [ "$MAX_EVENTS" -ne 0 ]; then
    max_event_args=(--demand-tlb-pattern-max-events "$MAX_EVENTS")
fi

echo "[RUN] trace: $TRACE"
echo "[RUN] warmup: ${N_WARM}M, ROI: ${N_SIM}M, max events/core: ${MAX_EVENTS}"
"$BINARY" \
    --warmup-instructions "${N_WARM}000000" \
    --simulation-instructions "${N_SIM}000000" \
    --hide-heartbeat \
    --demand-tlb-pattern \
    --demand-tlb-pattern-output "$PATTERN_DIR" \
    "${max_event_args[@]}" \
    "$TRACE" \
    > "$LOG_FILE"

echo "[DONE] simulation log: $LOG_FILE"
echo "[DONE] pattern data: $PATTERN_DIR"
