#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
CHAMPSIM_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)
TRACE="${TRACE:-/data0/tzh/champsim_traces/SPEC06/433.milc-127B.champsimtrace.xz}"
BINARY="${CHAMPSIM_ROOT}/bin/433.milc-127B-demand-tlb-pattern-permit-pgc-1core"
TEST_WARM="${TEST_WARM:-100000}"
TEST_SIM="${TEST_SIM:-200000}"

if [ ! -x "$BINARY" ]; then
    echo "[ERROR] Missing binary: $BINARY" >&2
    exit 1
fi

mkdir -p "${CASE_DIR}/result/validation"
validation_dir=$(mktemp -d "${CASE_DIR}/result/validation/baseline-equivalence.XXXXXX")
baseline_log="${validation_dir}/baseline.log"
demand_only_log="${validation_dir}/demand_only.log"
combined_enabled_log="${validation_dir}/combined_enabled.log"
demand_only_dir="${validation_dir}/demand_only_pattern"
combined_demand_dir="${validation_dir}/combined_demand_pattern"
combined_pattern_dir="${validation_dir}/unified_dtlb_access"
combined_stlb_access_dir="${validation_dir}/unified_stlb_access"
combined_stlb_miss_dir="${validation_dir}/unified_stlb_miss"
combined_figure_dir="${validation_dir}/dtlb_access_figures"
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
    --demand-tlb-pattern-output "$demand_only_dir" \
    "$TRACE" > "$demand_only_log"

env \
    DUMP_VBERTI_CROSS_PAGE_DEMAND_PATTERN=1 \
    DUMP_VBERTI_CROSS_PAGE_DEMAND_PATTERN_OUTPUT="$combined_pattern_dir" \
    "$BINARY" \
    --warmup-instructions "$TEST_WARM" \
    --simulation-instructions "$TEST_SIM" \
    --hide-heartbeat \
    --demand-tlb-pattern \
    --demand-tlb-pattern-output "$combined_demand_dir" \
    "$TRACE" > "$combined_enabled_log"

python3 "${SCRIPT_DIR}/compare_simulation_logs.py" "$baseline_log" "$demand_only_log"
python3 "${SCRIPT_DIR}/compare_simulation_logs.py" "$demand_only_log" "$combined_enabled_log"
cmp "${demand_only_dir}/demand_tlb_pattern_core_0.csv" "${combined_demand_dir}/demand_tlb_pattern_core_0.csv"
cmp "${demand_only_dir}/logger_summary.txt" "${combined_demand_dir}/logger_summary.txt"
python3 "${SCRIPT_DIR}/validate_demand_tlb_pattern.py" \
    --input "${combined_demand_dir}/demand_tlb_pattern_core_0.csv" \
    --metadata "${combined_demand_dir}/metadata.json" \
    --logger-summary "${combined_demand_dir}/logger_summary.txt"
python3 "${SCRIPT_DIR}/validate_demand_tlb_pattern.py" \
    --input "${combined_pattern_dir}/tlb_pattern_core_0.csv" \
    --metadata "${combined_pattern_dir}/metadata.json" \
    --logger-summary "${combined_pattern_dir}/logger_summary.txt"
python3 "${SCRIPT_DIR}/prepare_tlb_pattern_streams.py" \
    --input "${combined_pattern_dir}/tlb_pattern_core_0.csv" \
    --source-metadata "${combined_pattern_dir}/metadata.json" \
    --dtlb-ordered-output "${combined_pattern_dir}/tlb_pattern_core_0_global_seq_ordered.csv" \
    --stlb-access-dir "$combined_stlb_access_dir" \
    --stlb-miss-dir "$combined_stlb_miss_dir"
python3 "${SCRIPT_DIR}/analyze_demand_tlb_pattern.py" \
    --input "${combined_pattern_dir}/tlb_pattern_core_0_global_seq_ordered.csv" \
    --metadata "${combined_pattern_dir}/metadata.json" \
    --output-dir "$combined_figure_dir" \
    --stream-kind dtlb_access \
    --coarse-bin-size 10000

echo "[PASS] Default-off isolation, existing-demand-stream equivalence, and unified-pattern validation: $validation_dir"
