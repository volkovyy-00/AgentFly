#!/usr/bin/env bash
# The checks of AGENTS.md "Commands": `quick` while you work, `full` before you report a step done.
#
# Usage: scripts/check.sh quick|full
#
# - quick: ruff, then the parallel tests without the ones marked `slow` (tests/README.md).
# - full: the AGENTS.md "Check" line, word for word (tests/test_ci_workflow.py compares them).
# - Each check is its own line, never in a pipe or an `&&` list: under `set -e` the first one
#   that fails ends the script with its exit code.
set -euo pipefail

usage() {
  echo "usage: scripts/check.sh quick|full" >&2
  exit 2
}

[[ $# -eq 1 ]] || usage

cd "$(dirname "$0")/.."

case "$1" in
  quick)
    uv run ruff check .
    uv run ruff format --check .
    env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -n auto --dist loadgroup -m "not slow"
    ;;
  full)
    uv run ruff check .
    uv run ruff format --check .
    env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -n auto --dist loadgroup
    ;;
  *)
    usage
    ;;
esac
