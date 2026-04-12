"""Adversarial malformed-input & unicode tests — step 3 of issue #136.

Scenarios covered:
  5. Huge paste: `ita send` a 1 MB text blob.
  6. Malformed UUID: Hypothesis-driven fuzz over `-s` argument.
  9. Unicode session names: emoji, RTL, ZWJ sequences — name/lookup/filter survive.
"""
import sys
import time
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = [pytest.mark.adversarial, pytest.mark.integration]


# ── 5. Huge paste ─────────────────────────────────────────────────────────────

@pytest.mark.adversarial
@pytest.mark.integration
def test_huge_paste_1mb(session):
	"""ita send a ~1 MB text blob.

	Acceptance criteria:
	  - rc=0 (chunking handled internally, terminal not locked).
	  - Session still responds to a subsequent `ita run` command.
	  - No Python traceback in stderr.

	Potential bug: if ita does not chunk the paste and the OS pipe buffer
	overflows, the process may deadlock.  Tag known_broken if this hangs.
	"""
	# ~1 MB of printable ASCII across many short lines.
	line = 'x' * 78 + '\n'
	blob = line * (1_048_576 // len(line) + 1)  # at least 1 MB
	assert len(blob) >= 1_000_000, f"blob too small: {len(blob)}"

	r = ita('send', '--raw', blob, '-s', session, timeout=60)

	assert 'Traceback (most recent call last)' not in r.stderr, (
		f"Uncaught exception on 1 MB send:\n{r.stderr}"
	)
	assert r.returncode == 0, (
		f"ita send 1 MB failed: rc={r.returncode}\nstderr:{r.stderr!r}"
	)

	# Give the terminal time to digest, then assert it's still alive.
	time.sleep(2)
	r2 = ita('run', 'echo post_huge_paste_alive', '-s', session, timeout=20)
	assert r2.returncode == 0, (
		f"Session unresponsive after 1 MB paste: rc={r2.returncode}\n"
		f"stdout:{r2.stdout!r}\nstderr:{r2.stderr!r}"
	)
	assert 'post_huge_paste_alive' in r2.stdout, (
		f"Session alive but expected marker missing: {r2.stdout!r}"
	)


# ── 6. Malformed UUID — Hypothesis fuzz ──────────────────────────────────────

# Strategies that produce UUID-shaped but hostile values:
#   - path traversal sequences
#   - null bytes
#   - very long strings
#   - control characters
#   - typical UUIDs with mutations
_malformed_uuid_strategy = st.one_of(
	# Path traversal
	st.just('../../etc/passwd'),
	st.just('../../../etc/shadow'),
	st.just('/etc/passwd'),
	st.just('\\..\\..\\windows\\system32'),
	# Null and control bytes
	st.just('\x00\x01\x02'),
	st.just('\x00'),
	st.just('\r\n'),
	# Long strings (10 000+ chars)
	st.text(
		alphabet=st.characters(blacklist_categories=('Cs',)),
		min_size=10_000,
		max_size=10_001,
	),
	# Random printable text (catches injection attempts via shell)
	st.text(
		alphabet=st.characters(
			whitelist_categories=('Lu', 'Ll', 'Nd', 'Po', 'Pd', 'Sm'),
		),
		min_size=1,
		max_size=256,
	),
	# UUID-shaped but wrong
	st.just('00000000-0000-0000-0000-000000000000'),
	st.just('FAKE_SESSION_ID_DOES_NOT_EXIST'),
)


@pytest.mark.adversarial
@pytest.mark.property
@given(session_arg=_malformed_uuid_strategy)
@settings(max_examples=60, deadline=10_000)
def test_malformed_session_id_fuzz(session_arg):
	"""Hypothesis fuzz: `-s <hostile_value>` must never:
	  - succeed (rc=0)
	  - traverse the filesystem (no /etc/passwd content in output)
	  - inject shell commands (output stays inert)
	  - hang or crash with a Python traceback

	A positive rc ≠ 0 with a clean error message is the only acceptable outcome.
	"""
	r = ita('read', '-s', session_arg, timeout=10)

	# Must NOT succeed — a hostile UUID should never resolve.
	assert r.returncode != 0, (
		f"ita read -s {session_arg!r} unexpectedly succeeded (rc=0). "
		f"stdout:{r.stdout!r}"
	)

	# No path traversal: /etc/passwd content must not appear.
	combined = r.stdout + r.stderr
	assert 'root:' not in combined, (
		f"Path traversal output detected with session_arg={session_arg!r}:\n{combined!r}"
	)

	# No unhandled Python exception.
	assert 'Traceback (most recent call last)' not in combined, (
		f"Uncaught exception for session_arg={session_arg!r}:\n{combined!r}"
	)


@pytest.mark.adversarial
@pytest.mark.property
@given(session_arg=_malformed_uuid_strategy)
@settings(max_examples=60, deadline=10_000)
def test_malformed_session_id_send_fuzz(session_arg):
	"""Same invariants as above, but via `ita send` — a write path."""
	r = ita('send', 'hello', '-s', session_arg, timeout=10)

	assert r.returncode != 0, (
		f"ita send -s {session_arg!r} unexpectedly succeeded (rc=0). "
		f"stdout:{r.stdout!r}"
	)

	combined = r.stdout + r.stderr
	assert 'root:' not in combined, (
		f"Path traversal output detected (send) with session_arg={session_arg!r}:\n{combined!r}"
	)
	assert 'Traceback (most recent call last)' not in combined, (
		f"Uncaught exception (send) for session_arg={session_arg!r}:\n{combined!r}"
	)


# ── 9. Unicode session names ──────────────────────────────────────────────────

# Chosen samples: emoji, RTL Arabic text, ZWJ sequence, mixed-script.
_UNICODE_NAMES = [
	'🎉🐍💥',                          # emoji cluster
	'مرحبا',                           # Arabic RTL
	'שלום',                            # Hebrew RTL
	'👨‍👩‍👧‍👦',                  # ZWJ family sequence
	'日本語セッション',                  # Japanese
	'café résumé naïve',               # Latin with diacritics
	'\u202e reversed',                  # RTL override character
	'normal\u200bword',                 # zero-width space mid-name
]


@pytest.mark.adversarial
@pytest.mark.integration
@pytest.mark.parametrize('name', _UNICODE_NAMES, ids=[repr(n) for n in _UNICODE_NAMES])
def test_unicode_session_name_create_lookup(name):
	"""Create a session with a unicode name; lookup and filter in `status` must not crash.

	Acceptable outcomes:
	  - Session created and appears in `status --json` (rc=0).
	  - Session creation fails gracefully with rc=1 and a message (iTerm2 may
	    reject certain code points) — NOT a crash.

	Forbidden: Python traceback, hang, rc > 1.
	"""
	import json

	r_new = ita('new', '--name', name, timeout=15)
	assert r_new.returncode in (0, 1), (
		f"ita new --name {name!r}: unexpected rc={r_new.returncode}\n"
		f"stderr:{r_new.stderr!r}"
	)
	assert 'Traceback (most recent call last)' not in r_new.stderr, (
		f"Uncaught exception creating session with name {name!r}:\n{r_new.stderr}"
	)

	if r_new.returncode != 0:
		# Creation failed cleanly — that's fine; still assert no crash.
		return

	sid = r_new.stdout.strip().split('\t')[-1]
	try:
		# `status --json` must survive listing a session with a unicode name.
		r_status = ita('status', '--json', timeout=10)
		assert r_status.returncode == 0, (
			f"status --json failed after creating unicode-named session: "
			f"rc={r_status.returncode}\nstderr:{r_status.stderr!r}"
		)
		assert 'Traceback (most recent call last)' not in r_status.stderr, (
			f"Uncaught exception in status --json with unicode session present:\n"
			f"{r_status.stderr}"
		)

		# JSON must still parse cleanly.
		try:
			sessions = json.loads(r_status.stdout)
		except json.JSONDecodeError as e:
			pytest.fail(
				f"status --json produced invalid JSON with unicode session name "
				f"{name!r}:\n{r_status.stdout[:400]!r}\nError: {e}"
			)

		# The session we just created must be present.
		sids_found = {s.get('session_id') for s in sessions}
		assert sid in sids_found, (
			f"Session {sid} with unicode name {name!r} not found in status output. "
			f"Possible encoding issue in session listing."
		)

	finally:
		ita('close', '-s', sid, timeout=10)


@pytest.mark.adversarial
@pytest.mark.integration
@pytest.mark.parametrize('name', _UNICODE_NAMES, ids=[repr(n) for n in _UNICODE_NAMES])
def test_unicode_session_name_filter(name):
	"""After creating a unicode-named session, `ita read` and `ita run` by session
	ID must work normally — unicode in the name must not corrupt the ID lookup.
	"""
	r_new = ita('new', '--name', name, timeout=15)
	if r_new.returncode != 0:
		pytest.skip(f"Session creation refused for name {name!r} — skipping lookup test")

	sid = r_new.stdout.strip().split('\t')[-1]
	try:
		time.sleep(0.5)
		r_read = ita('read', '-s', sid, timeout=10)
		assert r_read.returncode == 0, (
			f"read by ID failed for unicode-named session {name!r}: "
			f"rc={r_read.returncode}\nstderr:{r_read.stderr!r}"
		)
		assert 'Traceback (most recent call last)' not in r_read.stderr, (
			f"Uncaught exception on read for unicode-named session:\n{r_read.stderr}"
		)
	finally:
		ita('close', '-s', sid, timeout=10)
