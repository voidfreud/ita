"""Stress tests: cross-session isolation, large output, rapid-fire, concurrent sessions."""
import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = [pytest.mark.integration, pytest.mark.stress]


def test_cross_session_var_isolation():
	"""Variables set in session A must not appear in session B."""
	s1 = ita('new').stdout.strip()
	s2 = ita('new').stdout.strip()
	try:
		ita_ok('var', 'set', 'isoltest', 's1_value', '-s', s1)
		r = ita('var', 'get', 'isoltest', '-s', s2)
		assert 's1_value' not in r.stdout, "Variable bled from s1 into s2"
	finally:
		ita('close', '-s', s1)
		ita('close', '-s', s2)


def test_large_output_500_lines(session):
	"""run should handle 500-line output without truncation artifacts."""
	r = ita('run', 'seq 1 500', '-n', '500', '-s', session)
	assert r.returncode == 0
	assert '500' in r.stdout  # last line must be present


def test_rapid_fire_inject(session):
	"""20 rapid inject calls must all succeed."""
	for i in range(20):
		r = ita('inject', f'ping{i}', '-s', session)
		assert r.returncode == 0, f"inject failed on iteration {i}"


def test_rapid_fire_pref_roundtrip():
	"""5 set/get pref roundtrips must be consistent."""
	key = 'DIM_BACKGROUND_WINDOWS'
	original = ita('pref', 'get', key).stdout.strip()
	try:
		for i in range(5):
			val = 'true' if i % 2 == 0 else 'false'
			ita_ok('pref', 'set', key, val)
			got = ita('pref', 'get', key).stdout.strip()
			assert got == val, f"Round {i}: expected {val}, got {got}"
	finally:
		ita('pref', 'set', key, original)


def test_interleaved_two_sessions():
	"""Commands on two sessions interleaved — no cross-contamination in capture."""
	s1 = ita('new').stdout.strip()
	s2 = ita('new').stdout.strip()
	try:
		for i in range(5):
			ita('send', f'echo s1_{i}', '-s', s1)
			ita('send', f'echo s2_{i}', '-s', s2)
		time.sleep(1.5)
		out1 = ita('capture', '-s', s1).stdout
		out2 = ita('capture', '-s', s2).stdout
		assert 's2_' not in out1, f"s2 output bled into s1 capture:\n{out1}"
		assert 's1_' not in out2, f"s1 output bled into s2 capture:\n{out2}"
	finally:
		ita('close', '-s', s1)
		ita('close', '-s', s2)


def test_run_timeout_respected(session):
	"""run --timeout should not block longer than timeout + small buffer."""
	start = time.time()
	ita('run', 'sleep 60', '--timeout', '3', '-s', session)
	elapsed = time.time() - start
	assert elapsed < 10, f"run took {elapsed:.1f}s — timeout not respected"
	ita('key', 'ctrl+c', '-s', session)


def test_ten_sessions_open_close():
	"""Open and close 10 sessions sequentially — no resource leaks."""
	for i in range(10):
		r = ita('new')
		assert r.returncode == 0, f"new failed on iteration {i}"
		sid = r.stdout.strip()
		r2 = ita('close', '-s', sid)
		assert r2.returncode == 0, f"close failed on iteration {i}"
