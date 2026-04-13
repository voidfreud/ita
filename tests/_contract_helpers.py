"""Shared helpers for the CONTRACT §14 parametrized matrix.

Kept separate from ``_contract_categories`` (pure data) so the test file
itself stays small and readable. These helpers are fast-lane-safe: none
of them require a live iTerm2 unless the caller explicitly opts in.

Performance note (#292): the matrix invokes ita hundreds of times per
run. Subprocess dispatch dominated (~500 ms each × 328 cells ≈ 170 s).
We now dispatch in-process via Click's ``CliRunner`` — ~20× faster —
and keep a handful of genuine subprocess smokes in the matrix to guard
the OS entry-point path (argv parsing, console script, `python -m ita`).
"""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from typing import Any

from click.testing import CliRunner

from helpers import ita
from ita import cli as _cli
from ita._envelope import EXIT_CODES, SCHEMA_VERSION, ItaError


# Sentinel target guaranteed not to exist. Used by rule 1 / 3 / 5 to drive
# the not-found / ambiguous / missing-identity code paths without touching
# real iTerm2 state. Pattern borrowed from tests/test_envelope.py.
GHOST_SID = "nonexistent-session-xyz"


# ── In-process invocation (fast path) ──────────────────────────────────────
# CliRunner runs the Click group in the current interpreter. Callbacks that
# reach for the iTerm2 async API will raise before touching the network
# because there's no event loop; that's exactly the error path the matrix
# is probing for, so it's a feature.
#
# @ita_command-wrapped callbacks emit their §4 envelope on stdout themselves
# (see src/ita/_envelope.py), so ItaError → envelope translation is handled
# by the command layer — CliRunner just captures stdout. For legacy raises
# we fall through to Click's default ClickException rendering, which the
# matrix's rule-1 probe treats as rc!=0 / no envelope (pytest.skip path).

def _uses_json(args: tuple[str, ...]) -> bool:
	return any(a in ("--json", "--as-json") for a in args)


def invoke(*args: str, timeout: int = 15) -> SimpleNamespace:
	"""Invoke `ita <args...>` in-process.

	Returns a ``SimpleNamespace`` with ``returncode``, ``stdout``, ``stderr``
	to match ``subprocess.CompletedProcess`` duck-typing — existing matrix
	tests read only those three attrs.

	*timeout* is accepted for API parity with the subprocess shim but has
	no effect in-process; the pytest ``--timeout`` wraps the whole test.

	ItaError fallback: non-migrated commands raise ``ItaError`` instead of
	emitting their own envelope; the real CLI's ``main()`` wraps that and
	writes the §4 error envelope on --json. CliRunner bypasses ``main()``,
	so we replicate the fallback here to keep test semantics identical to
	the subprocess path.
	"""
	runner = CliRunner()
	# standalone_mode=False mirrors src/ita/__init__.py::main: Click won't
	# auto-handle ClickException / ItaError, so we receive the exception on
	# ``result.exception`` and can apply the envelope fallback below.
	result = runner.invoke(
		_cli, list(args), catch_exceptions=True, standalone_mode=False,
	)
	exc = result.exception
	if isinstance(exc, ItaError):
		exit_code = EXIT_CODES[exc.code]
		stdout = result.output
		if _uses_json(args):
			envelope = {
				"schema": SCHEMA_VERSION,
				"ok": False,
				"op": args[0] if args else "",
				"target": None,
				"state_before": None,
				"state_after": None,
				"elapsed_ms": 0,
				"warnings": [],
				"error": {"code": exc.code, "reason": exc.reason},
				"data": {},
			}
			stdout = json.dumps(envelope) + "\n"
		return SimpleNamespace(
			returncode=exit_code,
			stdout=stdout,
			stderr=result.stderr,
		)
	return SimpleNamespace(
		returncode=result.exit_code,
		stdout=result.output,
		stderr=result.stderr,
	)


def invoke_subprocess(*args: str, timeout: int = 15) -> subprocess.CompletedProcess:
	"""Genuine subprocess invocation — reserved for the matrix's OS-path
	smoke tests. Exercises argv parsing, console-script dispatch, and the
	`python -m ita` entrypoint that in-process ``invoke`` bypasses."""
	return ita(*args, timeout=timeout)


def invoke_json(*args: str, timeout: int = 15) -> tuple[SimpleNamespace, dict[str, Any] | None]:
	"""Invoke with --json appended. Returns (result, parsed-envelope-or-None).

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


# Shared-state hygiene: see the ``_reset_ita_module_state`` autouse fixture
# at the top of ``test_contract_matrix.py``. It clears ``ita._lock``'s two
# module-level mutables between cells so CliRunner's shared interpreter
# can't leak state. Matrix cells drive --help / ghost-SID / --json paths
# that bail before lock acquisition, so in practice neither mutates; the
# reset is belt-and-suspenders for future callers.


# ── Rule-4 protection harness (#292) ───────────────────────────────────────
# Lets the rule-4 matrix drive every mutator through its `check_protected`
# call-path without a live iTerm2. We substitute three things in the
# singleton ``iterm2`` module and the canonical ``ita._protect`` source:
#
#   1. ``iterm2.run_until_complete`` — run the coroutine synchronously via
#      ``asyncio.run`` against a fake connection. Every ita module pulls
#      ``run_iterm`` (and therefore ``iterm2.run_until_complete``) from the
#      same module object, so a single patch propagates.
#   2. ``iterm2.async_get_app`` — return a fake ``App`` whose
#      ``get_session_by_id(GHOST_SID)`` returns a minimal fake session.
#      ``resolve_session`` then happily resolves GHOST_SID without touching
#      the network.
#   3. ``ita._protect.get_protected`` — seeded to ``{GHOST_SID}`` so the
#      real ``check_protected`` fires ``ItaError("protected", …)`` the
#      instant the mutator reaches it.
#
# The helper is a context manager so each test cell applies it narrowly;
# it avoids a pytest fixture so tests that want their own variation (e.g.
# seed with a different SID) can still call it directly.

import asyncio
import contextlib


def _build_fake_session(sid: str) -> SimpleNamespace:
	"""Minimal iterm2.Session stand-in. Only attributes the mutator needs
	*before* it reaches check_protected. Anything after is irrelevant —
	the raise short-circuits execution."""
	tab = SimpleNamespace(tab_id="fake-tab", window=SimpleNamespace(window_id="fake-win"))

	async def _noop(*_a, **_kw):
		return None

	return SimpleNamespace(
		session_id=sid,
		name="fake-session",
		tab=tab,
		window=tab.window,
		async_send_text=_noop,
		async_inject=_noop,
		async_get_variable=_noop,
		async_set_name=_noop,
	)


class _FakeApp:
	"""Minimal iterm2.App stand-in. resolve_session only needs
	``get_session_by_id`` for the fast-path UUID match."""
	terminal_windows: list = []

	def __init__(self, session: SimpleNamespace) -> None:
		self._session = session

	@property
	def windows(self):
		return []

	@property
	def current_terminal_window(self):
		return None

	def get_session_by_id(self, sid: str):
		if sid == self._session.session_id:
			return self._session
		return None


@contextlib.contextmanager
def seeded_protection(sid: str = GHOST_SID):
	"""Patch the three seams needed to drive any mutator into the
	``check_protected`` raise without a live iTerm2. Yields ``None``.

	Fast-lane-safe: every patch is purely in-process."""
	from unittest.mock import patch
	import iterm2  # singleton

	session = _build_fake_session(sid)
	app = _FakeApp(session)

	async def _fake_get_app(_connection):
		return app

	def _fake_run_until_complete(main):
		asyncio.run(main(None))

	with patch.object(iterm2, "run_until_complete", _fake_run_until_complete), \
		patch.object(iterm2, "async_get_app", _fake_get_app), \
		patch("ita._protect.get_protected", lambda: {sid}):
		yield


__all__ = [
	"GHOST_SID",
	"invoke",
	"invoke_subprocess",
	"invoke_json",
	"split_path",
	"looks_like_envelope",
	"assert_no_lie",
	"assert_rc_matches_envelope",
	"assert_stdout_clean",
	"assert_stderr_no_traceback",
	"assert_identity_required",
	"seeded_protection",
]
