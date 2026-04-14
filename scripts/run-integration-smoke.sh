#!/usr/bin/env bash
# run-integration-smoke.sh — drive the integration lane externally.
#
# Prereq: iTerm2 running, idle terminal window, dedicated if possible.
#
# Lap A (background, default):
#   bash scripts/run-integration-smoke.sh
#
# Lap B (foreground, for comparison per T36):
#   ITA_DISABLE_BACKGROUND=1 bash scripts/run-integration-smoke.sh
#
# Artifact: /tmp/ita-integration-<ts>.json (pytest-json-report)
#           or  /tmp/ita-integration-<ts>.xml (junit fallback)
#
# Issue: #387
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

TS="$(date +%Y%m%d-%H%M%S)"
JSON_ARTIFACT="/tmp/ita-integration-${TS}.json"
XML_ARTIFACT="/tmp/ita-integration-${TS}.xml"

# Lap B support: let the caller force foreground mode so the fixtures
# actually create visible tabs/windows for the human-comparison lap.
if [ "${ITA_DISABLE_BACKGROUND:-0}" = "1" ]; then
	unset ITA_DEFAULT_BACKGROUND
	echo "[smoke] ITA_DEFAULT_BACKGROUND unset (Lap B, foreground)"
fi

# Prefer pytest-json-report when available; fall back to JUnit XML otherwise.
if uv run --extra dev python -c "import pytest_jsonreport" >/dev/null 2>&1; then
	echo "[smoke] using pytest-json-report -> ${JSON_ARTIFACT}"
	ARTIFACT="$JSON_ARTIFACT"
	set +e
	uv run --extra dev pytest -m integration --timeout=60 \
		--json-report --json-report-file="$JSON_ARTIFACT"
	rc=$?
	set -e
else
	echo "[smoke] pytest-json-report not importable; falling back to JUnit XML -> ${XML_ARTIFACT}"
	ARTIFACT="$XML_ARTIFACT"
	set +e
	uv run --extra dev pytest -m integration --timeout=60 \
		--junitxml="$XML_ARTIFACT"
	rc=$?
	set -e
	# Minimal post-process summary so the operator sees pass/fail counts
	# without reaching for xmlstarlet.
	if [ -f "$XML_ARTIFACT" ]; then
		grep -Eo 'testsuite[^>]*(tests|failures|errors|skipped)="[0-9]+"' "$XML_ARTIFACT" \
			| head -5 || true
	fi
fi

echo "[smoke] artifact: ${ARTIFACT}"
exit "$rc"
