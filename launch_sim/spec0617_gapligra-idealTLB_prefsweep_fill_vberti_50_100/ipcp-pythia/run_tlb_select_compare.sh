#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

find_champsim_root() {
    local dir="$1"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/Makefile" ] && [ -d "$dir/src" ] && [ -d "$dir/launch_sim" ]; then
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

compare_tag_from_dir() {
    local dir="$1"
    local name parent grandparent
    name=$(basename "$dir")
    parent=$(basename "$(dirname "$dir")")
    grandparent=$(basename "$(dirname "$(dirname "$dir")")")
    if [ "$parent" = "spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100" ]; then
        echo "${parent}/${name}"
    elif [ "$grandparent" = "spec0617_gapligra-idealTLB_prefsweep_fill_vberti_50_100" ]; then
        echo "${grandparent}/${parent}"
    else
        echo "$parent"
    fi
}

COMPARE_TAG=${COMPARE_TAG:-$(compare_tag_from_dir "$SCRIPT_DIR")}
SELECT_BASE_TAG="nopref-workload-sweep"
BASELINE_TAG="pref-workload-sweep"
IDEAL_DEMAND_TAG="ideal-demand-workload-sweep"
IDEAL_L1PREF_TAG="ideal-l1pref-workload-sweep"
IDEAL_ALL_TAG="ideal-all-workload-sweep"
FLOW_TAG="select_trace"

MAX_PARALLEL=${MAX_PARALLEL:-4}
TRACE_DIRS=${TRACE_DIRS:-/data0/tzh/champsim_traces/SPEC06:/data0/tzh/champsim_traces/SPEC17:/data0/tzh/champsim_traces/GAP:/data0/tzh/champsim_traces/Ligra:/data0/tzh/champsim_traces/QMM:/data0/tzh/champsim_traces/PARSEC:/data2/zcq/champsim_traces_xsbench}
N_WARM=${N_WARM:-50}
N_SIM=${N_SIM:-100}
SKIP_EXISTING=${SKIP_EXISTING:-1}
TRACE_FILTER=${TRACE_FILTER:-${BENCH_FILTER:-}}
SELECT_THRESHOLD=${SELECT_THRESHOLD:-1.0}
PREFSWEEP_ROOT=$(dirname "$SCRIPT_DIR")
SELECT_TRACE_JSON=${SELECT_TRACE_JSON:-}
SELECT_TRACE_JSON_BASENAME=${SELECT_TRACE_JSON_BASENAME:-stlb_mpki_gt_${SELECT_THRESHOLD}_selected_traces.json}

DP_DIR="${SCRIPT_DIR}/data_process_for_compare"
TOOL_PY="${DP_DIR}/tlb_select_tools.py"

flow_root() {
    echo "${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}"
}

select_trace_json() {
    if [ -n "$SELECT_TRACE_JSON" ]; then
        echo "$SELECT_TRACE_JSON"
    else
        echo "${PREFSWEEP_ROOT}/${SELECT_TRACE_JSON_BASENAME}"
    fi
}

require_select_trace_json() {
    local selected
    selected="$(select_trace_json)"
    if [ ! -f "$selected" ]; then
        echo "[ERROR] Selected trace JSON not found: $selected" >&2
        echo "[ERROR] Copy an existing selected-trace JSON there, or set SELECT_TRACE_JSON=/path/to/json." >&2
        exit 1
    fi
    echo "$selected"
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

config_dir() {
    echo "${SCRIPT_DIR}/$1"
}

build_script() {
    echo "$(config_dir "$1")/build_champsim.sh"
}

run_script() {
    echo "$(config_dir "$1")/launch_workload_sweep.sh"
}

result_dir() {
    echo "${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/$1"
}

csv_dir() {
    echo "${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/$1"
}

trace_csv() {
    local tag="$1"
    local prefix="$2"
    echo "$(csv_dir "$tag")/${prefix}_trace_level.csv"
}

workload_csv() {
    local tag="$1"
    local prefix="$2"
    echo "$(csv_dir "$tag")/${prefix}_workload_agg.csv"
}

check_env() {
    IFS=':' read -r -a dirs <<< "$TRACE_DIRS"
    for trace_dir in "${dirs[@]}"; do
        if [ ! -d "$trace_dir" ]; then
            echo "[ERROR] TRACE_DIR not found: $trace_dir"
            exit 1
        fi
    done
    ensure_exec "$TOOL_PY"
    for tag in "$SELECT_BASE_TAG" "$BASELINE_TAG" "$IDEAL_DEMAND_TAG" "$IDEAL_L1PREF_TAG" "$IDEAL_ALL_TAG"; do
        ensure_exec "$(build_script "$tag")"
        ensure_exec "$(run_script "$tag")"
    done
}

do_build_config() {
    local tag="$1"
    echo "[STEP] build $tag"
    COMPARE_TAG="$COMPARE_TAG" TRACE_DIRS="$TRACE_DIRS" "$(build_script "$tag")"
}

do_run_config() {
    local tag="$1"
    local p=${2:-$MAX_PARALLEL}
    local select_json=${3:-}
    echo "[STEP] run $tag (parallel=$p)"
    COMPARE_TAG="$COMPARE_TAG" TRACE_DIRS="$TRACE_DIRS" MAX_PARALLEL="$p" SKIP_EXISTING="$SKIP_EXISTING" DO_BUILD=0 N_WARM="$N_WARM" N_SIM="$N_SIM" \
        TRACE_FILTER="$TRACE_FILTER" SELECT_TRACE_JSON="$select_json" "$(run_script "$tag")" "$p" "$TRACE_FILTER"
}

do_build_all() {
    do_build_config "$BASELINE_TAG"
    do_build_config "$IDEAL_DEMAND_TAG"
    do_build_config "$IDEAL_L1PREF_TAG"
    do_build_config "$IDEAL_ALL_TAG"
}

do_run_all() {
    local p=${1:-$MAX_PARALLEL}
    local selected
    selected="$(require_select_trace_json)"
    do_run_config "$BASELINE_TAG" "$p" "$selected"
    do_run_config "$IDEAL_DEMAND_TAG" "$p" "$selected"
    do_run_config "$IDEAL_L1PREF_TAG" "$p" "$selected"
    do_run_config "$IDEAL_ALL_TAG" "$p" "$selected"
}

do_select_json() {
    echo "[STEP] select traces by nopref STLB MPKI > ${SELECT_THRESHOLD}"
    python3 "$TOOL_PY" select-trace-json \
        --result-dir "$(result_dir "$SELECT_BASE_TAG")" \
        --out-json "$(select_trace_json)" \
        --threshold "$SELECT_THRESHOLD"
}

do_csv_config() {
    local tag="$1"
    local prefix="$2"
    local select_json="$3"
    local title="$4"
    local out_dir
    out_dir=$(csv_dir "$tag")
    mkdir -p "$out_dir"
    echo "[STEP] CSV/figures $tag -> ${FLOW_TAG}"
    python3 "$TOOL_PY" single-config \
        --result-dir "$(result_dir "$tag")" \
        --select-trace-json "$select_json" \
        --trace-level-csv "$(trace_csv "$tag" "$prefix")" \
        --workload-csv "$(workload_csv "$tag" "$prefix")" \
        --fig-png "${out_dir}/${prefix}_stlb_miss_causes.png" \
        --fig-pdf "${out_dir}/${prefix}_stlb_miss_causes.pdf" \
        --figure-title "$title"
}

do_csv_all_for_flow() {
    local select_json="$1"
    do_csv_config "$BASELINE_TAG" "baseline" "$select_json" "baseline pref STLB miss causes"
    do_csv_config "$IDEAL_DEMAND_TAG" "ideal_demand" "$select_json" "ideal demand STLB miss causes"
    do_csv_config "$IDEAL_L1PREF_TAG" "ideal_l1pref" "$select_json" "ideal L1 prefetch STLB miss causes"
    do_csv_config "$IDEAL_ALL_TAG" "ideal_all" "$select_json" "ideal all STLB miss causes"
}

do_ideal_compare() {
    local out_dir
    out_dir="$(flow_root)/data_process_for_compare"
    mkdir -p "$out_dir"
    echo "[STEP] ideal STLB IPC upper-bound compare (${FLOW_TAG})"
    python3 "$TOOL_PY" compare-ideal \
        --baseline-csv "$(workload_csv "$BASELINE_TAG" baseline)" \
        --ideal-demand-csv "$(workload_csv "$IDEAL_DEMAND_TAG" ideal_demand)" \
        --ideal-l1pref-csv "$(workload_csv "$IDEAL_L1PREF_TAG" ideal_l1pref)" \
        --ideal-all-csv "$(workload_csv "$IDEAL_ALL_TAG" ideal_all)" \
        --out-csv "${out_dir}/ideal_stlb_ipc_upperbound_compare.csv" \
        --fig-png "${out_dir}/ideal_stlb_ipc_upperbound_compare.png" \
        --fig-pdf "${out_dir}/ideal_stlb_ipc_upperbound_compare.pdf" \
        --figure-title "Ideal STLB IPC upper bound"
}

do_backend() {
    local selected
    selected="$(require_select_trace_json)"
    do_csv_all_for_flow "$selected"
    do_ideal_compare
}

do_full_backend() {
    echo "[INFO] full_trace backend is disabled in ${COMPARE_TAG}; this flow only reports selected traces."
}

show_status() {
    echo "========== SPEC06+SPEC17+GAP+Ligra+QMM+PARSEC+XSBench IDEAL STLB IPC UPPERBOUND STATUS =========="
    echo "CHAMPSIM_ROOT : $CHAMPSIM_ROOT"
    echo "COMPARE_TAG   : $COMPARE_TAG"
    echo "TRACE_DIRS    : $TRACE_DIRS"
    echo "TRACE_FILTER  : ${TRACE_FILTER:-<none>}"
    echo "MAX_PARALLEL  : $MAX_PARALLEL"
    echo "N_WARM        : $N_WARM"
    echo "N_SIM         : $N_SIM"
    echo "SKIP_EXISTING : $SKIP_EXISTING"
    echo "THRESHOLD     : $SELECT_THRESHOLD"
    echo "SELECT_MODE   : preselected JSON; default all/run-only skip nopref"
    echo "SELECT_JSON   : $(select_trace_json)"
    echo "SELECT_BASE   : $(result_dir "$SELECT_BASE_TAG") (optional, only for select-json/run-nopref)"
    echo "NOPREF        : $(result_dir "$SELECT_BASE_TAG") (not used by default)"
    echo "BASELINE      : $(result_dir "$BASELINE_TAG")"
    echo "IDEAL_DEMAND  : $(result_dir "$IDEAL_DEMAND_TAG")"
    echo "IDEAL_L1PREF  : $(result_dir "$IDEAL_L1PREF_TAG")"
    echo "IDEAL_ALL     : $(result_dir "$IDEAL_ALL_TAG")"
    echo "CSV_ROOT      : $(flow_root)"
    echo "================================================================="
}

cmd=${1:-all}
if [ "$cmd" = "all" ] && [ -n "${2:-}" ]; then
    MAX_PARALLEL="$2"
fi

case "$cmd" in
    all)
        check_env
        do_build_all
        do_run_all "$MAX_PARALLEL"
        do_backend
        ;;
    build-only)
        check_env
        do_build_all
        ;;
    run-only)
        check_env
        do_run_all "${2:-$MAX_PARALLEL}"
        ;;
    select-json)
        check_env
        do_select_json
        ;;
    backend|figures)
        check_env
        do_backend
        ;;
    full-backend|full-trace)
        check_env
        do_full_backend
        ;;
    backend-all)
        check_env
        do_backend
        ;;
    compare)
        check_env
        do_ideal_compare
        ;;
    build-baseline|build-pref)
        check_env
        do_build_config "$BASELINE_TAG"
        ;;
    build-nopref)
        check_env
        do_build_config "$SELECT_BASE_TAG"
        ;;
    build-demand)
        check_env
        do_build_config "$IDEAL_DEMAND_TAG"
        ;;
    build-l1pref)
        check_env
        do_build_config "$IDEAL_L1PREF_TAG"
        ;;
    build-allideal)
        check_env
        do_build_config "$IDEAL_ALL_TAG"
        ;;
    run-baseline|run-pref)
        check_env
        do_run_config "$BASELINE_TAG" "${2:-$MAX_PARALLEL}" "$(require_select_trace_json)"
        ;;
    run-nopref)
        check_env
        do_run_config "$SELECT_BASE_TAG" "${2:-$MAX_PARALLEL}"
        ;;
    run-demand)
        check_env
        do_run_config "$IDEAL_DEMAND_TAG" "${2:-$MAX_PARALLEL}" "$(require_select_trace_json)"
        ;;
    run-l1pref)
        check_env
        do_run_config "$IDEAL_L1PREF_TAG" "${2:-$MAX_PARALLEL}" "$(require_select_trace_json)"
        ;;
    run-allideal)
        check_env
        do_run_config "$IDEAL_ALL_TAG" "${2:-$MAX_PARALLEL}" "$(require_select_trace_json)"
        ;;
    status)
        show_status
        ;;
    clean-csv)
        echo "[STEP] clean csv outputs: ${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}"
        rm -rf "${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}"
        ;;
    *)
        echo "Usage: $0 {all [p]|build-only|run-only [p]|select-json|backend|figures|full-backend|full-trace|backend-all|compare|build-nopref|build-baseline|build-pref|build-demand|build-l1pref|build-allideal|run-nopref [p]|run-baseline [p]|run-pref [p]|run-demand [p]|run-l1pref [p]|run-allideal [p]|clean-csv|status}"
        exit 1
        ;;
esac

echo "[DONE] command '$cmd' completed"
