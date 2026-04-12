"""Invariant: every mutator refuses a protected session without --force.

Widened beyond the COMMANDS `writes=True` set to include commands that
modify session state but are not yet tagged `writes=True` in the inventory:
  name, resize, theme, profile apply, profile set, tmux start, broadcast ops.

Marks: @pytest.mark.contract + @pytest.mark.integration

NOTE: theme, profile apply, profile set, tmux start, and broadcast ops do NOT
currently call check_protected() — they are expected to FAIL this test.
These are marked xfail(strict=False) as candidate bugs until fixed.
"""
import pytest

from conftest import ita
from test_contracts import COMMANDS, _idfn

# ── Mutators already in the inventory ──────────────────────────────────────
_INVENTORY_MUTATORS = [c for c in COMMANDS if c["writes"]]

# ── Widened mutators not yet tagged writes=True in inventory ───────────────
# Each entry: (label, args_fn) where args_fn(sid) -> list[str] full invocation
_EXTRA_MUTATORS = [
	("name",          lambda sid: ["name", "-s", sid, "renamed-test"]),
	("resize",        lambda sid: ["resize", "-s", sid, "--rows", "24", "--cols", "80"]),
	("theme",         lambda sid: ["theme", "Dark Background"]),
	("profile_apply", lambda sid: ["profile", "apply", "-s", sid, "Default"]),
	("profile_set",   lambda sid: ["profile", "set", "-s", sid, "Normal Font", "Monaco 12"]),
	("tmux_start",    lambda sid: ["tmux", "start"]),
	("broadcast_on",  lambda sid: ["broadcast", "on"]),
	("broadcast_send",lambda sid: ["broadcast", "send", "x"]),
]

# Commands suspected NOT to honour protection yet (candidate bugs).
_UNPROTECTED_MUTATORS = {
	"theme", "profile_apply", "profile_set", "tmux_start",
	"broadcast_on", "broadcast_send",
}


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize(
	"cmd",
	_INVENTORY_MUTATORS,
	ids=[_idfn(c) for c in _INVENTORY_MUTATORS],
)
def test_inventory_mutator_refuses_protected(cmd, protected_session):
	"""Write-class inventory commands refuse protected session without --force."""
	sid = protected_session["sid"]
	parts = cmd["path"].split() + ["-s", sid] + cmd["args"]
	r = ita(*parts, timeout=30)
	assert r.returncode != 0, (
		f"{cmd['path']} accepted write on protected session (rc=0)"
	)
	combined = r.stdout + r.stderr
	assert combined.strip(), (
		f"{cmd['path']} refused (rc!=0) but produced no output"
	)


@pytest.mark.contract
@pytest.mark.integration
@pytest.mark.parametrize(
	"label,args_fn",
	[(label, fn) for label, fn in _EXTRA_MUTATORS],
	ids=[label for label, _ in _EXTRA_MUTATORS],
)
def test_extra_mutator_refuses_protected(label, args_fn, protected_session):
	"""Widened mutators (name/resize/theme/profile/tmux/broadcast) also refuse protected sessions.

	Commands in _UNPROTECTED_MUTATORS are xfail(strict=False): currently suspected
	to NOT call check_protected — failures here are candidate bugs.
	"""
	sid = protected_session["sid"]
	parts = args_fn(sid)
	if label in _UNPROTECTED_MUTATORS:
		pytest.xfail(
			f"{label}: suspected not to call check_protected() — candidate bug"
		)
	r = ita(*parts, timeout=30)
	assert r.returncode != 0, (
		f"{label}: accepted write on protected session (rc=0)"
	)
