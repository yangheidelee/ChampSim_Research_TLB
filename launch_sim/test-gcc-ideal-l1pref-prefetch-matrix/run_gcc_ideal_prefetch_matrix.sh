#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

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

COMPARE_TAG=$(basename "$SCRIPT_DIR")
TOOL_PY="${SCRIPT_DIR}/gcc_ideal_matrix_tools.py"
CONFIG_DIR="${SCRIPT_DIR}/configs"
REF_JSON="${REF_JSON:-${CHAMPSIM_ROOT}/launch_sim/1core-spec0617_gapligra-idealTLB-select-trace-compare_jsonnew/pref-workload-sweep/1C.fullBW.stlb.stats.json}"
TRACE_PATH="${TRACE_PATH:-/data0/tzh/champsim_traces/SPEC17/602.gcc_s-2226B.champsimtrace.xz}"
N_WARM="${N_WARM:-20}"
N_SIM="${N_SIM:-50}"
MAX_PARALLEL="${MAX_PARALLEL:-2}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"
MAKE_ARGS="${MAKE_ARGS:-}"
CONFIG_TAG_REGEX="${CONFIG_TAG_REGEX:-}"
RESULT_ROOT="${CHAMPSIM_ROOT}/results/${COMPARE_TAG}"
CSV_ROOT="${CHAMPSIM_ROOT}/csv_figure/${COMPARE_TAG}"

ensure_exec() {
    local f="$1"
    if [ ! -f "$f" ]; then
        echo "[ERROR] Missing file: $f"
        exit 1
    fi
    if [ ! -x "$f" ]; then
        chmod +x "$f"
    fi
}

check_env() {
    ensure_exec "$TOOL_PY"
    if [ ! -f "$REF_JSON" ]; then
        echo "[ERROR] Reference JSON not found: $REF_JSON"
        exit 1
    fi
    if [ ! -f "$TRACE_PATH" ]; then
        echo "[ERROR] GCC trace not found: $TRACE_PATH"
        exit 1
    fi
    if ! [[ "$N_WARM" =~ ^[0-9]+$ ]] || ! [[ "$N_SIM" =~ ^[0-9]+$ ]]; then
        echo "[ERROR] N_WARM and N_SIM must be integer million-instruction counts"
        exit 1
    fi
}

load_specs() {
    mapfile -t CONFIG_SPECS < <(
        "$TOOL_PY" list-configs | while IFS= read -r spec; do
            IFS='|' read -r tag _rest <<< "$spec"
            if [ -z "$CONFIG_TAG_REGEX" ] || [[ "$tag" =~ $CONFIG_TAG_REGEX ]]; then
                echo "$spec"
            fi
        done
    )
}

prepare_configs() {
    echo "[STEP] generate config JSONs from: $REF_JSON"
    "$TOOL_PY" write-configs --reference "$REF_JSON" --configs-dir "$CONFIG_DIR"
}

build_one() {
    local tag="$1"
    local binary="$2"
    local config_json="${CONFIG_DIR}/${tag}.json"
    if [ ! -f "$config_json" ]; then
        echo "[ERROR] Config JSON not found: $config_json"
        exit 1
    fi
    echo "[BUILD] $tag -> $binary"
    cd "$CHAMPSIM_ROOT"
    echo "[CMD] ./config.sh $config_json"
    ./config.sh "$config_json"
    echo "[CMD] make ${MAKE_ARGS}"
    # shellcheck disable=SC2086
    make ${MAKE_ARGS}
    if [ ! -x "${CHAMPSIM_ROOT}/bin/${binary}" ]; then
        echo "[ERROR] Build failed; missing binary: ${CHAMPSIM_ROOT}/bin/${binary}"
        exit 1
    fi
}

build_all() {
    prepare_configs
    load_specs
    for spec in "${CONFIG_SPECS[@]}"; do
        IFS='|' read -r tag _label binary _ideal _l1d _l2c _options <<< "$spec"
        build_one "$tag" "$binary"
    done
}

option_tag() {
    local option_text="$1"
    if [ -z "$option_text" ]; then
        echo "no_option"
        return
    fi
    read -r -a opts <<< "$option_text"
    local tag
    tag=$(printf "%s_" "${opts[@]}")
    tag=${tag%_}
    echo "$tag" | tr ' ' '_' | tr -cd '[:alnum:]_.=-'
}

run_one() {
    local spec="$1"
    IFS='|' read -r tag label binary ideal l1d l2c options <<< "$spec"
    local result_dir="${RESULT_ROOT}/${tag}"
    local trace_tag
    trace_tag=$(basename "$TRACE_PATH")
    trace_tag=${trace_tag%.xz}
    trace_tag=${trace_tag%.gz}
    trace_tag=${trace_tag%.champsimtrace}
    local opt_tag
    opt_tag=$(option_tag "$options")
    local outfile="${result_dir}/${trace_tag}-${binary}-${opt_tag}.log"
    local binary_path="${CHAMPSIM_ROOT}/bin/${binary}"

    if [ ! -x "$binary_path" ]; then
        echo "[ERROR] Missing binary for ${tag}: $binary_path"
        return 1
    fi
    mkdir -p "$result_dir"
    if [ -f "$outfile" ] && [ "$SKIP_EXISTING" = "1" ] && grep -q "^\[ROI Statistics\]" "$outfile"; then
        echo "[SKIP] $label complete: $outfile"
        return 0
    fi

    read -r -a option_array <<< "$options"
    echo "[RUN] $label ideal=${ideal} L1D=${l1d} L2C=${l2c}"
    echo "[CMD] $binary_path --warmup-instructions ${N_WARM}000000 --simulation-instructions ${N_SIM}000000 ${options} $TRACE_PATH"
    "$binary_path" \
        --warmup-instructions "${N_WARM}000000" \
        --simulation-instructions "${N_SIM}000000" \
        "${option_array[@]}" \
        "$TRACE_PATH" \
        > "$outfile"
    echo "[INFO] output: $outfile"
}

run_all() {
    load_specs
    local running_jobs=0
    for spec in "${CONFIG_SPECS[@]}"; do
        run_one "$spec" &
        running_jobs=$((running_jobs + 1))
        if [ "$running_jobs" -ge "$MAX_PARALLEL" ]; then
            wait -n
            running_jobs=$((running_jobs - 1))
        fi
    done
    while [ "$running_jobs" -gt 0 ]; do
        wait -n
        running_jobs=$((running_jobs - 1))
    done
}

summarize() {
    echo "[STEP] summarize logs"
    "$TOOL_PY" summarize --result-root "$RESULT_ROOT" --out-dir "$CSV_ROOT"
}

status() {
    echo "========== GCC ideal L1-prefetch/prefetcher matrix =========="
    echo "CHAMPSIM_ROOT : $CHAMPSIM_ROOT"
    echo "SCRIPT_DIR    : $SCRIPT_DIR"
    echo "COMPARE_TAG   : $COMPARE_TAG"
    echo "REF_JSON      : $REF_JSON"
    echo "TRACE_PATH    : $TRACE_PATH"
    echo "N_WARM        : $N_WARM"
    echo "N_SIM         : $N_SIM"
    echo "MAX_PARALLEL  : $MAX_PARALLEL"
    echo "SKIP_EXISTING : $SKIP_EXISTING"
    echo "CONFIG_TAG_REGEX : ${CONFIG_TAG_REGEX:-<all>}"
    echo "RESULT_ROOT   : $RESULT_ROOT"
    echo "CSV_ROOT      : $CSV_ROOT"
    echo "CONFIGS:"
    load_specs
    for spec in "${CONFIG_SPECS[@]}"; do
        IFS='|' read -r tag label binary ideal l1d l2c options <<< "$spec"
        echo "  - ${tag}: ${label}; ideal=${ideal}; L1D=${l1d}; L2C=${l2c}; binary=${binary}; options=${options}"
    done
    echo "============================================================="
}

usage() {
    cat <<EOF
Usage: $(basename "$0") [status|prepare-configs|build-only|run-only|summarize|all] [MAX_PARALLEL]

Defaults:
  TRACE_PATH=$TRACE_PATH
  N_WARM=$N_WARM
  N_SIM=$N_SIM
  MAX_PARALLEL=$MAX_PARALLEL
  CONFIG_TAG_REGEX=${CONFIG_TAG_REGEX:-<all>}

Example:
  cd $CHAMPSIM_ROOT
  MAX_PARALLEL=5 $SCRIPT_DIR/$(basename "$0") all 5
EOF
}

cmd=${1:-all}
if [ -n "${2:-}" ]; then
    MAX_PARALLEL="$2"
fi

case "$cmd" in
    status)
        check_env
        status
        ;;
    prepare-configs)
        check_env
        prepare_configs
        ;;
    build-only)
        check_env
        build_all
        ;;
    run-only)
        check_env
        run_all
        ;;
    summarize)
        check_env
        summarize
        ;;
    all)
        check_env
        build_all
        run_all
        summarize
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        echo "[ERROR] Unknown command: $cmd"
        usage
        exit 1
        ;;
esac
