#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
INPUT="${INPUT:-${CASE_DIR}/result/bfs-3.trace.stlb_access_trace.csv}"
OUTDIR="${OUTDIR:-${CASE_DIR}/csv_figure/bfs-3.trace}"
WINDOW="${WINDOW:-100}"
DELTA_CLIP="${DELTA_CLIP:-64}"

python3 "${SCRIPT_DIR}/plot_stlb_access_patterns.py" \
    --input "$INPUT" \
    --outdir "$OUTDIR" \
    --window "$WINDOW" \
    --delta-clip "$DELTA_CLIP"
