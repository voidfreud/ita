"""Re-run all --json commands and overwrite stored schema snapshots.

Usage:
    uv run scripts/update_json_snapshots.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ITA = ROOT / "src" / "ita.py"
SNAPSHOT_DIR = ROOT / "tests" / "snapshots" / "json"

# Import command inventory without importing pytest
sys.path.insert(0, str(ROOT / "tests"))
from test_contracts import COMMANDS  # noqa: E402


def _derive_schema(value) -> dict:
	if isinstance(value, dict):
		return {
			"type": "object",
			"properties": {k: _derive_schema(v) for k, v in value.items()},
		}
	if isinstance(value, list):
		if value:
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


def main():
	SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
	json_cmds = [c for c in COMMANDS if c.get("json")]
	updated = 0
	skipped = 0

	for cmd in json_cmds:
		parts = cmd["path"].split()
		extra = list(cmd.get("args", []))
		result = subprocess.run(
			["uv", "run", str(ITA)] + parts + ["--json"] + extra,
			capture_output=True, text=True, timeout=30,
		)
		if result.returncode != 0:
			print(f"SKIP {cmd['path']}: rc={result.returncode}")
			skipped += 1
			continue
		try:
			value = json.loads(result.stdout)
		except json.JSONDecodeError as exc:
			print(f"SKIP {cmd['path']}: {exc}")
			skipped += 1
			continue

		schema = _derive_schema(value)
		name = cmd["path"].replace(" ", "_")
		snap_path = SNAPSHOT_DIR / f"{name}.schema.json"
		snap_path.write_text(json.dumps(schema, indent=2) + "\n")
		print(f"  OK {cmd['path']} → {snap_path.relative_to(ROOT)}")
		updated += 1

	print(f"\n{updated} snapshots updated, {skipped} skipped.")


if __name__ == "__main__":
	main()
