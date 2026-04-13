# src/_lock.py
"""Session write-lock — helpers + CLI (#109).

Helpers (moved from `_core.py` in Phase 3 protection-lock cluster):
  WRITELOCK_FILE, acquire_writelock, release_writelock, check_writelock,
  get_writelocks, session_writelock (context manager).

CLI:
  `ita lock -s NAME`       acquire a persistent write-lock
  `ita unlock -s NAME`     release it
  `ita lock --list`        show all locks (live + stale)

Write-lock model (CONTRACT §10):
  Owner identity is `{pid, cookie}` written atomically under fcntl.LOCK_EX.
  Parent-PID-based ownership is FORBIDDEN (closed #282 regression). Unlock
  matches the same cookie `release_writelock` uses; a dead PID is reclaimed
  silently.

Commands that mutate a session (run, send, key, inject, close, clear, restart)
acquire the lock for the duration of the call via `session_writelock` and
release it in a finally block, so a crashed invocation can't leave a
permanent lock.
"""
import fcntl
import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click

from ._envelope import ItaError

# ── Writelock file + state ─────────────────────────────────────────────────
#
# ~/.ita_writelock JSON shape:  {session_id: {"pid": int, "cookie": str, "at": iso8601}}

WRITELOCK_FILE = Path.home() / ".ita_writelock"

# Cookies for locks acquired by this process instance; keyed by session_id.
#
# #321: `_held_cookies` is module-level mutable state. Python has a GIL, but
# dict mutations across async callbacks or sibling threads are not atomic at
# the logical level (a read-then-write can interleave). We guard all access
# with a `threading.Lock` rather than `asyncio.Lock` because the writelock
# helpers are SYNCHRONOUS (fcntl.flock on a file handle) — they're called
# from sync code inside iTerm2 async callbacks, not awaited as coroutines.
# A threading.Lock works in both threaded and async-single-thread contexts.
_held_cookies: dict[str, str] = {}
_held_cookies_lock = threading.Lock()


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
	with _held_cookies_lock:
		_held_cookies[session_id] = cookie
	return True


def release_writelock(session_id: str) -> None:
	"""Release iff held by this process (matched by cookie). No-op otherwise, so safe in finally.

	Read-modify-write of WRITELOCK_FILE happens under fcntl.LOCK_EX so two
	threads/processes releasing different sessions don't overwrite each
	other's pop (which would leave residue in _held_cookies and ghost
	entries on disk). Same locking discipline as acquire_writelock."""
	with _held_cookies_lock:
		our_cookie = _held_cookies.get(session_id)
	if our_cookie is None:
		return  # we never held it
	with open(WRITELOCK_FILE, 'a+') as f:
		fcntl.flock(f, fcntl.LOCK_EX)
		f.seek(0)
		raw = f.read()
		try:
			data = json.loads(raw) if raw.strip() else {}
		except json.JSONDecodeError:
			data = {}
		entry = data.get(session_id)
		if entry is None:
			# Disk entry already gone (raced with another release/acquire).
			# Still clear our in-memory cookie so we don't leak it.
			with _held_cookies_lock:
				_held_cookies.pop(session_id, None)
			return
		stored_cookie = entry.get('cookie')
		if stored_cookie is not None:
			if stored_cookie != our_cookie:
				return
		elif int(entry.get('pid', 0)) != os.getpid():
			return
		data.pop(session_id, None)
		with _held_cookies_lock:
			_held_cookies.pop(session_id, None)
		# Atomic in-place rewrite (still under flock)
		f.seek(0)
		f.truncate()
		if data:
			f.write(json.dumps(data, indent=2) + '\n')


def check_writelock(session_id: str, force_lock: bool = False) -> None:
	"""Raise ItaError("locked", ...) if `session_id` is locked by another live PID.

	Stale entries are NOT reclaimed here — acquire_writelock does that a
	moment later. `--force-lock` (formerly `--force`) skips entirely."""
	if force_lock:
		return
	entry = _load_writelocks().get(session_id)
	if not entry:
		return
	pid = int(entry.get('pid', 0))
	if not _pid_alive(pid):
		return  # stale — acquire_writelock will reclaim
	# If this process already holds the lock, treat as non-blocking (nested
	# re-entry inside the same invocation is safe; the cookie is ours).
	with _held_cookies_lock:
		our_cookie = _held_cookies.get(session_id)
	if our_cookie and entry.get('cookie') == our_cookie:
		return
	raise ItaError("locked",
		f"Session {session_id[:8]}… is write-locked by pid {pid} "
		f"(since {entry.get('at', '?')}). Use --force-lock to override, "
		f"or wait for the other ita invocation to finish.")


def get_writelocks() -> dict:
	"""Current on-disk writelock map. Used by `ita lock --list`."""
	return _load_writelocks()


class session_writelock:
	"""Context manager: check + acquire on enter, release on exit.
	Raises ItaError("locked") if held by another live PID. `--force-lock`
	bypasses entirely. Exception-safe — release runs from __exit__ whether
	the body raised or not, which is the whole point (a crashed write must
	not orphan a lock)."""
	def __init__(self, session_id: str, force_lock: bool = False):
		self.session_id = session_id
		self.force_lock = force_lock
		self.held = False

	def __enter__(self):
		if self.force_lock:
			return self
		check_writelock(self.session_id, force_lock=False)
		if not acquire_writelock(self.session_id):
			# Race: between check and acquire, someone grabbed it.
			raise ItaError("locked",
				f"Session {self.session_id[:8]}… was just write-locked by "
				f"another ita invocation. Retry, or pass --force-lock.")
		self.held = True
		return self

	def __exit__(self, exc_type, exc, tb):
		if self.held:
			release_writelock(self.session_id)
		return False


# ── Deprecated --force alias warning ───────────────────────────────────────

_FORCE_DEPRECATION_WARNED = False


def warn_force_deprecated() -> None:
	"""Emit a one-line deprecation notice to stderr the first time a command
	in this process accepts `--force` as a combined alias. `--force` means
	BOTH `--force-protected` and `--force-lock` (#294). Idempotent."""
	global _FORCE_DEPRECATION_WARNED
	if _FORCE_DEPRECATION_WARNED:
		return
	_FORCE_DEPRECATION_WARNED = True
	print("ita: warning: --force is deprecated; use --force-protected "
		  "and/or --force-lock (#294)", file=sys.stderr)


def resolve_force_flags(force: bool, force_protected: bool, force_lock: bool) -> tuple[bool, bool]:
	"""Collapse legacy `--force` + split flags into (force_protected, force_lock).

	`--force` (deprecated) implies BOTH overrides and fires the deprecation
	warning. Explicit split flags compose with `--force` (union of bypasses)."""
	if force:
		warn_force_deprecated()
		return True, True
	return force_protected, force_lock


# ── CLI: lock / unlock ─────────────────────────────────────────────────────

# Late imports from _core to avoid circular import: _lock is imported by
# _core for re-export back-compat; we need the CLI group + runner at command
# definition time but the helpers above must be importable without _core.
from ._core import cli, run_iterm, resolve_session, confirm_or_skip, success_echo  # noqa: E402


@cli.command()
@click.option('-s', '--session', 'session_id', default=None,
	help='Session to write-lock (name, UUID, or 8+ char UUID prefix).')
@click.option('--list', 'list_only', is_flag=True, help='List all write-locks.')
def lock(session_id, list_only):
	"""Manually acquire a persistent write-lock on a session.

	Unlike the per-command lock (which releases when the write finishes), this
	keeps the lock held by the current shell's PID until `ita unlock` or the
	process exits. Handy when you want to reserve a session across several
	commands while another agent is active."""
	if list_only:
		data = get_writelocks()
		if not data:
			click.echo("No write-locks.")
			return
		for sid, entry in sorted(data.items()):
			pid = int(entry.get('pid', 0))
			alive = 'live' if _pid_alive(pid) else 'stale'
			click.echo(f"{sid}\tpid={pid}\t{alive}\t{entry.get('at', '?')}")
		return
	async def _resolve(connection):
		session = await resolve_session(connection, session_id)
		return session.session_id
	sid = run_iterm(_resolve)
	if acquire_writelock(sid):
		click.echo(f"Write-locked: {sid}")
	else:
		raise ItaError("locked",
			f"Session {sid[:8]}… is already write-locked by another live process.")


@cli.command()
@click.option('-s', '--session', 'session_id', default=None,
	help='Session to unlock.')
@click.option('-y', '--yes', 'yes', is_flag=True, help='Skip confirmation prompt.')
@click.option('--dry-run', is_flag=True, help='Print what would be unlocked without doing it.')
@click.option('-q', '--quiet', is_flag=True, help='Suppress confirmation message.')
def unlock(session_id, yes, dry_run, quiet):
	"""Release a persistent write-lock (reverse of `ita lock`).

	Ownership is matched by COOKIE, not by PID or PPID (CONTRACT §10, #282).
	A dead-PID entry is reclaimed silently; a live-PID entry whose cookie
	we don't hold is refused."""
	if not confirm_or_skip("release write-lock", dry_run=dry_run, yes=yes):
		return
	async def _resolve(connection):
		session = await resolve_session(connection, session_id)
		return session.session_id
	sid = run_iterm(_resolve)
	data = get_writelocks()
	entry = data.get(sid)
	if entry is None:
		success_echo(f"Not write-locked: {sid}", quiet)
		return
	stored_cookie = entry.get('cookie')
	with _held_cookies_lock:
		our_cookie = _held_cookies.get(sid)
	# Cookie match → we own it, release normally.
	if stored_cookie is not None and our_cookie is not None and stored_cookie == our_cookie:
		release_writelock(sid)
		success_echo(f"Unlocked: {sid}", quiet)
		return
	# No cookie match. If the holder's PID is dead, reclaim the entry
	# (stale → safe). Otherwise refuse; do NOT fall back to PPID checks.
	pid = int(entry.get('pid', 0))
	if not _pid_alive(pid):
		data.pop(sid, None)
		_save_writelocks(data)
		success_echo(f"Cleared stale lock: {sid}", quiet)
		return
	raise ItaError("locked",
		f"Session {sid[:8]}… is write-locked by pid {pid}, not this process. "
		f"End that process, or pass --force-lock on the write command.")
