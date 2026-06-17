#!/bin/bash
set -euo pipefail

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

COMPARE_TAG=$(basename "$SCRIPT_DIR")
NOPREF_TAG="nopref-workload-sweep"
PREF_TAG="pref-workload-sweep"
FLOW_TAG="select_trace"

MAX_PARALLEL=${MAX_PARALLEL:-4}
TRACE_DIRS=${TRACE_DIRS:-/data0/tzh/champsim_traces/SPEC06:/data0/tzh/champsim_traces/SPEC17:/data0/tzh/champsim_traces/GAP:/data0/tzh/champsim_traces/Ligra}
N_WARM=${N_WARM:-50}
N_SIM=${N_SIM:-200}
SKIP_EXISTING=${SKIP_EXISTING:-1}
TRACE_FILTER=${TRACE_FILTER:-${BENCH_FILTER:-}}
SELECT_THRESHOLD=${SELECT_THRESHOLD:-1.0}

NOPREF_DIR="${SCRIPT_DIR}/${NOPREF_TAG}"
PREF_DIR="${SCRIPT_DIR}/${PREF_TAG}"
DP_DIR="${SCRIPT_DIR}/data_process_for_compare"
TOOL_PY="${DP_DIR}/tlb_select_tools.py"

BUILD_NOPREF="${NOPREF_DIR}/build_champsim.sh"
BUILD_PREF="${PREF_DIR}/build_champsim.sh"
RUN_NOPREF="${NOPREF_DIR}/launch_workload_sweep.sh"
RUN_PREF="${PREF_DIR}/launch_workload_sweep.sh"
CSV_NOPREF="${NOPREF_DIR}/nopref_tlb_backend.sh"
CSV_PREF="${PREF_DIR}/pref_tlb_backend.sh"
COMPARE_SCRIPT="${DP_DIR}/compare_pref_vs_nopref_ipc.sh"

flow_root() {
    echo "${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}"
}

select_trace_json() {
    echo "$(flow_root)/data_process_for_compare/llc_mpki_gt_${SELECT_THRESHOLD}_selected_traces.json"
}

ensure_exec() {
    local f="$1"
    if [ ! -f "$f" ]; then
        echo "[ERROR] Required script missing: $f"
        exit 1
    fi
    if [ ! -x "$f" ]; then
        chmod +x "$f"
    fi
}

check_env() {
    IFS=':' read -r -a dirs <<< "$TRACE_DIRS"
    for trace_dir in "${dirs[@]}"; do
        if [ ! -d "$trace_dir" ]; then
            echo "[ERROR] TRACE_DIR not found: $trace_dir"
            exit 1
        fi
    done
    ensure_exec "$BUILD_NOPREF"
    ensure_exec "$BUILD_PREF"
    ensure_exec "$RUN_NOPREF"
    ensure_exec "$RUN_PREF"
    ensure_exec "$CSV_NOPREF"
    ensure_exec "$CSV_PREF"
    ensure_exec "$COMPARE_SCRIPT"
    ensure_exec "$TOOL_PY"
}

do_build_nopref() {
    echo "[STEP] build nopref"
    TRACE_DIRS="$TRACE_DIRS" "$BUILD_NOPREF"
}

do_build_pref() {
    echo "[STEP] build pref"
    TRACE_DIRS="$TRACE_DIRS" "$BUILD_PREF"
}

do_run_nopref() {
    local p=${1:-$MAX_PARALLEL}
    echo "[STEP] run nopref (parallel=$p)"
    TRACE_DIRS="$TRACE_DIRS" MAX_PARALLEL="$p" SKIP_EXISTING="$SKIP_EXISTING" DO_BUILD=0 N_WARM="$N_WARM" N_SIM="$N_SIM" \
        TRACE_FILTER="$TRACE_FILTER" "$RUN_NOPREF" "$p" "$TRACE_FILTER"
}

do_run_pref() {
    local p=${1:-$MAX_PARALLEL}
    echo "[STEP] run pref (parallel=$p)"
    TRACE_DIRS="$TRACE_DIRS" MAX_PARALLEL="$p" SKIP_EXISTING="$SKIP_EXISTING" DO_BUILD=0 N_WARM="$N_WARM" N_SIM="$N_SIM" \
        TRACE_FILTER="$TRACE_FILTER" "$RUN_PREF" "$p" "$TRACE_FILTER"
}

do_select_json() {
    echo "[STEP] select traces by nopref LLC MPKI > ${SELECT_THRESHOLD}"
    python3 "$TOOL_PY" select-trace-json \
        --result-dir "${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${NOPREF_TAG}" \
        --out-json "$(select_trace_json)" \
        --threshold "$SELECT_THRESHOLD"
}

do_csv_nopref() {
    echo "[STEP] nopref selected CSV/figures"
    FLOW_TAG="$FLOW_TAG" SELECT_TRACE_JSON="$(select_trace_json)" "$CSV_NOPREF"
}

do_csv_pref() {
    echo "[STEP] pref selected CSV/figures"
    FLOW_TAG="$FLOW_TAG" SELECT_TRACE_JSON="$(select_trace_json)" "$CSV_PREF"
}

do_compare() {
    echo "[STEP] IPC compare"
    FLOW_TAG="$FLOW_TAG" "$COMPARE_SCRIPT"
}

do_full_csv_nopref() {
    echo "[STEP] nopref full-trace CSV/figures"
    FLOW_TAG="full_trace" SELECT_TRACE_JSON="ALL" "$CSV_NOPREF"
}

do_full_csv_pref() {
    echo "[STEP] pref full-trace CSV/figures"
    FLOW_TAG="full_trace" SELECT_TRACE_JSON="ALL" "$CSV_PREF"
}

do_full_compare() {
    echo "[STEP] full-trace IPC/STLB compare"
    FLOW_TAG="full_trace" "$COMPARE_SCRIPT"
}

do_full_backend() {
    do_full_csv_nopref
    do_full_csv_pref
    do_full_compare
}

show_status() {
    echo "========== SPEC06+SPEC17+GAP+Ligra LLC SELECT STATUS =========="
    echo "CHAMPSIM_ROOT : $CHAMPSIM_ROOT"
    echo "COMPARE_TAG   : $COMPARE_TAG"
    echo "TRACE_DIRS    : $TRACE_DIRS"
    echo "TRACE_FILTER  : ${TRACE_FILTER:-<none>}"
    echo "MAX_PARALLEL  : $MAX_PARALLEL"
    echo "N_WARM        : $N_WARM"
    echo "N_SIM         : $N_SIM"
    echo "SKIP_EXISTING : $SKIP_EXISTING"
    echo "THRESHOLD     : $SELECT_THRESHOLD"
    echo "RESULT_NOPREF : ${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${NOPREF_TAG}"
    echo "RESULT_PREF   : ${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${PREF_TAG}"
    echo "CSV_ROOT      : $(flow_root)"
    echo "FULL_CSV_ROOT : ${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/full_trace"
    echo "SELECT_JSON   : $(select_trace_json)"
    echo "=================================================="
}

cmd=${1:-all}
if [ "$cmd" = "all" ] && [ -n "${2:-}" ]; then
    MAX_PARALLEL="$2"
fi

case "$cmd" in
    all)
        check_env
        do_build_nopref
        do_build_pref
        do_run_nopref "$MAX_PARALLEL"
        do_run_pref "$MAX_PARALLEL"
        do_select_json
        do_csv_nopref
        do_csv_pref
        do_compare
        do_full_backend
        ;;
    build-only)
        check_env
        do_build_nopref
        do_build_pref
        ;;
    run-only)
        check_env
        do_run_nopref "${2:-$MAX_PARALLEL}"
        do_run_pref "${2:-$MAX_PARALLEL}"
        ;;
    select-json)
        check_env
        do_select_json
        ;;
    backend|figures)
        check_env
        do_select_json
        do_csv_nopref
        do_csv_pref
        do_compare
        ;;
    full-backend|full-trace)
        check_env
        do_full_backend
        ;;
    backend-all)
        check_env
        do_select_json
        do_csv_nopref
        do_csv_pref
        do_compare
        do_full_backend
        ;;
    compare)
        check_env
        do_compare
        ;;
    build-nopref)
        check_env
        do_build_nopref
        ;;
    build-pref)
        check_env
        do_build_pref
        ;;
    run-nopref)
        check_env
        do_run_nopref "${2:-$MAX_PARALLEL}"
        ;;
    run-pref)
        check_env
        do_run_pref "${2:-$MAX_PARALLEL}"
        ;;
    csv-nopref)
        check_env
        do_csv_nopref
        ;;
    csv-pref)
        check_env
        do_csv_pref
        ;;
    status)
        show_status
        ;;
    clean-csv)
        echo "[STEP] clean csv outputs: ${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}"
        rm -rf "${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}"
        ;;
    *)
        echo "Usage: $0 {all [p]|build-only|run-only [p]|select-json|backend|figures|full-backend|full-trace|backend-all|compare|build-nopref|build-pref|run-nopref [p]|run-pref [p]|csv-nopref|csv-pref|clean-csv|status}"
        exit 1
        ;;
esac

echo "[DONE] command '$cmd' completed"
