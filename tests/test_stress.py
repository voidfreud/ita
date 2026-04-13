"""Stress tests: cross-session isolation, large output, rapid-fire, concurrent sessions."""
import concurrent.futures
import json
import os
import resource
import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = [pytest.mark.integration, pytest.mark.stress]


def test_cross_session_var_isolation():
	"""Variables set in session A must not appear in session B."""
	s1 = ita('new').stdout.strip().split('\t')[-1]
	s2 = ita('new').stdout.strip().split('\t')[-1]
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
	s1 = ita('new').stdout.strip().split('\t')[-1]
	s2 = ita('new').stdout.strip().split('\t')[-1]
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
		sid = r.stdout.strip().split('\t')[-1]
		r2 = ita('close', '-s', sid)
		assert r2.returncode == 0, f"close failed on iteration {i}"


# ---------------------------------------------------------------------------
# New stress scenarios (issue #238)
# ---------------------------------------------------------------------------

def test_parallel_nx_m_commands(session_factory):
	"""10 sessions × 5 commands each in parallel — all succeed, no tracebacks, all alive."""
	sids = session_factory(10)
	commands = [
		lambda sid=sid, cmd=cmd: ita(*cmd, '-s', sid)
		for sid in sids
		for cmd in [
			('run', 'echo hi'),
			('send', 'echo ping'),
			('read',),
			('run', 'true'),
			('send', 'echo done'),
		]
	]
	with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
		results = list(pool.map(lambda f: f(), commands))

	for i, r in enumerate(results):
		assert r.returncode == 0, f"command {i} failed (rc={r.returncode}): {r.stderr}"
		assert 'Traceback' not in r.stderr, f"command {i} produced traceback:\n{r.stderr}"

	# All sessions still alive
	status_r = ita('status', '--json')
	assert status_r.returncode == 0
	alive_ids = {s['session_id'] for s in json.loads(status_r.stdout)}
	for sid in sids:
		assert sid in alive_ids, f"session {sid} is gone after parallel load"


def test_fd_leak_100_runs(session):
	"""100 short 'ita run' invocations must not leak file descriptors in the test process."""
	def _open_fd_count():
		# /dev/fd is a reliable macOS/Linux dirfd listing
		try:
			return len(os.listdir('/dev/fd'))
		except OSError:
			soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
			return sum(1 for fd in range(soft) if _fd_open(fd))

	def _fd_open(fd):
		try:
			os.fstat(fd)
			return True
		except OSError:
			return False

	baseline = _open_fd_count()
	for _ in range(100):
		ita('run', 'echo x', '-s', session)
	final = _open_fd_count()
	assert final <= baseline + 10, (
		f"FD leak detected: baseline={baseline}, final={final}, delta={final - baseline}"
	)


@pytest.mark.xfail(
	reason=(
		"ita is a subprocess-only CLI entry point (not an importable module); "
		"in-process asyncio task leak measurement requires a refactored library API. "
		"Candidate improvement: extract ita's async core into a proper package."
	),
	strict=False,
)
def test_asyncio_task_leak():
	"""Creating/closing 50 sessions in-process must not leak asyncio tasks.

	Currently xfail: ita.py is a script, not an importable library.
	Tracking: restructure ita into a library to enable in-process testing.
	"""
	# If ita were importable as a library this would work.  For now, force the
	# xfail branch so the test is visible on the radar without blocking CI.
	raise NotImplementedError(
		"ita must be extracted to an importable library before this test can run"
	)


def test_memory_ceiling_200_cycles(session_factory):
	"""200 new/close pairs — RSS growth must stay under 50 MB."""
	try:
		import psutil
		def _rss():
			return psutil.Process().memory_info().rss
	except ImportError:
		# Fallback: ru_maxrss (peak, not current — still useful as a ceiling check)
		def _rss():
			usage = resource.getrusage(resource.RUSAGE_SELF)
			# On macOS ru_maxrss is in bytes; on Linux it's KB
			scale = 1 if sys.platform == 'darwin' else 1024
			return usage.ru_maxrss * scale

	samples = []
	for i in range(200):
		sids = session_factory(1)
		ita('close', '-s', sids[0])
		if i % 50 == 49:
			samples.append(_rss())

	growth = samples[-1] - samples[0]
	assert growth < 50 * 1024 * 1024, (
		f"Memory growth exceeded ceiling: {growth / 1024 / 1024:.1f} MB over 200 cycles "
		f"(samples: {[f'{s/1024/1024:.1f}MB' for s in samples]})"
	)


def test_window_count_stability():
	"""100 rapid create/destroy cycles must not alter the window count."""
	def _window_count():
		r = ita('window', 'list', '--json')
		assert r.returncode == 0, f"window list failed: {r.stderr}"
		return len(json.loads(r.stdout))

	before = _window_count()
	for _ in range(100):
		r = ita('new')
		assert r.returncode == 0
		sid = r.stdout.strip().split('\t')[-1]
		ita('close', '-s', sid)
	after = _window_count()

	assert after == before, (
		f"Window count changed after 100 create/destroy cycles: before={before}, after={after}"
	)
