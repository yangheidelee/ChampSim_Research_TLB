#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 7 ]; then
    echo "Usage: ./script/build_one.sh CONFIG_NAME BASE_JSON BINARY_NAME L1I_PREF L1D_PREF L2C_PREF LLC_PREF" >&2
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

find_champsim_root() {
    local dir="$1"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/Makefile" ] && [ -d "$dir/bin" ] && [ -d "$dir/src" ]; then
            echo "$dir"
            return 0
        fi
        dir=$(dirname "$dir")
    done
    return 1
}

CHAMPSIM_ROOT=$(find_champsim_root "$SCRIPT_DIR") || {
    echo "[ERROR] Cannot locate ChampSim root from $SCRIPT_DIR" >&2
    exit 1
}

CONFIG_NAME="$1"
BASE_JSON="$2"
BINARY_NAME="$3"
L1I_PREF="$4"
L1D_PREF="$5"
L2C_PREF="$6"
LLC_PREF="$7"
LLC_REPL="${LLC_REPL:-drrip}"
NUM_CORE="${NUM_CORE:-1}"
MAKE_JOBS="${MAKE_JOBS:-}"
STLB_PREF="${STLB_PREF:-}"
STLB_PQ_SIZE="${STLB_PQ_SIZE:-16}"
PTW_PQ_SIZE="${PTW_PQ_SIZE:-16}"

if [[ "$BASE_JSON" != /* ]]; then
    BASE_JSON="${SCRIPT_DIR}/${BASE_JSON}"
fi
if [ ! -f "$BASE_JSON" ]; then
    echo "[ERROR] Missing base json: $BASE_JSON" >&2
    exit 1
fi

for pref in "$L1I_PREF" "$L1D_PREF" "$L2C_PREF" "$LLC_PREF"; do
    if [ ! -d "${CHAMPSIM_ROOT}/prefetcher/${pref}" ]; then
        echo "[ERROR] Missing prefetcher: ${pref}" >&2
        exit 1
    fi
done
if [ -n "$STLB_PREF" ] && [ ! -d "${CHAMPSIM_ROOT}/prefetcher_stlb/${STLB_PREF}" ]; then
    echo "[ERROR] Missing STLB prefetcher: ${CHAMPSIM_ROOT}/prefetcher_stlb/${STLB_PREF}" >&2
    exit 1
fi
if [ ! -d "${CHAMPSIM_ROOT}/replacement/${LLC_REPL}" ]; then
    echo "[ERROR] Missing replacement policy: ${LLC_REPL}" >&2
    exit 1
fi

GEN_DIR="${SCRIPT_DIR}/.generated"
GEN_JSON="${GEN_DIR}/${CONFIG_NAME}.json"
mkdir -p "$GEN_DIR"

python3 - "$BASE_JSON" "$GEN_JSON" "$BINARY_NAME" "$NUM_CORE" "$L1I_PREF" "$L1D_PREF" "$L2C_PREF" "$LLC_PREF" "$LLC_REPL" \
    "$STLB_PREF" "$STLB_PQ_SIZE" "$PTW_PQ_SIZE" <<'PY'
import json
import pathlib
import sys

base_json, out_json, binary_name, num_core, l1i, l1d, l2c, llc, llc_repl, stlb_pref, stlb_pq_size, ptw_pq_size = sys.argv[1:]
config = json.loads(pathlib.Path(base_json).read_text())
config["executable_name"] = binary_name
config["num_cores"] = int(num_core)
config.setdefault("L1I", {})["prefetcher"] = l1i
config.setdefault("L1D", {})["prefetcher"] = l1d
config.setdefault("L2C", {})["prefetcher"] = l2c
config.setdefault("LLC", {})["prefetcher"] = llc
config.setdefault("LLC", {})["replacement"] = llc_repl
if stlb_pref:
    config.setdefault("STLB", {})["prefetcher"] = f"prefetcher_stlb/{stlb_pref}"
    config["STLB"]["prefetch_as_load"] = False
    config["STLB"]["prefetch_activate"] = "LOAD"
    config["STLB"]["pq_size"] = int(stlb_pq_size)
    config.setdefault("PTW", {})["pq_size"] = int(ptw_pq_size)
pathlib.Path(out_json).write_text(json.dumps(config, indent=2) + "\n")
PY

cd "$CHAMPSIM_ROOT"
echo "[BUILD] ${CONFIG_NAME}: ${BINARY_NAME}"
echo "[CMD] ./config.sh ${GEN_JSON}"
./config.sh "$GEN_JSON"
if [ -n "$MAKE_JOBS" ]; then
    echo "[CMD] make -j ${MAKE_JOBS}"
    make -j "$MAKE_JOBS"
else
    echo "[CMD] make"
    make
fi

if [ ! -x "${CHAMPSIM_ROOT}/bin/${BINARY_NAME}" ]; then
    echo "[ERROR] Build did not produce bin/${BINARY_NAME}" >&2
    exit 1
fi

echo "[INFO] Binary: ${CHAMPSIM_ROOT}/bin/${BINARY_NAME}"
