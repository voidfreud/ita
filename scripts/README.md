# scripts/

Operator-facing helpers. Run from repo root.

## run-integration-smoke.sh

Drive the integration lane externally so you can start it, walk away, and
come back to a structured artifact. See issue #387.

```
# Prereq: iTerm2 running, idle terminal window, dedicated if possible.

# Lap A (background, default — fixtures stay off-focus):
bash scripts/run-integration-smoke.sh

# Lap B (foreground, for comparison per T36):
ITA_DISABLE_BACKGROUND=1 bash scripts/run-integration-smoke.sh

# Artifact: /tmp/ita-integration-<ts>.json (pytest-json-report)
#           or  /tmp/ita-integration-<ts>.xml (junit fallback)
```

Exits non-zero on test failures. Artifact path is echoed at end.
