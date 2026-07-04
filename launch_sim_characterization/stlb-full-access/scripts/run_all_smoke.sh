#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

"${SCRIPT_DIR}/build.sh"
"${SCRIPT_DIR}/run_smoke_bfs3.sh"
"${SCRIPT_DIR}/postprocess_smoke.sh"
