"""Regression: #222 — `focus --json` null path must include `session_name` key.

CONTRACT §4 Key stability: every documented --json key is present on every
code path; absent values are `null`, never omitted. Consumers iterate keys
and must not hit KeyError on the "no focused window" branch.
"""
import json

import pytest
from click.testing import CliRunner

from ita import _orientation
from ita._core import cli


FOCUS_KEYS = {'window_id', 'tab_id', 'session_id', 'session_name'}


@pytest.mark.regression
def test_issue_222_focus_json_null_path_includes_session_name(monkeypatch):
	"""Null path (no focused window): all four keys present, all None."""
	monkeypatch.setattr(_orientation, 'run_iterm', lambda _coro: None)
	r = CliRunner().invoke(cli, ['focus', '--json'])
	assert r.exit_code == 0, r.output
	data = json.loads(r.output)
	assert set(data.keys()) == FOCUS_KEYS
	assert data['session_name'] is None
	assert data['window_id'] is None
	assert data['tab_id'] is None
	assert data['session_id'] is None


@pytest.mark.regression
def test_issue_222_focus_json_happy_path_includes_session_name(monkeypatch):
	"""Happy path (focused session): same key set, populated values."""
	fake = {
		'window_id': 'W-UUID',
		'tab_id': 'T-UUID',
		'session_id': 'S-UUID',
		'session_name': 'main',
	}
	monkeypatch.setattr(_orientation, 'run_iterm', lambda _coro: fake)
	r = CliRunner().invoke(cli, ['focus', '--json'])
	assert r.exit_code == 0, r.output
	data = json.loads(r.output)
	assert set(data.keys()) == FOCUS_KEYS
	assert data['session_name'] == 'main'
