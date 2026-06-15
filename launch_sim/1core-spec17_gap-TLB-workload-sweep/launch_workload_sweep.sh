#!/bin/bash
set -euo pipefail

if [ "$#" -gt 1 ]; then
    echo "Usage: ./launch_workload_sweep.sh [MAX_PARALLEL]"
    echo "Example: ./launch_workload_sweep.sh 4"
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
CHAMPSIM_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
EXP_TAG=$(basename "${SCRIPT_DIR}")

BUILD_SCRIPT="${SCRIPT_DIR}/build_champsim.sh"
RUN_SCRIPT="${SCRIPT_DIR}/run_1core.sh"
BUILD_INFO_FILE="${SCRIPT_DIR}/build_info.env"
TRACE_DIR=${CHAMPSIM_TRACE_DIR:-"${CHAMPSIM_ROOT}/traces"}

MAX_PARALLEL=${1:-${MAX_PARALLEL:-1}}
if ! [[ "$MAX_PARALLEL" =~ ^[0-9]+$ ]] || [ "$MAX_PARALLEL" -lt 1 ]; then
    echo "[ERROR] MAX_PARALLEL must be a positive integer, got: $MAX_PARALLEL"
    exit 1
fi

if [ ! -x "$BUILD_SCRIPT" ]; then
    echo "[ERROR] Cannot execute build script: $BUILD_SCRIPT"
    exit 1
fi

if [ ! -x "$RUN_SCRIPT" ]; then
    echo "[ERROR] Cannot execute run script: $RUN_SCRIPT"
    exit 1
fi

if [ ! -d "$TRACE_DIR" ]; then
    echo "[ERROR] Trace directory not found: $TRACE_DIR"
    exit 1
fi

TRACE_FILES=("${TRACE_DIR}"/6*.champsimtrace.xz)
if [ "${TRACE_FILES[0]}" = "${TRACE_DIR}/6*.champsimtrace.xz" ]; then
    echo "[ERROR] No spec17 6xx trace files found in: $TRACE_DIR"
    echo "[HINT] Set CHAMPSIM_TRACE_DIR=/path/to/SPEC17 if traces are not under ${CHAMPSIM_ROOT}/traces"
    exit 1
fi

echo "[BUILD] no L2 prefetcher base"
echo "[CMD] ${BUILD_SCRIPT}"
"${BUILD_SCRIPT}"

# shellcheck disable=SC1090
source "${BUILD_INFO_FILE}"

echo "[INFO] parallel simulations: ${MAX_PARALLEL}"

running_jobs=0
for trace_path in "${TRACE_FILES[@]}"; do
    trace_name=$(basename "$trace_path")
    echo "[RUN] trace=${trace_name}"
    echo "[CMD] ${RUN_SCRIPT} ${BINARY_NAME} ${DEFAULT_N_WARM} ${DEFAULT_N_SIM} ${trace_path} ${DEFAULT_OPTION}"
    "${RUN_SCRIPT}" "${BINARY_NAME}" "${DEFAULT_N_WARM}" "${DEFAULT_N_SIM}" "${trace_path}" ${DEFAULT_OPTION} &

    running_jobs=$((running_jobs + 1))
    if [ "$running_jobs" -ge "$MAX_PARALLEL" ]; then
        wait -n
        running_jobs=$((running_jobs - 1))
    fi
done

while [ "$running_jobs" -gt 0 ]; do
    wait -n
    running_jobs=$((running_jobs - 1))
done

echo "[DONE] Workload sweep completed for folder tag: ${EXP_TAG}"
