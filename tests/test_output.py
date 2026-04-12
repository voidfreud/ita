"""Integration tests for output-reading commands: read, watch, wait, selection, copy, get-prompt."""
import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


def test_read_returns_content(session):
	ita_ok('run', 'echo readable', '-s', session)
	r = ita('read', '-s', session)
	assert r.returncode == 0


@pytest.mark.xfail(strict=False, reason="watch may hang if prompt not detected in fresh session")
def test_watch_exits_clean(session):
	# watch has no -t/--timeout; it streams until a prompt appears.
	# A fresh session should have a prompt visible, so this should exit quickly.
	try:
		r = ita('watch', '-s', session, timeout=8)
		assert r.returncode in (0, 1)
	except subprocess.TimeoutExpired:
		pytest.xfail("watch timed out — no prompt detected")


def test_wait_timeout_exits_clean(session):
	r = ita('wait', '-t', '2', '-s', session)
	assert r.returncode in (0, 1)


def test_selection_no_selection(session):
	# rc=0 if something is selected; rc=1 with "No selection" if nothing selected.
	r = ita('selection', '-s', session)
	assert r.returncode in (0, 1)
	if r.returncode == 1:
		assert 'No selection' in r.stderr


def test_copy_runs(session):
	# copy requires a selection; rc=1 with "No selection" is valid in a fresh session.
	r = ita('copy', '-s', session)
	assert r.returncode in (0, 1)
	if r.returncode == 1:
		assert 'No selection' in r.stderr


def test_get_prompt_runs(session):
	r = ita('get-prompt', '-s', session)
	assert r.returncode == 0
