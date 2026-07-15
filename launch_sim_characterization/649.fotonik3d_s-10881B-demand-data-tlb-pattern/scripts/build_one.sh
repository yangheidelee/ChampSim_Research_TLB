#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: ./build_one.sh CONFIG_JSON BINARY_NAME" >&2
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CHAMPSIM_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)
CONFIG_FILE="$1"
BINARY_NAME="$2"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "[ERROR] Missing config: $CONFIG_FILE" >&2
    exit 1
fi

cd "$CHAMPSIM_ROOT"
echo "[BUILD] $BINARY_NAME"
echo "[CMD] ./config.sh ${CONFIG_FILE}"
./config.sh "$CONFIG_FILE"

echo "[CMD] make -j ${MAKE_JOBS:-$(nproc)}"
make -j "${MAKE_JOBS:-$(nproc)}"

if [ ! -x "${CHAMPSIM_ROOT}/bin/${BINARY_NAME}" ]; then
    echo "[ERROR] Build did not produce bin/${BINARY_NAME}" >&2
    exit 1
fi

echo "[INFO] Binary: ${CHAMPSIM_ROOT}/bin/${BINARY_NAME}"
