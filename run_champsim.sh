#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 4 ]; then
    echo "Illegal number of parameters"
    echo "Usage: ./run_champsim.sh [BINARY] [N_WARM_MILLION] [N_SIM_MILLION] [TRACE] [OPTION...]"
    exit 1
fi

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

BINARY=$1
N_WARM=$2
N_SIM=$3
TRACE=$4
shift 4
OPTIONS=("$@")

if [[ "${BINARY}" != /* ]]; then
    if [ -x "${ROOT_DIR}/bin/${BINARY}" ]; then
        BINARY="${ROOT_DIR}/bin/${BINARY}"
    else
        BINARY="${ROOT_DIR}/${BINARY}"
    fi
fi

if [ ! -x "${BINARY}" ]; then
    echo "[ERROR] Cannot find executable ChampSim binary: ${BINARY}"
    exit 1
fi

if ! [[ "${N_WARM}" =~ ^[0-9]+$ ]]; then
    echo "[ERROR] Number of warmup instructions in millions is NOT a number: ${N_WARM}" >&2
    exit 1
fi

if ! [[ "${N_SIM}" =~ ^[0-9]+$ ]]; then
    echo "[ERROR] Number of simulation instructions in millions is NOT a number: ${N_SIM}" >&2
    exit 1
fi

if [ ! -f "${TRACE}" ]; then
    echo "[ERROR] Cannot find trace file: ${TRACE}"
    exit 1
fi

BINARY_BASE=$(basename "${BINARY}")
TRACE_BASE=$(basename "${TRACE}")
TRACE_BASE=${TRACE_BASE%.xz}
TRACE_BASE=${TRACE_BASE%.gz}
TRACE_BASE=${TRACE_BASE%.champsimtrace}

RESULT_DIR="${ROOT_DIR}/results/${BINARY_BASE}-${N_SIM}M"
RESULT_FILE="${RESULT_DIR}/${TRACE_BASE}.log"

mkdir -p "${RESULT_DIR}"

echo "Running ChampSim..."
echo "Binary: ${BINARY}"
echo "Warmup: ${N_WARM}M"
echo "Simulation: ${N_SIM}M"
echo "Trace: ${TRACE}"
echo "Output: ${RESULT_FILE}"
echo

"${BINARY}" \
    --warmup-instructions "${N_WARM}000000" \
    --simulation-instructions "${N_SIM}000000" \
    "${OPTIONS[@]}" \
    "${TRACE}" \
    > "${RESULT_FILE}"

echo "Finished: ${RESULT_FILE}"
