#!/usr/bin/env bash
# The CI gate, one stage per call: GitHub Actions and Jenkins both run this file, so the two
# pipelines cannot drift apart. Run all stages locally with `scripts/ci.sh all`.
#
# A stage fails the build on any non-zero exit: a lint warning, a type error, one failing test,
# one surviving canary or one known vulnerability in a dependency.
set -euo pipefail

stage() {
  case "$1" in
    install)  uv sync --locked ;;
    lint)     uv run ruff check . && uv run ruff format --check . ;;
    types)    uv run mypy ;;
    test)     uv run pytest -p no:cacheprovider ;;
    # KeysBench: every grader against its reference, antipattern and reward hacks (judge calls replayed).
    graders)  uv run python -m keysbench check-graders ;;
    # Each mutation must turn the suite red, on a temp copy of the repo (never the checkout).
    canaries) uv run python scripts/canaries.py ;;
    # Known vulnerabilities in the locked dependencies fail the build.
    audit)    uv run pip-audit ;;
    all)      for s in install lint types test graders canaries audit; do echo "== $s"; stage "$s"; done ;;
    *)        echo "unknown stage: $1" >&2; return 2 ;;
  esac
}

stage "${1:-all}"
