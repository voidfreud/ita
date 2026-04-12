"""Tests for point-in-time query commands: wait, selection, copy, get-prompt (_query.py)."""
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# wait — effect
# ---------------------------------------------------------------------------

def test_wait_pattern_match_fires(session):
	"""wait --pattern with a literal marker actually detects it."""
	ita_ok('run', 'echo WAIT_MARKER_ABC', '-s', session)
	r = ita('wait', '--pattern', 'WAIT_MARKER_ABC', '--json', '-t', '10', '-s', session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert data['matched'] is True
	assert 'WAIT_MARKER_ABC' in (data['line'] or '')


def test_wait_fixed_string_match(session):
	"""--fixed-string treats pattern as literal substring (no regex meta-chars)."""
	ita_ok('run', 'echo LITERAL.DOT+PLUS', '-s', session)
	r = ita('wait', '--pattern', 'LITERAL.DOT+PLUS', '--fixed-string', '--json', '-t', '10', '-s', session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert data['matched'] is True


def test_wait_timeout_json_matched_false(session):
	"""When pattern not found within timeout, --json returns matched:false."""
	r = ita('wait', '--pattern', 'NEVER_APPEARS_XYZZY', '--json', '-t', '2', '-s', session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert data['matched'] is False
	assert data['line'] is None
	assert isinstance(data['elapsed_ms'], int)
	assert data['elapsed_ms'] >= 2000


@pytest.mark.error
def test_wait_invalid_regex_fails(session):
	"""Invalid --pattern regex exits non-zero with message."""
	r = ita('wait', '--pattern', '[bad(', '-t', '2', '-s', session)
	assert r.returncode != 0
	assert 'Invalid regex' in r.stderr or 'regex' in r.stderr.lower()


@pytest.mark.error
def test_wait_timeout_without_json_without_pattern_exits_zero(session):
	"""wait with no pattern and no --json exits 0 (waits for prompt, may find it)."""
	r = ita('wait', '-t', '3', '-s', session)
	# rc=0 whether or not a prompt was found — no pattern means no failure mode
	assert r.returncode == 0


@pytest.mark.error
def test_wait_pattern_timeout_without_json_raises(session):
	"""wait --pattern timeout (no --json) raises ClickException → non-zero rc."""
	r = ita('wait', '--pattern', 'NEVER_XYZZY_TIMEOUT', '-t', '2', '-s', session)
	assert r.returncode != 0
	assert 'Timeout' in r.stderr


@pytest.mark.contract
def test_wait_json_schema(session):
	"""--json schema: {matched: bool, line: str|null, elapsed_ms: int}."""
	import jsonschema
	schema = {
		'type': 'object',
		'required': ['matched', 'line', 'elapsed_ms'],
		'properties': {
			'matched': {'type': 'boolean'},
			'line': {'type': ['string', 'null']},
			'elapsed_ms': {'type': 'integer', 'minimum': 0},
		},
	}
	r = ita('wait', '--json', '-t', '2', '-s', session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	jsonschema.validate(data, schema)


# ---------------------------------------------------------------------------
# selection — happy / edge / contract
# ---------------------------------------------------------------------------

def test_selection_no_selection_rc_zero(session):
	"""No selection → rc=0, empty stdout (silent return, not an error)."""
	r = ita('selection', '-s', session)
	assert r.returncode == 0
	assert r.stdout.strip() == ''


@pytest.mark.contract
def test_selection_json_no_selection_schema(session):
	"""selection --json with no selection returns {text: null}."""
	import jsonschema
	schema = {
		'type': 'object',
		'required': ['text'],
		'properties': {
			'text': {'type': ['string', 'null']},
		},
	}
	r = ita('selection', '--json', '-s', session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	jsonschema.validate(data, schema)
	assert data['text'] is None  # nothing selected


@pytest.mark.contract
def test_selection_no_ansi_leakage(session):
	r = ita('selection', '-s', session)
	assert r.returncode == 0
	assert '\x1b[' not in r.stdout
	assert '\x00' not in r.stdout


# ---------------------------------------------------------------------------
# copy — effect / contract
# ---------------------------------------------------------------------------

def test_copy_no_selection_exits_zero(session):
	"""No selection → rc=0, no clipboard write, no crash."""
	r = ita('copy', '-s', session)
	assert r.returncode == 0
	# No output expected when nothing to copy (source silently returns)
	assert r.stdout.strip() == ''


@pytest.mark.error
def test_copy_nonexistent_session():
	r = ita('copy', '-s', 'w0000000-0000-0000-0000-000000000000')
	assert r.returncode != 0


# ---------------------------------------------------------------------------
# get-prompt — happy / contract
# ---------------------------------------------------------------------------

def test_get_prompt_rc_zero(session):
	r = ita('get-prompt', '-s', session)
	assert r.returncode == 0


@pytest.mark.contract
def test_get_prompt_json_schema_success(session):
	"""After a command, get-prompt --json returns schema-valid payload."""
	import jsonschema
	ita_ok('run', 'echo schema_check', '-s', session)
	r = ita('get-prompt', '--json', '-s', session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	# Source may return {} when shell integration absent — allow both shapes
	if data:
		schema = {
			'type': 'object',
			'required': ['cwd', 'command', 'exit_code'],
			'properties': {
				'cwd': {'type': ['string', 'null']},
				'command': {'type': ['string', 'null']},
				'exit_code': {'type': ['integer', 'null']},
			},
		}
		jsonschema.validate(data, schema)


@pytest.mark.contract
def test_get_prompt_json_empty_when_no_integration(session):
	"""get-prompt --json returns {} (not null, not missing key) when no prompt info."""
	r = ita('get-prompt', '--json', '-s', session)
	assert r.returncode == 0
	data = json.loads(r.stdout)
	assert isinstance(data, dict)  # {} or full dict — never null/list


@pytest.mark.contract
def test_get_prompt_text_fallback_message(session):
	"""get-prompt plain output is human-readable (no raw repr/exceptions)."""
	r = ita('get-prompt', '-s', session)
	assert r.returncode == 0
	# Should either show 'cwd:' or the 'no prompt info' message
	assert 'cwd:' in r.stdout or 'No prompt info' in r.stdout or r.stdout.strip() == ''


@pytest.mark.error
def test_get_prompt_nonexistent_session():
	r = ita('get-prompt', '-s', 'w0000000-0000-0000-0000-000000000000')
	assert r.returncode != 0
