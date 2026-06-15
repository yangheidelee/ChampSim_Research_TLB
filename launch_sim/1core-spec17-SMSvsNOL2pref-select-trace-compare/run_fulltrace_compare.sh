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
BASE_TAG="1core-spec17-nol2pref-workload-sweep"
SMS_TAG="1core-spec17-sms-workload-sweep"
FULL_FLOW_TAG="full_trace"
SELECT_FLOW_TAG="select_trace"

MAX_PARALLEL=${MAX_PARALLEL:-4}
TRACE_DIR=${TRACE_DIR:-/data0/tzh/champsim_traces/SPEC17}
WEIGHT_DIR=${WEIGHT_DIR:-${CHAMPSIM_ROOT}/simpoint_weight}
N_WARM=${N_WARM:-50}
N_SIM=${N_SIM:-200}
RUN_BASE=${RUN_BASE:-1}
RUN_SMS=${RUN_SMS:-1}
DO_BUILD=${DO_BUILD:-1}
DO_RUN=${DO_RUN:-1}
DO_SINGLE_CSV_FIG=${DO_SINGLE_CSV_FIG:-1}
DO_GENERATE_WEIGHT_MAP=${DO_GENERATE_WEIGHT_MAP:-1}
DO_COMPARE=${DO_COMPARE:-1}
SKIP_EXISTING=${SKIP_EXISTING:-1}
BENCH_FILTER=${BENCH_FILTER:-}

BASE_DIR="${SCRIPT_DIR}/${BASE_TAG}"
SMS_DIR="${SCRIPT_DIR}/${SMS_TAG}"
DP_DIR="${SCRIPT_DIR}/data_process_for_compare"

BUILD_BASE="${BASE_DIR}/build_champsim.sh"
BUILD_SMS="${SMS_DIR}/build_champsim.sh"
RUN_SWEEP_BASE="${BASE_DIR}/launch_workload_sweep.sh"
RUN_SWEEP_SMS="${SMS_DIR}/launch_workload_sweep.sh"
CSV_BASE="${BASE_DIR}/nol2pref_base_csv_figure.sh"
CSV_SMS="${SMS_DIR}/sms_degree_csv_figure.sh"
WEIGHT_MAP_SCRIPT="${DP_DIR}/generate_spec17_trace_weight_map.sh"
COMPARE_SCRIPT="${DP_DIR}/compare_sms_vs_base_fulltrace.sh"
TOOL_PY="${DP_DIR}/spec17_fulltrace_tools.py"

full_flow_root() {
    echo "${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FULL_FLOW_TAG}"
}

select_flow_root() {
    echo "${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${SELECT_FLOW_TAG}"
}

select_trace_json() {
    echo "$(select_flow_root)/data_process_for_compare/baseline_LLC_demand_MKPI_select_trace.json"
}

weight_map_csv_for_flow() {
    local flow_tag="$1"
    echo "${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${flow_tag}/data_process_for_compare/spec17_trace_weight_map.csv"
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
    if [ ! -d "$TRACE_DIR" ]; then
        echo "[ERROR] TRACE_DIR not found: $TRACE_DIR"
        exit 1
    fi
    if [ ! -d "$WEIGHT_DIR" ]; then
        echo "[ERROR] WEIGHT_DIR not found: $WEIGHT_DIR"
        exit 1
    fi
    if [ ! -d "$BASE_DIR" ] || [ ! -d "$SMS_DIR" ] || [ ! -d "$DP_DIR" ]; then
        echo "[ERROR] Compare folder structure is incomplete under: $SCRIPT_DIR"
        exit 1
    fi

    ensure_exec "$BUILD_BASE"
    ensure_exec "$BUILD_SMS"
    ensure_exec "$RUN_SWEEP_BASE"
    ensure_exec "$RUN_SWEEP_SMS"
    ensure_exec "$CSV_BASE"
    ensure_exec "$CSV_SMS"
    ensure_exec "$WEIGHT_MAP_SCRIPT"
    ensure_exec "$COMPARE_SCRIPT"
    ensure_exec "$TOOL_PY"
}

do_build_base() {
    echo "[STEP] build base"
    TRACE_DIR="$TRACE_DIR" WEIGHT_DIR="$WEIGHT_DIR" "$BUILD_BASE"
}

do_build_sms() {
    echo "[STEP] build sms"
    TRACE_DIR="$TRACE_DIR" WEIGHT_DIR="$WEIGHT_DIR" "$BUILD_SMS"
}

do_run_base() {
    local p=${1:-$MAX_PARALLEL}
    echo "[STEP] run base (parallel=$p)"
    TRACE_DIR="$TRACE_DIR" MAX_PARALLEL="$p" SKIP_EXISTING="$SKIP_EXISTING" DO_BUILD=0 BENCH_FILTER="$BENCH_FILTER" \
        "$RUN_SWEEP_BASE" "$p" "$BENCH_FILTER"
}

do_run_sms() {
    local p=${1:-$MAX_PARALLEL}
    echo "[STEP] run sms (parallel=$p)"
    TRACE_DIR="$TRACE_DIR" MAX_PARALLEL="$p" SKIP_EXISTING="$SKIP_EXISTING" DO_BUILD=0 BENCH_FILTER="$BENCH_FILTER" \
        "$RUN_SWEEP_SMS" "$p" "$BENCH_FILTER"
}

do_weight_map() {
    local flow_tag=${1:-$FULL_FLOW_TAG}
    echo "[STEP] generate weight map (${flow_tag})"
    TRACE_DIR="$TRACE_DIR" WEIGHT_DIR="$WEIGHT_DIR" FLOW_TAG="$flow_tag" "$WEIGHT_MAP_SCRIPT"
}

do_select_json() {
    echo "[STEP] generate select-trace json"
    local full_weight_map
    full_weight_map="$(weight_map_csv_for_flow "$FULL_FLOW_TAG")"
    if [ ! -f "$full_weight_map" ]; then
        do_weight_map "$FULL_FLOW_TAG"
    fi
    python3 "$TOOL_PY" select-trace-json \
        --result-dir "${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${BASE_TAG}" \
        --weight-map-csv "$full_weight_map" \
        --out-json "$(select_trace_json)" \
        --threshold 1.0
}

do_csv_base_full() {
    echo "[STEP] base csv+figure (full_trace)"
    FLOW_TAG="$FULL_FLOW_TAG" "$CSV_BASE"
}

do_csv_sms_full() {
    echo "[STEP] sms csv+figure (full_trace)"
    FLOW_TAG="$FULL_FLOW_TAG" "$CSV_SMS"
}

do_compare_full() {
    echo "[STEP] compare sms vs base (full_trace)"
    FLOW_TAG="$FULL_FLOW_TAG" "$COMPARE_SCRIPT"
}

do_csv_base_select() {
    echo "[STEP] base csv+figure (select_trace)"
    FLOW_TAG="$SELECT_FLOW_TAG" SELECT_TRACE_JSON="$(select_trace_json)" "$CSV_BASE"
}

do_csv_sms_select() {
    echo "[STEP] sms csv+figure (select_trace)"
    FLOW_TAG="$SELECT_FLOW_TAG" SELECT_TRACE_JSON="$(select_trace_json)" "$CSV_SMS"
}

do_compare_select() {
    echo "[STEP] compare sms vs base (select_trace)"
    FLOW_TAG="$SELECT_FLOW_TAG" "$COMPARE_SCRIPT"
}

do_full_flow() {
    check_env
    if [ "$DO_BUILD" = "1" ]; then
        if [ "$RUN_BASE" = "1" ]; then do_build_base; fi
        if [ "$RUN_SMS" = "1" ]; then do_build_sms; fi
    fi

    if [ "$DO_RUN" = "1" ]; then
        if [ "$RUN_BASE" = "1" ]; then do_run_base "$MAX_PARALLEL"; fi
        if [ "$RUN_SMS" = "1" ]; then do_run_sms "$MAX_PARALLEL"; fi
    fi

    if [ "$DO_GENERATE_WEIGHT_MAP" = "1" ]; then
        do_weight_map "$FULL_FLOW_TAG"
    fi

    if [ "$DO_SINGLE_CSV_FIG" = "1" ]; then
        if [ "$RUN_BASE" = "1" ]; then do_csv_base_full; fi
        if [ "$RUN_SMS" = "1" ]; then do_csv_sms_full; fi
    fi

    if [ "$DO_COMPARE" = "1" ]; then
        do_compare_full
    fi
}

do_select_flow() {
    check_env
    do_select_json
    do_weight_map "$SELECT_FLOW_TAG"
    if [ "$DO_SINGLE_CSV_FIG" = "1" ]; then
        if [ "$RUN_BASE" = "1" ]; then do_csv_base_select; fi
        if [ "$RUN_SMS" = "1" ]; then do_csv_sms_select; fi
    fi
    if [ "$DO_COMPARE" = "1" ]; then
        do_compare_select
    fi
}

clean_csv() {
    local dir="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}"
    echo "[STEP] clean csv outputs: $dir"
    rm -rf "$dir"
}

show_status() {
    echo "========== SELECT-TRACE COMPARE STATUS =========="
    echo "CHAMPSIM_ROOT : $CHAMPSIM_ROOT"
    echo "COMPARE_TAG   : $COMPARE_TAG"
    echo "TRACE_DIR     : $TRACE_DIR"
    echo "WEIGHT_DIR    : $WEIGHT_DIR"
    echo "MAX_PARALLEL  : $MAX_PARALLEL"
    echo "N_WARM        : $N_WARM"
    echo "N_SIM         : $N_SIM"
    echo "SKIP_EXISTING : $SKIP_EXISTING"
    echo "BENCH_FILTER  : ${BENCH_FILTER:-<none>}"
    echo "RESULT_BASE   : ${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${BASE_TAG}"
    echo "RESULT_SMS    : ${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${SMS_TAG}"
    echo "FULL_ROOT     : $(full_flow_root)"
    echo "SELECT_ROOT   : $(select_flow_root)"
    echo "SELECT_JSON   : $(select_trace_json)"
    echo "==============================================="
}

cmd=${1:-all}
if [ "$cmd" = "all" ] && [ -n "${2:-}" ]; then
    if [[ "${2:-}" =~ ^[0-9]+$ ]] && [ "${2}" -gt 0 ]; then
        MAX_PARALLEL="$2"
    else
        echo "[ERROR] parallel count must be a positive integer: ${2:-}"
        exit 1
    fi
fi

case "$cmd" in
    all)
        do_full_flow
        do_select_flow
        ;;
    full-only)
        do_full_flow
        ;;
    build-only)
        check_env
        if [ "$RUN_BASE" = "1" ]; then do_build_base; fi
        if [ "$RUN_SMS" = "1" ]; then do_build_sms; fi
        ;;
    run-only)
        check_env
        if [ "$RUN_BASE" = "1" ]; then do_run_base "${2:-$MAX_PARALLEL}"; fi
        if [ "$RUN_SMS" = "1" ]; then do_run_sms "${2:-$MAX_PARALLEL}"; fi
        ;;
    csv-only|full-csv-only)
        check_env
        do_weight_map "$FULL_FLOW_TAG"
        if [ "$RUN_BASE" = "1" ]; then do_csv_base_full; fi
        if [ "$RUN_SMS" = "1" ]; then do_csv_sms_full; fi
        ;;
    compare|compare-only|full-compare-only)
        check_env
        do_compare_full
        ;;
    build-base)
        check_env
        do_build_base
        ;;
    build-sms)
        check_env
        do_build_sms
        ;;
    run-base)
        check_env
        do_run_base "${2:-$MAX_PARALLEL}"
        ;;
    run-sms)
        check_env
        do_run_sms "${2:-$MAX_PARALLEL}"
        ;;
    csv-base)
        check_env
        do_weight_map "$FULL_FLOW_TAG"
        do_csv_base_full
        ;;
    csv-sms)
        check_env
        do_weight_map "$FULL_FLOW_TAG"
        do_csv_sms_full
        ;;
    weight-map)
        check_env
        do_weight_map "$FULL_FLOW_TAG"
        ;;
    select-json)
        check_env
        do_select_json
        ;;
    select-only|select-csv-only|select-compare-only)
        do_select_flow
        ;;
    figures)
        check_env
        do_weight_map "$FULL_FLOW_TAG"
        if [ "$RUN_BASE" = "1" ]; then do_csv_base_full; fi
        if [ "$RUN_SMS" = "1" ]; then do_csv_sms_full; fi
        do_compare_full
        ;;
    clean-csv)
        clean_csv
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 {all|full-only|select-only|select-json|build-only|run-only|csv-only|compare-only|build-base|build-sms|run-base [p]|run-sms [p]|csv-base|csv-sms|weight-map|compare|figures|clean-csv|status}"
        exit 1
        ;;
esac

echo "[DONE] command '$cmd' completed"
