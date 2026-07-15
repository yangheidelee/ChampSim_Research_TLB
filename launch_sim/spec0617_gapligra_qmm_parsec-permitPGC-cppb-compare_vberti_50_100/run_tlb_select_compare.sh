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
PERMIT_TAG="pref-workload-sweep"
CPPB_TAG="pref-cppb-workload-sweep"
TLB_RESCUE_TAG="tlb-rescue-workload-sweep"
CPPB_TLB_RESCUE_TAG="pref-cppb-tlb-rescue-workload-sweep"

MAX_PARALLEL=${MAX_PARALLEL:-4}
TRACE_DIRS=${TRACE_DIRS:-/data0/tzh/champsim_traces/SPEC06:/data0/tzh/champsim_traces/SPEC17:/data2/zcq/champsim_traces_gap:/data0/tzh/champsim_traces/Ligra:/data0/tzh/champsim_traces/QMM:/data0/tzh/champsim_traces/PARSEC:/data2/zcq/champsim_traces_xsbench}
N_WARM=${N_WARM:-50}
N_SIM=${N_SIM:-100}
SKIP_EXISTING=${SKIP_EXISTING:-1}
TRACE_FILTER=${TRACE_FILTER:-${BENCH_FILTER:-}}
SELECT_SET=${SELECT_SET:-stlb}
SELECT_TRACE_JSON=${SELECT_TRACE_JSON:-}
FLOW_TAG=${FLOW_TAG:-}

PERMIT_DIR="${SCRIPT_DIR}/${PERMIT_TAG}"
CPPB_DIR="${SCRIPT_DIR}/${CPPB_TAG}"
TLB_RESCUE_DIR="${SCRIPT_DIR}/${TLB_RESCUE_TAG}"
CPPB_TLB_RESCUE_DIR="${SCRIPT_DIR}/${CPPB_TLB_RESCUE_TAG}"
DP_DIR="${SCRIPT_DIR}/data_process_for_compare"
SELECT_DIR="${SCRIPT_DIR}/selected_traces"
TOOL_PY="${DP_DIR}/tlb_select_tools.py"

BUILD_PERMIT="${PERMIT_DIR}/build_champsim.sh"
BUILD_CPPB="${CPPB_DIR}/build_champsim.sh"
BUILD_TLB_RESCUE="${TLB_RESCUE_DIR}/build_champsim.sh"
BUILD_CPPB_TLB_RESCUE="${CPPB_TLB_RESCUE_DIR}/build_champsim.sh"
RUN_PERMIT="${PERMIT_DIR}/launch_workload_sweep.sh"
RUN_CPPB="${CPPB_DIR}/launch_workload_sweep.sh"
RUN_TLB_RESCUE="${TLB_RESCUE_DIR}/launch_workload_sweep.sh"
RUN_CPPB_TLB_RESCUE="${CPPB_TLB_RESCUE_DIR}/launch_workload_sweep.sh"

default_select_trace_json() {
    case "$SELECT_SET" in
        stlb|stlb-mpki|stlb_mpki)
            echo "${SELECT_DIR}/stlb_mpki_gt_1.0_selected_traces.json"
            ;;
        llc|llc-spec|llc_spec|spec-llc|spec_llc)
            echo "${SELECT_DIR}/llc_mpki_gt_1.0_spec_selected_traces.json"
            ;;
        *)
            echo "[ERROR] Unknown SELECT_SET=${SELECT_SET}. Use stlb or llc-spec." >&2
            exit 1
            ;;
    esac
}

effective_select_trace_json() {
    if [ -n "$SELECT_TRACE_JSON" ]; then
        echo "$SELECT_TRACE_JSON"
    else
        default_select_trace_json
    fi
}

effective_flow_tag() {
    if [ -n "$FLOW_TAG" ]; then
        echo "$FLOW_TAG"
        return
    fi
    case "$SELECT_SET" in
        stlb|stlb-mpki|stlb_mpki)
            echo "stlb_mpki_gt_1_select_trace"
            ;;
        llc|llc-spec|llc_spec|spec-llc|spec_llc)
            echo "spec_llc_mpki_gt_1_select_trace"
            ;;
        *)
            echo "custom_select_trace"
            ;;
    esac
}

flow_root() {
    echo "${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/$(effective_flow_tag)"
}

require_select_trace_json() {
    local selected
    selected="$(effective_select_trace_json)"
    if [ ! -f "$selected" ]; then
        echo "[ERROR] Selected trace JSON not found: $selected" >&2
        echo "[ERROR] Use SELECT_SET=stlb, SELECT_SET=llc-spec, or SELECT_TRACE_JSON=/path/to/json." >&2
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

check_env() {
    IFS=':' read -r -a dirs <<< "$TRACE_DIRS"
    for trace_dir in "${dirs[@]}"; do
        if [ ! -d "$trace_dir" ]; then
            echo "[ERROR] TRACE_DIR not found: $trace_dir"
            exit 1
        fi
    done
    require_select_trace_json >/dev/null
    ensure_exec "$BUILD_PERMIT"
    ensure_exec "$BUILD_CPPB"
    ensure_exec "$BUILD_TLB_RESCUE"
    ensure_exec "$BUILD_CPPB_TLB_RESCUE"
    ensure_exec "$RUN_PERMIT"
    ensure_exec "$RUN_CPPB"
    ensure_exec "$RUN_TLB_RESCUE"
    ensure_exec "$RUN_CPPB_TLB_RESCUE"
    ensure_exec "$TOOL_PY"
}

do_build_permit() {
    echo "[STEP] build permit PGC"
    TRACE_DIRS="$TRACE_DIRS" "$BUILD_PERMIT"
}

do_build_cppb() {
    echo "[STEP] build permit PGC + CP-PB"
    TRACE_DIRS="$TRACE_DIRS" "$BUILD_CPPB"
}

do_build_tlb_rescue() {
    echo "[STEP] build permit PGC + ordered TLB rescue"
    TRACE_DIRS="$TRACE_DIRS" "$BUILD_TLB_RESCUE"
}

do_build_cppb_tlb_rescue() {
    echo "[STEP] build permit PGC + CP-PB + ordered TLB rescue"
    TRACE_DIRS="$TRACE_DIRS" "$BUILD_CPPB_TLB_RESCUE"
}

do_run_config() {
    local tag="$1"
    local run_script="$2"
    local label="$3"
    local p=${4:-$MAX_PARALLEL}
    local selected
    selected="$(require_select_trace_json)"
    echo "[STEP] run ${label} selected traces (parallel=$p)"
    TRACE_DIRS="$TRACE_DIRS" MAX_PARALLEL="$p" SKIP_EXISTING="$SKIP_EXISTING" DO_BUILD=0 N_WARM="$N_WARM" N_SIM="$N_SIM" \
        TRACE_FILTER="$TRACE_FILTER" SELECT_TRACE_JSON="$selected" "$run_script" "$p" "$TRACE_FILTER"
}

do_run_permit() {
    do_run_config "$PERMIT_TAG" "$RUN_PERMIT" "permit PGC" "${1:-$MAX_PARALLEL}"
}

do_run_cppb() {
    do_run_config "$CPPB_TAG" "$RUN_CPPB" "permit PGC + CP-PB" "${1:-$MAX_PARALLEL}"
}

do_run_tlb_rescue() {
    do_run_config "$TLB_RESCUE_TAG" "$RUN_TLB_RESCUE" "permit PGC + ordered TLB rescue" "${1:-$MAX_PARALLEL}"
}

do_run_cppb_tlb_rescue() {
    do_run_config "$CPPB_TLB_RESCUE_TAG" "$RUN_CPPB_TLB_RESCUE" "permit PGC + CP-PB + ordered TLB rescue" "${1:-$MAX_PARALLEL}"
}

result_dir() {
    local config_tag="$1"
    echo "${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${config_tag}"
}

config_csv_dir() {
    local config_tag="$1"
    echo "$(flow_root)/${config_tag}"
}

trace_csv() {
    local config_tag="$1"
    local prefix="$2"
    echo "$(config_csv_dir "$config_tag")/${prefix}_trace_level.csv"
}

workload_csv() {
    local config_tag="$1"
    local prefix="$2"
    echo "$(config_csv_dir "$config_tag")/${prefix}_workload_summary.csv"
}

do_csv_config() {
    local config_tag="$1"
    local prefix="$2"
    local title="$3"
    local selected
    selected="$(require_select_trace_json)"
    echo "[STEP] ${title} CSV/figures"
    python3 "$TOOL_PY" single-config \
        --result-dir "$(result_dir "$config_tag")" \
        --select-trace-json "$selected" \
        --trace-level-csv "$(trace_csv "$config_tag" "$prefix")" \
        --workload-csv "$(workload_csv "$config_tag" "$prefix")" \
        --fig-png "$(config_csv_dir "$config_tag")/${prefix}_stlb_miss_causes.png" \
        --fig-pdf "$(config_csv_dir "$config_tag")/${prefix}_stlb_miss_causes.pdf" \
        --figure-title "${title}: STLB miss causes" \
        --mpki-fig-png "$(config_csv_dir "$config_tag")/${prefix}_stlb_mpki.png" \
        --mpki-fig-pdf "$(config_csv_dir "$config_tag")/${prefix}_stlb_mpki.pdf" \
        --mpki-figure-title "${title}: STLB MPKI"
}

do_csv_permit() {
    do_csv_config "$PERMIT_TAG" "permit_pgc" "Permit PGC"
}

do_csv_cppb() {
    do_csv_config "$CPPB_TAG" "permit_pgc_cppb" "Permit PGC + CP-PB"
}

do_csv_tlb_rescue() {
    do_csv_config "$TLB_RESCUE_TAG" "permit_pgc_tlb_rescue" "Permit PGC + Ordered TLB Rescue"
}

do_csv_cppb_tlb_rescue() {
    do_csv_config "$CPPB_TLB_RESCUE_TAG" "permit_pgc_cppb_tlb_rescue" "Permit PGC + CP-PB + Ordered TLB Rescue"
}

do_compare() {
    local out_dir
    out_dir="$(flow_root)/data_process_for_compare"
    echo "[STEP] permit PGC vs permit PGC + CP-PB compare"
    python3 "$TOOL_PY" compare-permit-cppb \
        --permit-trace-csv "$(trace_csv "$PERMIT_TAG" "permit_pgc")" \
        --cppb-trace-csv "$(trace_csv "$CPPB_TAG" "permit_pgc_cppb")" \
        --out-csv "${out_dir}/permit_pgc_cppb_vs_permit_pgc_compare.csv" \
        --trace-out-csv "${out_dir}/permit_pgc_cppb_vs_permit_pgc_trace_compare.csv" \
        --ipc-fig-png "${out_dir}/permit_pgc_cppb_vs_permit_pgc_ipc_speedup.png" \
        --ipc-fig-pdf "${out_dir}/permit_pgc_cppb_vs_permit_pgc_ipc_speedup.pdf" \
        --stlb-fig-png "${out_dir}/permit_pgc_cppb_vs_permit_pgc_stlb_demand_mpki_reduction.png" \
        --stlb-fig-pdf "${out_dir}/permit_pgc_cppb_vs_permit_pgc_stlb_demand_mpki_reduction.pdf"
}

do_compare_multi() {
    local out_dir
    out_dir="$(flow_root)/data_process_for_compare"
    echo "[STEP] permit PGC baseline multi-config compare"
    python3 "$TOOL_PY" compare-permit-multi \
        --permit-trace-csv "$(trace_csv "$PERMIT_TAG" "permit_pgc")" \
        --cppb-trace-csv "$(trace_csv "$CPPB_TAG" "permit_pgc_cppb")" \
        --tlb-rescue-trace-csv "$(trace_csv "$TLB_RESCUE_TAG" "permit_pgc_tlb_rescue")" \
        --cppb-tlb-rescue-trace-csv "$(trace_csv "$CPPB_TLB_RESCUE_TAG" "permit_pgc_cppb_tlb_rescue")" \
        --out-csv "${out_dir}/permit_pgc_baseline_multi_compare.csv" \
        --trace-out-csv "${out_dir}/permit_pgc_baseline_multi_trace_compare.csv" \
        --selected-trace-count-csv "${out_dir}/permit_pgc_baseline_multi_selected_trace_count.csv" \
        --ipc-fig-png "${out_dir}/permit_pgc_baseline_multi_ipc_compare.png" \
        --ipc-fig-pdf "${out_dir}/permit_pgc_baseline_multi_ipc_compare.pdf" \
        --stlb-fig-png "${out_dir}/permit_pgc_baseline_multi_stlb_demand_mpki_reduction.png" \
        --stlb-fig-pdf "${out_dir}/permit_pgc_baseline_multi_stlb_demand_mpki_reduction.pdf"
}

do_compare_multi_dtlb() {
    local out_dir selected
    out_dir="$(flow_root)/data_process_for_compare"
    selected="$(require_select_trace_json)"
    echo "[STEP] permit PGC baseline multi-config DTLB real-demand compare"
    python3 "$TOOL_PY" compare-permit-multi-dtlb \
        --permit-result-dir "$(result_dir "$PERMIT_TAG")" \
        --cppb-result-dir "$(result_dir "$CPPB_TAG")" \
        --tlb-rescue-result-dir "$(result_dir "$TLB_RESCUE_TAG")" \
        --cppb-tlb-rescue-result-dir "$(result_dir "$CPPB_TLB_RESCUE_TAG")" \
        --select-trace-json "$selected" \
        --out-csv "${out_dir}/permit_pgc_baseline_multi_dtlb_real_demand_compare.csv" \
        --trace-out-csv "${out_dir}/permit_pgc_baseline_multi_dtlb_real_demand_trace_compare.csv" \
        --selected-trace-count-csv "${out_dir}/permit_pgc_baseline_multi_dtlb_real_demand_selected_trace_count.csv" \
        --fig-png "${out_dir}/permit_pgc_baseline_multi_dtlb_real_demand_mpki_reduction.png" \
        --fig-pdf "${out_dir}/permit_pgc_baseline_multi_dtlb_real_demand_mpki_reduction.pdf"
}

show_status() {
    echo "========== PERMIT PGC vs PERMIT PGC + CP-PB STATUS =========="
    echo "CHAMPSIM_ROOT : $CHAMPSIM_ROOT"
    echo "COMPARE_TAG   : $COMPARE_TAG"
    echo "TRACE_DIRS    : $TRACE_DIRS"
    echo "TRACE_FILTER  : ${TRACE_FILTER:-<none>}"
    echo "MAX_PARALLEL  : $MAX_PARALLEL"
    echo "N_WARM        : $N_WARM"
    echo "N_SIM         : $N_SIM"
    echo "SKIP_EXISTING : $SKIP_EXISTING"
    echo "SELECT_SET    : $SELECT_SET"
    echo "SELECT_JSON   : $(effective_select_trace_json)"
    echo "FLOW_TAG      : $(effective_flow_tag)"
    echo "RESULT_PERMIT : $(result_dir "$PERMIT_TAG")"
    echo "RESULT_CPPB   : $(result_dir "$CPPB_TAG")"
    echo "RESULT_RESCUE : $(result_dir "$TLB_RESCUE_TAG")"
    echo "RESULT_CPPB_R : $(result_dir "$CPPB_TLB_RESCUE_TAG")"
    echo "CSV_ROOT      : $(flow_root)"
    echo "============================================================="
}

cmd=${1:-all}
if [ "$cmd" = "all" ] && [ -n "${2:-}" ]; then
    MAX_PARALLEL="$2"
fi

case "$cmd" in
    all)
        check_env
        do_build_permit
        do_build_cppb
        do_build_tlb_rescue
        do_build_cppb_tlb_rescue
        do_run_permit "$MAX_PARALLEL"
        do_run_cppb "$MAX_PARALLEL"
        do_run_tlb_rescue "$MAX_PARALLEL"
        do_run_cppb_tlb_rescue "$MAX_PARALLEL"
        do_csv_permit
        do_csv_cppb
        do_csv_tlb_rescue
        do_csv_cppb_tlb_rescue
        do_compare
        do_compare_multi
        do_compare_multi_dtlb
        ;;
    build-only)
        check_env
        do_build_permit
        do_build_cppb
        do_build_tlb_rescue
        do_build_cppb_tlb_rescue
        ;;
    run-only)
        check_env
        do_run_permit "${2:-$MAX_PARALLEL}"
        do_run_cppb "${2:-$MAX_PARALLEL}"
        do_run_tlb_rescue "${2:-$MAX_PARALLEL}"
        do_run_cppb_tlb_rescue "${2:-$MAX_PARALLEL}"
        ;;
    backend|figures)
        check_env
        do_csv_permit
        do_csv_cppb
        do_csv_tlb_rescue
        do_csv_cppb_tlb_rescue
        do_compare
        do_compare_multi
        do_compare_multi_dtlb
        ;;
    compare)
        check_env
        do_compare
        ;;
    build-permit|build-pref)
        check_env
        do_build_permit
        ;;
    build-cppb)
        check_env
        do_build_cppb
        ;;
    build-tlb-rescue|build-rescue)
        check_env
        do_build_tlb_rescue
        ;;
    build-cppb-tlb-rescue|build-cppb-rescue)
        check_env
        do_build_cppb_tlb_rescue
        ;;
    run-permit|run-pref)
        check_env
        do_run_permit "${2:-$MAX_PARALLEL}"
        ;;
    run-cppb)
        check_env
        do_run_cppb "${2:-$MAX_PARALLEL}"
        ;;
    run-tlb-rescue|run-rescue)
        check_env
        do_run_tlb_rescue "${2:-$MAX_PARALLEL}"
        ;;
    run-cppb-tlb-rescue|run-cppb-rescue)
        check_env
        do_run_cppb_tlb_rescue "${2:-$MAX_PARALLEL}"
        ;;
    csv-permit|csv-pref)
        check_env
        do_csv_permit
        ;;
    csv-cppb)
        check_env
        do_csv_cppb
        ;;
    csv-tlb-rescue|csv-rescue)
        check_env
        do_csv_tlb_rescue
        ;;
    csv-cppb-tlb-rescue|csv-cppb-rescue)
        check_env
        do_csv_cppb_tlb_rescue
        ;;
    compare-multi)
        check_env
        do_compare_multi
        do_compare_multi_dtlb
        ;;
    status)
        show_status
        ;;
    clean-csv)
        echo "[STEP] clean csv outputs: ${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/$(effective_flow_tag)"
        rm -rf "$(flow_root)"
        ;;
    *)
        cat <<EOF
Usage: $0 [all|build-only|run-only|backend|compare|compare-multi|status|clean-csv] [MAX_PARALLEL]

Common environment:
  SELECT_SET=stlb      Use STLB MPKI > 1 selected traces. This is the default.
  SELECT_SET=llc-spec  Use SPEC06+SPEC17 traces selected by nopref LLC MPKI > 1.
  FLOW_TAG=name        Override csv_figure subdirectory name.
  SELECT_TRACE_JSON=p  Use a custom selected trace JSON.
  N_WARM=50 N_SIM=100 MAX_PARALLEL=15 SKIP_EXISTING=1

Examples:
  N_WARM=50 N_SIM=100 $0 all 15
  SELECT_SET=llc-spec N_WARM=50 N_SIM=100 $0 all 15
  SELECT_SET=stlb $0 backend
  $0 run-tlb-rescue 15
  $0 run-cppb-tlb-rescue 15
EOF
        exit 1
        ;;
esac
