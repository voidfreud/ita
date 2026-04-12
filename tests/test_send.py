"""Integration tests for input commands: run, send, inject, key."""
import sys
import time
import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


@pytest.fixture
def settled_session(session):
	"""Session with a 1s pause so the shell is fully ready before run commands."""
	time.sleep(1)
	return session


# ── run ───────────────────────────────────────────────────────────────────────

def test_run_echo(settled_session):
	r = ita('run', 'echo hello', '-s', settled_session)
	assert r.returncode == 0
	assert 'hello' in r.stdout


def test_run_exit_code_passthrough(settled_session):
	r = ita('run', 'exit 42', '-s', settled_session)
	assert r.returncode == 42


def test_run_exit_0(settled_session):
	r = ita('run', 'true', '-s', settled_session)
	assert r.returncode == 0
	assert r.stdout.strip() == ''


def test_run_json(settled_session):
	import json
	r = ita('run', 'echo hi', '--json', '-s', settled_session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert 'output' in data and 'exit_code' in data and 'elapsed_ms' in data
	assert 'hi' in data['output']
	assert data['exit_code'] == 0


def test_run_lines_cap(settled_session):
	"""Last N lines of seq 1 100 with -n 10 should include line 100."""
	r = ita('run', 'seq 1 100', '-n', '10', '-s', settled_session)
	assert r.returncode == 0
	lines = [l for l in r.stdout.splitlines() if l.strip()]
	assert len(lines) <= 10
	assert '100' in r.stdout  # seq 1 100 ends with 100


def test_run_no_trailing_newline_indicator(settled_session):
	"""printf without \\n must not leak prompt indicator into output."""
	r = ita('run', "printf 'noeol'", '-s', settled_session)
	assert r.returncode == 0
	assert r.stdout.strip() == 'noeol'


def test_run_multiline(settled_session):
	r = ita('run', 'printf "a\\nb\\nc"', '-s', settled_session)
	assert r.returncode == 0
	assert r.stdout.strip().splitlines() == ['a', 'b', 'c']


def test_run_no_leading_blank_lines(settled_session):
	r = ita('run', 'echo clean', '-s', settled_session)
	assert r.returncode == 0
	if r.stdout:
		assert not r.stdout.startswith('\n')


@pytest.mark.parametrize('cmd,check', [
	('echo "hello world"',       lambda o: 'hello world' in o),
	('echo $HOME',               lambda o: '/' in o),
	('echo ""',                  lambda o: o.strip() == ''),
])
def test_run_variants(settled_session, cmd, check):
	r = ita('run', cmd, '-s', settled_session)
	assert r.returncode == 0
	assert check(r.stdout), f"Output check failed for {cmd!r}: {r.stdout!r}"


# ── send ──────────────────────────────────────────────────────────────────────

def test_send_with_newline(session):
	r = ita('send', 'echo sent', '-s', session)
	assert r.returncode == 0


def test_send_raw(session):
	r = ita('send', '--raw', 'text', '-s', session)
	assert r.returncode == 0


def test_send_no_newline_alias(session):
	r = ita('send', '-n', 'text', '-s', session)
	assert r.returncode == 0


# ── inject ────────────────────────────────────────────────────────────────────

def test_inject_text(session):
	r = ita('inject', 'hello', '-s', session)
	assert r.returncode == 0


def test_inject_hex_valid(session):
	r = ita('inject', '--hex', '68656c6c6f', '-s', session)  # "hello"
	assert r.returncode == 0


def test_inject_hex_spaces(session):
	r = ita('inject', '--hex', '68 65 6c 6c 6f', '-s', session)
	assert r.returncode == 0


def test_inject_hex_empty_noop(session):
	r = ita('inject', '--hex', '', '-s', session)
	assert r.returncode == 0


def test_inject_hex_invalid():
	r = ita('inject', '--hex', 'zz')
	assert r.returncode == 1
	assert 'hex' in r.stderr.lower() or 'Invalid' in r.stderr


# ── key ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('k', [
	'enter', 'esc', 'tab', 'space', 'backspace',
	'up', 'down', 'left', 'right',
	'home', 'end', 'pgup', 'pgdn', 'delete',
	'f1', 'f5', 'f12', 'f13', 'f19',
])
def test_key_named(session, k):
	r = ita('key', k, '-s', session)
	assert r.returncode == 0, f"key {k} failed: {r.stderr}"


@pytest.mark.parametrize('k', [
	# ctrl+d deliberately omitted — sends EOF, kills session
	'ctrl+a', 'ctrl+b', 'ctrl+c', 'ctrl+e', 'ctrl+z',
	'ctrl+[', 'ctrl+\\', 'ctrl+]',
])
def test_key_ctrl(session, k):
	r = ita('key', k, '-s', session)
	assert r.returncode == 0, f"key {k} failed: {r.stderr}"


@pytest.mark.parametrize('k', ['alt+a', 'alt+f', 'alt+b'])
def test_key_alt(session, k):
	r = ita('key', k, '-s', session)
	assert r.returncode == 0


def test_key_multiple(session):
	r = ita('key', 'ctrl+a', 'ctrl+e', '-s', session)
	assert r.returncode == 0


def test_key_unknown_fails():
	r = ita('key', 'notarealkey')
	assert r.returncode == 1
	assert 'unknown' in r.stderr.lower()
