#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CONFIG="${SCRIPT_DIR}/1C.no-data-prefetch.milc-pattern.json"
BINARY_NAME="milc-274B-demand-tlb-pattern-1core"
MODE="${1:-all}"

build() {
    "${SCRIPT_DIR}/build_one.sh" "$CONFIG" "$BINARY_NAME"
}

case "$MODE" in
    build)
        build
        ;;
    run)
        "${SCRIPT_DIR}/run_pattern.sh"
        ;;
    analyze)
        python3 "${SCRIPT_DIR}/test_analyze_demand_tlb_pattern.py"
        python3 "${SCRIPT_DIR}/test_prepare_tlb_pattern_streams.py"
        "${SCRIPT_DIR}/postprocess.sh"
        ;;
    test)
        build
        python3 "${SCRIPT_DIR}/test_analyze_demand_tlb_pattern.py"
        python3 "${SCRIPT_DIR}/test_prepare_tlb_pattern_streams.py"
        "${SCRIPT_DIR}/test_baseline_equivalence.sh"
        ;;
    smoke)
        build
        python3 "${SCRIPT_DIR}/test_analyze_demand_tlb_pattern.py"
        python3 "${SCRIPT_DIR}/test_prepare_tlb_pattern_streams.py"
        N_WARM="${N_WARM:-1}" N_SIM="${N_SIM:-2}" SKIP_EXISTING="${SKIP_EXISTING:-0}" "${SCRIPT_DIR}/run_pattern.sh"
        "${SCRIPT_DIR}/postprocess.sh"
        "${SCRIPT_DIR}/test_baseline_equivalence.sh"
        ;;
    all)
        build
        python3 "${SCRIPT_DIR}/test_analyze_demand_tlb_pattern.py"
        python3 "${SCRIPT_DIR}/test_prepare_tlb_pattern_streams.py"
        "${SCRIPT_DIR}/run_pattern.sh"
        "${SCRIPT_DIR}/postprocess.sh"
        ;;
    *)
        echo "Usage: $0 {all|build|run|analyze|test|smoke}" >&2
        exit 1
        ;;
esac
