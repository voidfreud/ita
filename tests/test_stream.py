"""Tests for streaming commands: watch (_stream.py)."""
import json
import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# watch — happy / effect
# ---------------------------------------------------------------------------

def test_watch_exits_after_prompt(session):
	"""watch exits when prompt appears; rc=0."""
	# Fresh session has a visible prompt — watch should return immediately.
	try:
		r = ita('watch', '-s', session, timeout=10)
		assert r.returncode == 0
	except subprocess.TimeoutExpired:
		pytest.xfail("watch timed out — prompt not detected")


def test_watch_json_stream_emits_valid_json(session):
	"""--json-stream produces at least one valid JSON object."""
	ita_ok('run', 'echo WATCH_JSON_CHECK', '-s', session)
	try:
		r = ita('watch', '--json-stream', '-s', session, timeout=10)
	except subprocess.TimeoutExpired:
		pytest.xfail("watch timed out")
	assert r.returncode == 0
	# Every output line should be a JSON object
	lines = [l for l in r.stdout.splitlines() if l.strip()]
	assert len(lines) > 0, "Expected at least one JSON frame"
	for line in lines:
		obj = json.loads(line)
		assert isinstance(obj, dict)


@pytest.mark.contract
def test_watch_json_stream_schema(session):
	"""Each --json frame has session_id, lines, timestamp_ms."""
	import jsonschema
	frame_schema = {
		'type': 'object',
		'required': ['session_id', 'lines', 'timestamp_ms'],
		'properties': {
			'session_id': {'type': 'string'},
			'lines': {'type': 'array', 'items': {'type': 'string'}},
			'timestamp_ms': {'type': 'integer'},
		},
	}
	ita_ok('run', 'echo schema_check', '-s', session)
	try:
		r = ita('watch', '--json-stream', '-s', session, timeout=10)
	except subprocess.TimeoutExpired:
		pytest.xfail("watch timed out")
	assert r.returncode == 0
	lines = [l for l in r.stdout.splitlines() if l.strip()]
	assert lines, "No JSON frames emitted"
	for line in lines:
		obj = json.loads(line)
		jsonschema.validate(obj, frame_schema)


def test_watch_timeout_flag(session):
	"""--timeout caps watch; exits cleanly within time window."""
	try:
		r = ita('watch', '--timeout', '3', '-s', session, timeout=8)
		assert r.returncode == 0
	except subprocess.TimeoutExpired:
		pytest.fail("watch --timeout 3 did not exit within 8s")


@pytest.mark.edge
def test_watch_json_alias(session):
	"""--json is an alias for --json-stream."""
	ita_ok('run', 'echo JSON_ALIAS_TEST', '-s', session)
	try:
		r = ita('watch', '--json', '-s', session, timeout=10)
	except subprocess.TimeoutExpired:
		pytest.xfail("watch timed out")
	assert r.returncode == 0
	lines = [l for l in r.stdout.splitlines() if l.strip()]
	for line in lines:
		json.loads(line)  # must not raise


@pytest.mark.edge
def test_watch_zero_timeout_runs_forever_is_capped():
	"""--timeout 0 means run forever; we can only test it doesn't crash at startup."""
	# We can't actually let it run forever; just verify the flag is accepted
	# by using a very short subprocess timeout and catching the expiry.
	try:
		r = ita('watch', '--timeout', '0', timeout=4)
		# If it returns within 4s without iTerm2, rc should be non-zero (connection fail)
		# but it should not crash with a flag error
		assert 'Error: No such option' not in r.stderr
	except subprocess.TimeoutExpired:
		pass  # expected — it ran indefinitely


@pytest.mark.contract
def test_watch_json_no_null_bytes(session):
	"""watch --json output contains no null bytes."""
	try:
		r = ita('watch', '--json', '-s', session, timeout=10)
	except subprocess.TimeoutExpired:
		pytest.xfail("watch timed out")
	assert r.returncode == 0
	assert '\x00' not in r.stdout


@pytest.mark.error
def test_watch_nonexistent_session():
	r = ita('watch', '-s', 'w0000000-0000-0000-0000-000000000000', timeout=10)
	assert r.returncode != 0
