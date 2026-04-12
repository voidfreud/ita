"""Smoke tests verifying fixes from PRs #149–#152.

Each test maps to a specific bug fix. This file is a one-time merge
verification — once green, these become regression guards.

Ref: https://github.com/voidfreud/ita/issues/157
"""
import json
import sys
import time

import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


# ── PR #149 — broadcast json, event loop, color coercion ────────────────────

@pytest.mark.known_broken
def test_broadcast_list_json_no_crash():
	"""#113: broadcast list --json used to crash with NameError (missing import json)."""
	r = ita('broadcast', 'list', '--json')
	assert r.returncode == 0, f"broadcast list --json crashed: {r.stderr}"
	data = json.loads(r.stdout)
	assert isinstance(data, list)


def test_watch_no_deprecation_warning(session):
	"""#114: watch should use get_running_loop(), not deprecated get_event_loop()."""
	r = ita('watch', '--timeout', '2', '-s', session, timeout=10)
	# watch may exit 0 or 1 (timeout), but should not emit DeprecationWarning
	assert 'DeprecationWarning' not in r.stderr


def test_profile_set_color_dark_coercion(session):
	"""#108: profile set set_cursor_color_dark should coerce hex to iterm2.Color."""
	r = ita('profile', 'set', 'set_cursor_color_dark', '#FF0000', '-s', session)
	assert r.returncode == 0, f"color coercion failed: {r.stderr}"


def test_profile_set_color_light_coercion(session):
	"""#108: _color_light variant also coerces."""
	r = ita('profile', 'set', 'set_cursor_color_light', '#00FF00', '-s', session)
	assert r.returncode == 0, f"color coercion failed: {r.stderr}"


def test_profile_set_plain_color_coercion(session):
	"""#108: plain set_cursor_color also coerces."""
	r = ita('profile', 'set', 'set_cursor_color', '#0000FF', '-s', session)
	assert r.returncode == 0, f"color coercion failed: {r.stderr}"


# ── PR #150 — var get built-ins, repl errors ────────────────────────────────

def test_var_get_builtin_jobName(session):
	"""#101: var get jobName should not prepend user. prefix."""
	r = ita('var', 'get', 'jobName', '-s', session)
	# rc=0 means it resolved the built-in (not user.jobName which would error).
	# Value may be empty on a freshly created session — that's fine.
	assert r.returncode == 0, f"var get jobName failed: {r.stderr}"


def test_var_get_builtin_columns(session):
	"""#101: var get columns — another built-in that must skip user. prefix."""
	r = ita('var', 'get', 'columns', '-s', session)
	assert r.returncode == 0, f"var get columns failed: {r.stderr}"
	val = r.stdout.strip()
	assert val.isdigit(), f"Expected integer column count, got: {val!r}"


def test_var_get_builtin_rows(session):
	"""#101: var get rows — another built-in."""
	r = ita('var', 'get', 'rows', '-s', session)
	assert r.returncode == 0
	assert r.stdout.strip().isdigit()


def test_var_get_dot_qualified_skips_prefix(session):
	"""#101: dot-qualified names like session.name skip user. prefix."""
	r = ita('var', 'get', 'session.name', '-s', session)
	assert r.returncode == 0, f"var get session.name failed: {r.stderr}"


def test_var_get_explicit_user_prefix(session):
	"""#101: explicit user.* prefix is preserved, not doubled."""
	# Set then get with explicit user. prefix
	ita_ok('var', 'set', 'user.smoketest', 'hello', '-s', session)
	r = ita('var', 'get', 'user.smoketest', '-s', session)
	assert r.returncode == 0
	assert 'hello' in r.stdout


def test_repl_error_not_bare_exit_code(session):
	"""#104: repl subcommand failure should show real error, not 'Error: 1'."""
	# Run an invalid command through the CLI (not repl, since repl is interactive)
	# Instead test that a failing command's stderr has a meaningful message
	r = ita('var', 'get', 'nonexistent_unlikely_var_name', '-s', session)
	# Whatever the result, stderr should not contain bare "Error: 1"
	if r.returncode != 0:
		assert 'Error: 1' not in r.stderr, "Bare 'Error: 1' leaked through"


# ── PR #151 — tmux API fixes ────────────────────────────────────────────────
# tmux tests require a tmux-CC session, which may not be available.
# These are light checks that the commands don't crash on import/invocation.

def test_tmux_connections_no_crash():
	"""#121: tmux connections should not crash (was using getattr fallback)."""
	r = ita('tmux', 'connections')
	# rc=0 with empty output (no tmux) or rc=1 with meaningful error — both ok
	# The bug was a TypeError crash, so any clean exit is success
	assert r.returncode in (0, 1), f"tmux connections crashed: {r.stderr}"
	if r.returncode == 1:
		assert 'TypeError' not in r.stderr


def test_tmux_visible_help():
	"""#105: tmux visible subcommand exists and doesn't crash on --help."""
	r = ita('tmux', 'visible', '--help')
	assert r.returncode == 0
	assert 'Usage:' in r.stdout


# ── PR #152 — session identity overhaul ──────────────────────────────────────

def test_status_name_first_format():
	"""#133: status output has NAME, SESSION-ID, PROCESS, PATH columns."""
	r = ita('status')
	assert r.returncode == 0
	header = r.stdout.splitlines()[0]
	assert 'NAME' in header
	assert 'SESSION-ID' in header
	assert 'PROCESS' in header
	assert 'PATH' in header


def test_new_returns_name_tab_uuid():
	"""#134: ita new output is name\\tUUID."""
	r = ita('new')
	assert r.returncode == 0
	parts = r.stdout.strip().split('\t')
	assert len(parts) == 2, f"Expected name\\tUUID, got: {r.stdout.strip()!r}"
	name, uuid = parts
	assert name, "name portion is empty"
	assert uuid, "UUID portion is empty"
	# Cleanup
	ita('close', '-s', uuid)


def test_new_named_session():
	"""#134: ita new --name creates session with that name."""
	test_name = 'ita-smoke-named'
	r = ita('new', '--name', test_name)
	assert r.returncode == 0
	parts = r.stdout.strip().split('\t')
	assert parts[0] == test_name
	sid = parts[-1]
	# Cleanup
	ita('close', '-s', sid)


def test_new_reuse_existing():
	"""#134: ita new --reuse returns existing session if name matches."""
	test_name = 'ita-smoke-reuse'
	r1 = ita('new', '--name', test_name)
	assert r1.returncode == 0
	sid1 = r1.stdout.strip().split('\t')[-1]

	r2 = ita('new', '--name', test_name, '--reuse')
	assert r2.returncode == 0
	sid2 = r2.stdout.strip().split('\t')[-1]
	assert sid1 == sid2, "reuse should return same session ID"

	# Cleanup
	ita('close', '-s', sid1)


def test_new_duplicate_name_without_reuse_fails():
	"""#134: duplicate name without --reuse should error."""
	test_name = 'ita-smoke-dup'
	r1 = ita('new', '--name', test_name)
	assert r1.returncode == 0
	sid = r1.stdout.strip().split('\t')[-1]

	r2 = ita('new', '--name', test_name)
	assert r2.returncode == 1, "duplicate name should fail without --reuse"
	assert 'already exists' in r2.stderr.lower()

	# Cleanup — need to close both if duplicate was created
	ita('close', '-s', sid)
	if r2.returncode == 0:
		sid2 = r2.stdout.strip().split('\t')[-1]
		ita('close', '-s', sid2)


def test_command_without_session_flag_errors():
	"""#111: commands without -s should give clear error, not silent fallback."""
	r = ita('run', 'echo test')
	assert r.returncode == 1
	assert 'no session specified' in r.stderr.lower() or 'session' in r.stderr.lower()


def test_resolve_by_name(session):
	"""#123: -s accepts a session name, not just UUID."""
	# Get the name of our test session
	r = ita('status', '--json')
	assert r.returncode == 0
	sessions = json.loads(r.stdout)
	match = [s for s in sessions if s['session_id'] == session]
	assert match, f"Session {session} not found in status"
	name = match[0]['session_name']
	if name:
		r2 = ita('run', 'echo resolved-by-name', '-s', name)
		assert r2.returncode == 0
		assert 'resolved-by-name' in r2.stdout


def test_resolve_by_uuid_prefix(session):
	"""#123: -s accepts 8+ char UUID prefix."""
	time.sleep(0.5)  # let shell settle
	prefix = session[:8]
	r = ita('run', 'echo resolved-by-prefix', '-s', prefix)
	assert r.returncode == 0
	assert 'resolved-by-prefix' in r.stdout
