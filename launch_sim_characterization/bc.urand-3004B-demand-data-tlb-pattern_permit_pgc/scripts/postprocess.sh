#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
DTLB_RESULT_DIR="${CASE_DIR}/result/dtlb_access"
DEMAND_ONLY_RESULT_DIR="${CASE_DIR}/result/demand_only_dtlb_access"
STLB_ACCESS_RESULT_DIR="${CASE_DIR}/result/stlb_access"
STLB_MISS_RESULT_DIR="${CASE_DIR}/result/stlb_miss"
OUTPUT_ROOT="${CASE_DIR}/csv_figure"

input_csv="${DTLB_RESULT_DIR}/tlb_pattern_core_0.csv"
ordered_input_csv="${DTLB_RESULT_DIR}/tlb_pattern_core_0_global_seq_ordered.csv"
metadata="${DTLB_RESULT_DIR}/metadata.json"
summary="${DTLB_RESULT_DIR}/logger_summary.txt"
demand_only_csv="${DEMAND_ONLY_RESULT_DIR}/demand_tlb_pattern_core_0.csv"
demand_only_metadata="${DEMAND_ONLY_RESULT_DIR}/metadata.json"
demand_only_summary="${DEMAND_ONLY_RESULT_DIR}/logger_summary.txt"

for required in "$input_csv" "$metadata" "$summary"; do
    if [ ! -s "$required" ]; then
        echo "[ERROR] Missing pattern input: $required" >&2
        exit 1
    fi
done

mkdir -p "$OUTPUT_ROOT/dtlb_access" "$OUTPUT_ROOT/stlb_access" "$OUTPUT_ROOT/stlb_miss"

# Remove outputs from the superseded standalone comparison and old secondary
# sequence views.  The current run regenerates one records CSV per stream on
# the shared global_seq axis.
rm -rf \
    "$OUTPUT_ROOT/vberti_prefetch_vs_demand" \
    "$OUTPUT_ROOT/dtlb_access_ppn" \
    "$OUTPUT_ROOT/stlb_access_ppn" \
    "$OUTPUT_ROOT/stlb_miss_ppn"
for output_dir in \
    "$OUTPUT_ROOT/dtlb_access" "$OUTPUT_ROOT/stlb_access" "$OUTPUT_ROOT/stlb_miss"; do
    rm -f "$output_dir"/02_local_page_offset_raster_records_*.csv
done

python3 "${SCRIPT_DIR}/validate_demand_tlb_pattern.py" \
    --input "$input_csv" \
    --metadata "$metadata" \
    --logger-summary "$summary"

if [ -s "$demand_only_csv" ] && [ -s "$demand_only_metadata" ] && [ -s "$demand_only_summary" ]; then
    python3 "${SCRIPT_DIR}/validate_demand_tlb_pattern.py" \
        --input "$demand_only_csv" \
        --metadata "$demand_only_metadata" \
        --logger-summary "$demand_only_summary"
fi

python3 "${SCRIPT_DIR}/prepare_tlb_pattern_streams.py" \
    --input "$input_csv" \
    --source-metadata "$metadata" \
    --dtlb-ordered-output "$ordered_input_csv" \
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
if [ -n "${REGION_ID:-}" ]; then
    virtual_analysis_args+=(--region-id "$REGION_ID")
fi
python3 "${SCRIPT_DIR}/analyze_demand_tlb_pattern.py" \
    --input "$ordered_input_csv" --metadata "$metadata" \
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

echo "[DONE] Unified demand + cross-page-vBerti VPN figures/tables: $OUTPUT_ROOT/{dtlb_access,stlb_access,stlb_miss}"
