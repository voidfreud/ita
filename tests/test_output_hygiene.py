"""Output-hygiene unit tests for CONTRACT §3 / §9 (issues #327, #331).

Pure-unit coverage — no iTerm2 required. These tests exercise
`_is_prompt_line` and `_trim_output_lines` directly."""
import os

import pytest

from ita._screen import _is_prompt_line
from ita._send import _trim_output_lines


# ── #327: _is_prompt_line ─────────────────────────────────────────────────

class TestIsPromptLine:
	"""CONTRACT §9: line ends with prompt char (after trailing whitespace
	strip) → prompt. Prompt char + non-whitespace content → NOT prompt."""

	@pytest.mark.parametrize("line", [
		"$",
		"%",
		"#",
		">",
		"❯",
		"›",
		"~ ❯",
		"user@host %",
		"$   ",         # trailing whitespace still a prompt
		"\x00$",        # NUL-prefixed is still a prompt
	])
	def test_bare_prompts_are_prompts(self, line):
		assert _is_prompt_line(line) is True

	@pytest.mark.parametrize("line", [
		"",
		"   ",
		"hello world",
		"regular output",
		"$ ls",                      # echo remnant: prompt + non-ws
		"~ ❯ make test",             # echo remnant with command
		"% echo foo",                # echo remnant
		"cost: $5",                  # content ending in digits
	])
	def test_non_prompts(self, line):
		assert _is_prompt_line(line) is False

	def test_content_glued_to_prompt_char_is_not_prompt(self):
		# Regression #331: data like `price: 5%` or `regex: ^foo$` ends in a
		# prompt char but the char is glued to non-whitespace — CONTENT.
		assert _is_prompt_line("price: 5%") is False
		assert _is_prompt_line("regex: ^foo$") is False

	def test_user_extensions_via_env(self, monkeypatch):
		monkeypatch.setenv("ITA_PROMPT_CHARS", "§")
		assert _is_prompt_line("custom §") is True
		assert _is_prompt_line("custom § not-prompt") is False


# ── #331: _trim_output_lines ──────────────────────────────────────────────

class TestTrimOutputLines:
	"""CONTRACT §3 / §9: content ending in a prompt char is CONTENT. KEEP it."""

	def test_drops_trailing_bare_prompt(self):
		lines = ["hello", "world", "$"]
		assert _trim_output_lines(lines) == ["hello", "world"]

	def test_keeps_content_ending_in_prompt_char_regression_331(self):
		# Regression: the last row is real data ("price: 5%"), NOT a bare
		# prompt. Old code stripped the trailing `%` and erased data.
		lines = ["price: 5%"]
		assert _trim_output_lines(lines) == ["price: 5%"]

	def test_keeps_dollar_terminated_content(self):
		lines = ["regex: ^foo$"]
		assert _trim_output_lines(lines) == ["regex: ^foo$"]

	def test_drops_leading_and_trailing_blanks(self):
		lines = ["", "  ", "data", "", ""]
		assert _trim_output_lines(lines) == ["data"]

	def test_empty_input(self):
		assert _trim_output_lines([]) == []

	def test_only_blanks(self):
		assert _trim_output_lines(["", "  "]) == []

	def test_prompt_after_content_then_blanks(self):
		lines = ["one", "two", "$", ""]
		# blanks dropped first, then bare `$` → dropped.
		assert _trim_output_lines(lines) == ["one", "two"]
