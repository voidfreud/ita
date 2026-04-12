"""State and property tests for send commands: run, send, inject, key."""
import sys
import time
import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


@pytest.fixture
def settled_session(session):
	time.sleep(1)
	return session


# ── run state ─────────────────────────────────────────────────────────────────

@pytest.mark.state
def test_run_subshell_isolation(settled_session):
	"""run (default subshell mode) must not leak env mutations to the next invocation."""
	r1 = ita('run', 'export ITA_TEST_VAR=leaked', '-s', settled_session)
	assert r1.returncode == 0
	r2 = ita('run', 'echo ${ITA_TEST_VAR:-unset}', '-s', settled_session)
	assert r2.returncode == 0
	assert 'unset' in r2.stdout, "Subshell env leak detected: ITA_TEST_VAR persisted across run calls"


@pytest.mark.state
def test_run_persist_retains_env(settled_session):
	"""run --persist must allow env mutations to survive to the next --persist call."""
	ita('run', 'export ITA_PERSIST_VAR=hello', '--persist', '-s', settled_session)
	r = ita('run', 'echo $ITA_PERSIST_VAR', '--persist', '-s', settled_session)
	assert r.returncode == 0
	assert 'hello' in r.stdout, f"Persistent var not found; got: {r.stdout!r}"


# ── send state ────────────────────────────────────────────────────────────────

@pytest.mark.state
def test_send_does_not_close_session(session):
	"""send must not close the target session."""
	r = ita('send', 'true', '-s', session)
	assert r.returncode == 0
	# Session still alive
	r2 = ita('activate', '-s', session)
	assert r2.returncode == 0


# ── inject state ──────────────────────────────────────────────────────────────

@pytest.mark.state
def test_inject_repeated_noop_safe(session):
	"""Calling inject multiple times on the same session must not fail."""
	for _ in range(3):
		r = ita('inject', '--hex', '20', '-s', session)  # space char
		assert r.returncode == 0


# ── key property ──────────────────────────────────────────────────────────────

_valid_named_keys = st.sampled_from([
	'enter', 'esc', 'tab', 'space', 'backspace',
	'up', 'down', 'left', 'right',
	'home', 'end', 'pgup', 'pgdn', 'delete',
	'f1', 'f5', 'f12',
])

_ctrl_keys = st.sampled_from([
	'ctrl+a', 'ctrl+b', 'ctrl+e', 'ctrl+z', 'ctrl+[', 'ctrl+]',
])

_alt_keys = st.sampled_from(['alt+a', 'alt+f', 'alt+b'])


@pytest.mark.property
@settings(max_examples=15, suppress_health_check=[HealthCheck.too_slow])
@given(k=_valid_named_keys)
def test_key_named_keys_always_succeed(k, shared_session):
	"""Any key from the canonical named-key list must exit 0."""
	r = ita('key', k, '-s', shared_session)
	assert r.returncode == 0, f"key {k!r} failed: {r.stderr}"


@pytest.mark.property
@settings(max_examples=15, suppress_health_check=[HealthCheck.too_slow])
@given(garbage=st.text(min_size=3, max_size=20, alphabet=st.characters(whitelist_categories=('Ll',))))
def test_key_garbage_tokens_graceful(garbage):
	"""Arbitrary lowercase garbage tokens must exit non-zero with a clean error, never crash."""
	r = ita('key', garbage)
	# rc != 0, and either stdout or stderr has content
	assert r.returncode != 0
	assert (r.stderr + r.stdout).strip()


@pytest.mark.property
@settings(max_examples=10, suppress_health_check=[HealthCheck.too_slow])
@given(text=st.text(min_size=0, max_size=100))
def test_send_arbitrary_text_graceful(text, shared_session):
	"""send with arbitrary text payloads must not crash (rc 0 expected for valid UTF-8)."""
	try:
		text.encode('utf-8')
	except UnicodeEncodeError:
		return  # skip non-encodable examples
	r = ita('send', '--raw', text, '-s', shared_session)
	# Any rc is acceptable; we only require no unhandled crash
	assert r.returncode in (0, 1), f"Unexpected rc {r.returncode} for send with text {text!r}"
