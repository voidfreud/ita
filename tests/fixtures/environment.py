"""Environment fixtures: clean_iterm, hypothesis_profiles."""
import json
import os
import pytest
from hypothesis import settings, HealthCheck

from conftest import ita


# ---------------------------------------------------------------------------
# Hypothesis profiles — registered at import time, not as a pytest fixture
# ---------------------------------------------------------------------------

settings.register_profile(
	"fast",
	max_examples=10,
	deadline=500,
	suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
	"thorough",
	max_examples=200,
	deadline=5000,
	suppress_health_check=[HealthCheck.too_slow],
)

_profile = os.environ.get("ITA_HYPOTHESIS_PROFILE", "fast")
settings.load_profile(_profile)


# ---------------------------------------------------------------------------
# clean_iterm — session-scoped orphan detector
# ---------------------------------------------------------------------------

def _snapshot_iterm() -> dict[str, set[str]]:
	"""Return sets of window_id, tab_id, session_id currently in iTerm2."""
	r = ita('status', '--json', timeout=10)
	if r.returncode != 0:
		return {"windows": set(), "tabs": set(), "sessions": set()}
	try:
		items = json.loads(r.stdout)
	except (json.JSONDecodeError, ValueError):
		return {"windows": set(), "tabs": set(), "sessions": set()}

	windows: set[str] = set()
	tabs: set[str] = set()
	sessions: set[str] = set()
	for item in items:
		if "window_id" in item:
			windows.add(item["window_id"])
		if "tab_id" in item:
			tabs.add(item["tab_id"])
		if "session_id" in item:
			sessions.add(item["session_id"])
	return {"windows": windows, "tabs": tabs, "sessions": sessions}


@pytest.fixture(scope='session')
def clean_iterm(request):
	"""Snapshot window/tab/session IDs at session start.

	At teardown, diff the snapshot and report orphans.
	Warn-only by default; set ITA_STRICT_ORPHANS=1 to promote to pytest.fail.
	"""
	strict = os.environ.get("ITA_STRICT_ORPHANS", "0") == "1"
	before = _snapshot_iterm()
	yield
	after = _snapshot_iterm()

	orphan_windows = after["windows"] - before["windows"]
	orphan_tabs = after["tabs"] - before["tabs"]
	orphan_sessions = after["sessions"] - before["sessions"]

	if not (orphan_windows or orphan_tabs or orphan_sessions):
		return

	parts = []
	if orphan_sessions:
		parts.append(f"sessions={orphan_sessions}")
	if orphan_tabs:
		parts.append(f"tabs={orphan_tabs}")
	if orphan_windows:
		parts.append(f"windows={orphan_windows}")
	msg = f"clean_iterm: orphaned iTerm2 objects after test session: {', '.join(parts)}"

	if strict:
		pytest.fail(msg)
	else:
		import warnings
		warnings.warn(msg, stacklevel=1)
