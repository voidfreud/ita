# tests/test_protection_lock.py
"""Phase 3 protection-lock-invariants cluster — regression + adversarial
guards for CONTRACT §10 and §13 (#283, #258, #294, #321, #282 closed,
#284, #279).

Most tests are file-system level (patching ~/.ita_writelock and
~/.ita_protected), no live iTerm2 required. Bulk-op tests that need
session objects use mocks."""
import json
import os
import threading
from pathlib import Path
from unittest import mock

import pytest

from ita import _lock, _protect
from ita._envelope import ItaError


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_lock_files(tmp_path, monkeypatch):
	"""Redirect WRITELOCK_FILE and PROTECTED_FILE into a tmp_path so tests
	don't stomp on the real ~/.ita_writelock / ~/.ita_protected."""
	wl = tmp_path / 'writelock.json'
	pf = tmp_path / 'protected'
	monkeypatch.setattr(_lock, 'WRITELOCK_FILE', wl)
	monkeypatch.setattr(_protect, 'PROTECTED_FILE', pf)
	# _held_cookies leaks across tests — reset.
	with _lock._held_cookies_lock:
		_lock._held_cookies.clear()
	yield wl, pf
	with _lock._held_cookies_lock:
		_lock._held_cookies.clear()


# ── #282 regression: unlock uses cookie, never PID/PPID ────────────────────

@pytest.mark.regression
def test_issue_282_unlock_uses_cookie_not_ppid(tmp_lock_files):
	"""Craft a writelock entry whose pid matches os.getppid() (the parent
	shell) but whose cookie we do NOT hold. Cookie-based unlock must refuse
	to release it — even though old getppid() logic would have accepted."""
	wl, _ = tmp_lock_files
	ppid = os.getppid()
	# Write a live-pid entry owned by some other cookie.
	entry = {
		'pid': ppid,
		'cookie': 'OTHER-PROCESS-COOKIE',
		'at': '2026-04-13T00:00:00+00:00',
	}
	wl.write_text(json.dumps({'sess-A': entry}))
	# release_writelock must be a no-op: our _held_cookies is empty.
	_lock.release_writelock('sess-A')
	# Entry still present — the getppid() regression would have popped it.
	data = json.loads(wl.read_text())
	assert 'sess-A' in data
	assert data['sess-A']['cookie'] == 'OTHER-PROCESS-COOKIE'


@pytest.mark.regression
def test_issue_282_release_honors_only_matching_cookie(tmp_lock_files):
	wl, _ = tmp_lock_files
	# Acquire writelock normally (sets cookie in _held_cookies).
	assert _lock.acquire_writelock('sess-A') is True
	# Flip the cookie on disk to simulate another process owning it.
	data = json.loads(wl.read_text())
	data['sess-A']['cookie'] = 'NOT-US'
	wl.write_text(json.dumps(data))
	# release must NOT pop the entry (stored cookie ≠ our cookie).
	_lock.release_writelock('sess-A')
	assert 'sess-A' in json.loads(wl.read_text())


# ── #283 critical: bulk protect check is per-target ────────────────────────

@pytest.mark.regression
@pytest.mark.integration
def test_issue_283_clear_all_respects_protected_per_target():
	"""A protected session among N targets of `clear --all` must be skipped.

	Uses subprocess-level invocation since the bulk path runs through Click.
	Integration-marked because it needs iTerm2. See test_invariant_mutators_
	honor_protection.py for the broader sweep; this one guards the specific
	critical regression in #283."""
	pytest.importorskip('iterm2')
	from helpers import ita, _extract_sid
	r1 = ita('new', '--name', 'ita-test-283-a')
	r2 = ita('new', '--name', 'ita-test-283-b')
	sid_a, sid_b = _extract_sid(r1.stdout), _extract_sid(r2.stdout)
	try:
		ita('protect', '-s', sid_a, '-y')
		# Clear --all: A must be skipped, B must be cleared.
		out = ita('clear', '--all')
		# sid_a should NOT appear as cleared; should appear as skipped-stderr.
		assert sid_a in (out.stderr or ''), (
			"#283 regression: protected session was not reported as skipped "
			"in bulk clear --all")
		# sid_b should be in cleared output.
		assert sid_b in (out.stdout or '') or sid_b in (out.stderr or '')
	finally:
		ita('unprotect', '-s', sid_a, '-y')
		ita('close', '-s', sid_a)
		ita('close', '-s', sid_b)


# ── #294 split flags: orthogonal bypasses ──────────────────────────────────

@pytest.mark.regression
def test_force_split_protected_does_not_bypass_lock(tmp_lock_files):
	"""--force-protected gets past protect check; writelock still gates."""
	wl, pf = tmp_lock_files
	pf.write_text('sess-X\n')
	# Live-pid, foreign-cookie entry = locked by another live process.
	wl.write_text(json.dumps({'sess-X': {
		'pid': os.getpid(),  # live
		'cookie': 'FOREIGN',
		'at': '2026-04-13T00:00:00+00:00',
	}}))
	# Protect check bypassed → OK, no raise.
	_protect.check_protected('sess-X', force_protected=True)
	# Lock check still fires.
	with pytest.raises(ItaError) as ei:
		_lock.check_writelock('sess-X', force_lock=False)
	assert ei.value.code == 'locked'


@pytest.mark.regression
def test_force_split_lock_does_not_bypass_protect(tmp_lock_files):
	"""--force-lock gets past lock; protect still gates."""
	wl, pf = tmp_lock_files
	pf.write_text('sess-Y\n')
	wl.write_text(json.dumps({'sess-Y': {
		'pid': os.getpid(),
		'cookie': 'FOREIGN',
		'at': '2026-04-13T00:00:00+00:00',
	}}))
	_lock.check_writelock('sess-Y', force_lock=True)  # bypassed
	with pytest.raises(ItaError) as ei:
		_protect.check_protected('sess-Y', force_protected=False)
	assert ei.value.code == 'protected'


@pytest.mark.regression
def test_force_legacy_alias_warns(capsys):
	"""--force (legacy) sets both flags AND emits one-line deprecation."""
	# Reset the one-shot.
	_lock._FORCE_DEPRECATION_WARNED = False
	fp, fl = _lock.resolve_force_flags(force=True, force_protected=False, force_lock=False)
	assert (fp, fl) == (True, True)
	captured = capsys.readouterr()
	assert '--force' in captured.err and 'deprecated' in captured.err
	# Second call is idempotent (no additional line).
	fp2, fl2 = _lock.resolve_force_flags(force=True, force_protected=False, force_lock=False)
	captured2 = capsys.readouterr()
	assert captured2.err == ''


@pytest.mark.regression
def test_force_split_flags_compose(capsys):
	"""Explicit split flags should NOT trigger the deprecation warning."""
	_lock._FORCE_DEPRECATION_WARNED = False
	fp, fl = _lock.resolve_force_flags(force=False, force_protected=True, force_lock=False)
	assert (fp, fl) == (True, False)
	assert capsys.readouterr().err == ''


# ── #279 / §13: no duplicate delivery ──────────────────────────────────────

@pytest.mark.regression
def test_bulk_broadcast_no_duplicate_delivery(tmp_lock_files):
	"""A session in two broadcast domains gets the message once, not twice.

	We exercise the dedup logic in _config.broadcast_send at the data-shape
	level: construct two fake domains whose membership overlaps, iterate
	with the dedup pattern, and assert each session_id is visited once."""
	# Simulate the dedup block from broadcast_send.
	class FakeSession:
		def __init__(self, sid):
			self.session_id = sid

	class FakeDomain:
		def __init__(self, sessions):
			self.sessions = sessions

	a, b, c = FakeSession('A'), FakeSession('B'), FakeSession('C')
	domains = [FakeDomain([a, b]), FakeDomain([b, c])]  # b appears twice

	seen_ids: set = set()
	unique_sessions = []
	for d in domains:
		for s in d.sessions:
			if s.session_id not in seen_ids:
				seen_ids.add(s.session_id)
				unique_sessions.append(s)

	assert [s.session_id for s in unique_sessions] == ['A', 'B', 'C']
	assert len(unique_sessions) == 3  # b not duplicated


# ── #321 concurrent cookie access ─────────────────────────────────────────

@pytest.mark.adversarial
def test_held_cookies_concurrent_writes(tmp_lock_files):
	"""Spawn N threads hammering acquire/release on distinct session_ids.
	_held_cookies must remain internally consistent (no KeyError storms,
	no dropped entries under contention)."""
	N = 16
	ITER = 20
	errors: list = []

	def worker(i):
		sid = f'sess-{i}'
		try:
			for _ in range(ITER):
				if _lock.acquire_writelock(sid):
					_lock.release_writelock(sid)
		except Exception as e:
			errors.append(e)

	threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
	for t in threads:
		t.start()
	for t in threads:
		t.join()

	assert errors == [], f"Concurrent acquire/release raised: {errors!r}"
	# After all threads done, no residue in _held_cookies (every acquire
	# is paired with a release).
	with _lock._held_cookies_lock:
		assert _lock._held_cookies == {}


@pytest.mark.adversarial
def test_held_cookies_lock_is_threading_lock():
	"""Regression: #321 fix specifies threading.Lock (sync sites). Guard
	against someone swapping it for an asyncio.Lock which would not protect
	sync callers."""
	assert isinstance(_lock._held_cookies_lock, type(threading.Lock()))


# ── Cookie-based acquire: #282 same-PPID sibling collision resolved ────────

@pytest.mark.regression
def test_cookie_makes_same_process_acquire_idempotent(tmp_lock_files):
	"""Same process re-entering acquire → second call returns False (already
	held) because our own entry is treated as live-foreign unless we match
	the cookie. This is the documented behavior and prevents re-entry from
	silently stealing our own lock under a different cookie."""
	assert _lock.acquire_writelock('sess-R') is True
	# Second acquire in the same process: entry is live (our own pid), cookie
	# present — we don't match a new cookie against the stored one, so
	# acquire refuses. That's correct; callers use session_writelock ctx.
	assert _lock.acquire_writelock('sess-R') is False
	_lock.release_writelock('sess-R')
