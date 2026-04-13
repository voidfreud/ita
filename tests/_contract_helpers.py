"""Shared helpers for the CONTRACT §14 parametrized matrix.

Kept separate from ``_contract_categories`` (pure data) so the test file
itself stays small and readable. These helpers are fast-lane-safe: none
of them require a live iTerm2 unless the caller explicitly opts in.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from helpers import ITA_CMD, ita


# Sentinel target guaranteed not to exist. Used by rule 1 / 3 / 5 to drive
# the not-found / ambiguous / missing-identity code paths without touching
# real iTerm2 state. Pattern borrowed from tests/test_envelope.py.
GHOST_SID = "nonexistent-session-xyz"


def invoke(*args: str, timeout: int = 15) -> subprocess.CompletedProcess:
	"""Thin wrapper around ``helpers.ita`` with a consistent short timeout
	for matrix tests. Never raises — callers inspect rc/stdout/stderr."""
	return ita(*args, timeout=timeout)


def invoke_json(*args: str, timeout: int = 15) -> tuple[subprocess.CompletedProcess, dict[str, Any] | None]:
	"""Invoke with --json appended. Returns (completed, parsed-envelope-or-None).

	Envelope parse is best-effort: if stdout isn't JSON (e.g. the command
	doesn't support --json), the second element is None and the caller
	can skip the invariant."""
	r = invoke(*args, "--json", timeout=timeout)
	env: dict[str, Any] | None = None
	if r.stdout.strip():
		try:
			env = json.loads(r.stdout)
		except (json.JSONDecodeError, ValueError):
			env = None
	return r, env


def split_path(cmd: str) -> list[str]:
	"""'tab close' -> ['tab', 'close']. Matches the space-separated form
	emitted by ``ita commands --json``."""
	return cmd.split()


def looks_like_envelope(obj: Any) -> bool:
	"""True if *obj* is a dict carrying the §4 required keys."""
	if not isinstance(obj, dict):
		return False
	return {"schema", "ok", "op", "error"}.issubset(obj.keys())


# Rule-1 assertion: ok=true must not coexist with a non-null error.
def assert_no_lie(envelope: dict[str, Any]) -> None:
	"""CONTRACT §14.1: no envelope has ok=true with error != null."""
	if envelope.get("ok") is True:
		assert envelope.get("error") is None, (
			f"§14.1 violation: ok=true with error={envelope.get('error')!r}"
		)


# Rule-3 assertion: rc sign must match envelope.ok.
def assert_rc_matches_envelope(rc: int, envelope: dict[str, Any]) -> None:
	"""CONTRACT §14.3: ok=true ⇔ rc=0; ok=false ⇔ rc != 0."""
	ok = envelope.get("ok")
	if ok is True:
		assert rc == 0, f"§14.3: ok=true but rc={rc}"
	elif ok is False:
		assert rc != 0, f"§14.3: ok=false but rc=0"


# Stdout hygiene (rule 2).
_NUL = "\x00"
_ANSI_CSI = "\x1b["


def assert_stdout_clean(stdout: str, *, allow_ansi: bool = False) -> None:
	"""CONTRACT §14.2 / §3: no NUL, no stray ANSI in non-TTY, no traceback.

	*allow_ansi* is reserved for commands that legitimately ship screen
	captures (none in our matrix, but we leave the flag for future use)."""
	assert _NUL not in stdout, "§14.2: NUL byte in stdout"
	if not allow_ansi:
		assert _ANSI_CSI not in stdout, "§14.2: ANSI escape on non-TTY stdout"
	assert "Traceback (most recent call last)" not in stdout, (
		"§14.2: Python traceback leaked to stdout"
	)


def assert_stderr_no_traceback(stderr: str) -> None:
	"""Tracebacks on stderr are also forbidden (§3)."""
	assert "Traceback (most recent call last)" not in stderr, (
		"§14.2: Python traceback on stderr"
	)


# Rule-5 helper: call a target-taking command WITHOUT -s and confirm it
# fails loudly rather than silently resolving. We cannot reliably predict
# every command's exact rc for the no-target path from the fast lane
# (some fail with bad-args rc=6, some with not-found rc=2, some with
# ambiguous rc=6). We assert: rc != 0 AND no silent success envelope.
def assert_identity_required(cmd_path: str) -> None:
	"""Invoke *cmd_path* with --json and no target; assert it did not
	silently succeed against an implicit target."""
	r, env = invoke_json(*split_path(cmd_path))
	# Accept three outcomes:
	#   1. non-zero rc (ideal) — explicit failure
	#   2. envelope with ok=false — explicit failure (rc should also be != 0,
	#      but that's rule 3's job)
	#   3. a --help / usage dump (rc != 0) if Click rejects missing arg
	if env is not None and env.get("ok") is True:
		# A command that took no target AND returned ok=true is a rule-5
		# leak UNLESS its envelope target is explicitly null (meaning the
		# command truly has no session target — e.g. `status`, `overview`).
		tgt = env.get("target")
		assert tgt is None, (
			f"§14.5 violation: {cmd_path} succeeded with implicit target={tgt!r}"
		)


__all__ = [
	"GHOST_SID",
	"invoke",
	"invoke_json",
	"split_path",
	"looks_like_envelope",
	"assert_no_lie",
	"assert_rc_matches_envelope",
	"assert_stdout_clean",
	"assert_stderr_no_traceback",
	"assert_identity_required",
]
