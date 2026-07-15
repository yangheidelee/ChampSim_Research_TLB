#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
DTLB_RESULT_DIR="${CASE_DIR}/result/dtlb_access"
STLB_ACCESS_RESULT_DIR="${CASE_DIR}/result/stlb_access"
STLB_MISS_RESULT_DIR="${CASE_DIR}/result/stlb_miss"
OUTPUT_ROOT="${CASE_DIR}/csv_figure"

input_csv="${DTLB_RESULT_DIR}/demand_tlb_pattern_core_0.csv"
metadata="${DTLB_RESULT_DIR}/metadata.json"
summary="${DTLB_RESULT_DIR}/logger_summary.txt"

for required in "$input_csv" "$metadata" "$summary"; do
    if [ ! -s "$required" ]; then
        echo "[ERROR] Missing pattern input: $required" >&2
        exit 1
    fi
done

header=$(head -n 1 "$input_csv")
has_physical_fields=1
for field in pa ppn physical_region_2m page_offset_in_physical_region physical_address_valid; do
    if [[ ",$header," != *",$field,"* ]]; then
        has_physical_fields=0
        break
    fi
done

mkdir -p "$OUTPUT_ROOT/dtlb_access" "$OUTPUT_ROOT/stlb_access" "$OUTPUT_ROOT/stlb_miss"
if [ "$has_physical_fields" -eq 1 ]; then
    mkdir -p "$OUTPUT_ROOT/dtlb_access_ppn" "$OUTPUT_ROOT/stlb_access_ppn" "$OUTPUT_ROOT/stlb_miss_ppn"
fi

python3 "${SCRIPT_DIR}/validate_demand_tlb_pattern.py" \
    --input "$input_csv" \
    --metadata "$metadata" \
    --logger-summary "$summary"

python3 "${SCRIPT_DIR}/prepare_tlb_pattern_streams.py" \
    --input "$input_csv" \
    --source-metadata "$metadata" \
    --stlb-access-dir "$STLB_ACCESS_RESULT_DIR" \
    --stlb-miss-dir "$STLB_MISS_RESULT_DIR"

common_analysis_args=(
    --coarse-bin-size "${COARSE_BIN_SIZE:-50000}"
    --top-pcs "${TOP_PCS:-32}"
    --pc-rank-by "${PC_RANK_BY:-stlb_miss}"
    --delta-limit "${DELTA_LIMIT:-16}"
    --wide-delta-limit "${WIDE_DELTA_LIMIT:-64}"
)

if [ -n "${SEQ_START:-}" ]; then
    common_analysis_args+=(--seq-start "$SEQ_START")
fi
if [ -n "${SEQ_END:-}" ]; then
    common_analysis_args+=(--seq-end "$SEQ_END")
fi

virtual_analysis_args=("${common_analysis_args[@]}")
physical_analysis_args=("${common_analysis_args[@]}")
if [ -n "${REGION_ID:-}" ]; then
    virtual_analysis_args+=(--region-id "$REGION_ID")
fi
if [ -n "${PHYSICAL_REGION_ID:-}" ]; then
    physical_analysis_args+=(--region-id "$PHYSICAL_REGION_ID")
fi
python3 "${SCRIPT_DIR}/analyze_demand_tlb_pattern.py" \
    --input "$input_csv" --metadata "$metadata" \
    --output-dir "$OUTPUT_ROOT/dtlb_access" --stream-kind dtlb_access \
    --address-space virtual "${virtual_analysis_args[@]}"
python3 "${SCRIPT_DIR}/analyze_demand_tlb_pattern.py" \
    --input "$STLB_ACCESS_RESULT_DIR/stlb_access_core_0.csv" --metadata "$STLB_ACCESS_RESULT_DIR/metadata.json" \
    --output-dir "$OUTPUT_ROOT/stlb_access" --stream-kind stlb_access \
    --address-space virtual "${virtual_analysis_args[@]}"
python3 "${SCRIPT_DIR}/analyze_demand_tlb_pattern.py" \
    --input "$STLB_MISS_RESULT_DIR/stlb_miss_core_0.csv" --metadata "$STLB_MISS_RESULT_DIR/metadata.json" \
    --output-dir "$OUTPUT_ROOT/stlb_miss" --stream-kind stlb_miss \
    --address-space virtual "${virtual_analysis_args[@]}"

echo "[DONE] VPN figures/tables: $OUTPUT_ROOT/{dtlb_access,stlb_access,stlb_miss}"
if [ "$has_physical_fields" -eq 1 ]; then
    python3 "${SCRIPT_DIR}/analyze_demand_tlb_pattern.py" \
        --input "$input_csv" --metadata "$metadata" \
        --output-dir "$OUTPUT_ROOT/dtlb_access_ppn" --stream-kind dtlb_access \
        --address-space physical "${physical_analysis_args[@]}"
    python3 "${SCRIPT_DIR}/analyze_demand_tlb_pattern.py" \
        --input "$STLB_ACCESS_RESULT_DIR/stlb_access_core_0.csv" --metadata "$STLB_ACCESS_RESULT_DIR/metadata.json" \
        --output-dir "$OUTPUT_ROOT/stlb_access_ppn" --stream-kind stlb_access \
        --address-space physical "${physical_analysis_args[@]}"
    python3 "${SCRIPT_DIR}/analyze_demand_tlb_pattern.py" \
        --input "$STLB_MISS_RESULT_DIR/stlb_miss_core_0.csv" --metadata "$STLB_MISS_RESULT_DIR/metadata.json" \
        --output-dir "$OUTPUT_ROOT/stlb_miss_ppn" --stream-kind stlb_miss \
        --address-space physical "${physical_analysis_args[@]}"
    echo "[DONE] PPN figures/tables: $OUTPUT_ROOT/{dtlb_access_ppn,stlb_access_ppn,stlb_miss_ppn}"
else
    echo "[WARN] Existing raw stream has no PPN fields; PPN postprocessing was skipped." >&2
    echo "[WARN] VPN/DTLB/STLB results are complete. Re-run simulation with current instrumentation only if PPN figures are required." >&2
fi
