"""Repaint-stress tests: targets the append-only-screen assumption (#232)
and `run` output-scoping fragility.

All tests are marked @pytest.mark.stress and @pytest.mark.integration.
xfail tests are direct evidence for bug #232.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita

pytestmark = [pytest.mark.stress, pytest.mark.integration]

# ---------------------------------------------------------------------------
# Scenario 1 — carriage-return repaint (progress bar pattern)
# ---------------------------------------------------------------------------

def test_run_carriage_return_repaint(session):
	"""Invariant: run must return only final line-based output; \\r-overwritten
	fragments must not appear in captured stdout.

	Probes: run output-scoping fragility — partial \\r lines bleeding through."""
	cmd = (
		"for i in $(seq 1 10); do "
		"  printf '\\rProgress %d/10' \"$i\"; sleep 0.1; "
		"done; printf '\\n'; echo DONE"
	)
	r = ita('run', cmd, '-s', session, timeout=30)
	assert r.returncode == 0, f"run failed: {r.stderr}"
	assert 'DONE' in r.stdout, f"DONE sentinel missing from stdout:\n{r.stdout!r}"
	lines = [ln for ln in r.stdout.splitlines() if '\r' in ln and 'Progress' in ln]
	assert not lines, f"Partial \\r lines leaked into output: {lines}"


# ---------------------------------------------------------------------------
# Scenario 2 — clear-then-print (pre-clear content must not leak)
# ---------------------------------------------------------------------------

def test_run_clear_then_print(session):
	"""Invariant: content written before `clear` must not appear in run's
	captured output; only post-clear content is in scope.

	Probes: append-only-screen assumption (#232) — stale screen content leaking."""
	ita('run', 'echo PRE_CLEAR_MARKER', '-s', session, timeout=10)
	r = ita('run', 'clear; echo AFTER', '-s', session, timeout=10)
	assert r.returncode == 0, f"run failed: {r.stderr}"
	assert 'AFTER' in r.stdout, f"AFTER missing: {r.stdout!r}"
	assert 'PRE_CLEAR_MARKER' not in r.stdout, (
		f"Pre-clear content leaked into scoped output:\n{r.stdout!r}"
	)


# ---------------------------------------------------------------------------
# Scenario 3 — large output (5000 lines, no truncation)
# ---------------------------------------------------------------------------

def test_run_large_output_5000_lines(session):
	"""Invariant: run must capture all 5000 lines without truncation.

	Probes: run output-scoping fragility — buffer or scroll-back limits."""
	r = ita('run', 'seq 1 5000', '-n', '5000', '-s', session, timeout=60)
	assert r.returncode == 0, f"run failed: {r.stderr}"
	lines = [ln for ln in r.stdout.splitlines() if ln.strip().isdigit()]
	assert len(lines) == 5000, f"Expected 5000 numeric lines, got {len(lines)}"
	assert '5000' in r.stdout, "Last line (5000) missing — truncation detected"


# ---------------------------------------------------------------------------
# Scenario 4 — very wide line (512 cols, no wrap artifacts)
# ---------------------------------------------------------------------------

def test_run_wide_line_no_wrap(session):
	"""Invariant: a 512-character line must arrive in captured output as a
	single unbroken token, not split across multiple lines.

	Probes: terminal column-wrap leaking into run's captured stdout."""
	payload = 'x' * 512
	r = ita('run', f'printf "%s\\n" "{payload}"', '-s', session, timeout=15)
	assert r.returncode == 0, f"run failed: {r.stderr}"
	# At least one line in output must be the full 512-char string
	assert payload in r.stdout, (
		f"512-char line not found intact; possible wrap artifact.\n"
		f"stdout (first 200 chars): {r.stdout[:200]!r}"
	)


# ---------------------------------------------------------------------------
# Scenario 5 — ANSI colours stripped in --json mode
# ---------------------------------------------------------------------------

def test_run_ansi_stripped_in_json_mode(session):
	"""Invariant: --json output must not contain raw ANSI escape sequences;
	text displayed to the user should be clean.

	Probes: run output-scoping fragility — ANSI passthrough in JSON capture."""
	r = ita('run', r"printf '\e[31mred\e[0m\n'", '--json', '-s', session, timeout=15)
	assert r.returncode == 0, f"run failed: {r.stderr}"
	assert '\x1b[' not in r.stdout, (
		f"Raw ANSI escape present in --json output:\n{r.stdout!r}"
	)
	assert 'red' in r.stdout, f"'red' text missing from output:\n{r.stdout!r}"


# ---------------------------------------------------------------------------
# Scenario 6 — watch misses DONE sentinel during repainting loop (xfail #232)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
	strict=False,
	reason=(
		"#232 append-only-screen assumption: watch reads snapshot lines "
		"from the terminal buffer; \\r-overwritten lines overwrite earlier "
		"lines in the buffer so the DONE sentinel may land on a previously-seen "
		"row and be skipped by the change-detection heuristic."
	),
)
def test_watch_misses_done_during_repaint(session):
	"""Invariant: watch must eventually deliver the DONE sentinel even when
	the command uses \\r-based in-place repainting.

	Expected to FAIL as evidence for bug #232."""
	cmd = (
		"for i in $(seq 1 5); do "
		"  printf '\\rTick %d/5' \"$i\"; sleep 0.2; "
		"done; printf '\\n'; echo DONE"
	)
	ita('send', cmd + '\n', '-s', session)
	time.sleep(3)

	r = ita('watch', '--timeout', '5', '--until', 'DONE', '-s', session, timeout=10)
	assert 'DONE' in r.stdout, (
		f"watch never delivered DONE sentinel during repaint loop:\n{r.stdout!r}"
	)


# ---------------------------------------------------------------------------
# Scenario 7 — watch while session clears mid-stream (xfail #232)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
	strict=False,
	reason=(
		"#232 append-only-screen assumption: a mid-stream `clear` resets the "
		"visible buffer; watch's snapshot diff may interpret the cleared screen "
		"as 'no new content' and stall or miss subsequent output."
	),
)
def test_watch_clears_mid_stream(session):
	"""Invariant: watch must continue delivering output after a mid-stream clear.

	Expected to FAIL as evidence for bug #232."""
	cmd = "echo BEFORE; sleep 0.5; clear; echo AFTER_CLEAR"
	ita('send', cmd + '\n', '-s', session)
	time.sleep(2.5)

	r = ita('watch', '--timeout', '5', '--until', 'AFTER_CLEAR', '-s', session, timeout=10)
	assert 'AFTER_CLEAR' in r.stdout, (
		f"watch lost output after mid-stream clear:\n{r.stdout!r}"
	)


# ---------------------------------------------------------------------------
# Scenario 8 — concurrent read + run on same session
# ---------------------------------------------------------------------------

def test_concurrent_read_and_run(session):
	"""Invariant: a `read` issued concurrently with `run` must reflect the
	run's output, not stale pre-run content.

	Probes: run output-scoping fragility — race between snapshot and execution."""
	import concurrent.futures

	sentinel = 'CONCURRENT_SENTINEL_42'

	def do_run():
		return ita('run', f'echo {sentinel}', '-s', session, timeout=20)

	def do_read():
		time.sleep(0.3)  # slight delay so run has started
		return ita('read', '-s', session, timeout=20)

	with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
		fut_run = ex.submit(do_run)
		fut_read = ex.submit(do_read)
		run_result = fut_run.result()
		read_result = fut_read.result()

	assert run_result.returncode == 0, f"run failed: {run_result.stderr}"
	# read should see the sentinel at some point (may be in run result or read result)
	combined = run_result.stdout + read_result.stdout
	assert sentinel in combined, (
		f"Sentinel never appeared in run or read output.\n"
		f"run stdout: {run_result.stdout!r}\n"
		f"read stdout: {read_result.stdout!r}"
	)


# ---------------------------------------------------------------------------
# Scenario 9 — embedded NUL byte handling
# ---------------------------------------------------------------------------

def test_run_embedded_nul_stripped_or_escaped(session):
	"""Invariant: NUL bytes in command output must be stripped or escaped;
	raw NUL (\\x00) must never appear in captured stdout string.

	Probes: run output-scoping fragility — binary safety of captured output."""
	r = ita('run', r"printf 'a\0b\n'", '-s', session, timeout=15)
	assert r.returncode == 0, f"run failed: {r.stderr}"
	assert '\x00' not in r.stdout, (
		f"Raw NUL byte present in captured output — binary safety violation:\n"
		f"{r.stdout!r}"
	)
	# Remaining printable content should survive
	assert 'a' in r.stdout and 'b' in r.stdout, (
		f"Expected 'a' and 'b' in output after NUL handling:\n{r.stdout!r}"
	)


# ---------------------------------------------------------------------------
# Scenario 10 — fullscreen TUI / alternate screen buffer
# ---------------------------------------------------------------------------

def test_read_after_alt_screen_tui(session):
	"""Invariant: after a command that enters and exits the alternate screen
	buffer (tput smcup/rmcup), `read` must return to the normal buffer and
	capture coherent content — not garbage from the alt-screen or an empty string.

	Documents behavior: alt-screen content may or may not be preserved; the
	key invariant is that `read` does not hang and returns something non-empty."""
	r = ita(
		'run',
		"tput smcup; echo 'alt-screen-content'; sleep 0.5; tput rmcup; echo NORMAL_SCREEN",
		'-s', session,
		timeout=20,
	)
	assert r.returncode == 0, f"run failed: {r.stderr}"
	read_r = ita('read', '-s', session, timeout=10)
	assert read_r.returncode == 0, f"read failed after alt-screen: {read_r.stderr}"
	assert read_r.stdout.strip(), (
		"read returned empty string after alt-screen TUI — buffer may be lost"
	)
