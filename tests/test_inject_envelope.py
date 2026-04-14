"""Envelope shape for `ita inject` and `ita key` (CONTRACT §4, task #13).

These run in the fast lane — the error paths hit `resolve_session` against
a ghost sid, so no live iTerm2 is needed. The `_parse_key` bad-args path
can even short-circuit before any resolution.
"""
import json

import pytest

from tests.helpers import ita


REQUIRED_KEYS = {"schema", "ok", "op", "target", "elapsed_ms",
				 "warnings", "error", "data"}


def _assert_envelope_shape(env: dict, *, op: str) -> None:
	"""Check the fields §4 mandates. We don't pull jsonschema here — the
	required-key set and the rc↔ok invariant are enough to catch regressions."""
	missing = REQUIRED_KEYS - env.keys()
	assert not missing, f"envelope missing required keys: {missing}"
	assert env["schema"] == "ita/1"
	assert env["op"] == op
	assert isinstance(env["elapsed_ms"], int) and env["elapsed_ms"] >= 0
	assert isinstance(env["warnings"], list)
	# mutator → state_* fields present (may be null but the keys exist).
	assert "state_before" in env
	assert "state_after" in env


# ── inject error paths (no iTerm2 needed) ─────────────────────────────────────

@pytest.mark.contract
def test_inject_envelope_not_found():
	"""§4: --json inject against a ghost session → ok=false, error.code=not-found, rc=2."""
	r = ita('inject', '-s', 'ghost-sid-xyz', 'hello', '--json')
	assert r.returncode == 2, f"expected rc=2 (not-found), got {r.returncode}: {r.stderr}"
	env = json.loads(r.stdout)
	_assert_envelope_shape(env, op='inject')
	assert env["ok"] is False
	assert env["error"]["code"] == "not-found"


@pytest.mark.contract
def test_inject_envelope_bad_hex():
	"""§4: --json inject --hex with invalid pairs → ok=false, error.code=bad-args, rc=6.

	This fires before session resolution (encoder runs first), so no live
	iTerm2 is ever touched. Also covers the rc=6 legacy → ItaError surface."""
	r = ita('inject', '--hex', 'zz', '-s', 'ghost-sid-xyz', '--json')
	assert r.returncode == 6, f"expected rc=6 (bad-args), got {r.returncode}: {r.stderr}"
	env = json.loads(r.stdout)
	_assert_envelope_shape(env, op='inject')
	assert env["ok"] is False
	assert env["error"]["code"] == "bad-args"
	assert "hex" in env["error"]["reason"].lower()


# ── key error paths ──────────────────────────────────────────────────────────

@pytest.mark.contract
def test_key_envelope_unknown_key():
	"""§4: --json key with an unrecognized token → bad-args, rc=6.

	`_parse_key` raises ItaError before iTerm2 is contacted, so this stays
	in the fast lane."""
	r = ita('key', 'not-a-real-key', '-s', 'ghost-sid-xyz', '--json')
	assert r.returncode == 6, f"expected rc=6 (bad-args), got {r.returncode}: {r.stderr}"
	env = json.loads(r.stdout)
	_assert_envelope_shape(env, op='key')
	assert env["ok"] is False
	assert env["error"]["code"] == "bad-args"


@pytest.mark.contract
def test_key_envelope_not_found():
	"""§4: --json key against a ghost session → not-found, rc=2."""
	r = ita('key', 'enter', '-s', 'ghost-sid-xyz', '--json')
	assert r.returncode == 2, f"expected rc=2 (not-found), got {r.returncode}: {r.stderr}"
	env = json.loads(r.stdout)
	_assert_envelope_shape(env, op='key')
	assert env["ok"] is False
	assert env["error"]["code"] == "not-found"


# ── happy-path envelope shape (needs live iTerm2 session) ────────────────────

@pytest.mark.contract
def test_inject_envelope_happy_path(session):
	"""§4: --json inject on a real session → ok=true, op=inject, target.session set,
	state_before/after = 'ready', data.bytes_written reflects the payload."""
	r = ita('inject', 'hi', '-s', session, '--json')
	assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr}"
	env = json.loads(r.stdout)
	_assert_envelope_shape(env, op='inject')
	assert env["ok"] is True
	assert env["error"] is None
	assert env["target"] is not None and env["target"].get("session")
	assert env["state_before"] == "ready"
	assert env["state_after"] == "ready"
	assert env["data"]["bytes_written"] == 2
	assert env["data"]["hex"] is False


@pytest.mark.contract
def test_key_envelope_happy_path(session):
	"""§4: --json key on a real session → ok=true, op=key, data.keys echoed back."""
	r = ita('key', 'space', '-s', session, '--json')
	assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr}"
	env = json.loads(r.stdout)
	_assert_envelope_shape(env, op='key')
	assert env["ok"] is True
	assert env["error"] is None
	assert env["data"]["keys"] == ["space"]
	assert env["data"]["bytes_written"] >= 1
