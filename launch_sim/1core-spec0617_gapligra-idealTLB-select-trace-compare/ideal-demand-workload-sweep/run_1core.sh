#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 4 ]; then
    echo "Illegal number of parameters"
    echo "Usage: ./run_1core.sh [BINARY] [N_WARM_MILLION] [N_SIM_MILLION] [TRACE] [OPTION...]"
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
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

COMPARE_TAG=${COMPARE_TAG:-$(basename "$(dirname "$SCRIPT_DIR")")}
CONFIG_TAG=${CONFIG_TAG:-$(basename "$SCRIPT_DIR")}
TRACE_DIR="${TRACE_DIR:-/data0/tzh/champsim_traces/SPEC17}"
RESULT_DIR="${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${CONFIG_TAG}"
BINARY=$1
N_WARM=$2
N_SIM=$3
TRACE=$4
shift 4
OPTIONS=("$@")
SKIP_EXISTING=${SKIP_EXISTING:-0}

if [[ "$BINARY" != /* ]]; then
    BINARY="${CHAMPSIM_ROOT}/bin/${BINARY}"
fi
if [ ! -x "$BINARY" ]; then
    echo "[ERROR] Cannot find a ChampSim binary: $BINARY"
    exit 1
fi
if ! [[ "$N_WARM" =~ ^[0-9]+$ ]]; then
    echo "[ERROR]: Number of warmup instructions in millions is NOT a number: $N_WARM" >&2
    exit 1
fi
if ! [[ "$N_SIM" =~ ^[0-9]+$ ]]; then
    echo "[ERROR]: Number of simulation instructions in millions is NOT a number: $N_SIM" >&2
    exit 1
fi

if [[ "$TRACE" == /* ]]; then
    TRACE_PATH="$TRACE"
else
    TRACE_PATH="${TRACE_DIR}/${TRACE}"
fi
if [ ! -f "$TRACE_PATH" ]; then
    echo "[ERROR] Cannot find a trace file: $TRACE_PATH"
    exit 1
fi

mkdir -p "$RESULT_DIR"
if [ "${#OPTIONS[@]}" -gt 0 ]; then
    OPTION_TAG=$(printf "%s_" "${OPTIONS[@]}")
    OPTION_TAG=${OPTION_TAG%_}
    OPTION_TAG=$(echo "$OPTION_TAG" | tr ' ' '_' | tr -cd '[:alnum:]_.=-')
else
    OPTION_TAG="no_option"
fi

TRACE_TAG=$(basename "$TRACE_PATH")
TRACE_TAG=${TRACE_TAG%.xz}
TRACE_TAG=${TRACE_TAG%.gz}
TRACE_TAG=${TRACE_TAG%.champsimtrace}
BINARY_TAG=$(basename "$BINARY")
OUTFILE="${RESULT_DIR}/${TRACE_TAG}-${BINARY_TAG}-${OPTION_TAG}.log"

if [ -f "$OUTFILE" ] && [ "$SKIP_EXISTING" = "1" ]; then
    echo "[SKIP] Existing output: $OUTFILE"
    exit 0
fi

echo "[CMD] $BINARY --warmup-instructions ${N_WARM}000000 --simulation-instructions ${N_SIM}000000 ${OPTIONS[*]-} $TRACE_PATH"
"$BINARY" \
    --warmup-instructions "${N_WARM}000000" \
    --simulation-instructions "${N_SIM}000000" \
    "${OPTIONS[@]}" \
    "$TRACE_PATH" \
    > "$OUTFILE"

echo "[INFO] Simulation output: $OUTFILE"
