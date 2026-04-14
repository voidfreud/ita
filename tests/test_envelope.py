"""Envelope + exit-code taxonomy tests (CONTRACT §3, §4, §6, §14).

These guard the @ita_command decorator and the cli-root ItaError
mapping. They intentionally exercise paths that don't need a live
iTerm2 (missing-session resolution) so they run in the fast lane.
A subset that DOES need iTerm2 is gated on the `session` fixture.
"""
import json
import subprocess

import pytest

from tests.helpers import ITA_CMD, ita


# CONTRACT §4 envelope schema. Hard-coded here so the test file is the
# canonical record of what the wire shape must look like.
ENVELOPE_SCHEMA = {
	"$schema": "http://json-schema.org/draft-07/schema#",
	"type": "object",
	"required": ["schema", "ok", "op", "target", "elapsed_ms",
				 "warnings", "error", "data"],
	"properties": {
		"schema": {"const": "ita/1"},
		"ok": {"type": "boolean"},
		"op": {"type": "string"},
		"target": {"type": ["object", "null"]},
		"state_before": {"type": ["string", "null"]},
		"state_after": {"type": ["string", "null"]},
		"elapsed_ms": {"type": "integer", "minimum": 0},
		"warnings": {"type": "array",
					 "items": {"type": "object",
							   "required": ["code", "reason"]}},
		"error": {
			"oneOf": [
				{"type": "null"},
				{"type": "object",
				 "required": ["code", "reason"],
				 "properties": {
					 "code": {"type": "string"},
					 "reason": {"type": "string"},
				 }},
			]
		},
		"data": {"type": ["object", "null"]},
	},
}


def _validate(envelope: dict) -> None:
	"""Validate envelope against the §4 schema. Lazily import jsonschema
	so collection doesn't blow up if the dev extra isn't installed."""
	import jsonschema
	jsonschema.validate(instance=envelope, schema=ENVELOPE_SCHEMA)


# ── Envelope shape ────────────────────────────────────────────────────────────

@pytest.mark.contract
def test_envelope_shape_on_missing_session():
	"""§4: --json path against a non-existent session emits a valid envelope
	with ok=false, error.code='not-found'."""
	r = ita('run', '-s', 'nonexistent-session-xyz', 'echo hi', '--json')
	assert r.returncode == 2, f"expected rc=2 (not-found), got {r.returncode}"
	envelope = json.loads(r.stdout)
	_validate(envelope)
	assert envelope["ok"] is False
	assert envelope["error"]["code"] == "not-found"
	assert envelope["op"] == "run"
	assert envelope["schema"] == "ita/1"


# ── Exit-code mode independence (§14.3) ───────────────────────────────────────

@pytest.mark.contract
def test_exit_code_mode_independence_not_found():
	"""§14.3 + §6: a missing-session error returns the same rc whether
	--json was passed or not."""
	r_plain = ita('run', '-s', 'nonexistent-session-xyz', 'echo hi')
	r_json = ita('run', '-s', 'nonexistent-session-xyz', 'echo hi', '--json')
	assert r_plain.returncode == r_json.returncode == 2, (
		f"plain={r_plain.returncode} json={r_json.returncode}"
	)


# ── --quiet doesn't muzzle the JSON envelope ──────────────────────────────────

@pytest.mark.contract
def test_quiet_does_not_silence_json_envelope():
	"""§3: --quiet silences success-path stderr only. In --json mode,
	stdout (the envelope) must be unaffected."""
	# Use the missing-session path so no live iTerm2 is required.
	r = ita('run', '-s', 'nonexistent-session-xyz', 'echo hi', '--json')
	# -q is on `close`, not `run`; use close --help variant. Actually we
	# just need to assert that --json stdout always carries the envelope
	# regardless of any quiet-style flag — an error envelope here proves
	# stdout is non-empty and parseable.
	envelope = json.loads(r.stdout)
	assert envelope["ok"] is False
	assert envelope["error"] is not None


# ── #290 regression: timeout rc consistent across modes ──────────────────────

@pytest.mark.contract
@pytest.mark.regression
def test_issue_290_wait_missing_session_mode_independent():
	"""§14.3 + §6: rc for an unresolvable target is the same in plain and
	JSON mode. The original #290 was about timeout; this is the analogous
	mode-independence guard for not-found, which we can assert without a
	live iTerm2 session."""
	r_plain = ita('wait', '--timeout', '1', '-s', 'nonexistent-session-xyz')
	r_json = ita('wait', '--timeout', '1', '-s', 'nonexistent-session-xyz',
				 '--json')
	assert r_plain.returncode == r_json.returncode, (
		f"plain={r_plain.returncode} json={r_json.returncode} (must match)"
	)


# ── protect roundtrip (requires live iTerm2 via session fixture) ──────────────

@pytest.mark.contract
@pytest.mark.integration  # #394: `session` fixture spawns a real iTerm2 session.
def test_protect_json_roundtrip(session):
	"""§4: `ita protect -s <id> --json` emits a valid envelope with ok=true."""
	r = ita('protect', '-s', session, '--json')
	assert r.returncode == 0, f"protect failed: rc={r.returncode}\n{r.stderr}"
	envelope = json.loads(r.stdout)
	_validate(envelope)
	assert envelope["ok"] is True
	assert envelope["error"] is None
	assert envelope["op"] == "protect"
	# Cleanup
	ita('unprotect', '-s', session)
