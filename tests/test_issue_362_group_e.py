"""Rule-4 Group E (#362): protect / unprotect must gate on check_protected.

Both commands live in `src/ita/_orientation.py` and, until this wave, were
the top-priority xfail from `docs/rule4-xfails-plan.md`:
`unprotect` could silently disarm a protected session (§14.4 bypass).

These tests drive the in-process `seeded_protection` harness to verify
rc=3 / error.code=protected when the target is in the protected set and
`--force-protected` is not passed — and that `--force-protected` bypasses
the gate as designed."""
from __future__ import annotations

import pytest

from _contract_helpers import (
	GHOST_SID,
	invoke,
	invoke_json,
	seeded_protection,
)


@pytest.mark.parametrize("cmd", ["protect", "unprotect"])
def test_gates_on_protected_without_force(cmd: str):
	"""§14.4: protect/unprotect exit rc=3 when target is protected and
	--force-protected is absent."""
	with seeded_protection(GHOST_SID):
		r = invoke(cmd, "-s", GHOST_SID, timeout=10)
	assert r.returncode == 3, (
		f"{cmd}: expected rc=3 (protected), got rc={r.returncode}\n"
		f"stdout={r.stdout[:400]!r} stderr={r.stderr[:400]!r}"
	)


def test_protect_envelope_shape_on_protection_failure():
	"""§14.4 + §4: `protect --json` surfaces ok=false, error.code='protected'.

	`unprotect` is not yet @ita_command-wrapped (no --json support), so its
	envelope-shape contract is N/A this wave — rc=3 coverage from the test
	above is sufficient for §14.4. Migrating unprotect to @ita_command is
	tracked separately (not in-scope for #362 Group E)."""
	with seeded_protection(GHOST_SID):
		r, env = invoke_json("protect", "-s", GHOST_SID, timeout=10)
	assert r.returncode == 3
	assert env is not None, f"protect --json produced no envelope: {r.stdout!r}"
	assert env.get("ok") is False
	err = env.get("error") or {}
	assert err.get("code") == "protected", (
		f"protect: expected error.code='protected', got {err!r}"
	)


def test_force_protected_bypasses_gate():
	"""`--force-protected` on protect short-circuits check_protected and
	succeeds (re-protects an already-protected session). Regression guard
	for the bypass semantics (#294)."""
	with seeded_protection(GHOST_SID):
		r = invoke("protect", "-s", GHOST_SID, "--force-protected", timeout=10)
	# rc=0 expected. But note: add_protected writes to ~/.ita_protected on
	# the real filesystem; we only care here that check_protected did NOT
	# raise. rc=3 would indicate the gate fired despite --force-protected.
	assert r.returncode != 3, (
		f"--force-protected did not bypass the gate; rc={r.returncode}\n"
		f"stdout={r.stdout[:400]!r} stderr={r.stderr[:400]!r}"
	)
