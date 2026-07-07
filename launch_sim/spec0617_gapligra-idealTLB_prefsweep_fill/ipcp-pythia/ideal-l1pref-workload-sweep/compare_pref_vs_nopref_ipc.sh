#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
COMPARE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
COMPARE_SCRIPT="${COMPARE_DIR}/data_process_for_compare/compare_pref_vs_nopref_ipc.sh"

if [ ! -x "$COMPARE_SCRIPT" ]; then
    chmod +x "$COMPARE_SCRIPT"
fi

"$COMPARE_SCRIPT" "$@"
