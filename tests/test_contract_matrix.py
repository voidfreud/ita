"""CONTRACT §14 parametrized invariant matrix.

One test function per invariant, parametrized over every leaf command
in ``ita commands --json``. Fast-lane whenever the invariant can be
verified without touching live iTerm2; ``@pytest.mark.integration``
otherwise.

Companion modules:
  tests/_contract_categories.py  — command → category map (data)
  tests/_contract_helpers.py     — shared assertion helpers + invoke()

Invocation strategy (#292): the bulk matrix runs in-process via Click's
``CliRunner`` (see ``_contract_helpers.invoke``). Three explicit smoke
tests at the bottom of this module shell out to the real `python -m ita`
entrypoint so argv parsing, console-script dispatch, and __main__
wiring stay covered.

Rule 6 (readiness) is deferred to the integration lane per task #8.
"""
from __future__ import annotations

import json

import pytest

from _contract_categories import (
	CATEGORIES,
	PATH_TAKERS,
	TARGET_TAKERS,
	commands_with,
)
from _contract_helpers import (
	GHOST_SID,
	assert_identity_required,
	assert_no_lie,
	assert_rc_matches_envelope,
	assert_stderr_no_traceback,
	assert_stdout_clean,
	invoke,
	invoke_json,
	invoke_subprocess,
	split_path,
)


pytestmark = pytest.mark.contract


# ── Shared-state reset (CliRunner hygiene) ─────────────────────────────────
# Every cell runs in the same interpreter now. Reset known ita module-level
# globals so earlier cells can't leak state into later ones. Cheap; see
# _contract_helpers.py for the rationale.

@pytest.fixture(autouse=True)
def _reset_ita_module_state():
	from ita import _lock
	_lock._held_cookies.clear()
	_lock._FORCE_DEPRECATION_WARNED = False
	yield
	_lock._held_cookies.clear()
	_lock._FORCE_DEPRECATION_WARNED = False


# ── Surface coverage guard ──────────────────────────────────────────────────
# If a new ita command ships without landing in CATEGORIES, this test fails
# and the matrix refuses to drift.

def test_categorization_covers_surface():
	"""Every leaf command from `ita commands --json` must be categorized."""
	r = invoke("commands", "--json", timeout=10)
	assert r.returncode == 0, f"`ita commands --json` failed: {r.stderr}"
	tree = json.loads(r.stdout)

	leaves: set[str] = set()

	def walk(node: dict, prefix: str = "") -> None:
		for c in node.get("commands", []):
			name = f"{prefix} {c['name']}".strip()
			if "commands" in c:
				walk(c, name)
			else:
				leaves.add(name)

	walk(tree)
	missing = leaves - set(CATEGORIES)
	extra = set(CATEGORIES) - leaves
	assert not missing, f"uncategorized commands: {sorted(missing)}"
	assert not extra, f"stale categorizations: {sorted(extra)}"


# ── Parametrize helpers ─────────────────────────────────────────────────────

ALL_CMDS = sorted(CATEGORIES.keys())
MUTATORS = commands_with("mutator")
READONLY = commands_with("readonly")
META_CMDS = commands_with("meta")


def _id(cmd: str) -> str:
	return cmd.replace(" ", "-")


# ── Rule 1: never lie ──────────────────────────────────────────────────────
# Fast-lane surface: invoke `<cmd> --help`. `--help` always exits 0 with no
# envelope and no iTerm2 traffic; it's the smallest universal probe that
# exercises argument parsing and the command-dispatch layer.

@pytest.mark.parametrize("cmd", ALL_CMDS, ids=_id)
def test_rule1_help_never_lies(cmd: str):
	"""§14.1: `<cmd> --help` never returns an envelope claiming ok=true with
	a non-null error, and never prints a traceback."""
	r = invoke(*split_path(cmd), "--help", timeout=10)
	# --help should always rc=0 and never leak tracebacks.
	assert r.returncode == 0, (
		f"§14.1: {cmd} --help failed rc={r.returncode}\n{r.stderr}"
	)
	assert "Traceback (most recent call last)" not in r.stdout
	assert "Traceback (most recent call last)" not in r.stderr


# Ghost-session probe: for every target-taking command, invoking against a
# non-existent SID in --json mode must produce an envelope with ok=false
# and a concrete error — never a silent success.

GHOST_PROBES = sorted(c for c in TARGET_TAKERS if c in CATEGORIES)


@pytest.mark.parametrize("cmd", GHOST_PROBES, ids=_id)
def test_rule1_ghost_target_never_lies(cmd: str):
	"""§14.1: --json against a ghost SID never returns ok=true."""
	# Some commands (watch/stream/on *) block waiting for events; skip them
	# in the fast lane since a ghost target should short-circuit but we don't
	# want the test to wedge if that short-circuit regresses.
	if "streaming" in CATEGORIES[cmd]:
		pytest.skip(f"{cmd} is streaming — covered under integration lane")
	# `run` needs a command arg; others don't. Be minimal.
	extra: list[str] = []
	if cmd == "run":
		extra = ["echo", "x"]
	elif cmd == "send" or cmd == "inject":
		extra = ["x"]
	elif cmd == "key":
		extra = ["ctrl-c"]
	elif cmd == "name":
		extra = ["test-name"]
	elif cmd == "annotate":
		extra = ["note"]
	elif cmd == "tab title" or cmd == "window title":
		extra = ["t"]
	elif cmd == "var get":
		extra = ["foo"]
	elif cmd == "var set":
		extra = ["foo", "bar"]
	elif cmd == "tab profile" or cmd == "profile apply":
		extra = ["Default"]
	elif cmd == "profile set":
		extra = ["key", "value"]
	elif cmd == "profile get":
		extra = ["Default", "key"]
	elif cmd == "profile show":
		extra = ["Default"]
	elif cmd == "resize":
		extra = ["--rows", "24", "--cols", "80"]
	r, env = invoke_json(*split_path(cmd), "-s", GHOST_SID, *extra, timeout=10)
	if env is None:
		pytest.skip(f"{cmd} emitted no --json envelope (likely not supported)")
	assert_no_lie(env)
	assert env.get("ok") is False, f"§14.1: {cmd} claimed ok=true against ghost SID"


# ── Rule 2: stdout hygiene & UTF-8 fidelity ────────────────────────────────

@pytest.mark.parametrize("cmd", ALL_CMDS, ids=_id)
def test_rule2_help_stdout_clean(cmd: str):
	"""§14.2: `<cmd> --help` stdout carries no NUL, no ANSI, no traceback."""
	r = invoke(*split_path(cmd), "--help", timeout=10)
	assert_stdout_clean(r.stdout)
	assert_stderr_no_traceback(r.stderr)


@pytest.mark.parametrize("cmd", GHOST_PROBES, ids=_id)
def test_rule2_ghost_target_stdout_clean(cmd: str):
	"""§14.2: error-path stdout is clean too — no ANSI, no NUL, no traceback.
	--json envelopes are allowed on stdout; plain-mode stderr carries the
	user message."""
	if "streaming" in CATEGORIES[cmd]:
		pytest.skip(f"{cmd} is streaming — covered under integration lane")
	r = invoke(*split_path(cmd), "-s", GHOST_SID, "--json", timeout=10)
	assert_stdout_clean(r.stdout)
	assert_stderr_no_traceback(r.stderr)


# UTF-8 fidelity for text-transmit commands (inject/send). Astral-plane
# codepoints must survive end-to-end; lone surrogates must fail with
# rc=6 (bad-args). This is partial coverage from the fast lane — we can
# only verify the validation half without a live session. The end-to-end
# half is handled by tests/test_inject_utf8_229.py.

UTF8_TRANSMIT_CMDS = ["inject", "send"]


@pytest.mark.parametrize("cmd", UTF8_TRANSMIT_CMDS, ids=_id)
def test_rule2_utf8_lone_surrogate_rejected(cmd: str):
	"""§14.2: un-encodable input (lone surrogate) must fail loudly with
	rc=6, not be silently mangled. Exercises the argv validation path —
	no live session needed since the surrogate rejection happens before
	target resolution."""
	# Lone high surrogate. In-process we pass the str straight through;
	# if Click or the command rejects it that's equivalent to loud failure.
	bad = "\ud83d"  # lone high surrogate
	try:
		r = invoke(*split_path(cmd), "-s", GHOST_SID, bad, timeout=10)
	except (UnicodeEncodeError, ValueError):
		# Runtime refused to even build the call — equivalent to loud failure.
		return
	assert r.returncode != 0, f"§14.2: {cmd} accepted lone surrogate silently"


# ── Rule 3: exit code matches envelope ─────────────────────────────────────

RULE3_CMDS = sorted(set(MUTATORS) | set(READONLY))


@pytest.mark.parametrize("cmd", RULE3_CMDS, ids=_id)
def test_rule3_rc_matches_envelope_on_ghost_target(cmd: str):
	"""§14.3: for commands that accept --json and a target, error-path rc
	and envelope.ok agree."""
	if cmd not in TARGET_TAKERS:
		pytest.skip(f"{cmd} takes no target — rule 3 matrix cell exercised elsewhere")
	if "streaming" in CATEGORIES[cmd]:
		pytest.skip(f"{cmd} is streaming — covered under integration lane")
	# Build minimal argv (same table as rule 1 — keep duplication local,
	# it's only a handful of commands that need positionals).
	positional_map = {
		"run": ["echo", "x"], "send": ["x"], "inject": ["x"], "key": ["ctrl-c"],
		"name": ["n"], "annotate": ["n"], "tab title": ["t"], "window title": ["t"],
		"var get": ["foo"], "var set": ["foo", "bar"],
		"tab profile": ["Default"], "profile apply": ["Default"],
		"profile set": ["k", "v"], "profile get": ["Default", "k"],
		"profile show": ["Default"],
		"resize": ["--rows", "24", "--cols", "80"],
	}
	extra = positional_map.get(cmd, [])
	r, env = invoke_json(*split_path(cmd), "-s", GHOST_SID, *extra, timeout=10)
	if env is None:
		pytest.skip(f"{cmd} emits no envelope on --json (no-op for rule 3)")
	assert_rc_matches_envelope(r.returncode, env)


# ── Rule 4: protection / lock / path-trust ─────────────────────────────────
# These need a live session to meaningfully exercise. Mark integration.

@pytest.mark.integration
@pytest.mark.parametrize("cmd", MUTATORS, ids=_id)
def test_rule4_mutator_honors_protection(cmd: str, session):  # noqa: ARG001
	"""§14.4: every mutator refuses to act on a protected session unless
	the opt-out flag is passed. Deferred to the integration lane because
	it requires a live target; matrix cell exists so gaps are visible."""
	pytest.skip(
		f"rule 4 protection matrix for {cmd} — covered by existing integration "
		f"tests (test_invariant_mutators_honor_protection.py); this cell is a "
		f"matrix placeholder. TODO(#292): wire full parametrized coverage."
	)


# Path-trust sub-rule (§14.4, #325). Fast-lane-safe because validation
# runs before iTerm2 contact: a path outside CWD must fail rc=6 even
# against a ghost session.

@pytest.mark.parametrize("cmd", sorted(PATH_TAKERS), ids=_id)
def test_rule4_path_trust_rejects_escape(cmd: str):
	"""§14.4 / #325: caller-supplied paths must resolve under CWD. An
	absolute escape path fails with bad-args (rc=6), not silent truncation."""
	# Limit to the one path-taking command we can probe cheaply without a
	# live session: `run --stdin /etc/hosts`. Others write files (save,
	# capture, restore) and need a session target to exercise the path
	# validator; mark them as integration-lane matrix cells.
	if cmd != "run":
		pytest.skip(
			f"{cmd} path-trust needs a live session — matrix placeholder. "
			f"TODO(#292): integration-lane coverage."
		)
	r = invoke("run", "-s", GHOST_SID, "--stdin", "/etc/hosts", "cat",
			   "--json", timeout=10)
	# Either the path validator (rc=6) or the resolver (rc=2) must loudly
	# refuse. The forbidden outcome is rc=0 / silent success.
	assert r.returncode != 0, "§14.4: path escape silently accepted"


# ── Rule 5: identity is explicit ───────────────────────────────────────────

RULE5_CMDS = sorted(TARGET_TAKERS & set(CATEGORIES))


@pytest.mark.parametrize("cmd", RULE5_CMDS, ids=_id)
def test_rule5_identity_explicit(cmd: str):
	"""§14.5: no command succeeds against an implicit target. Invoking a
	target-taker without -s must either fail rc != 0 or return an envelope
	with target=null / ok=false."""
	if "streaming" in CATEGORIES[cmd]:
		pytest.skip(f"{cmd} is streaming — covered under integration lane")
	# Several target-takers also require positional args; omitting -s alone
	# should still fail. We don't supply positionals here — click will bail
	# with rc=2 (usage) which is itself an explicit-failure outcome and
	# satisfies rule 5. The forbidden outcome is ok=true with a resolved
	# target.
	assert_identity_required(cmd)


# ── Rule 6: readiness — DEFERRED to integration lane (task #8) ────────────

@pytest.mark.skip(reason="rule 6 handled in integration lane per task #8")
@pytest.mark.parametrize("cmd", sorted({"new", "tab new", "window new", "split"}))
def test_rule6_readiness_deferred(cmd: str):
	"""§14.6 placeholder — TODO(#292, task #8): create-then-return commands
	must not return before session is ready (or --no-wait given)."""
	pass


# ── OS entry-point smoke tests (real subprocess) ───────────────────────────
# The bulk matrix above runs in-process via CliRunner for speed. These
# three smokes exercise the actual `python -m ita` entrypoint so argv
# parsing, console-script wiring, __main__.main() and the auto-protect
# side-effect path stay covered. Cost: ~3 × ~500 ms ≈ 1.5 s total.

def test_subprocess_smoke_help():
	"""Real subprocess: `ita --help` returns rc=0 with clean stdout."""
	r = invoke_subprocess("--help", timeout=15)
	assert r.returncode == 0, f"ita --help failed: {r.stderr}"
	assert "Usage:" in r.stdout
	assert "Traceback" not in r.stdout
	assert "Traceback" not in r.stderr


def test_subprocess_smoke_version():
	"""Real subprocess: `ita --version` returns rc=0 and prints a version."""
	r = invoke_subprocess("--version", timeout=15)
	assert r.returncode == 0, f"ita --version failed: {r.stderr}"
	assert "version" in r.stdout.lower()
	assert "Traceback" not in r.stderr


def test_subprocess_smoke_commands_json():
	"""Real subprocess: `ita commands --json` emits a parseable tree.
	Guards the console-script / __main__ path that CliRunner bypasses."""
	r = invoke_subprocess("commands", "--json", timeout=15)
	assert r.returncode == 0, f"ita commands --json failed: {r.stderr}"
	tree = json.loads(r.stdout)
	assert "commands" in tree, "missing top-level 'commands' key"
	assert "Traceback" not in r.stderr
