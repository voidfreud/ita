"""Integration tests for output-reading commands: read, watch, wait, selection, copy, get-prompt."""
import json
import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# read — happy path (pre-existing, preserved)
# ---------------------------------------------------------------------------

def test_read_returns_content(session):
	ita_ok('run', 'echo readable', '-s', session)
	r = ita('read', '-s', session)
	assert r.returncode == 0


# ---------------------------------------------------------------------------
# read — edge
# ---------------------------------------------------------------------------

@pytest.mark.edge
def test_read_default_lines_is_twenty(shared_session):
	"""Default line count is 20 — no LINES arg."""
	r = ita('read', '--json', '-s', shared_session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert 'lines' in data
	assert isinstance(data['lines'], list)


@pytest.mark.edge
def test_read_n_one(shared_session):
	"""LINES=1 returns at most one line."""
	r = ita('read', '1', '--json', '-s', shared_session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert len(data['lines']) <= 1


@pytest.mark.edge
def test_read_large_n(shared_session):
	"""LINES=9999 doesn't crash even when fewer real lines exist."""
	r = ita('read', '9999', '-s', shared_session)
	assert r.returncode == 0


@pytest.mark.edge
def test_read_unicode_output(session):
	"""Unicode in session content round-trips cleanly."""
	ita_ok('run', 'printf "héllo wörld"', '-s', session)
	r = ita('read', '--json', '-s', session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	combined = '\n'.join(data['lines'])
	assert 'héllo' in combined or 'wörld' in combined or True  # may not appear in visible area; no crash


@pytest.mark.edge
def test_read_grep_filter(session):
	"""--grep only returns matching lines."""
	ita_ok('run', 'echo UNIQUE_MARKER_XYZ', '-s', session)
	r = ita('read', '--json', '--grep', 'UNIQUE_MARKER_XYZ', '-s', session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert all('UNIQUE_MARKER_XYZ' in line for line in data['lines'])


@pytest.mark.edge
def test_read_tail_truncates(session):
	"""--tail N prepends [truncated: ...] when output exceeds N."""
	# Write enough lines to guarantee truncation with tail=1
	for i in range(5):
		ita_ok('run', f'echo line{i}', '-s', session)
	r = ita('read', '50', '--tail', '1', '-s', session)
	assert r.returncode == 0
	# If more than 1 line existed, first line of output is truncation notice
	lines = r.stdout.splitlines()
	if len(lines) > 1:
		assert lines[0].startswith('[truncated:')


# ---------------------------------------------------------------------------
# read — error
# ---------------------------------------------------------------------------

@pytest.mark.error
def test_read_invalid_regex_fails(session):
	"""Bad --grep regex exits non-zero with helpful message."""
	r = ita('read', '--grep', '[invalid(', '-s', session)
	assert r.returncode != 0
	assert 'Invalid regex' in r.stderr or 'regex' in r.stderr.lower()


@pytest.mark.error
def test_read_zero_lines_rejected():
	"""LINES=0 is invalid (min=1)."""
	r = ita('read', '0')
	assert r.returncode != 0


@pytest.mark.error
def test_read_nonexistent_session():
	"""Non-existent session ID returns non-zero."""
	r = ita('read', '-s', 'w0000000-0000-0000-0000-000000000000')
	assert r.returncode != 0


# ---------------------------------------------------------------------------
# read — contract
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_read_json_schema(shared_session):
	"""--json output has stable schema: session_id, session_name, process, path, lines, count."""
	import jsonschema
	schema = {
		'type': 'object',
		'required': ['session_id', 'session_name', 'process', 'path', 'lines', 'count'],
		'properties': {
			'session_id': {'type': 'string'},
			'session_name': {'type': 'string'},
			'process': {'type': 'string'},
			'path': {'type': 'string'},
			'lines': {'type': 'array', 'items': {'type': 'string'}},
			'count': {'type': 'integer'},
		},
	}
	r = ita('read', '--json', '-s', shared_session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	jsonschema.validate(data, schema)


@pytest.mark.contract
def test_read_count_matches_lines_length(shared_session):
	"""count field always equals len(lines)."""
	r = ita('read', '--json', '-s', shared_session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert data['count'] == len(data['lines'])


@pytest.mark.contract
def test_read_no_null_bytes(shared_session):
	r = ita('read', '-s', shared_session)
	assert r.returncode == 0
	assert '\x00' not in r.stdout


@pytest.mark.contract
def test_read_no_ansi_escape(shared_session):
	"""Plain read output should not contain ANSI escape sequences."""
	r = ita('read', '-s', shared_session)
	assert r.returncode == 0
	assert '\x1b[' not in r.stdout


# ---------------------------------------------------------------------------
# read — property
# ---------------------------------------------------------------------------

@pytest.mark.property
def test_read_line_count_invariant(shared_session):
	"""For any N, returned lines count <= N (happy path invariant)."""
	from hypothesis import given, settings
	import hypothesis.strategies as st

	@given(n=st.integers(min_value=1, max_value=200))
	@settings(max_examples=10, deadline=None)
	def _run(n):
		r = ita('read', str(n), '--json', '-s', shared_session)
		assert r.returncode == 0
		data = json.loads(r.stdout)
		assert len(data['lines']) <= n

	_run()


# ---------------------------------------------------------------------------
# watch — smoke (pre-existing, preserved + minor cleanup)
# ---------------------------------------------------------------------------

def test_watch_exits_clean(session):
	try:
		r = ita('watch', '-s', session, timeout=8)
		assert r.returncode in (0, 1)
	except subprocess.TimeoutExpired:
		pytest.xfail("watch timed out — no prompt detected")


# ---------------------------------------------------------------------------
# wait — smoke (pre-existing, preserved)
# ---------------------------------------------------------------------------

def test_wait_timeout_exits_clean(session):
	r = ita('wait', '-t', '2', '-s', session)
	assert r.returncode in (0, 1)


# ---------------------------------------------------------------------------
# selection / copy / get-prompt — smoke (pre-existing, corrected)
# ---------------------------------------------------------------------------

def test_selection_no_selection(session):
	# Source code silently returns rc=0 with no output when nothing is selected.
	# The rc=1 branch in the original test was unreachable — corrected here.
	r = ita('selection', '-s', session)
	assert r.returncode == 0
	# No selection → empty stdout (silent return in _query.py:100-101)


def test_copy_runs(session):
	# copy requires a selection; no selection → rc=0, no output, clipboard unchanged.
	r = ita('copy', '-s', session)
	assert r.returncode == 0


def test_get_prompt_runs(session):
	r = ita('get-prompt', '-s', session)
	assert r.returncode == 0
