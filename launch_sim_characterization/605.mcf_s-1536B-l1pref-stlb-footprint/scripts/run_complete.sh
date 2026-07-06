#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)

TRACE="${TRACE:-/data0/tzh/champsim_traces/SPEC17/605.mcf_s-1536B.champsimtrace.xz}"
TRACE_TAG="${TRACE_TAG:-605.mcf_s-1536B}"
N_WARM="${N_WARM:-20}"
N_SIM="${N_SIM:-50}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"
DO_BUILD="${DO_BUILD:-1}"

echo "[COMPLETE] case: ${CASE_DIR}"
echo "[COMPLETE] trace: ${TRACE}"
echo "[COMPLETE] warmup: ${N_WARM}M, roi: ${N_SIM}M, skip_existing: ${SKIP_EXISTING}, build: ${DO_BUILD}"

TRACE="$TRACE" TRACE_TAG="$TRACE_TAG" N_WARM="$N_WARM" N_SIM="$N_SIM" SKIP_EXISTING="$SKIP_EXISTING" DO_BUILD="$DO_BUILD" \
  "${SCRIPT_DIR}/run_all.sh"

TRACE="$TRACE" TRACE_TAG="$TRACE_TAG" N_WARM="$N_WARM" N_SIM="$N_SIM" SKIP_EXISTING="$SKIP_EXISTING" DO_BUILD="$DO_BUILD" \
  "${SCRIPT_DIR}/run_discard_pgc.sh"

TRACE_TAG="$TRACE_TAG" "${SCRIPT_DIR}/make_vberti_pgc_tlb_compare.py"

echo "[COMPLETE] all done"
echo "[COMPLETE] result: ${CASE_DIR}/result"
echo "[COMPLETE] csv_figure: ${CASE_DIR}/csv_figure"
