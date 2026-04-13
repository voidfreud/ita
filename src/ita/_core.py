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
import fcntl
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
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

# ── Session write-lock (#109) ──────────────────────────────────────────────
#
# Lightweight per-session exclusive lock so two concurrent ita invocations
# (e.g. parallel Claude agents) can't interleave writes on the same session.
# Held only for the duration of a single write command; a crashed invocation
# leaves behind a stale record that the next caller reclaims via a live-PID
# probe (os.kill(pid, 0)). ~/.ita_writelock JSON shape:
#     {session_id: {"pid": int, "at": iso8601}}
#
# TODO (Phase 3 protection-lock branch): move to _lock.py.

WRITELOCK_FILE = Path.home() / ".ita_writelock"
# Cookies for locks acquired by this process instance; keyed by session_id.
_held_cookies: dict[str, str] = {}


def _load_writelocks() -> dict:
	if not WRITELOCK_FILE.exists():
		return {}
	try:
		return json.loads(WRITELOCK_FILE.read_text() or '{}')
	except (json.JSONDecodeError, OSError):
		return {}  # corrupt → treat empty; a write will overwrite cleanly


def _save_writelocks(data: dict) -> None:
	if data:
		WRITELOCK_FILE.write_text(json.dumps(data, indent=2) + '\n')
	else:
		WRITELOCK_FILE.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
	"""True if a process with `pid` is alive. ProcessLookupError → dead;
	PermissionError means something's there but we can't signal it → alive."""
	if pid <= 0:
		return False
	try:
		os.kill(pid, 0)
		return True
	except ProcessLookupError:
		return False
	except PermissionError:
		return True


def acquire_writelock(session_id: str) -> bool:
	"""Try to claim the write-lock. Returns False if another *live* PID+cookie
	holds it; stale locks (dead PID or no cookie) are silently reclaimed.

	Owner identity is {pid, cookie} so same-parent invocations (#282) can't
	collide: each process gets its own unique cookie written atomically via
	fcntl.LOCK_EX (fixes TOCTOU, #197)."""
	cookie = uuid.uuid4().hex
	with open(WRITELOCK_FILE, 'a+') as f:
		fcntl.flock(f, fcntl.LOCK_EX)
		f.seek(0)
		raw = f.read()
		try:
			data = json.loads(raw) if raw.strip() else {}
		except json.JSONDecodeError:
			data = {}
		entry = data.get(session_id)
		# Old-format entries (no cookie) are treated as stale and reclaimed.
		if entry and entry.get('cookie') and _pid_alive(int(entry.get('pid', 0))):
			return False
		data[session_id] = {
			'pid': os.getpid(),
			'cookie': cookie,
			'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
		}
		f.seek(0)
		f.truncate()
		f.write(json.dumps(data, indent=2) + '\n')
	_held_cookies[session_id] = cookie
	return True


def release_writelock(session_id: str) -> None:
	"""Release iff held by this process (matched by cookie). No-op otherwise, so safe in finally."""
	data = _load_writelocks()
	entry = data.get(session_id)
	if entry:
		stored_cookie = entry.get('cookie')
		our_cookie = _held_cookies.get(session_id)
		# New-format: must match cookie. Old-format (no cookie): fall back to pid.
		if stored_cookie is not None:
			if stored_cookie != our_cookie:
				return
		elif int(entry.get('pid', 0)) != os.getpid():
			return
		data.pop(session_id, None)
		_held_cookies.pop(session_id, None)
		_save_writelocks(data)


def check_writelock(session_id: str, force: bool = False) -> None:
	"""Raise ClickException if `session_id` is locked by another live PID.

	Stale entries are NOT reclaimed here — acquire_writelock does that a
	moment later. --force skips entirely (mirrors check_protected)."""
	if force:
		return
	entry = _load_writelocks().get(session_id)
	if not entry:
		return
	pid = int(entry.get('pid', 0))
	if not _pid_alive(pid):
		return  # stale — acquire_writelock will reclaim
	raise click.ClickException(
		f"Session {session_id[:8]}… is write-locked by pid {pid} "
		f"(since {entry.get('at', '?')}). Use --force to override, "
		f"or wait for the other ita invocation to finish."
	)


def get_writelocks() -> dict:
	"""Current on-disk writelock map. Used by `ita lock --list`."""
	return _load_writelocks()


class session_writelock:
	"""Context manager: check + acquire on enter, release on exit. Raises
	ClickException if held by another live PID. --force bypasses entirely.
	Exception-safe — release runs from __exit__ whether the body raised or
	not, which is the whole point (a crashed write must not orphan a lock)."""
	def __init__(self, session_id: str, force: bool = False):
		self.session_id = session_id
		self.force = force
		self.held = False

	def __enter__(self):
		if self.force:
			return self
		check_writelock(self.session_id, force=False)
		if not acquire_writelock(self.session_id):
			# Race: between check and acquire, someone grabbed it.
			raise click.ClickException(
				f"Session {self.session_id[:8]}… was just write-locked by "
				f"another ita invocation. Retry, or pass --force."
			)
		self.held = True
		return self

	def __exit__(self, exc_type, exc, tb):
		if self.held:
			release_writelock(self.session_id)
		return False


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
	"""Return a flat list of every session across all windows/tabs."""
	return [s for w in app.terminal_windows for t in w.tabs for s in t.sessions]


async def resolve_session(connection, session_id: str | None = None) -> 'iterm2.Session':
	"""
	Resolve target session by exact ID, name, or 8+ char UUID prefix.
	Raises ClickException if no session_id given or nothing found.
	"""
	if not session_id:
		raise ItaError("bad-args",
			"no session specified. Use -s NAME or -s UUID-PREFIX.\n"
			"Run 'ita status' to list available sessions.")
	app = await iterm2.async_get_app(connection)
	# 1. Exact session ID match
	session = app.get_session_by_id(session_id)
	if session:
		return session
	# 2. Exact name match
	all_sess = _all_sessions(app)
	name_matches = [s for s in all_sess if s.name == session_id]
	if len(name_matches) == 1:
		return name_matches[0]
	if len(name_matches) > 1:
		ids = ', '.join(s.session_id[:8] for s in name_matches)
		raise ItaError("bad-args",
			f"session name {session_id!r} is ambiguous — matches: {ids}.\n"
			f"Use -s UUID-PREFIX to disambiguate.")
	# 3. 8+ char UUID prefix match (case-insensitive)
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
