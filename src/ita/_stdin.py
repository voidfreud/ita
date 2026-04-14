# src/_stdin.py
"""`ita run --stdin FILE` path validation + read (#325, CONTRACT §14.4).

Isolated from `_run.py` so the traversal-rule logic can be unit-tested
without spinning up the full run pipeline."""
import os
import sys
from pathlib import Path
from ._envelope import ItaError


def _load_stdin_script(stdin_path: str, allow_outside_cwd: bool) -> str:
	"""Read the `--stdin FILE` script for `ita run`, with path-traversal
	validation (#325, CONTRACT §14.4).

	Rules:
	- `-` means "read from process stdin"; no path checks apply.
	- Otherwise the path must exist and resolve (realpath) to a regular file
	  under the caller's CWD. Attempts that escape CWD via `..`, symlinks,
	  or absolute paths fail with `bad-args` (rc=6).
	- `--stdin-allow-outside-cwd` opts out of the CWD containment check
	  (explicit, non-interactive consent — CONTRACT §1 agent-only).

	The file contents are returned as a string. Raises `ItaError("bad-args", ...)`
	on any violation; no partial side effects."""
	if stdin_path == '-':
		try:
			return sys.stdin.read()
		except OSError as e:
			raise ItaError("bad-args", f"cannot read from stdin: {e}") from e
	p = Path(stdin_path)
	if not p.exists():
		raise ItaError("bad-args", f"--stdin path not found: {stdin_path!r}")
	try:
		resolved = p.resolve(strict=True)
	except (OSError, RuntimeError) as e:
		raise ItaError("bad-args", f"cannot resolve --stdin path {stdin_path!r}: {e}") from e
	if not resolved.is_file():
		raise ItaError("bad-args",
			f"--stdin path is not a regular file: {stdin_path!r} (resolved to {resolved})")
	if not allow_outside_cwd:
		cwd = Path(os.getcwd()).resolve()
		try:
			resolved.relative_to(cwd)
		except ValueError:
			raise ItaError("bad-args",
				f"--stdin path {stdin_path!r} resolves outside CWD ({resolved}); "
				f"pass --stdin-allow-outside-cwd to opt in explicitly (#325).")
	try:
		return resolved.read_text()
	except OSError as e:
		raise ItaError("bad-args", f"cannot read --stdin path {stdin_path!r}: {e}") from e
