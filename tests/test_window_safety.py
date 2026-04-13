"""Tests for CONTRACT §10 window-safety / destructive-blast-radius (#340).

Covers:
  - Single-session close refuses last-session-in-last-tab cascade (rc=6).
  - --allow-window-close opt-in actually proceeds.
  - Multi-tab windows close one tab without cascade (rc=0).
  - `ita window close` requires --allow-window-close.
  - `close --all` skips cascading members and surfaces them in warnings[].
  - Claude Code auto-protect: CLAUDECODE env + ITERM_SESSION_ID → session
	id lands in ~/.ita_protected on any ita invocation.
  - Detection failure is silent: no CLAUDECODE, command still runs.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from helpers import ITA_CMD, ita, _extract_sid, TEST_SESSION_PREFIX


# ── Single-session close cascade refusal ───────────────────────────────────

@pytest.mark.integration
@pytest.mark.regression
def test_close_session_refuses_window_cascade():
	"""A session alone in its tab, alone in its window → close without
	--allow-window-close must rc=6 (bad-args). CONTRACT §10 #340."""
	# Fresh window with a single session.
	r_new = ita('new', '--window', '--name', TEST_SESSION_PREFIX + 'w-cascade-refuse')
	assert r_new.returncode == 0, r_new.stderr
	sid = _extract_sid(r_new.stdout)
	try:
		r = ita('close', '-s', sid)
		assert r.returncode == 6, (
			f"expected rc=6 (cascade refused), got {r.returncode}\n"
			f"stdout: {r.stdout}\nstderr: {r.stderr}"
		)
		assert 'window' in r.stderr.lower() or 'cascade' in r.stderr.lower()
	finally:
		# Cleanup: opt in to cascade so the window actually goes away.
		ita('close', '-s', sid, '--allow-window-close', timeout=10)


@pytest.mark.integration
@pytest.mark.regression
def test_close_session_with_allow_window_close_proceeds():
	"""Same setup + --allow-window-close → rc=0. CONTRACT §10 #340."""
	r_new = ita('new', '--window', '--name', TEST_SESSION_PREFIX + 'w-cascade-allow')
	assert r_new.returncode == 0, r_new.stderr
	sid = _extract_sid(r_new.stdout)
	r = ita('close', '-s', sid, '--allow-window-close')
	assert r.returncode == 0, (
		f"expected rc=0 with --allow-window-close, got {r.returncode}\n"
		f"stdout: {r.stdout}\nstderr: {r.stderr}"
	)


@pytest.mark.integration
@pytest.mark.regression
def test_close_session_in_multitab_window_succeeds():
	"""Two tabs in one window → closing one session rc=0, no cascade.
	CONTRACT §10 #340."""
	r_new = ita('new', '--window', '--name', TEST_SESSION_PREFIX + 'w-multitab-a')
	assert r_new.returncode == 0, r_new.stderr
	sid_a = _extract_sid(r_new.stdout)
	# Second session: a plain tab. `ita new` without --window targets the
	# current terminal window, which is the one we just made (most recent).
	r_new2 = ita('new', '--name', TEST_SESSION_PREFIX + 'w-multitab-b')
	assert r_new2.returncode == 0, r_new2.stderr
	sid_b = _extract_sid(r_new2.stdout)
	try:
		# Closing sid_b is safe — its window still has sid_a's tab.
		r = ita('close', '-s', sid_b)
		assert r.returncode == 0, (
			f"expected rc=0 for non-cascading tab close, got {r.returncode}\n"
			f"stderr: {r.stderr}"
		)
	finally:
		# Teardown — sid_a is now last-in-last-tab, opt in.
		ita('close', '-s', sid_a, '--allow-window-close', timeout=10)
		ita('close', '-s', sid_b, timeout=10)


# ── window close flag requirement ──────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.regression
def test_window_close_requires_flag():
	"""`ita window close -w X` without --allow-window-close → rc=6.
	CONTRACT §10 #340."""
	r_new = ita('window', 'new')
	assert r_new.returncode == 0, r_new.stderr
	wid = r_new.stdout.strip()
	try:
		r = ita('window', 'close', wid)
		assert r.returncode == 6, (
			f"expected rc=6 (flag required), got {r.returncode}\n"
			f"stderr: {r.stderr}"
		)
		assert 'allow-window-close' in r.stderr.lower() or 'window' in r.stderr.lower()
	finally:
		ita('window', 'close', wid, '--allow-window-close', timeout=10)


# ── Bulk close: per-member cascade skip with warnings[] ────────────────────

@pytest.mark.integration
@pytest.mark.regression
def test_clear_all_skips_cascading_members():
	"""Three sessions each alone in their own window → `close --all` skips
	them all (they'd cascade-close the window) and reports each in the
	envelope's warnings[]. CONTRACT §10 "Bulk close protects against
	cascade (#340)".

	Note: the task spec labels this test `clear --all` but the CONTRACT
	cascade-skip logic lives in the bulk `close` path — `clear` is Ctrl+L
	and doesn't destroy anything, so the skip semantics don't apply there.
	"""
	names = [TEST_SESSION_PREFIX + f'cascade-bulk-{i}' for i in range(3)]
	sids = []
	try:
		for n in names:
			r = ita('new', '--window', '--name', n)
			assert r.returncode == 0, r.stderr
			sids.append(_extract_sid(r.stdout))
		# close --all --where name~=ita-test-cascade-bulk- ensures we only
		# match our own sessions; envelope in JSON mode.
		r = ita('close', '--where', f'session_name~={TEST_SESSION_PREFIX}cascade-bulk-',
				'--json')
		# rc may be 0 (partial success is still ok: no members closed but
		# command itself succeeded). Assert structure, not rc.
		envelope = json.loads(r.stdout)
		warn_sids = {
			w.get('session_id') for w in envelope.get('warnings', [])
			if w.get('code') == 'window-cascade-skipped'
		}
		for sid in sids:
			assert sid in warn_sids, (
				f"expected cascade skip for {sid} in warnings[], got "
				f"{envelope.get('warnings')}"
			)
	finally:
		for sid in sids:
			ita('close', '-s', sid, '--allow-window-close', timeout=10)


# ── Claude Code auto-protect ───────────────────────────────────────────────

@pytest.mark.regression
def test_claudecode_session_auto_protected(tmp_path, monkeypatch):
	"""With CLAUDECODE=1 and ITERM_SESSION_ID set, any ita invocation
	adds the session UUID suffix to ~/.ita_protected. CONTRACT §10
	"Auto-protect the Claude Code session (#340)"."""
	# Point ~/.ita_protected at a throwaway file to avoid clobbering the
	# developer's real protected list.
	fake_home = tmp_path
	monkeypatch.setenv('HOME', str(fake_home))
	fake_sid = 'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'
	env = os.environ.copy()
	env['HOME'] = str(fake_home)
	env['CLAUDECODE'] = '1'
	env['ITERM_SESSION_ID'] = f'w0t0p0:{fake_sid}'
	# Any ita command — use `--help` so we don't require iTerm2 connectivity.
	subprocess.run(ITA_CMD + ['--help'], env=env, capture_output=True, timeout=30)
	protected_file = fake_home / '.ita_protected'
	assert protected_file.exists(), "auto-protect hook did not create ~/.ita_protected"
	assert fake_sid in protected_file.read_text(), (
		f"expected {fake_sid} in protected file, got: {protected_file.read_text()!r}"
	)


@pytest.mark.regression
def test_claudecode_detection_failure_is_silent(tmp_path):
	"""With no CLAUDECODE env var, ita still runs and exits normally — the
	auto-protect hook must not block dispatch on detection failure.
	CONTRACT §10 #340."""
	fake_home = tmp_path
	env = os.environ.copy()
	env['HOME'] = str(fake_home)
	env.pop('CLAUDECODE', None)
	env.pop('ITERM_SESSION_ID', None)
	r = subprocess.run(ITA_CMD + ['--help'], env=env, capture_output=True,
					   timeout=30, text=True)
	assert r.returncode == 0, (
		f"ita --help should rc=0 without CLAUDECODE, got {r.returncode}\n"
		f"stderr: {r.stderr}"
	)
	# And no ~/.ita_protected should have appeared.
	protected_file = fake_home / '.ita_protected'
	assert not protected_file.exists(), (
		f"auto-protect must be silent without CLAUDECODE, but protected "
		f"file exists: {protected_file.read_text()!r}"
	)
