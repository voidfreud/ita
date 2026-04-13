"""Regression for #320 — REPL must not let adversarial input reach a shell,
and must surface bad input as a readable error rather than a crash.

The repl entrypoint uses `shlex.split` then dispatches via
`click.testing.CliRunner.invoke(cli, argv)`, so no shell is ever invoked —
these tests lock that down by (a) unit-testing the token validator and
(b) end-to-end feeding adversarial lines through `ita repl` and asserting
the outer process still exits cleanly with no side-effects."""
import subprocess
import pytest

from ita._interactive import _validate_repl_tokens


ITA = ['uv', 'run', 'python', '-m', 'ita']


# ──────────────────────────────────────────────────────────────────────────
# Unit: _validate_repl_tokens rejects the classic injection payloads
# ──────────────────────────────────────────────────────────────────────────

class TestValidateTokens:
	def test_empty_rejected(self):
		ok, err = _validate_repl_tokens([])
		assert not ok and 'empty' in err

	def test_unknown_verb_rejected(self):
		ok, err = _validate_repl_tokens(['definitely-not-a-command'])
		assert not ok and 'unknown command' in err

	def test_known_verb_accepted(self):
		# `commands` is a built-in ita top-level verb; if it ever disappears
		# this test should be updated, not silently broken.
		ok, err = _validate_repl_tokens(['commands'])
		assert ok and err is None

	@pytest.mark.parametrize('payload', [
		'\x00', '\n', '\r', '\x1b', '\x07',
	])
	def test_control_chars_rejected(self, payload):
		ok, err = _validate_repl_tokens(['commands', f'arg{payload}here'])
		assert not ok and 'control character' in err

	def test_tab_allowed(self):
		# Tab is the one C0 control we keep — it's a legitimate argument
		# character (file paths, session names on Linux permit it).
		ok, _ = _validate_repl_tokens(['commands', 'a\tb'])
		assert ok

	@pytest.mark.parametrize('payload', [
		# Classic shell metacharacters — these are LITERAL tokens after
		# shlex.split with no quoting, so they should pass validation
		# (the verb is unknown, that's what gets rejected).
		'; rm -rf /',
		'&& echo pwned',
		'`whoami`',
		'$(whoami)',
		'| cat /etc/passwd',
	])
	def test_shell_metacharacters_are_literal_not_executed(self, payload):
		"""Sanity: shlex tokenizes these as literal strings, never expanded."""
		import shlex
		tokens = shlex.split(payload)
		# First token is the (bogus) verb; we only care that nothing ran.
		ok, err = _validate_repl_tokens(tokens)
		assert not ok
		assert 'unknown command' in err


# ──────────────────────────────────────────────────────────────────────────
# End-to-end: repl subprocess stays clean under adversarial input
# ──────────────────────────────────────────────────────────────────────────

def _run_repl(stdin, timeout=15):
	return subprocess.run(
		ITA + ['repl'],
		input=stdin, capture_output=True, text=True, timeout=timeout,
	)


@pytest.mark.edge
class TestReplInjectionResistant:
	"""Each case: pipe adversarial line + `exit` → outer rc must be 0, no
	trace of the payload having been executed by a shell (e.g. no `uid=` from
	`$(id)`, no `/bin/sh` error text)."""

	@pytest.mark.parametrize('line', [
		'commands; rm -rf /tmp/should-not-matter',
		'commands && echo PWNED',
		'commands `id`',
		'commands $(id)',
		'commands | cat /etc/passwd',
		'commands > /tmp/ita-320-should-not-exist',
	])
	def test_shell_metacharacters_dont_execute(self, line):
		r = _run_repl(f'{line}\nexit\n')
		assert r.returncode == 0
		# If a shell had run `$(id)` or `id`, stdout/stderr would contain
		# a uid=… line. It must not.
		assert 'uid=' not in r.stdout
		assert 'uid=' not in r.stderr
		# `echo PWNED` executed by a shell would emit a line starting with
		# PWNED; the raw string may appear in the prompt echo of our own
		# input. Check for the output signature, not the substring.
		assert '\nPWNED\n' not in r.stdout and not r.stdout.startswith('PWNED')
		# And the "should not exist" artefact must not exist.
		import os
		assert not os.path.exists('/tmp/ita-320-should-not-exist')

	def test_unclosed_quote_surfaces_parse_error_no_crash(self):
		# shlex.split raises ValueError here; repl must catch it.
		r = _run_repl('commands "unclosed\nexit\n')
		assert r.returncode == 0
		assert 'parse error' in r.stderr or 'Error' in r.stderr

	def test_unknown_verb_surfaces_error_no_crash(self):
		r = _run_repl('totally-nonexistent\nexit\n')
		assert r.returncode == 0
		assert 'unknown command' in r.stderr

	def test_null_byte_in_arg_rejected(self):
		# click.prompt reads a line, so we can't literally send \x00 through
		# stdin readline — but we can via an escaped token that shlex keeps
		# intact. The most reliable check is the unit test above; here we
		# confirm the REPL doesn't crash on weird control chars.
		r = _run_repl('commands \x1b[31mred\x1b[0m\nexit\n')
		assert r.returncode == 0
		assert 'control character' in r.stderr
