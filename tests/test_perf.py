"""Performance benchmarks: per-command p50 / p99 latency gates.

Run with:  pytest -m "perf" --benchmark-only
Budget violations cause test failures (rc != 0 in the perf CI lane).

Notes:
- pedantic(rounds=20, iterations=1) → 20 data points per command.
- p99 over 20 samples is effectively the max; acceptable for a gate.
  See docs/TESTING.md §7 Budget table for the spec.
"""
import json
import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = [pytest.mark.integration, pytest.mark.perf]

ITA = Path(__file__).parent.parent / 'src' / 'ita.py'


def _run(*args):
	"""Minimal subprocess call for benchmarking — no assertion, returns CompletedProcess."""
	return subprocess.run(
		['uv', 'run', str(ITA)] + list(args),
		capture_output=True, text=True, timeout=30,
	)


def _p99(stats):
	"""Compute p99 from benchmark stats data list."""
	data = sorted(stats.data)
	if not data:
		return float('inf')
	idx = max(0, int(len(data) * 0.99) - 1)
	return data[idx]


# ---------------------------------------------------------------------------
# Fixtures: sessions created once per module for read-heavy benchmarks
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def perf_session():
	"""Single session shared across all perf tests in this module."""
	r = ita('new', '--name', 'ita-test-perf-shared')
	assert r.returncode == 0, f"perf_session: failed to create: {r.stderr}"
	parts = r.stdout.strip().split('\t')
	sid = parts[-1] if len(parts) > 1 else parts[0]
	yield sid
	ita('close', '-s', sid, timeout=10)


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

def test_perf_status_json(benchmark, perf_session):
	"""ita status --json  p50 < 100 ms, p99 < 300 ms"""
	result = benchmark(_run, 'status', '--json')
	p50 = benchmark.stats.median
	p99 = _p99(benchmark.stats)
	assert p50 < 0.100, f"status --json p50 too slow: {p50*1000:.1f}ms (budget 100ms)"
	assert p99 < 0.300, f"status --json p99 too slow: {p99*1000:.1f}ms (budget 300ms)"


def test_perf_version(benchmark):
	"""ita version  p50 < 50 ms  (pure local read — no iTerm2 API call expected)."""
	result = benchmark(_run, 'version')
	p50 = benchmark.stats.median
	# If this exceeds 50ms it almost certainly means ita is making an API call
	# on 'version', which is a candidate bug.
	assert p50 < 0.050, (
		f"version p50 too slow: {p50*1000:.1f}ms (budget 50ms) — "
		"if this is > 50ms, ita version may be making an iTerm2 API call (candidate bug)"
	)


def test_perf_run_echo(benchmark, perf_session):
	"""ita run 'echo hi' -s <session>  p50 < 500 ms, p99 < 1500 ms"""
	def _call():
		return _run('run', 'echo hi', '-s', perf_session)

	benchmark.pedantic(_call, rounds=20, iterations=1, warmup_rounds=3)
	p50 = benchmark.stats.median
	p99 = _p99(benchmark.stats)
	assert p50 < 0.500, f"run echo p50 too slow: {p50*1000:.1f}ms (budget 500ms)"
	assert p99 < 1.500, f"run echo p99 too slow: {p99*1000:.1f}ms (budget 1500ms)"


def test_perf_var_get(benchmark, perf_session):
	"""ita var get foo -s <session>  p50 < 200 ms, p99 < 600 ms"""
	# Pre-set the variable so var get has something to return
	ita_ok('var', 'set', 'perf_foo', 'bar', '-s', perf_session)

	def _call():
		return _run('var', 'get', 'perf_foo', '-s', perf_session)

	benchmark.pedantic(_call, rounds=20, iterations=1, warmup_rounds=3)
	p50 = benchmark.stats.median
	p99 = _p99(benchmark.stats)
	assert p50 < 0.200, f"var get p50 too slow: {p50*1000:.1f}ms (budget 200ms)"
	assert p99 < 0.600, f"var get p99 too slow: {p99*1000:.1f}ms (budget 600ms)"


def test_perf_send(benchmark, perf_session):
	"""ita send 'x' -s <session>  p50 < 200 ms"""
	def _call():
		return _run('send', 'x', '-s', perf_session)

	benchmark.pedantic(_call, rounds=20, iterations=1, warmup_rounds=3)
	p50 = benchmark.stats.median
	assert p50 < 0.200, f"send p50 too slow: {p50*1000:.1f}ms (budget 200ms)"


def test_perf_new_close(benchmark):
	"""ita new (create+register)  p50 < 1 s, p99 < 2.5 s.

	Uses pedantic so teardown (close) happens inside each round.
	"""
	created = []

	def _create():
		r = _run('new', '--name', 'ita-test-perf-bench')
		if r.returncode == 0:
			parts = r.stdout.strip().split('\t')
			sid = parts[-1] if len(parts) > 1 else parts[0]
			created.append(sid)
		return r

	benchmark.pedantic(_create, rounds=20, iterations=1, warmup_rounds=3)

	# Teardown: close any sessions that were created
	for sid in created:
		ita('close', '-s', sid, timeout=10)

	p50 = benchmark.stats.median
	p99 = _p99(benchmark.stats)
	assert p50 < 1.000, f"new p50 too slow: {p50*1000:.1f}ms (budget 1000ms)"
	assert p99 < 2.500, f"new p99 too slow: {p99*1000:.1f}ms (budget 2500ms)"


def test_perf_tab_list_json(benchmark, perf_session):
	"""ita tab list --json  p50 < 200 ms"""
	result = benchmark(_run, 'tab', 'list', '--json')
	p50 = benchmark.stats.median
	assert p50 < 0.200, f"tab list --json p50 too slow: {p50*1000:.1f}ms (budget 200ms)"
