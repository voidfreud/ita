"""Session-lifecycle fixtures: session_factory, broadcast_domain, protected_session, shell."""
import concurrent.futures
import shutil
import time
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


def _shell_params():
	"""Build params list; skip fish if not installed."""
	shells = ["bash", "zsh"]
	if shutil.which("fish"):
		shells.append("fish")
	return shells


@pytest.fixture(params=_shell_params())
def shell(request):
	"""Parametrized fixture that yields a running session ID for each shell.

	Strategy: spawn a fresh ``ita new`` session then immediately send
	``exec <shell>`` as the first keypress via ``--run``.  Profile-command
	override would require a pre-existing named iTerm2 profile per shell,
	which is not guaranteed on every machine.  Sending ``exec <shell>\\n``
	is simpler, portable, and survives the default profile.

	Yields a dict: {"sid": str, "shell": str}  (e.g. "bash" / "zsh" / "fish").

	Fish is skipped automatically when ``shutil.which("fish")`` returns None.
	"""
	shell_name: str = request.param
	safe_name = (
		TEST_SESSION_PREFIX + "shell-" + shell_name + "-" + request.node.name[:15]
	).replace(" ", "_")

	r = ita("new", "--name", safe_name, "--run", f"exec {shell_name}\n")
	assert r.returncode == 0, f"shell fixture: ita new failed: {r.stderr}"
	sid = _extract_sid(r.stdout)
	assert sid, "shell fixture: empty session ID"

	# Give the shell a moment to start before tests begin sending commands.
	time.sleep(0.4)

	def _teardown():
		ita("close", "-s", sid, timeout=10)

	request.addfinalizer(_teardown)
	yield {"sid": sid, "shell": shell_name}


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
