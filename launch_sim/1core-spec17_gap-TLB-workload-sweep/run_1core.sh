#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 4 ]; then
    echo "Illegal number of parameters"
    echo "Usage: ./run_1core.sh [BINARY] [N_WARM_MILLION] [N_SIM_MILLION] [TRACE] [OPTION...]"
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CHAMPSIM_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
EXP_TAG=$(basename "${SCRIPT_DIR}")

TRACE_DIR="${CHAMPSIM_ROOT}/traces"
RESULT_DIR="${CHAMPSIM_ROOT}/results/${EXP_TAG}"
BINARY=$1
N_WARM=$2
N_SIM=$3
TRACE=$4
shift 4
OPTIONS=("$@")

if [[ "${BINARY}" != /* ]]; then
    BINARY="${CHAMPSIM_ROOT}/bin/${BINARY}"
fi

if [ ! -x "${BINARY}" ]; then
    echo "[ERROR] Cannot find a ChampSim binary: ${BINARY}"
    exit 1
fi

if ! [[ "${N_WARM}" =~ ^[0-9]+$ ]]; then
    echo "[ERROR]: Number of warmup instructions in millions is NOT a number: ${N_WARM}" >&2
    exit 1
fi

if ! [[ "${N_SIM}" =~ ^[0-9]+$ ]]; then
    echo "[ERROR]: Number of simulation instructions in millions is NOT a number: ${N_SIM}" >&2
    exit 1
fi

if [[ "${TRACE}" == /* ]]; then
    TRACE_PATH="${TRACE}"
else
    TRACE_PATH="${TRACE_DIR}/${TRACE}"
fi

if [ ! -f "${TRACE_PATH}" ]; then
    echo "[ERROR] Cannot find a trace file: ${TRACE_PATH}"
    exit 1
fi

mkdir -p "${RESULT_DIR}"

if [ "${#OPTIONS[@]}" -gt 0 ]; then
    OPTION_TAG=$(printf "%s_" "${OPTIONS[@]}")
    OPTION_TAG=${OPTION_TAG%_}
    OPTION_TAG=$(echo "${OPTION_TAG}" | tr ' ' '_' | tr -cd '[:alnum:]_.=-')
else
    OPTION_TAG="no_option"
fi

TRACE_TAG=$(basename "${TRACE_PATH}")
TRACE_TAG=${TRACE_TAG%.xz}
TRACE_TAG=${TRACE_TAG%.gz}
TRACE_TAG=${TRACE_TAG%.champsimtrace}
BINARY_TAG=$(basename "${BINARY}")

OUTFILE="${RESULT_DIR}/${TRACE_TAG}-${BINARY_TAG}-${OPTION_TAG}.log"

echo "[CMD] ${BINARY} --warmup-instructions ${N_WARM}000000 --simulation-instructions ${N_SIM}000000 ${OPTIONS[*]-} ${TRACE_PATH}"
"${BINARY}" \
    --warmup-instructions "${N_WARM}000000" \
    --simulation-instructions "${N_SIM}000000" \
    "${OPTIONS[@]}" \
    "${TRACE_PATH}" \
    > "${OUTFILE}"

echo "[INFO] Simulation output: ${OUTFILE}"
