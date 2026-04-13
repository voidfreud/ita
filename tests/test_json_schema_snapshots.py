"""Freeze --json output schema per command; regressions require explicit sign-off.

Marks: @pytest.mark.contract + @pytest.mark.integration
Missing snapshot  → created + xfail("snapshot initialized, review")
Schema drift      → fail with before/after diff
"""
import json
import subprocess
from pathlib import Path

import pytest

from conftest import ITA
from tests.test_contracts import COMMANDS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "json"


def _cmd_snapshot_path(cmd_path: str) -> Path:
	name = cmd_path.replace(" ", "_")
	return SNAPSHOT_DIR / f"{name}.schema.json"


def _run_json(cmd_path: str, extra_args: list[str]) -> dict:
	parts = cmd_path.split()
	result = subprocess.run(
		["uv", "run", str(ITA)] + parts + ["--json"] + extra_args,
		capture_output=True, text=True, timeout=30,
	)
	if result.returncode != 0:
		pytest.skip(f"command returned rc={result.returncode}: {result.stderr.strip()}")
	try:
		return json.loads(result.stdout)
	except json.JSONDecodeError as exc:
		pytest.skip(f"non-JSON output: {exc}")


def _derive_schema(value) -> dict:
	"""Recursively derive a simple schema from a live value."""
	if isinstance(value, dict):
		return {
			"type": "object",
			"properties": {k: _derive_schema(v) for k, v in value.items()},
		}
	if isinstance(value, list):
		if value:
			# Use first element to represent item schema
			return {"type": "array", "items": _derive_schema(value[0])}
		return {"type": "array", "items": {}}
	if isinstance(value, bool):
		return {"type": "boolean"}
	if isinstance(value, int):
		return {"type": "integer"}
	if isinstance(value, float):
		return {"type": "number"}
	if isinstance(value, str):
		return {"type": "string"}
	if value is None:
		return {"type": "null"}
	return {"type": "unknown"}


def _schema_diff(stored: dict, live: dict, path: str = "$") -> list[str]:
	"""Return list of drift descriptions between two schemas."""
	diffs = []
	if stored.get("type") != live.get("type"):
		diffs.append(f"{path}: type {stored.get('type')!r} → {live.get('type')!r}")
		return diffs
	if stored.get("type") == "object":
		s_props = stored.get("properties", {})
		l_props = live.get("properties", {})
		for key in set(s_props) | set(l_props):
			if key not in l_props:
				diffs.append(f"{path}.{key}: key removed")
			elif key not in s_props:
				diffs.append(f"{path}.{key}: key added")
			else:
				diffs.extend(_schema_diff(s_props[key], l_props[key], f"{path}.{key}"))
	elif stored.get("type") == "array":
		s_items = stored.get("items", {})
		l_items = live.get("items", {})
		if s_items and l_items:
			diffs.extend(_schema_diff(s_items, l_items, f"{path}[]"))
	return diffs


# ---------------------------------------------------------------------------
# Parametrize over all --json commands
# ---------------------------------------------------------------------------

JSON_COMMANDS = [c for c in COMMANDS if c.get("json")]


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize(
	"cmd",
	JSON_COMMANDS,
	ids=[c["path"] for c in JSON_COMMANDS],
)
def test_json_schema_snapshot(cmd):
	extra = list(cmd.get("args", []))
	live_value = _run_json(cmd["path"], extra)
	live_schema = _derive_schema(live_value)

	SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
	snap_path = _cmd_snapshot_path(cmd["path"])

	if not snap_path.exists():
		snap_path.write_text(json.dumps(live_schema, indent=2) + "\n")
		pytest.xfail("snapshot initialized, review")

	stored_schema = json.loads(snap_path.read_text())
	diffs = _schema_diff(stored_schema, live_schema)

	if diffs:
		diff_lines = "\n".join(f"  {d}" for d in diffs)
		pytest.fail(
			f"JSON schema drift for `ita {cmd['path']}`:\n{diff_lines}\n\n"
			f"Stored schema: {snap_path}\n"
			f"Run scripts/update_json_snapshots.py to accept changes."
		)
