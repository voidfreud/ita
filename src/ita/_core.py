# src/_core.py
"""Core helpers shared by all ita modules.

Split layout (Phase 2, #256 follow-up):
  - _protect.py   — protected-session set, check_protected
  - _screen.py    — prompt detection, null-strip, read_session_lines
  - _filter.py    — --where KEY=VALUE parse/match
  - _envelope.py  — exit-code taxonomy + SCHEMA_VERSION (CONTRACT §4, §6)

This file keeps: emit, success_echo, confirm_or_skip, run_iterm, resolve_session,
the writelock helpers (moved to _lock.py in Phase 3 protection-lock branch),
and the `cli` root. Names extracted to the modules above are re-exported here
so existing `from _core import X` imports keep working; once each Phase 3 branch
touches its module, it can import directly from the correct source.
"""
import json
import sys
from collections.abc import Awaitable, Callable
from typing import Any

import click
import iterm2

# Re-exports — back-compat shims for existing callers. Phase 3 branches will
# migrate their own modules to import from the canonical source.
from ._protect import (  # noqa: F401
	PROTECTED_FILE, get_protected, add_protected, remove_protected, check_protected,
)
from ._screen import (  # noqa: F401
	PROMPT_CHARS, _SENTINEL_RE, _is_prompt_line, strip, last_non_empty_index,
	read_session_lines,
)
from ._filter import parse_filter, match_filter  # noqa: F401
from ._envelope import (  # noqa: F401
	SCHEMA_VERSION, EXIT_CODES,
	EXIT_OK, EXIT_NOT_FOUND, EXIT_PROTECTED, EXIT_TIMEOUT, EXIT_LOCKED,
	EXIT_BAD_ARGS, EXIT_API_UNREACHABLE, EXIT_NO_SHELL_INTEGRATION,
	ItaError,
)

# ── Session write-lock (#109) — moved to _lock.py (Phase 3) ────────────────
#
# Helpers live in _lock.py. Re-exported at the END of this module (after
# `cli` is defined) so existing `from ._core import session_writelock`
# imports keep working without a circular import (_lock imports _core.cli).
# Phase 2 follow-up cleanup: migrate callers to `from ._lock import ...`
# and drop this re-export shim.


# ── Output helpers ─────────────────────────────────────────────────────────


def emit(data: Any, use_json: bool = False) -> None:
	"""Print data as plain text or JSON."""
	if use_json:
		click.echo(json.dumps(data, indent=2))
	else:
		if isinstance(data, list):
			for item in data:
				click.echo(item)
		else:
			click.echo(data)


# ── Global-flag helpers (#139, #143) ────────────────────────────────────────

def success_echo(msg: str, quiet: bool = False) -> None:
	"""Print a success confirmation unless --quiet is set.
	Confirmations go to stderr so stdout stays clean for agents that parse it
	(matches the existing close/name/clear conventions)."""
	if not quiet:
		click.echo(msg, err=True)


def confirm_or_skip(msg: str, dry_run: bool = False, yes: bool = False) -> bool:
	"""Gatekeeper for destructive operations.

	Returns True if the caller should proceed with the mutation, False if
	this was a --dry-run (already printed). Raises ClickException if a
	confirmation prompt is needed but stdin is not a TTY.

	Flag semantics:
	  --dry-run  → print "Would: {msg}" to stdout, return False.
	  --yes / -y → skip prompt, return True.
	  neither    → prompt on TTY; on non-TTY, error with "use --yes".
	"""
	if dry_run:
		click.echo(f"Would: {msg}")
		return False
	if yes:
		return True
	if not sys.stdin.isatty():
		raise click.ClickException(
			f"{msg}: confirmation required but stdin is not a TTY. "
			f"Pass --yes/-y to proceed non-interactively."
		)
	return click.confirm(f"{msg}?", default=False)

# ── iTerm2 runner ──────────────────────────────────────────────────────────

def run_iterm(coro: Callable[..., Awaitable[Any]]) -> Any:
	"""
	Run an iTerm2 async coroutine synchronously.
	Usage:
		result = run_iterm(lambda conn: some_async_fn(conn))
	"""
	result: dict = {}
	error: dict = {}

	async def _main(connection):
		try:
			result['value'] = await coro(connection)
		except Exception as exc:
			error['exc'] = exc

	iterm2.run_until_complete(_main)

	if error:
		exc = error['exc']
		if isinstance(exc, click.ClickException):
			raise exc
		raise click.ClickException(str(exc))

	return result.get('value')

# ── Session resolver ────────────────────────────────────────────────────────

def _all_sessions(app):
	"""Return a flat list of every session across all windows/tabs.

	Canonical iteration set: `app.terminal_windows` per CONTRACT §2 (#297).
	`app.windows` also returns hotkey / hidden windows which the agent
	surface is not expected to reference; any module iterating sessions
	uses this helper or mirrors its accessor."""
	return [s for w in app.terminal_windows for t in w.tabs for s in t.sessions]


async def _fresh_name(session) -> str:
	"""Read the live session name via a fresh RPC, falling back to the cached
	snapshot. The app-snapshot `session.name` is populated asynchronously by
	iTerm2 and can lag behind a prior `async_set_name` call from another
	process (see #160, #289), so for identity checks (uniqueness, resolution)
	we query the variable directly.

	Moved here from _session.py so resolve_session can use it without a
	circular import. Kept importable from _session via back-compat re-export."""
	try:
		fresh = await session.async_get_variable('session.name')
	except Exception:
		fresh = None
	if not fresh:
		try:
			fresh = await session.async_get_variable('name')
		except Exception:
			fresh = None
	if not fresh:
		fresh = session.name
	return strip(fresh or '')


async def resolve_session(connection, session_id: str | None = None) -> 'iterm2.Session':
	"""
	Resolve target session by exact UUID, exact name, or 8+ char UUID prefix
	(CONTRACT §2). Raises `ItaError("bad-args")` on empty / ambiguous input
	and `ItaError("not-found")` when nothing matches.

	Name comparison uses the *fresh* variable read (`_fresh_name`) rather
	than the app-snapshot cache, which can lag behind another ita process's
	`async_set_name` (#160, #289).
	"""
	if not session_id:
		raise ItaError("bad-args",
			"no session specified. Use -s NAME or -s UUID-PREFIX.\n"
			"Run 'ita status' to list available sessions.")
	app = await iterm2.async_get_app(connection)
	# 1. Exact session ID match — UUIDs can't collide, no freshness concern.
	session = app.get_session_by_id(session_id)
	if session:
		return session
	# 2. Exact name match — fetch fresh names to avoid the stale-cache race
	#    (#289). Pay one RPC per session; the resolver is rarely on a hot
	#    path and correctness beats the latency tax.
	all_sess = _all_sessions(app)
	fresh_names = [await _fresh_name(s) for s in all_sess]
	name_matches = [s for s, n in zip(all_sess, fresh_names) if n == session_id]
	if len(name_matches) == 1:
		return name_matches[0]
	if len(name_matches) > 1:
		ids = ', '.join(s.session_id[:8] for s in name_matches)
		raise ItaError("bad-args",
			f"session name {session_id!r} is ambiguous — matches: {ids}.\n"
			f"Use -s UUID-PREFIX to disambiguate.")
	# 3. 8+ char UUID prefix match (case-insensitive). Below the threshold
	#    is treated as not-found, not as a short-prefix match — the 8-char
	#    floor is a CONTRACT §2 rule, not a heuristic.
	if len(session_id) >= 8:
		sid_lower = session_id.lower()
		prefix_matches = [s for s in all_sess if s.session_id.lower().startswith(sid_lower)]
		if len(prefix_matches) == 1:
			return prefix_matches[0]
		if len(prefix_matches) > 1:
			ids = ', '.join(s.session_id[:8] for s in prefix_matches)
			raise ItaError("bad-args",
				f"session prefix {session_id!r} is ambiguous — matches: {ids}.")
	raise ItaError("not-found",
		f"session not found: {session_id}. Run 'ita status' to list sessions."
	)

# ── CLI root ────────────────────────────────────────────────────────────────


__version__ = '0.7.0'


@click.group()
@click.version_option(version=__version__)
def cli():
	"""ita — agent-first iTerm2 control."""
	pass


# ── Back-compat re-exports for writelock helpers (moved to _lock.py) ───────
# Phase 2 follow-up cleanup (#256-successor): migrate `from ._core import X`
# call sites to `from ._lock import X` and drop this block. Placed at the
# bottom so `_lock` can `from ._core import cli, run_iterm, ...` without a
# circular import at module-load time.
from ._lock import (  # noqa: E402, F401
	WRITELOCK_FILE, _held_cookies, _load_writelocks, _save_writelocks,
	_pid_alive, acquire_writelock, release_writelock, check_writelock,
	get_writelocks, session_writelock,
)
