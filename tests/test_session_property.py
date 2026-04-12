"""Property-based (Hypothesis) tests for session commands."""
import sys
import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita

pytestmark = [pytest.mark.integration, pytest.mark.property]


# Safe text strategy: printable ASCII only, no trailing/leading whitespace issues
_safe_name = st.text(
	alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-_'),
	min_size=1,
	max_size=30,
)

_garbage_id = st.text(
	alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-_'),
	min_size=1,
	max_size=64,
)


@pytest.mark.property
@settings(max_examples=10, suppress_health_check=[HealthCheck.too_slow])
@given(cols=st.integers(min_value=1, max_value=500), rows=st.integers(min_value=1, max_value=200))
def test_resize_valid_dims_never_crash(cols, rows, shared_session):
	"""resize with any valid col/row pair must not crash (rc may be non-zero for unsupported sizes)."""
	r = ita('resize', '--cols', str(cols), '--rows', str(rows), '-y', '-s', shared_session)
	# rc must be 0 or 1 — never unhandled exception (rc=2 means a CLI usage error we didn't intend)
	assert r.returncode in (0, 1), f"Unexpected rc {r.returncode} for resize {cols}x{rows}: {r.stderr}"


@pytest.mark.property
@settings(max_examples=10, suppress_health_check=[HealthCheck.too_slow])
@given(n=st.integers(min_value=1, max_value=1000))
def test_capture_lines_cap_property(n, shared_session):
	"""capture -n N must always return at most N lines."""
	r = ita('capture', '-n', str(n), '-s', shared_session)
	assert r.returncode == 0
	lines = [l for l in r.stdout.splitlines() if l.strip()]
	assert len(lines) <= n, f"capture -n {n} returned {len(lines)} lines"


@pytest.mark.property
@settings(max_examples=15, suppress_health_check=[HealthCheck.too_slow])
@given(garbage=_garbage_id)
def test_close_garbage_id_graceful_error(garbage):
	"""close with a garbage session ID must exit non-zero with a message, never crash."""
	r = ita('close', '-s', garbage)
	assert r.returncode != 0, f"Expected non-zero rc for garbage ID {garbage!r}"
	assert r.stderr.strip() or r.stdout.strip(), "Expected at least some error output"


@pytest.mark.property
@settings(max_examples=15, suppress_health_check=[HealthCheck.too_slow])
@given(garbage=_garbage_id)
def test_name_garbage_id_graceful_error(garbage):
	"""name with a garbage session ID must exit non-zero, never crash."""
	r = ita('name', 'irrelevant', '-s', garbage, '-y')
	assert r.returncode != 0
