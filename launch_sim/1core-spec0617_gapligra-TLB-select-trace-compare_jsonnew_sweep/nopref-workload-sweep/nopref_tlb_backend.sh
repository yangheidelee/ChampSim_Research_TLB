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

COMPARE_TAG=$(basename "$(dirname "$SCRIPT_DIR")")
CONFIG_TAG=$(basename "$SCRIPT_DIR")
FLOW_TAG=${FLOW_TAG:-select_trace}
BASELINE_SELECT_TAG=${BASELINE_SELECT_TAG:-1core-spec0617_gapligra-TLB-select-trace-compare_jsonnew}
SELECT_THRESHOLD=${SELECT_THRESHOLD:-1.0}
RESULT_DIR="${CHAMPSIM_ROOT}/results/${COMPARE_TAG}/${CONFIG_TAG}"
OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/${CONFIG_TAG}"
COMPARE_OUT_DIR="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}/${FLOW_TAG}/data_process_for_compare"
TOOL_PY="${CHAMPSIM_ROOT}/launch_sim/${COMPARE_TAG}/data_process_for_compare/tlb_select_tools.py"
SELECT_TRACE_JSON="${SELECT_TRACE_JSON:-}"

TRACE_LEVEL_CSV="${OUT_DIR}/nopref_trace_level.csv"
WORKLOAD_CSV="${OUT_DIR}/nopref_workload_agg.csv"
FIG_PNG="${OUT_DIR}/nopref_stlb_miss_causes.png"
FIG_PDF="${OUT_DIR}/nopref_stlb_miss_causes.pdf"
MPKI_FIG_PNG="${OUT_DIR}/nopref_stlb_mpki.png"
MPKI_FIG_PDF="${OUT_DIR}/nopref_stlb_mpki.pdf"
DRAM_PKI_FIG_PNG="${OUT_DIR}/nopref_dram_rq_read_pki.png"
DRAM_PKI_FIG_PDF="${OUT_DIR}/nopref_dram_rq_read_pki.pdf"
DRAM_SUMMARY_SHARE_FIG_PNG="${OUT_DIR}/nopref_dram_rq_summary_share.png"
DRAM_SUMMARY_SHARE_FIG_PDF="${OUT_DIR}/nopref_dram_rq_summary_share.pdf"
DRAM_DETAIL_SHARE_FIG_PNG="${OUT_DIR}/nopref_dram_rq_detail_share.png"
DRAM_DETAIL_SHARE_FIG_PDF="${OUT_DIR}/nopref_dram_rq_detail_share.pdf"
STLB_PTW_DRAM_TOUCH_SHARE_FIG_PNG="${OUT_DIR}/nopref_stlb_miss_ptw_dram_touch_share.png"
STLB_PTW_DRAM_TOUCH_SHARE_FIG_PDF="${OUT_DIR}/nopref_stlb_miss_ptw_dram_touch_share.pdf"

if [ ! -d "$RESULT_DIR" ]; then
    echo "[ERROR] Result directory not found: $RESULT_DIR"
    exit 1
fi

mkdir -p "$OUT_DIR" "$COMPARE_OUT_DIR"

if [ -z "$SELECT_TRACE_JSON" ]; then
    SELECT_TRACE_JSON="${CHAMPSIM_ROOT}/csv_figure/${BASELINE_SELECT_TAG}/select_trace/data_process_for_compare/stlb_mpki_gt_${SELECT_THRESHOLD}_selected_traces.json"
fi

FIG_TITLE="nopref selected STLB miss causes"
MPKI_FIG_TITLE="nopref selected STLB MPKI"
DRAM_PKI_FIG_TITLE="nopref selected DRAM RQ read requests PKI"
DRAM_SUMMARY_SHARE_FIG_TITLE="nopref selected DRAM RQ read traffic summary share"
DRAM_DETAIL_SHARE_FIG_TITLE="nopref selected DRAM RQ read traffic detail share"
STLB_PTW_DRAM_TOUCH_SHARE_FIG_TITLE="nopref selected STLB miss PTW DRAM touch share"
DONE_LABEL="nopref selected CSV + figures"
if [ "$SELECT_TRACE_JSON" = "ALL" ] || [ "$SELECT_TRACE_JSON" = "FULL" ] || [ "$SELECT_TRACE_JSON" = "NONE" ]; then
    FIG_TITLE="nopref full-trace STLB miss causes"
    MPKI_FIG_TITLE="nopref full-trace STLB MPKI"
    DRAM_PKI_FIG_TITLE="nopref full-trace DRAM RQ read requests PKI"
    DRAM_SUMMARY_SHARE_FIG_TITLE="nopref full-trace DRAM RQ read traffic summary share"
    DRAM_DETAIL_SHARE_FIG_TITLE="nopref full-trace DRAM RQ read traffic detail share"
    STLB_PTW_DRAM_TOUCH_SHARE_FIG_TITLE="nopref full-trace STLB miss PTW DRAM touch share"
    DONE_LABEL="nopref full-trace CSV + figures"
fi

python3 "$TOOL_PY" single-config \
    --result-dir "$RESULT_DIR" \
    --select-trace-json "$SELECT_TRACE_JSON" \
    --trace-level-csv "$TRACE_LEVEL_CSV" \
    --workload-csv "$WORKLOAD_CSV" \
    --fig-png "$FIG_PNG" \
    --fig-pdf "$FIG_PDF" \
    --figure-title "$FIG_TITLE" \
    --mpki-fig-png "$MPKI_FIG_PNG" \
    --mpki-fig-pdf "$MPKI_FIG_PDF" \
    --mpki-figure-title "$MPKI_FIG_TITLE" \
    --dram-pki-fig-png "$DRAM_PKI_FIG_PNG" \
    --dram-pki-fig-pdf "$DRAM_PKI_FIG_PDF" \
    --dram-pki-figure-title "$DRAM_PKI_FIG_TITLE" \
    --dram-summary-share-fig-png "$DRAM_SUMMARY_SHARE_FIG_PNG" \
    --dram-summary-share-fig-pdf "$DRAM_SUMMARY_SHARE_FIG_PDF" \
    --dram-summary-share-figure-title "$DRAM_SUMMARY_SHARE_FIG_TITLE" \
    --dram-detail-share-fig-png "$DRAM_DETAIL_SHARE_FIG_PNG" \
    --dram-detail-share-fig-pdf "$DRAM_DETAIL_SHARE_FIG_PDF" \
    --dram-detail-share-figure-title "$DRAM_DETAIL_SHARE_FIG_TITLE" \
    --stlb-ptw-dram-touch-share-fig-png "$STLB_PTW_DRAM_TOUCH_SHARE_FIG_PNG" \
    --stlb-ptw-dram-touch-share-fig-pdf "$STLB_PTW_DRAM_TOUCH_SHARE_FIG_PDF" \
    --stlb-ptw-dram-touch-share-figure-title "$STLB_PTW_DRAM_TOUCH_SHARE_FIG_TITLE"

echo "[DONE] $DONE_LABEL generated under: $OUT_DIR"
