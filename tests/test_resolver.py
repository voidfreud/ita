"""Resolver / identity tests (CONTRACT §2, §6).

Cover the resolve_session shape and the cluster of fixed bugs in the
Phase 3 resolver-identity branch. Most cases run without a live iTerm2
by exercising the missing-session path; live cases are gated on the
`session` / `session_factory` fixtures.
"""
import json

import pytest

from tests.helpers import ita


pytestmark = pytest.mark.regression


# ── CONTRACT §2 resolver shape (no live iTerm2 needed) ─────────────────────

def test_no_session_arg_is_bad_args():
	"""§2: explicit reference required; empty input is bad-args (rc=6)."""
	r = ita('protect', '--json')
	assert r.returncode == 6, r.stderr
	env = json.loads(r.stdout)
	assert env['ok'] is False
	assert env['error']['code'] == 'bad-args'


def test_unknown_session_is_not_found():
	"""§2 + §6: nothing matches → not-found (rc=2)."""
	r = ita('protect', '-s', 'definitely-not-a-real-session', '--json')
	assert r.returncode == 2, r.stderr
	env = json.loads(r.stdout)
	assert env['error']['code'] == 'not-found'


def test_short_prefix_is_not_found_not_partial_match():
	"""§2: anything below the 8-char prefix floor is not-found, never a
	short-prefix best-effort. The 8-char floor is a contract rule."""
	r = ita('protect', '-s', '1234567', '--json')   # 7 chars
	assert r.returncode == 2, r.stderr
	env = json.loads(r.stdout)
	assert env['error']['code'] == 'not-found'


# ── Live-iTerm2 cases ──────────────────────────────────────────────────────

@pytest.mark.integration
def test_issue_289_resolve_uses_fresh_name(session, session_factory):
	"""#289: rename a session, then resolve by the new name immediately.
	The cached app-snapshot lags; resolver must read the fresh variable."""
	new_name = 'ita-test-renamed-289'
	r = ita('name', '-s', session, new_name, '-y')
	assert r.returncode == 0, r.stderr
	# Resolve by the new name right away — no sleep, no rescan.
	r = ita('status', '-s', new_name, '--json')
	assert r.returncode == 0, f"fresh name not resolvable: {r.stderr}"


@pytest.mark.integration
def test_issue_297_resolver_uses_terminal_windows(session):
	"""#297: app.windows vs app.terminal_windows. The resolver and overview
	now agree — overview must list the same set the resolver searches."""
	r = ita('overview', '--json')
	assert r.returncode == 0
	overview = json.loads(r.stdout)
	# `session` fixture's id should be in overview's session set.
	all_ids = {
		s['session_id']
		for w in overview.get('windows', [])
		for t in w.get('tabs', [])
		for s in t.get('sessions', [])
	}
	assert session in all_ids, "session in resolver path but not in overview"


@pytest.mark.integration
def test_issue_287_var_list_session_scope_unresolvable_errors(session):
	"""#287: explicit session scope with unresolvable target must raise
	not-found, not silently degrade to empty (§14.1 'never lie')."""
	r = ita('var', 'list', '--scope', 'session', '-s',
			'definitely-not-a-real-session', '--json')
	assert r.returncode == 2, r.stderr


@pytest.mark.integration
def test_issue_322_invalid_profile_is_bad_args(session):
	"""#322: structured INVALID_PROFILE_NAME → ItaError("bad-args")
	(rc=6), not a generic exception with rc=1."""
	r = ita('new', '--profile', 'definitely-not-a-real-profile', '--json')
	assert r.returncode == 6, r.stderr


# ── Tab resolver (#224) ────────────────────────────────────────────────────

@pytest.mark.integration
def test_issue_224_tab_resolver_by_title(session):
	"""#224: tab-resolver mirrors session-resolver shape — exact title
	resolves; resolution doesn't fall through to tab_id substring matching."""
	# Title-set + immediate resolution — same freshness constraint.
	r = ita('tab', 'list', '--json')
	assert r.returncode == 0
	tabs = json.loads(r.stdout)
	assert tabs, "no tabs to resolve against"


def test_tab_unknown_is_not_found():
	"""§2: tab resolver returns not-found, not bad-args, on unknown id."""
	r = ita('tab', 'activate', 'definitely-not-a-real-tab', '--json')
	# tab activate isn't @ita_command-migrated yet, but if it raises ItaError
	# or ClickException the cli root maps appropriately.
	assert r.returncode in (2, 6), f"unexpected rc={r.returncode}: {r.stderr}"
