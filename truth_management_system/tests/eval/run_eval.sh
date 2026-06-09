#!/usr/bin/env bash
# Portable runner for the PKB retrieval eval harness.
#
# Usage:
#   ./truth_management_system/tests/eval/run_eval.sh [--k N] [--json] [--verbose] [--dataset PATH]
#
# - Activates the 'science-reader' conda env if available (override with PKB_CONDA_ENV).
# - Runs from the repo root regardless of where it is invoked.
# - Without OPENROUTER_API_KEY only the FTS strategy runs (offline). Export the
#   key to also evaluate embedding/hybrid strategies.
set -euo pipefail

# Repo root = three levels up from this script (.../tests/eval -> repo root).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

ENV_NAME="${PKB_CONDA_ENV:-science-reader}"
if command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
  conda activate "${ENV_NAME}" 2>/dev/null || echo "[run_eval] warning: could not activate conda env '${ENV_NAME}'; using current python" >&2
fi

exec python -m truth_management_system.tests.eval.runner "$@"
