# src/_state.py
"""Session state derivation (CONTRACT §7).

Single entry point: `derive_state(app, session) -> str`. Returns one of the
eight stable enum strings from CONTRACT §7:

	creating | ready | busy | waiting_prompt
	| no_shell_integration | timed_out | locked | dead

This module is the *canonical* state derivation: callers MUST NOT roll their
own. `timed_out` is never produced here — it is set explicitly by callers
whose own deadline elapses (e.g. the envelope's `state_after` on a timeout
error). `derive_state` only reports the *current* state of a session.

Issues addressed: #267 (state machine), #257 (readiness), #292 (invariants).
"""
import asyncio
import os

import iterm2

from ._core import _load_writelocks, _pid_alive
from ._readiness import _probe


# Max time to let `_probe` run before declaring `creating`. 250 ms matches
# the contract-cluster default so a fresh session that hasn't yet booted
# shell integration is reported as `creating` rather than as a false `ready`.
_PROBE_TIMEOUT_S = 0.25


async def derive_state(
	app: 'iterm2.App',
	session: 'iterm2.Session',
) -> str:
	"""Derive the CONTRACT §7 state for `session`.

	Priority (first match wins):
	  1. `dead`  — session_id no longer resident in any window/tab.
	  2. `locked` — a live *other* PID holds the write-lock.
	  3. `creating` — `_probe` doesn't settle within _PROBE_TIMEOUT_S.
	  4. `no_shell_integration` — shell alive but integration absent.
	  5. `ready` — shell alive + writable + prompt visible.
	  6. `busy` — shell alive, jobName populated, no prompt visible.
	  7. `waiting_prompt` — shell alive, writable, no prompt signal.
	  8. `creating` — fallback (shouldn't reach; defensive).

	Never returns `timed_out` — that's a caller-set value.
	"""
	sid = session.session_id

	# 1. dead — session gone from the app tree
	alive = False
	for window in app.terminal_windows:
		for tab in window.tabs:
			for s in tab.sessions:
				if s.session_id == sid:
					alive = True
					break
			if alive:
				break
		if alive:
			break
	if not alive:
		return 'dead'

	# 2. locked — another live process holds the write-lock
	entry = _load_writelocks().get(sid)
	if entry:
		try:
			lock_pid = int(entry.get('pid', 0))
		except (TypeError, ValueError):
			lock_pid = 0
		if lock_pid and lock_pid != os.getpid() and _pid_alive(lock_pid):
			return 'locked'

	# 3. probe — bounded by _PROBE_TIMEOUT_S; overrun → creating
	try:
		flags = await asyncio.wait_for(_probe(session), timeout=_PROBE_TIMEOUT_S)
	except (asyncio.TimeoutError, Exception):
		return 'creating'

	shell_alive = flags.get('shell_alive', False)
	prompt_visible = flags.get('prompt_visible', False)
	writable = flags.get('writable', False)
	shell_integration = flags.get('shell_integration_active', False)
	job_populated = flags.get('jobName_populated', False)

	# 4. no_shell_integration — shell up, integration absent
	if shell_alive and not shell_integration:
		return 'no_shell_integration'

	# 5. ready — the happy path
	if shell_alive and writable and prompt_visible:
		return 'ready'

	# 6. busy — a foreground job is running (jobName populated, no prompt)
	if shell_alive and job_populated and not prompt_visible:
		return 'busy'

	# 7. waiting_prompt — alive + writable, but no prompt signal
	if shell_alive and writable and not prompt_visible:
		return 'waiting_prompt'

	# 8. defensive fallback
	return 'creating'


# The canonical enum, exported for callers that want to validate strings.
VALID_STATES = (
	'creating',
	'ready',
	'busy',
	'waiting_prompt',
	'no_shell_integration',
	'timed_out',
	'locked',
	'dead',
)
