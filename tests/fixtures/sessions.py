"""Session-lifecycle fixtures: session_factory, broadcast_domain, protected_session."""
import concurrent.futures
import pytest

from conftest import ita, ita_ok, _extract_sid, TEST_SESSION_PREFIX


@pytest.fixture
def session_factory(request):
	"""Return a callable create(n=1) that spins N sessions in parallel.

	Each call to create() registers teardown for all sessions it created.
	Safe to call multiple times within one test (e.g. create(2) then create(1)).
	"""
	all_sids: list[str] = []

	def _teardown():
		for sid in all_sids:
			ita('close', '-s', sid, timeout=10)

	request.addfinalizer(_teardown)

	def create(n: int = 1) -> list[str]:
		safe_base = (TEST_SESSION_PREFIX + request.node.name[:20]).replace(' ', '_')

		def _spin(i: int) -> str:
			name = f"{safe_base}-{i}"
			r = ita('new', '--name', name)
			assert r.returncode == 0, f"session_factory: failed to create session {i}: {r.stderr}"
			sid = _extract_sid(r.stdout)
			assert sid, f"session_factory: empty session ID for session {i}"
			return sid

		with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, n)) as pool:
			sids = list(pool.map(_spin, range(n)))

		all_sids.extend(sids)
		return sids

	return create


@pytest.fixture
def broadcast_domain(session_factory):
	"""Setup a broadcast-on group (default 2 sessions); teardown calls broadcast off.

	Yields a list of session IDs that are part of the broadcast domain.
	"""
	sids = session_factory(2)
	ita_ok('broadcast', 'on', *sids)
	yield sids
	# Teardown: turn off broadcast (best-effort)
	ita('broadcast', 'off', *sids, timeout=10)


@pytest.fixture
def protected_session(request, session_factory):
	"""Session with protect applied.

	Parametrize with [True, False] via indirect=True.
	  True  -> test uses --force when writing
	  False -> test writes without --force (expected to be refused)

	Yields a dict: {"sid": str, "force": bool}
	"""
	force: bool = getattr(request, 'param', False)
	sids = session_factory(1)
	sid = sids[0]
	ita_ok('protect', '-s', sid)
	yield {"sid": sid, "force": force}
	# Unprotect before session_factory teardown closes it
	ita('unprotect', '-s', sid, timeout=10)
