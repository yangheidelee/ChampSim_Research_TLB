#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Illegal number of parameters"
    echo "Usage: ./build_champsim.sh [l1d_pref] [l2c_pref]"
    exit 1
fi

L1D_PREFETCHER=$1
L2C_PREFETCHER=$2

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CONFIG_FILE="${ROOT_DIR}/config_default.json"

BRANCH=perceptron
BTB=basic_btb
LLC_PREFETCHER=no
LLC_REPLACEMENT=drrip
NUM_CORE=1

BOLD=$(tput bold || true)
NORMAL=$(tput sgr0 || true)

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "[ERROR] Cannot find ${CONFIG_FILE}"
    exit 1
fi

if [ ! -d "${ROOT_DIR}/prefetcher/${L1D_PREFETCHER}" ]; then
    echo "[ERROR] Cannot find L1D prefetcher: ${L1D_PREFETCHER}"
    echo "[ERROR] Possible prefetchers:"
    find "${ROOT_DIR}/prefetcher" -mindepth 1 -maxdepth 1 -type d -printf "  %f\n" | sort
    exit 1
fi

if [ ! -d "${ROOT_DIR}/prefetcher/${L2C_PREFETCHER}" ]; then
    echo "[ERROR] Cannot find L2C prefetcher: ${L2C_PREFETCHER}"
    echo "[ERROR] Possible prefetchers:"
    find "${ROOT_DIR}/prefetcher" -mindepth 1 -maxdepth 1 -type d -printf "  %f\n" | sort
    exit 1
fi

if [ ! -d "${ROOT_DIR}/prefetcher/${LLC_PREFETCHER}" ]; then
    echo "[ERROR] Cannot find LLC prefetcher: ${LLC_PREFETCHER}"
    exit 1
fi

if [ ! -d "${ROOT_DIR}/replacement/${LLC_REPLACEMENT}" ]; then
    echo "[ERROR] Cannot find LLC replacement: ${LLC_REPLACEMENT}"
    exit 1
fi

BINARY_NAME="${BRANCH}-${L1D_PREFETCHER}-${L2C_PREFETCHER}-${LLC_PREFETCHER}-${LLC_REPLACEMENT}-${NUM_CORE}core-json"

python3 - "$CONFIG_FILE" "$L1D_PREFETCHER" "$L2C_PREFETCHER" "$BINARY_NAME" "$BRANCH" "$BTB" "$LLC_PREFETCHER" "$LLC_REPLACEMENT" "$NUM_CORE" <<'PY'
import json
import os
import sys
import tempfile

config_file, l1d_pref, l2c_pref, binary_name, branch, btb, llc_pref, llc_repl, num_core = sys.argv[1:]

with open(config_file, encoding="utf-8") as rfp:
    config = json.load(rfp)

config["executable_name"] = binary_name
config["num_cores"] = int(num_core)

for cpu in config.get("ooo_cpu", []):
    cpu["branch_predictor"] = branch
    cpu["btb"] = btb

config.setdefault("L1D", {})["prefetcher"] = l1d_pref
config.setdefault("L2C", {})["prefetcher"] = l2c_pref
config.setdefault("LLC", {})["prefetcher"] = llc_pref
config.setdefault("LLC", {})["replacement"] = llc_repl

directory = os.path.dirname(config_file)
fd, tmp_name = tempfile.mkstemp(prefix=".config_default.", suffix=".json", dir=directory, text=True)
with os.fdopen(fd, "w", encoding="utf-8") as wfp:
    json.dump(config, wfp, indent=2)
    wfp.write("\n")
os.replace(tmp_name, config_file)
PY

cd "${ROOT_DIR}"

echo "Building ChampSim with JSON configuration..."
echo "Config: ${CONFIG_FILE}"
echo "Binary: bin/${BINARY_NAME}"
echo

./config.sh "${CONFIG_FILE}"
make

if [ ! -x "bin/${BINARY_NAME}" ]; then
    echo "${BOLD}ChampSim build FAILED!${NORMAL}"
    exit 1
fi

echo
echo "${BOLD}ChampSim is successfully built${NORMAL}"
echo "Branch Predictor: ${BRANCH}"
echo "BTB: ${BTB}"
echo "L1D Prefetcher: ${L1D_PREFETCHER}"
echo "L2C Prefetcher: ${L2C_PREFETCHER}"
echo "LLC Prefetcher: ${LLC_PREFETCHER}"
echo "LLC Replacement: ${LLC_REPLACEMENT}"
echo "Cores: ${NUM_CORE}"
echo "Binary: bin/${BINARY_NAME}"
