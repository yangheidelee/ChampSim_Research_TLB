#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CHAMPSIM_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)
CONFIG_FILE="${SCRIPT_DIR}/1C.fullBW.stlb.stats.json"

cd "$CHAMPSIM_ROOT"
echo "[CMD] ./config.sh ${CONFIG_FILE}"
./config.sh "$CONFIG_FILE"

echo "[CMD] make -j ${MAKE_JOBS:-$(nproc)}"
make -j "${MAKE_JOBS:-$(nproc)}"

if [ ! -x "${CHAMPSIM_ROOT}/bin/tlb-pref-1core" ]; then
    echo "[ERROR] Build did not produce bin/tlb-pref-1core" >&2
    exit 1
fi

echo "[INFO] Binary: ${CHAMPSIM_ROOT}/bin/tlb-pref-1core"
