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
BASELINE_SELECT_TAG=${BASELINE_SELECT_TAG:-1core-spec0617_gapligra-TLB-select-trace-compare_jsonnew}
NOPREF_TAG="nopref-workload-sweep"
FLOW_TAG="select_trace"

PREF_CONFIG_SPECS=(
    "pref-workload-sweep:berti:pythia:Berti+pythia"
    "pref-ipcp-pythia-workload-sweep:ipcp:pythia:IPCP+pythia"
    "pref-berti-no-workload-sweep:berti:no:Berti+no"
    "pref-berti-ip_stride-workload-sweep:berti:ip_stride:Berti+ip_stride"
    "pref-sms-pythia-workload-sweep:sms:pythia:SMS+pythia"
)

MAX_PARALLEL=${MAX_PARALLEL:-4}
TRACE_DIRS=${TRACE_DIRS:-/data0/tzh/champsim_traces/SPEC06:/data0/tzh/champsim_traces/SPEC17:/data0/tzh/champsim_traces/GAP:/data0/tzh/champsim_traces/Ligra}
N_WARM=${N_WARM:-50}
N_SIM=${N_SIM:-200}
SKIP_EXISTING=${SKIP_EXISTING:-1}
TRACE_FILTER=${TRACE_FILTER:-${BENCH_FILTER:-}}
SELECT_THRESHOLD=${SELECT_THRESHOLD:-1.0}
SELECT_TRACE_JSON=${SELECT_TRACE_JSON:-${CHAMPSIM_ROOT}/csv_figure/${BASELINE_SELECT_TAG}/${FLOW_TAG}/data_process_for_compare/stlb_mpki_gt_${SELECT_THRESHOLD}_selected_traces.json}

NOPREF_DIR="${SCRIPT_DIR}/${NOPREF_TAG}"
DP_DIR="${SCRIPT_DIR}/data_process_for_compare"
TOOL_PY="${DP_DIR}/tlb_select_tools.py"

BUILD_NOPREF="${NOPREF_DIR}/build_champsim.sh"
RUN_NOPREF="${NOPREF_DIR}/launch_workload_sweep.sh"
CSV_NOPREF="${NOPREF_DIR}/nopref_tlb_backend.sh"
COMPARE_SCRIPT="${DP_DIR}/compare_pref_vs_nopref_ipc.sh"

flow_root() {
    echo "${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}"
}

select_trace_json() {
    echo "$SELECT_TRACE_JSON"
}

local_select_trace_json() {
    echo "$(flow_root)/data_process_for_compare/stlb_mpki_gt_${SELECT_THRESHOLD}_selected_traces.json"
}

parse_pref_spec() {
    local spec="$1"
    IFS=':' read -r PREF_TAG PREF_L1D PREF_L2C PREF_LABEL <<< "$spec"
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
    ensure_exec "$RUN_NOPREF"
    ensure_exec "$CSV_NOPREF"
    ensure_exec "$COMPARE_SCRIPT"
    ensure_exec "$TOOL_PY"
    if [ ! -f "$(select_trace_json)" ]; then
        echo "[ERROR] Selected trace JSON not found: $(select_trace_json)"
        exit 1
    fi
    for spec in "${PREF_CONFIG_SPECS[@]}"; do
        parse_pref_spec "$spec"
        local pref_dir="${SCRIPT_DIR}/${PREF_TAG}"
        if [ ! -d "$pref_dir" ]; then
            echo "[ERROR] Pref config directory not found: $pref_dir"
            exit 1
        fi
        ensure_exec "${pref_dir}/build_champsim.sh"
        ensure_exec "${pref_dir}/launch_workload_sweep.sh"
        ensure_exec "${pref_dir}/pref_tlb_backend.sh"
    done
}

do_build_nopref() {
    echo "[STEP] build nopref"
    TRACE_DIRS="$TRACE_DIRS" "$BUILD_NOPREF"
}

do_build_prefs() {
    for spec in "${PREF_CONFIG_SPECS[@]}"; do
        parse_pref_spec "$spec"
        echo "[STEP] build pref ${PREF_LABEL} (${PREF_TAG})"
        TRACE_DIRS="$TRACE_DIRS" L1D_PREFETCHER="$PREF_L1D" L2C_PREFETCHER="$PREF_L2C" \
            "${SCRIPT_DIR}/${PREF_TAG}/build_champsim.sh"
    done
}

do_run_nopref() {
    local p=${1:-$MAX_PARALLEL}
    echo "[STEP] run nopref selected traces (parallel=$p)"
    TRACE_DIRS="$TRACE_DIRS" MAX_PARALLEL="$p" SKIP_EXISTING="$SKIP_EXISTING" DO_BUILD=0 N_WARM="$N_WARM" N_SIM="$N_SIM" \
        TRACE_FILTER="$TRACE_FILTER" SELECT_TRACE_JSON="$(select_trace_json)" "$RUN_NOPREF" "$p" "$TRACE_FILTER"
}

do_run_prefs() {
    local p=${1:-$MAX_PARALLEL}
    for spec in "${PREF_CONFIG_SPECS[@]}"; do
        parse_pref_spec "$spec"
        echo "[STEP] run pref ${PREF_LABEL} selected traces (parallel=$p)"
        TRACE_DIRS="$TRACE_DIRS" MAX_PARALLEL="$p" SKIP_EXISTING="$SKIP_EXISTING" DO_BUILD=0 N_WARM="$N_WARM" N_SIM="$N_SIM" \
            TRACE_FILTER="$TRACE_FILTER" SELECT_TRACE_JSON="$(select_trace_json)" \
            L1D_PREFETCHER="$PREF_L1D" L2C_PREFETCHER="$PREF_L2C" \
            "${SCRIPT_DIR}/${PREF_TAG}/launch_workload_sweep.sh" "$p" "$TRACE_FILTER"
    done
}

do_select_json() {
    local selected_json
    local local_json
    selected_json=$(select_trace_json)
    local_json=$(local_select_trace_json)
    echo "[STEP] reuse selected traces from baseline: ${selected_json}"
    mkdir -p "$(dirname "$local_json")"
    if [ "$selected_json" != "$local_json" ]; then
        cp "$selected_json" "$local_json"
        echo "[INFO] copied selected trace JSON for this run: ${local_json}"
    fi
}

do_csv_nopref() {
    echo "[STEP] nopref selected CSV/figures"
    FLOW_TAG="$FLOW_TAG" SELECT_TRACE_JSON="$(select_trace_json)" "$CSV_NOPREF"
}

do_csv_prefs() {
    for spec in "${PREF_CONFIG_SPECS[@]}"; do
        parse_pref_spec "$spec"
        echo "[STEP] pref ${PREF_LABEL} selected CSV/figures"
        FLOW_TAG="$FLOW_TAG" SELECT_TRACE_JSON="$(select_trace_json)" CONFIG_LABEL="$PREF_LABEL" \
            "${SCRIPT_DIR}/${PREF_TAG}/pref_tlb_backend.sh"
    done
}

pref_csv_list() {
    local sep=""
    for spec in "${PREF_CONFIG_SPECS[@]}"; do
        parse_pref_spec "$spec"
        printf "%s%s" "$sep" "${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/${PREF_TAG}/pref_workload_agg.csv"
        sep=":"
    done
}

pref_label_list() {
    local sep=""
    for spec in "${PREF_CONFIG_SPECS[@]}"; do
        parse_pref_spec "$spec"
        printf "%s%s" "$sep" "$PREF_LABEL"
        sep=":"
    done
}

pref_config_list() {
    local sep=""
    for spec in "${PREF_CONFIG_SPECS[@]}"; do
        parse_pref_spec "$spec"
        printf "%s%s" "$sep" "$PREF_TAG"
        sep=":"
    done
}

do_compare() {
    echo "[STEP] multi-pref vs nopref compare"
    FLOW_TAG="$FLOW_TAG" PREF_CSV_LIST="$(pref_csv_list)" PREF_LABEL_LIST="$(pref_label_list)" PREF_CONFIG_LIST="$(pref_config_list)" \
        "$COMPARE_SCRIPT"
}

show_status() {
    echo "========== SPEC06+SPEC17+GAP+Ligra TLB SELECT STATUS =========="
    echo "CHAMPSIM_ROOT : $CHAMPSIM_ROOT"
    echo "COMPARE_TAG   : $COMPARE_TAG"
    echo "BASE_SELECT   : $BASELINE_SELECT_TAG"
    echo "TRACE_DIRS    : $TRACE_DIRS"
    echo "TRACE_FILTER  : ${TRACE_FILTER:-<none>}"
    echo "MAX_PARALLEL  : $MAX_PARALLEL"
    echo "N_WARM        : $N_WARM"
    echo "N_SIM         : $N_SIM"
    echo "SKIP_EXISTING : $SKIP_EXISTING"
    echo "THRESHOLD     : $SELECT_THRESHOLD"
    echo "RESULT_NOPREF : ${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${NOPREF_TAG}"
    for spec in "${PREF_CONFIG_SPECS[@]}"; do
        parse_pref_spec "$spec"
        echo "RESULT_PREF   : ${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${PREF_TAG} (${PREF_LABEL}, L1D=${PREF_L1D}, L2C=${PREF_L2C})"
    done
    echo "CSV_ROOT      : $(flow_root)"
    echo "SELECT_JSON   : $(select_trace_json)"
    echo "LOCAL_JSON    : $(local_select_trace_json)"
    echo "FULL_TRACE    : disabled"
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
        do_build_prefs
        do_run_nopref "$MAX_PARALLEL"
        do_run_prefs "$MAX_PARALLEL"
        do_select_json
        do_csv_nopref
        do_csv_prefs
        do_compare
        ;;
    build-only)
        check_env
        do_build_nopref
        do_build_prefs
        ;;
    run-only)
        check_env
        do_run_nopref "${2:-$MAX_PARALLEL}"
        do_run_prefs "${2:-$MAX_PARALLEL}"
        ;;
    select-json)
        check_env
        do_select_json
        ;;
    backend|figures)
        check_env
        do_select_json
        do_csv_nopref
        do_csv_prefs
        do_compare
        ;;
    full-backend|full-trace)
        echo "[ERROR] full_trace flow is disabled for ${COMPARE_TAG}; this sweep only uses the reused select_trace set."
        exit 1
        ;;
    backend-all)
        check_env
        do_select_json
        do_csv_nopref
        do_csv_prefs
        do_compare
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
        do_build_prefs
        ;;
    run-nopref)
        check_env
        do_run_nopref "${2:-$MAX_PARALLEL}"
        ;;
    run-pref)
        check_env
        do_run_prefs "${2:-$MAX_PARALLEL}"
        ;;
    csv-nopref)
        check_env
        do_csv_nopref
        ;;
    csv-pref)
        check_env
        do_csv_prefs
        ;;
    status)
        show_status
        ;;
    clean-csv)
        echo "[STEP] clean csv outputs: ${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}"
        rm -rf "${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}"
        ;;
    *)
        echo "Usage: $0 {all [p]|build-only|run-only [p]|select-json|backend|figures|backend-all|compare|build-nopref|build-pref|run-nopref [p]|run-pref [p]|csv-nopref|csv-pref|clean-csv|status}"
        exit 1
        ;;
esac

echo "[DONE] command '$cmd' completed"
