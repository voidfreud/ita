"""Regression tests for #342 — CONTRACT §2 "Mandatory naming on creation"
and "Focus-fallback is forbidden, end of".

Two halves:

Fast-lane (no iTerm2 required) — any `ita <cmd>` without an explicit
target flag must exit rc=6 with a "no <kind> specified" / "requires"
message. Uses Click's CliRunner so there's no subprocess overhead and
no chance of touching the live iTerm2 state.

Integration (requires live iTerm2, autoskipped by conftest) — create
3 objects of a kind without --name and verify auto counter (s1..s3,
t1..t3, w1..w3, tmux1..tmux3).
"""
import pytest
from click.testing import CliRunner

from ita._core import cli, next_free_name
from helpers import ita, ita_ok, _extract_sid, TEST_SESSION_PREFIX  # noqa: F401


# ── Unit — next_free_name helper ─────────────────────────────────────────

@pytest.mark.regression
class TestNextFreeName:
	"""CONTRACT §2: "Scan existing names; pick the first free counter." """

	def test_empty_set_returns_1(self):
		assert next_free_name('s', set()) == 's1'
		assert next_free_name('t', set()) == 't1'
		assert next_free_name('w', set()) == 'w1'
		assert next_free_name('tmux', set()) == 'tmux1'

	def test_skips_taken_counters(self):
		assert next_free_name('s', {'s1', 's2'}) == 's3'
		assert next_free_name('s', {'s1', 's3'}) == 's2'

	def test_ignores_unrelated_names(self):
		# user-chosen names that don't match the `<prefix><int>` pattern
		# don't count as "taken" counters.
		assert next_free_name('s', {'alice', 'bob'}) == 's1'


# ── Fast-lane — focus-fallback removal ────────────────────────────────────

@pytest.mark.regression
class TestFocusFallbackRemoved:
	"""CONTRACT §2: "Every command takes an explicit reference; a missing
	reference is bad-args (rc=6), never a silent default." """

	def setup_method(self):
		self.runner = CliRunner()

	def _invoke(self, *args):
		return self.runner.invoke(cli, list(args), standalone_mode=False)

	def _assert_bad_args(self, result, needle: str):
		# standalone_mode=False surfaces the exception directly.
		from ita._envelope import ItaError
		assert result.exception is not None, f"expected ItaError, got rc={result.exit_code}"
		assert isinstance(result.exception, ItaError), (
			f"expected ItaError, got {type(result.exception).__name__}: "
			f"{result.exception}")
		assert result.exception.code == 'bad-args'
		assert needle in result.exception.reason

	def test_tab_new_requires_window(self):
		"""`ita tab new` (no --window) used to create in current_terminal_window."""
		result = self._invoke('tab', 'new')
		self._assert_bad_args(result, 'no window specified')

	def test_tab_close_requires_tab_id(self):
		"""`ita tab close` with no tab_id (no more --current)."""
		result = self._invoke('tab', 'close')
		self._assert_bad_args(result, 'no tab specified')

	def test_window_close_requires_window_id(self):
		"""`ita window close` without WINDOW_ID used to need `--force`.
		Now WINDOW_ID is required (Click will emit UsageError)."""
		result = self._invoke('window', 'close')
		# Click's missing-argument path is UsageError (rc=2). Either that, or
		# our ItaError if anything else upstream intercepts. Accept either,
		# but reject rc=0.
		assert result.exit_code != 0

	def test_window_title_requires_window(self):
		"""`ita window title` had a silent current_terminal_window fallback."""
		result = self._invoke('window', 'title')
		# Missing required --window option → Click UsageError (rc=2).
		assert result.exit_code != 0

	def test_var_get_window_scope_requires_window(self):
		"""--scope window fell back to current_terminal_window."""
		result = self._invoke('var', 'get', 'frame', '--scope', 'window')
		self._assert_bad_args(result, '--window')

	def test_var_get_tab_scope_requires_tab(self):
		result = self._invoke('var', 'get', 'title', '--scope', 'tab')
		self._assert_bad_args(result, '--tab')

	def test_broadcast_on_requires_target(self):
		"""broadcast on fell back to current_terminal_window when no -s."""
		result = self._invoke('broadcast', 'on')
		self._assert_bad_args(result, 'no target specified')


# ── Integration — mandatory naming on creation ────────────────────────────

@pytest.mark.integration
@pytest.mark.regression
def test_session_new_auto_names_with_lowest_free_counter():
	"""§2: no --name → auto s1/s2/s3 sequentially."""
	created_sids = []
	created_names = []
	try:
		for _ in range(3):
			r = ita('new')
			assert r.returncode == 0, r.stderr
			line = r.stdout.strip()
			name, sid = line.split('\t')
			created_names.append(name)
			created_sids.append(sid)
		# Names should follow s<N> pattern, each unique, and ascend.
		# We can't guarantee exactly s1,s2,s3 because prior sessions may exist,
		# but the counters MUST be strictly increasing and follow the `s` prefix.
		counters = [int(n[1:]) for n in created_names if n.startswith('s')]
		assert len(counters) == 3, f"not all auto-named s<N>: {created_names}"
		assert counters == sorted(counters), f"non-monotonic: {counters}"
		assert len(set(counters)) == 3, f"duplicate counters: {counters}"
	finally:
		for sid in created_sids:
			ita('close', '-s', sid, timeout=10)


@pytest.mark.integration
@pytest.mark.regression
def test_session_new_explicit_name_collision_errors(session):  # noqa: F811
	"""§2: --name AND name taken → bad-args (rc=6), never silent rename."""
	# `session` fixture already created `ita-test-<testname>`. Reuse that name.
	# Fetch the live name via a fresh `ita new` that would collide.
	# The fixture's session name starts with ita-test-; get it:
	r = ita('status', '--json', timeout=10)
	assert r.returncode == 0
	import json
	sessions = json.loads(r.stdout)
	live_names = [s['session_name'] for s in sessions if s.get('session_name', '').startswith(TEST_SESSION_PREFIX)]
	assert live_names, "test fixture session should be live"
	taken = live_names[0]
	r = ita('new', '--name', taken)
	assert r.returncode == 6, f"expected rc=6, got {r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
	assert 'already taken' in r.stderr.lower() or 'already' in r.stderr.lower()
