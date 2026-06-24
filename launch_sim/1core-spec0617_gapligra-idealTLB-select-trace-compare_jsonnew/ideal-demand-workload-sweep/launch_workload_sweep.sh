#!/bin/bash
set -euo pipefail

if [ "$#" -gt 2 ]; then
    echo "Usage: ./launch_workload_sweep.sh [MAX_PARALLEL] [TRACE_FILTER]"
    echo "Example: ./launch_workload_sweep.sh 4"
    echo "Example: ./launch_workload_sweep.sh 4 657.xz_s"
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
find_champsim_root() {
    local dir="$1"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/Makefile" ] && [ -d "$dir/src" ] && [ -d "$dir/launch_sim" ]; then
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
TRACE_DIRS="${TRACE_DIRS:-/data0/tzh/champsim_traces/SPEC06:/data0/tzh/champsim_traces/SPEC17:/data0/tzh/champsim_traces/GAP:/data0/tzh/champsim_traces/Ligra}"
TRACE_FILTER=${2:-${TRACE_FILTER:-${BENCH_FILTER:-}}}
SELECT_TRACE_JSON=${SELECT_TRACE_JSON:-}
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

shopt -s nullglob
IFS=':' read -r -a TRACE_DIR_ARRAY <<< "$TRACE_DIRS"
TRACE_FILES=()
for trace_dir in "${TRACE_DIR_ARRAY[@]}"; do
    if [ ! -d "$trace_dir" ]; then
        echo "[ERROR] Trace directory not found: $trace_dir"
        exit 1
    fi
    if [ -n "$TRACE_FILTER" ]; then
        TRACE_FILES+=("${trace_dir}/${TRACE_FILTER}"*.champsimtrace.xz)
        TRACE_FILES+=("${trace_dir}/${TRACE_FILTER}"*.champsimtrace.gz)
    else
        TRACE_FILES+=("${trace_dir}"/4*.champsimtrace.xz)
        TRACE_FILES+=("${trace_dir}"/4*.champsimtrace.gz)
        TRACE_FILES+=("${trace_dir}"/6*.champsimtrace.xz)
        TRACE_FILES+=("${trace_dir}"/6*.champsimtrace.gz)
        TRACE_FILES+=("${trace_dir}"/gap.*.champsimtrace.xz)
        TRACE_FILES+=("${trace_dir}"/gap.*.champsimtrace.gz)
        TRACE_FILES+=("${trace_dir}"/ligra*.champsimtrace.xz)
        TRACE_FILES+=("${trace_dir}"/ligra*.champsimtrace.gz)
    fi
done
shopt -u nullglob

if [ -n "$SELECT_TRACE_JSON" ] && [[ "${SELECT_TRACE_JSON^^}" != "ALL" ]] && [[ "${SELECT_TRACE_JSON^^}" != "FULL" ]] && [[ "${SELECT_TRACE_JSON^^}" != "NONE" ]]; then
    if [ ! -f "$SELECT_TRACE_JSON" ]; then
        echo "[ERROR] SELECT_TRACE_JSON not found: $SELECT_TRACE_JSON"
        exit 1
    fi
    mapfile -t TRACE_FILES < <(python3 - "$SELECT_TRACE_JSON" "${TRACE_FILES[@]}" <<'PY'
import json
import pathlib
import sys

select_json = pathlib.Path(sys.argv[1])
selected = set(json.loads(select_json.read_text()).get("selected_trace_tags", []))

def trace_tag(path_text: str) -> str:
    name = pathlib.Path(path_text).name
    for suffix in [".xz", ".gz"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    if name.endswith(".champsimtrace"):
        name = name[: -len(".champsimtrace")]
    return name

for path_text in sys.argv[2:]:
    if trace_tag(path_text) in selected:
        print(path_text)
PY
)
fi

if [ "${#TRACE_FILES[@]}" -eq 0 ]; then
    echo "[ERROR] No SPEC06/SPEC17/GAP/Ligra trace files found in: $TRACE_DIRS"
    if [ -n "$SELECT_TRACE_JSON" ]; then
        echo "[ERROR] SELECT_TRACE_JSON filter: $SELECT_TRACE_JSON"
    fi
    exit 1
fi

if [ "$DO_BUILD" = "1" ]; then
    echo "[BUILD] pref config"
    echo "[CMD] ${BUILD_SCRIPT}"
    "${BUILD_SCRIPT}"
fi

# shellcheck disable=SC1090
source "${BUILD_INFO_FILE}"

RUN_N_WARM=${N_WARM:-${DEFAULT_N_WARM}}
RUN_N_SIM=${N_SIM:-${DEFAULT_N_SIM}}
if [ -n "${DEFAULT_OPTION:-}" ]; then
    read -r -a DEFAULT_OPTIONS <<< "$DEFAULT_OPTION"
else
    DEFAULT_OPTIONS=()
fi

echo "[INFO] parallel simulations: ${MAX_PARALLEL}"
echo "[INFO] compare tag=${COMPARE_TAG} config tag=${CONFIG_TAG} skip_existing=${SKIP_EXISTING}"
echo "[INFO] trace dirs=${TRACE_DIRS} filter=${TRACE_FILTER:-<none>}"
echo "[INFO] selected trace json=${SELECT_TRACE_JSON:-<none>} trace_count=${#TRACE_FILES[@]}"

running_jobs=0
for trace_path in "${TRACE_FILES[@]}"; do
    trace_name=$(basename "$trace_path")
    echo "[RUN] trace=${trace_name}"
    echo "[CMD] ${RUN_SCRIPT} ${BINARY_NAME} ${RUN_N_WARM} ${RUN_N_SIM} ${trace_path} ${DEFAULT_OPTIONS[*]-}"
    COMPARE_TAG="$COMPARE_TAG" CONFIG_TAG="$CONFIG_TAG" SKIP_EXISTING="$SKIP_EXISTING" \
        "${RUN_SCRIPT}" "${BINARY_NAME}" "${RUN_N_WARM}" "${RUN_N_SIM}" "${trace_path}" "${DEFAULT_OPTIONS[@]}" &

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
