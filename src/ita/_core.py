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
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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


@dataclass
class AppSnapshot:
	"""One-shot view of the live iTerm2 app tree (CONTRACT §7).

	Built once per ita invocation by `snapshot()`; subsequent reads are O(1)
	dict/list lookups, never additional `app.async_get_*` sweeps.

	Fields:
	  - `app`: the live `iterm2.App` (still good for direct mutator calls).
	  - `sessions`: every session under `app.terminal_windows` (CONTRACT §2).
	  - `fresh_names`: session_id → fresh name read (parallel-fetched once).
	  - `tab_of` / `window_of`: session_id → containing Tab / Window object.
	  - `current_session_id`: focused session id, or `None`.

	`names()` returns the populated set used for uniqueness / next_free_name.
	The `app` reference stays live; if a caller needs *post-mutation* state
	(e.g. after creating a new session), it should call `snapshot()` again.
	"""
	app: 'iterm2.App'
	sessions: list = field(default_factory=list)
	fresh_names: dict[str, str] = field(default_factory=dict)
	tab_of: dict = field(default_factory=dict)
	window_of: dict = field(default_factory=dict)
	current_session_id: str | None = None

	def names(self) -> set[str]:
		"""Populated fresh-name set, suitable for `next_free_name(taken=…)`."""
		return {n for n in self.fresh_names.values() if n}


async def snapshot(connection) -> AppSnapshot:
	"""Single full app sweep. Replaces ad-hoc `async_get_app(..)` + nested
	loops scattered across commands (#300).

	Fresh names are fetched in parallel via `asyncio.gather` — replaces the
	serial `await _fresh_name(s) for s in …` loops in `resolve_session`,
	`_session_records`, `new`, `tab_new`, `window_new` (#160 + #301)."""
	app = await iterm2.async_get_app(connection)
	snap = AppSnapshot(app=app)
	for window in app.terminal_windows:
		for tab in window.tabs:
			for session in tab.sessions:
				snap.sessions.append(session)
				snap.tab_of[session.session_id] = tab
				snap.window_of[session.session_id] = window
	if snap.sessions:
		names = await asyncio.gather(
			*(_fresh_name(s) for s in snap.sessions),
			return_exceptions=False,
		)
		for s, n in zip(snap.sessions, names):
			snap.fresh_names[s.session_id] = n
	try:
		cw = app.current_terminal_window
		if cw and cw.current_tab and cw.current_tab.current_session:
			snap.current_session_id = cw.current_tab.current_session.session_id
	except AttributeError:
		# Test fakes may not wire current_session through; tolerate it.
		pass
	return snap


def next_free_name(prefix: str, taken: set[str]) -> str:
	"""Lowest-counter free name for an object kind (CONTRACT §2 "Mandatory
	naming on creation (#342)").

	Scans `f"{prefix}1"`, `f"{prefix}2"`, … and returns the first not in
	`taken`. Shared across sessions (`s`), tabs (`t`), windows (`w`), tmux
	sessions (`tmux`) so auto-naming logic is not duplicated per command.
	"""
	i = 1
	while f"{prefix}{i}" in taken:
		i += 1
	return f"{prefix}{i}"


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
	# 2. Exact name match — fetch fresh names via the parallel snapshot
	#    (#289 + #300/#301). One concurrent batch instead of N serial RPCs.
	snap = await snapshot(connection)
	all_sess = snap.sessions
	name_matches = [s for s in all_sess if snap.fresh_names.get(s.session_id) == session_id]
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

# ── Focus capture/restore (#346) ───────────────────────────────────────────
#
# CONTRACT §10: creation commands accept `--background` to suppress the
# focus shift that iTerm2 forces on new tabs/windows/sessions. Capture the
# currently-focused (window, tab, session) BEFORE creating, then restore
# AFTER creating. If the captured target is gone when we go to restore —
# silently proceed (§1 non-goals: no interactive UI decisions).


@dataclass
class FocusSnapshot:
	"""Captured focus triple — any field may be None if nothing was focused."""
	window_id: str | None = None
	tab_id: str | None = None
	session_id: str | None = None


async def capture_focus(app) -> FocusSnapshot:
	"""Snapshot the currently-focused window/tab/session for later restore.

	Best-effort — any missing layer is recorded as None. Never raises; the
	caller uses the result only to pass to `restore_focus`."""
	try:
		window = app.current_terminal_window
		tab = window.current_tab if window else None
		session = tab.current_session if tab else None
		return FocusSnapshot(
			window_id=window.window_id if window else None,
			tab_id=tab.tab_id if tab else None,
			session_id=session.session_id if session else None,
		)
	except Exception:
		return FocusSnapshot()


async def restore_focus(app, snap: FocusSnapshot) -> None:
	"""Re-activate the session/tab/window captured by `capture_focus`.

	Fallback behaviour (#346): if the original target no longer exists,
	proceed silently — the user may have closed it in the interim, which
	is not an error state."""
	if snap is None:
		return
	try:
		if snap.session_id:
			for w in app.terminal_windows:
				for t in w.tabs:
					for s in t.sessions:
						if s.session_id == snap.session_id:
							await s.async_activate(
								select_tab=True, order_window_front=True)
							return
		if snap.tab_id:
			t = app.get_tab_by_id(snap.tab_id)
			if t:
				await t.async_activate(order_window_front=True)
				return
		if snap.window_id:
			w = app.get_window_by_id(snap.window_id)
			if w:
				await w.async_activate()
	except Exception:
		# §1 non-goal: never surface focus-restore failures to the agent.
		pass


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
