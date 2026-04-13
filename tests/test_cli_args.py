"""Pairwise CLI argument validation tests. No iTerm2 required."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita


# ── help / command registration ───────────────────────────────────────────────

def test_root_help():
	r = ita('--help')
	assert r.returncode == 0
	for cmd in [
		'status', 'run', 'send', 'inject', 'key', 'capture',
		'new', 'close', 'activate', 'name', 'restart', 'resize', 'clear',
		'split', 'pane', 'move', 'tab', 'window', 'save', 'restore', 'layouts',
		'var', 'app', 'pref', 'broadcast',
		'on', 'coprocess', 'annotate', 'rpc',
		'read', 'watch', 'wait', 'selection', 'copy', 'get-prompt',
		'profile', 'theme', 'menu', 'alert', 'ask', 'pick', 'repl',
	]:
		assert cmd in r.stdout, f"Command missing from --help: {cmd}"


@pytest.mark.parametrize('subcmd', [
	['run', '--help'], ['send', '--help'], ['inject', '--help'],
	['key', '--help'], ['capture', '--help'], ['new', '--help'],
	['close', '--help'], ['activate', '--help'], ['name', '--help'],
	['restart', '--help'], ['resize', '--help'], ['clear', '--help'],
	['annotate', '--help'], ['rpc', '--help'],
	['tab', '--help'], ['window', '--help'], ['split', '--help'],
	['var', '--help'], ['pref', '--help'], ['broadcast', '--help'],
	['on', '--help'], ['coprocess', '--help'],
])
def test_subcommand_help(subcmd):
	r = ita(*subcmd)
	assert r.returncode == 0
	assert 'Usage:' in r.stdout


# ── run arg validation ────────────────────────────────────────────────────────

@pytest.mark.parametrize('args,expected_rc', [
	(['run'],                               2),  # missing CMD positional (Click UsageError)
	# Empty-string CMD is a ClickException under the legacy path; the
	# envelope decorator (CONTRACT §6) now maps it to bad-args / rc=6.
	(['run', ''],                           6),
	(['run', 'echo', '--timeout', '0'],     2),  # timeout < min 1
	(['run', 'echo', '--lines', '0'],       2),  # lines < min 1
])
def test_run_bad_args(args, expected_rc):
	r = ita(*args)
	assert r.returncode == expected_rc, (
		f"args={args}: expected rc={expected_rc}, got {r.returncode}\nstderr: {r.stderr}"
	)


# ── inject arg validation ─────────────────────────────────────────────────────

def test_inject_missing_arg():
	"""inject with no DATA arg is a Click UsageError (rc=2), no iTerm2 needed."""
	r = ita('inject')
	assert r.returncode == 2, (
		f"expected rc=2, got {r.returncode}\nstderr: {r.stderr}"
	)


# ── key arg validation ────────────────────────────────────────────────────────

def test_key_no_args():
	r = ita('key')
	assert r.returncode == 2  # missing required KEYS arg


def test_key_unknown_name():
	r = ita('key', 'notarealkey')
	assert r.returncode == 1
	assert 'unknown' in r.stderr.lower()


# ── name validation ───────────────────────────────────────────────────────────

def test_name_whitespace_only_fails():
	# This reaches iTerm2 connection before validation — skip here, tested in test_session.py
	pass


# ── resize validation ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('args,expected_rc', [
	(['resize', '--cols', '80'],          2),  # missing --rows
	(['resize', '--rows', '24'],          2),  # missing --cols
	(['resize'],                          2),  # missing both
])
def test_resize_missing_required(args, expected_rc):
	r = ita(*args)
	assert r.returncode == expected_rc


# ── tab / window close no-args → rc=2 (UsageError) ───────────────────────────

def test_tab_close_no_args():
	# #342: tab close with no tab_id is now an ItaError("bad-args", ...) →
	# rc=6 (was UsageError/rc=2 when --current was a flag).
	r = ita('tab', 'close')
	assert r.returncode == 6, f"Expected rc=6, got {r.returncode}\nstderr: {r.stderr}"


def test_window_close_no_args():
	# #342: WINDOW_ID is now a required positional; Click still uses UsageError
	# (rc=2) for missing positional arguments.
	r = ita('window', 'close')
	assert r.returncode == 2, f"Expected rc=2, got {r.returncode}\nstderr: {r.stderr}"


# ── annotate range validation ─────────────────────────────────────────────────

def test_annotate_start_gt_end():
	# Requires iTerm2 to resolve session before range check — skip here
	pass


# ── capture --lines range ─────────────────────────────────────────────────────

def test_capture_lines_below_min():
	r = ita('capture', '-n', '0')
	assert r.returncode == 2  # below min=1


# ── var validation ────────────────────────────────────────────────────────────

def test_var_set_empty_name():
	# Empty name validation happens after iTerm2 connection — covered in test_config.py
	pass
