#!/bin/bash
set -euo pipefail

if [ "$#" -gt 2 ]; then
    echo "Usage: ./launch_workload_sweep.sh [MAX_PARALLEL] [BENCH_FILTER]"
    echo "Example: ./launch_workload_sweep.sh 4"
    echo "Example: ./launch_workload_sweep.sh 4 657.xz_s"
    exit 1
fi

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
CONFIG_TAG=$(basename "$SCRIPT_DIR")

BUILD_SCRIPT="${SCRIPT_DIR}/build_champsim.sh"
RUN_SCRIPT="${SCRIPT_DIR}/run_1core.sh"
BUILD_INFO_FILE="${SCRIPT_DIR}/build_info.env"
TRACE_DIR="${TRACE_DIR:-/data0/tzh/champsim_traces/SPEC17}"
BENCH_FILTER=${2:-${BENCH_FILTER:-}}
SKIP_EXISTING=${SKIP_EXISTING:-1}
DO_BUILD=${DO_BUILD:-1}
N_WARM=${N_WARM:-}
N_SIM=${N_SIM:-}

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

if [ -n "$BENCH_FILTER" ]; then
    TRACE_GLOB="${TRACE_DIR}/${BENCH_FILTER}-*.champsimtrace.xz"
else
    TRACE_GLOB="${TRACE_DIR}/6*.champsimtrace.xz"
fi

TRACE_FILES=($TRACE_GLOB)
shopt -s nullglob
TRACE_FILES=($TRACE_GLOB)
shopt -u nullglob
if [ "${#TRACE_FILES[@]}" -eq 0 ]; then
    echo "[ERROR] No spec17 6xx trace files found in: $TRACE_DIR"
    exit 1
fi

if [ "$DO_BUILD" = "1" ]; then
    echo "[BUILD] fixed sms degree=4"
    echo "[CMD] ${BUILD_SCRIPT}"
    "${BUILD_SCRIPT}"
fi

# shellcheck disable=SC1090
source "${BUILD_INFO_FILE}"

RUN_N_WARM=${N_WARM:-${DEFAULT_N_WARM}}
RUN_N_SIM=${N_SIM:-${DEFAULT_N_SIM}}

echo "[INFO] parallel simulations: ${MAX_PARALLEL}"
echo "[INFO] compare tag=${COMPARE_TAG} config tag=${CONFIG_TAG} skip_existing=${SKIP_EXISTING}"

running_jobs=0
for trace_path in "${TRACE_FILES[@]}"; do
    trace_name=$(basename "$trace_path")
    echo "[RUN] trace=${trace_name}"
    echo "[CMD] ${RUN_SCRIPT} ${BINARY_NAME} ${RUN_N_WARM} ${RUN_N_SIM} ${trace_name} ${DEFAULT_OPTION}"
    TRACE_DIR="$TRACE_DIR" COMPARE_TAG="$COMPARE_TAG" CONFIG_TAG="$CONFIG_TAG" SKIP_EXISTING="$SKIP_EXISTING" \
        "${RUN_SCRIPT}" "${BINARY_NAME}" "${RUN_N_WARM}" "${RUN_N_SIM}" "${trace_name}" "${DEFAULT_OPTION}" &

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

echo "[DONE] Workload sweep completed for config: ${CONFIG_TAG}"
