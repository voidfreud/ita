"""Session-lifecycle fixtures: session_factory, broadcast_domain, protected_session, shell."""
import concurrent.futures
import shutil
import time
import pytest

from helpers import (
	ita, ita_ok, _extract_sid, TEST_SESSION_PREFIX,
	_all_window_ids, _close_window,
)


@pytest.fixture
def session_factory(request):
	"""Return a callable create(n=1) that spins N sessions in parallel.

	Each call to create() registers teardown for all sessions it created.
	Safe to call multiple times within one test (e.g. create(2) then create(1)).

	#348: also tracks any windows opened by `ita new` and closes them in
	teardown (otherwise iTerm2 leaves an orphan default-shell window
	behind once our session is closed).
	"""
	all_sids: list[str] = []
	all_new_windows: set[str] = set()

	def _teardown():
		for sid in all_sids:
			ita('close', '-s', sid, timeout=10)
		for wid in all_new_windows:
			_close_window(wid)

	request.addfinalizer(_teardown)

	def create(n: int = 1) -> list[str]:
		# #380: full node name for legibility in iTerm2's session list.
		safe_base = (TEST_SESSION_PREFIX + request.node.name).replace(' ', '_')
		# TESTING.md §4.1 L2: register each successful sid into all_sids
		# IMMEDIATELY (not after the batch). If create() raises mid-batch,
		# the addfinalizer still cleans up everything we managed to spin up.
		# #348: also snapshot windows so we can clean any new ones.
		windows_before = _all_window_ids()

		def _spin(i: int) -> str:
			name = f"{safe_base}-{i}"
			r = ita('new', '--name', name)
			assert r.returncode == 0, f"session_factory: failed to create session {i}: {r.stderr}"
			sid = _extract_sid(r.stdout)
			assert sid, f"session_factory: empty session ID for session {i}"
			all_sids.append(sid)  # register before returning, in case caller raises
			return sid

		with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, n)) as pool:
			futures = [pool.submit(_spin, i) for i in range(n)]
			sids: list[str] = []
			for f in concurrent.futures.as_completed(futures):
				sids.append(f.result())  # may raise; partials already in all_sids

		# Capture any window that didn't exist before this batch.
		all_new_windows.update(_all_window_ids() - windows_before)
		return sids

	return create


@pytest.fixture
def broadcast_domain(session_factory):
	"""Setup a broadcast-on group (default 2 sessions); teardown calls broadcast off.

	Yields a list of session IDs that are part of the broadcast domain.
	"""
	sids = session_factory(2)
	ita_ok('broadcast', 'on', *[arg for sid in sids for arg in ('-s', sid)])
	yield sids
	# Teardown: turn off broadcast (best-effort)
	ita('broadcast', 'off', timeout=10)


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
	# #380: full node name for legibility in iTerm2's session list.
	safe_name = (
		TEST_SESSION_PREFIX + "shell-" + shell_name + "-" + request.node.name
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
