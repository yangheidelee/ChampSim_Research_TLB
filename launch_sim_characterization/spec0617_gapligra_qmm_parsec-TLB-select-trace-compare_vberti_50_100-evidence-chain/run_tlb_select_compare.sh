#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
HELPER_DIR="${SCRIPT_DIR}/script"

MODE="${1:-all}"
MAX_PARALLEL="${2:-${MAX_PARALLEL:-1}}"
N_WARM="${N_WARM:-50}"
N_SIM="${N_SIM:-100}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"
DO_BUILD="${DO_BUILD:-1}"
SELECT_TRACE_JSON="${SELECT_TRACE_JSON:-/home/zcq/git_prj/ChampSim/csv_figure/spec0617_gapligra_qmm_parsec-TLB-select-trace-compare_vberti_50_100/select_trace/data_process_for_compare/stlb_mpki_gt_1.0_selected_traces.json}"

NOPREF_BINARY="pgc-nopref-1core"
PERMIT_BINARY="pgc-permit-1core"
DISCARD_BINARY="pgc-discard-1core"
TRANSLATION_ONLY_BINARY="pgc-translation-only-1core"

usage() {
    cat <<EOF
Usage: ./run_tlb_select_compare.sh [all|build-only|run-only|run-nopref|run-permit|run-pref|run-discard|run-translation-only|select-json|backend|postprocess|status|clean-csv] [MAX_PARALLEL]

This case only runs selected traces from:
  ${SELECT_TRACE_JSON}

Defaults:
  N_WARM=${N_WARM}M
  N_SIM=${N_SIM}M
  SKIP_EXISTING=${SKIP_EXISTING}
EOF
}

check_layout() {
    for dir in "$HELPER_DIR" "${SCRIPT_DIR}/result" "${SCRIPT_DIR}/csv_figure"; do
        if [ ! -d "$dir" ]; then
            echo "[ERROR] Missing directory: $dir" >&2
            exit 1
        fi
    done
    if [ ! -f "$SELECT_TRACE_JSON" ]; then
        echo "[ERROR] Missing selected trace json: $SELECT_TRACE_JSON" >&2
        exit 1
    fi
}

build_all() {
    if [ "$DO_BUILD" != "1" ]; then
        echo "[SKIP] DO_BUILD=${DO_BUILD}, skip build"
        return
    fi
    "${HELPER_DIR}/build_one.sh" nopref 1C.nopref.json "$NOPREF_BINARY" next_line no ip_stride no
    "${HELPER_DIR}/build_one.sh" permit_pgc 1C.permit-pgc.json "$PERMIT_BINARY" next_line vberti ip_stride no
    "${HELPER_DIR}/build_one.sh" discard_pgc 1C.discard-pgc.json "$DISCARD_BINARY" next_line vberti_nocross ip_stride no
    "${HELPER_DIR}/build_one.sh" translation_only 1C.translation-only.json "$TRANSLATION_ONLY_BINARY" next_line vberti ip_stride no
}

run_config() {
    local config_name="$1"
    local binary_name="$2"
    shift 2
    N_WARM="$N_WARM" N_SIM="$N_SIM" SKIP_EXISTING="$SKIP_EXISTING" SELECT_TRACE_JSON="$SELECT_TRACE_JSON" \
        "${HELPER_DIR}/run_config.sh" "$config_name" "$binary_name" "$MAX_PARALLEL" "$@"
}

run_nopref() {
    run_config nopref "$NOPREF_BINARY"
}

run_permit() {
    run_config permit_pgc "$PERMIT_BINARY"
}

run_discard() {
    run_config discard_pgc "$DISCARD_BINARY"
}

run_translation_only() {
    run_config translation_only "$TRANSLATION_ONLY_BINARY" --l1d-cross-page-pf-translation-only
}

run_all() {
    run_nopref
    run_permit
    run_discard
    run_translation_only
}

postprocess() {
    SELECT_TRACE_JSON="$SELECT_TRACE_JSON" "${HELPER_DIR}/postprocess.py"
}

select_json() {
    local out_dir="${SCRIPT_DIR}/csv_figure/select_trace/data_process_for_compare"
    local out_json="${out_dir}/stlb_mpki_gt_1.0_selected_traces.json"
    mkdir -p "$out_dir"
    cp "$SELECT_TRACE_JSON" "$out_json"
    echo "[DONE] selected trace json copied to: $out_json"
}

status() {
    python3 - "$SCRIPT_DIR" "$SELECT_TRACE_JSON" <<'PY'
import json
import pathlib
import sys

case_dir = pathlib.Path(sys.argv[1])
selected_json = pathlib.Path(sys.argv[2])
tags = json.loads(selected_json.read_text()).get("selected_trace_tags", [])
configs = {
    "nopref": "pgc-nopref-1core",
    "permit_pgc": "pgc-permit-1core",
    "discard_pgc": "pgc-discard-1core",
    "translation_only": "pgc-translation-only-1core",
}

def complete(path):
    if not path.exists() or path.stat().st_size == 0:
        return False
    text = path.read_text(errors="replace")
    return "[ROI Statistics]" in text and "Core_0_TLB_cross_page_prefetch_coverage" in text

print(f"[STATUS] selected_trace_json={selected_json}")
print(f"[STATUS] selected_traces={len(tags)}")
for config, binary in configs.items():
    complete_count = partial_count = missing_count = 0
    for tag in tags:
        log = case_dir / "result" / config / f"{tag}-{binary}---hide-heartbeat.log"
        if complete(log):
            complete_count += 1
        elif log.exists() and log.stat().st_size > 0:
            partial_count += 1
        else:
            missing_count += 1
    print(f"[STATUS] {config}: complete={complete_count} partial={partial_count} missing={missing_count}")
PY
}

check_layout
echo "[CASE] ${SCRIPT_DIR}"
echo "[MODE] ${MODE} warm=${N_WARM}M sim=${N_SIM}M parallel=${MAX_PARALLEL} skip=${SKIP_EXISTING}"

case "$MODE" in
    all)
        build_all
        run_all
        postprocess
        ;;
    build-only)
        build_all
        ;;
    run-only)
        run_all
        ;;
    run-nopref)
        run_nopref
        ;;
    run-permit|run-pref)
        run_permit
        ;;
    run-discard)
        run_discard
        ;;
    run-translation-only|run-trans-only)
        run_translation_only
        ;;
    select-json)
        select_json
        ;;
    backend|postprocess|figures|compare|csv-nopref|csv-pref|csv-discard)
        postprocess
        ;;
    status)
        status
        ;;
    clean-csv)
        rm -rf "${SCRIPT_DIR}/csv_figure"
        mkdir -p "${SCRIPT_DIR}/csv_figure"
        ;;
    help|-h|--help)
        usage
        ;;
    *)
        usage >&2
        exit 1
        ;;
esac

echo "[DONE] ${MODE}"
