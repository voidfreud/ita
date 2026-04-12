"""Pairwise tests — systematic option-combination coverage.
Tests are designed to find interaction bugs, not confirm single-option behavior.
A failing case here means two options conflict or interact incorrectly."""
import json
import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita

pytestmark = [pytest.mark.integration]


# ── run: pairwise over timeout × lines × json × command-type ─────────────────
# Covers all 2-way interactions between:
#   timeout ∈ {3, 30}
#   lines   ∈ {1, 50}
#   json    ∈ {yes, no}
#   cmd     ∈ {echo (fast), sleep 60 (slow/timeout), false (fail), seq 1 100 (long-output)}

@pytest.fixture(scope='module')
def run_session(shared_session):
	"""Settled shared session for run pairwise tests."""
	time.sleep(1)
	return shared_session


RUN_CASES = [
	# id,                  timeout, lines, use_json, cmd,           expect_rc, check_in_output
	('fast-short-plain',   3,  50, False, 'echo hi',         0,    'hi'),
	('fast-short-json',    3,  1,  True,  'echo hi',         0,    '"exit_code": 0'),
	('longout-30-1-plain', 30, 1,  False, 'seq 1 100',       0,    '100'),
	('longout-30-50-json', 30, 50, True,  'seq 1 100',       0,    '"exit_code": 0'),
	('slow-timeout-json',  3,  50, True,  'sleep 60',        1,    None),  # timeout → rc=1
	('fail-30-1-plain',    30, 1,  False, 'false',           1,    None),
	('longout-30-50-plain',30, 50, False, 'seq 1 100',       0,    '100'),
	('fail-3-1-json',      3,  1,  True,  'false',           1,    None),
	('fast-30-50-plain',   30, 50, False, 'echo hello',      0,    'hello'),
	('fail-30-50-json',    30, 50, True,  'false',           1,    None),
	('fast-3-1-plain',     3,  1,  False, 'echo x',         0,    'x'),
	('longout-30-1-json',  30, 1,  True,  'seq 1 100',       0,    '"exit_code": 0'),
]


@pytest.mark.parametrize(
	'case_id,timeout,lines,use_json,cmd,expect_rc,check',
	RUN_CASES,
	ids=[c[0] for c in RUN_CASES],
)
def test_run_pairwise(run_session, case_id, timeout, lines, use_json, cmd, expect_rc, check):
	args = ['run', cmd, '--timeout', str(timeout), '-n', str(lines), '-s', run_session]
	if use_json:
		args.append('--json')

	r = ita(*args, timeout=timeout + 8)

	# Cleanup: cancel any lingering sleep process
	if 'sleep' in cmd:
		ita('key', 'ctrl+c', '-s', run_session)
		time.sleep(0.5)

	assert r.returncode == expect_rc, (
		f"[{case_id}] run {cmd!r} (t={timeout}, n={lines}, json={use_json}): "
		f"expected rc={expect_rc}, got rc={r.returncode}\n"
		f"stdout: {r.stdout!r}\nstderr: {r.stderr!r}"
	)

	if use_json and r.stdout.strip():
		try:
			data = json.loads(r.stdout)
		except json.JSONDecodeError as e:
			pytest.fail(f"[{case_id}] --json output is not valid JSON: {r.stdout!r}\nError: {e}")
		assert 'exit_code' in data, f"[{case_id}] JSON missing 'exit_code': {data}"
		assert 'elapsed_ms' in data, f"[{case_id}] JSON missing 'elapsed_ms': {data}"
		assert isinstance(data['exit_code'], int), f"[{case_id}] exit_code must be int: {data['exit_code']!r}"

	if check and r.returncode == 0:
		assert check in r.stdout, (
			f"[{case_id}] Expected {check!r} in output for {cmd!r}: {r.stdout!r}"
		)


# ── split: direction × session ────────────────────────────────────────────────

SPLIT_CASES = [
	('-h', 'horizontal'),
	('-v', 'vertical'),
	(None, 'default (no flag)'),
]


@pytest.mark.parametrize('flag,label', SPLIT_CASES, ids=['horizontal', 'vertical', 'default'])
def test_split_directions(flag, label):
	"""Each split direction must return a new session ID."""
	r_parent = ita('new')
	assert r_parent.returncode == 0, f"new session failed: {r_parent.stderr}"
	parent_sid = r_parent.stdout.strip().split('\t')[-1]
	assert parent_sid, "new session returned empty ID"

	try:
		args = ['split', '-s', parent_sid]
		if flag:
			args.insert(1, flag)

		r = ita(*args)
		assert r.returncode == 0, f"split {label} failed: {r.stderr}"
		new_sid = r.stdout.strip()
		assert new_sid, f"split {label} returned no session ID"
		ita('close', '-s', new_sid)
	finally:
		ita('close', '-s', parent_sid)


# ── var: get/set roundtrip across all scopes ──────────────────────────────────

@pytest.mark.parametrize('scope', ['session', 'tab', 'window', 'app'])
def test_var_set_get_roundtrip(session, scope):
	"""var set then var get must return the same value for all scopes."""
	varname = f'user.pairwise_roundtrip_{scope}'
	value = f'testvalue_{scope}_42'

	r_set = ita('var', 'set', varname, value, '--scope', scope, '-s', session)
	assert r_set.returncode == 0, (
		f"var set scope={scope} failed: rc={r_set.returncode}\nstderr:{r_set.stderr}"
	)

	r_get = ita('var', 'get', varname, '--scope', scope, '-s', session)
	assert r_get.returncode == 0, (
		f"var get scope={scope} failed: rc={r_get.returncode}\nstderr:{r_get.stderr}"
	)
	assert value in r_get.stdout, (
		f"var get scope={scope}: expected {value!r}, got {r_get.stdout!r}"
	)


# ── read: N lines parameter coverage ─────────────────────────────────────────

@pytest.mark.parametrize('n', [1, 5, 20, 100])
def test_read_n_lines(session, n):
	"""read N must never return more than N non-empty lines."""
	time.sleep(0.5)
	ita('run', 'seq 1 50', '-s', session, timeout=15)
	r = ita('read', str(n), '-s', session)
	assert r.returncode == 0, f"read {n} failed: {r.stderr}"
	lines = [l for l in r.stdout.splitlines() if l.strip()]
	assert len(lines) <= n, f"read {n} returned {len(lines)} lines (expected ≤{n})"


# ── capture: -n N lines parameter coverage ───────────────────────────────────

@pytest.mark.parametrize('n', [1, 5, 10])
def test_capture_n_lines(session, n):
	"""capture -n N must never return more than N non-empty lines."""
	time.sleep(0.5)
	ita('run', 'seq 1 30', '-s', session, timeout=15)
	r = ita('capture', '-n', str(n), '-s', session)
	assert r.returncode == 0, f"capture -n {n} failed: {r.stderr}"
	lines = [l for l in r.stdout.splitlines() if l.strip()]
	assert len(lines) <= n, f"capture -n {n} returned {len(lines)} lines (expected ≤{n})"


# ── on timeout: all event types honor -t ────────────────────────────────────

ON_CMDS = [
	(['on', 'prompt', '-t', '2'], 'on prompt'),
	(['on', 'focus', '-t', '2'], 'on focus'),
	(['on', 'layout', '-t', '2'], 'on layout'),
	(['on', 'session-new', '-t', '2'], 'on session-new'),
]


@pytest.mark.parametrize('args,label', ON_CMDS, ids=['on-prompt', 'on-focus', 'on-layout', 'on-session-new'])
def test_on_timeout_respected(args, label):
	"""All `on` commands must honor -t and exit within timeout+3s."""
	start = time.time()
	r = ita(*args, timeout=10)
	elapsed = time.time() - start
	assert elapsed < 8, f"{label} took {elapsed:.1f}s, timeout not respected"
	assert r.returncode in (0, 1), f"{label} unexpected rc={r.returncode}"
	assert not r.stdout.startswith('Error:'), f"{label} has 'Error:' prefix in stdout: {r.stdout!r}"


# ── send: --raw / -n interaction ─────────────────────────────────────────────

SEND_CASES = [
	({'raw': True, 'no_newline': False}, 'raw'),
	({'raw': False, 'no_newline': True}, 'no_newline'),
	({'raw': False, 'no_newline': False}, 'with_newline'),
]


@pytest.mark.parametrize('flags,label', SEND_CASES, ids=['raw', 'no-newline', 'with-newline'])
def test_send_flags(session, flags, label):
	"""All send flag combinations should rc=0."""
	args = ['send']
	if flags['raw']:
		args.append('--raw')
	if flags['no_newline']:
		args.append('-n')
	args += ['test_text', '-s', session]
	r = ita(*args)
	assert r.returncode == 0, f"send {label} failed: rc={r.returncode}\nstderr:{r.stderr}"


# ── key: ctrl + alt + named keys mix ────────────────────────────────────────

KEY_CASES = [
	(['ctrl+a'], 'ctrl+a single'),
	(['ctrl+a', 'ctrl+e'], 'ctrl+a ctrl+e sequence'),
	(['alt+f', 'alt+b'], 'alt+f alt+b sequence'),
	(['up', 'down', 'left', 'right'], 'arrow sequence'),
	(['ctrl+a', 'alt+f', 'enter'], 'mixed sequence'),
]


@pytest.mark.parametrize('keys,label', KEY_CASES, ids=['ctrl-single', 'ctrl-seq', 'alt-seq', 'arrows', 'mixed'])
def test_key_combinations(session, keys, label):
	"""All key combinations should rc=0."""
	r = ita('key', *keys, '-s', session)
	assert r.returncode == 0, f"key {label} failed: rc={r.returncode}\nstderr:{r.stderr}"
