#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
CHAMPSIM_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)
TRACE="${TRACE:-/data2/zcq/champsim_traces_xsbench/xs.XXL64hash-205B.champsimtrace.xz}"
BINARY="${CHAMPSIM_ROOT}/bin/xs.XXL64hash-205B-demand-tlb-pattern-1core"
TEST_WARM="${TEST_WARM:-100000}"
TEST_SIM="${TEST_SIM:-200000}"

if [ ! -x "$BINARY" ]; then
    echo "[ERROR] Missing binary: $BINARY" >&2
    exit 1
fi

mkdir -p "${CASE_DIR}/result/validation"
validation_dir=$(mktemp -d "${CASE_DIR}/result/validation/baseline-equivalence.XXXXXX")
baseline_log="${validation_dir}/baseline.log"
enabled_log="${validation_dir}/enabled.log"
pattern_dir="${validation_dir}/enabled_pattern"
forbidden_dir="${validation_dir}/baseline_must_not_exist"

"$BINARY" \
    --warmup-instructions "$TEST_WARM" \
    --simulation-instructions "$TEST_SIM" \
    --hide-heartbeat \
    --demand-tlb-pattern-output "$forbidden_dir" \
    "$TRACE" > "$baseline_log"

if [ -e "$forbidden_dir" ]; then
    echo "[ERROR] Logger-disabled run unexpectedly created output." >&2
    exit 1
fi

"$BINARY" \
    --warmup-instructions "$TEST_WARM" \
    --simulation-instructions "$TEST_SIM" \
    --hide-heartbeat \
    --demand-tlb-pattern \
    --demand-tlb-pattern-output "$pattern_dir" \
    "$TRACE" > "$enabled_log"

python3 "${SCRIPT_DIR}/compare_simulation_logs.py" "$baseline_log" "$enabled_log"
python3 "${SCRIPT_DIR}/validate_demand_tlb_pattern.py" \
    --input "${pattern_dir}/demand_tlb_pattern_core_0.csv" \
    --metadata "${pattern_dir}/metadata.json" \
    --logger-summary "${pattern_dir}/logger_summary.txt"

echo "[PASS] Baseline isolation outputs: $validation_dir"
