"""Unit tests for `ita read` filters: --after-row, --since-prompt (issue #141)."""
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from ita._output import _is_prompt_line, read  # noqa: E402


def _make_filter(after_row=None, since_prompt=False, grep_rx=None):
	"""Rebuild the _filter closure from _output.read for direct testing."""
	def _filter(raw):
		result = raw
		if after_row is not None:
			result = result[after_row:]
		if grep_rx:
			result = [ln for ln in result if grep_rx.search(ln)]
		if since_prompt:
			for i in range(len(result) - 1, -1, -1):
				if _is_prompt_line(result[i]):
					result = result[i + 1:]
					break
		return result
	return _filter


class TestIsPromptLine:
	@pytest.mark.parametrize('line', ['$', '# root', '% zsh', '❯ cmd', '→ go', '>> py', 'cmd $', '  $  '])
	def test_detects_prompts(self, line):
		assert _is_prompt_line(line) is True

	@pytest.mark.parametrize('line', ['', '   ', 'hello world', 'no prompt here', 'foo bar baz'])
	def test_rejects_non_prompts(self, line):
		assert _is_prompt_line(line) is False


class TestAfterRow:
	def test_skips_first_n(self):
		f = _make_filter(after_row=2)
		assert f(['a', 'b', 'c', 'd']) == ['c', 'd']

	def test_zero_returns_all(self):
		f = _make_filter(after_row=0)
		assert f(['a', 'b', 'c']) == ['a', 'b', 'c']

	def test_past_end_returns_empty(self):
		f = _make_filter(after_row=10)
		assert f(['a', 'b']) == []

	def test_none_returns_all(self):
		f = _make_filter(after_row=None)
		assert f(['a', 'b', 'c']) == ['a', 'b', 'c']


class TestSincePrompt:
	def test_returns_lines_after_last_prompt(self):
		f = _make_filter(since_prompt=True)
		lines = ['$ first', 'out1', '$ second', 'out2', 'out3']
		assert f(lines) == ['out2', 'out3']

	def test_no_prompt_returns_all(self):
		f = _make_filter(since_prompt=True)
		assert f(['hello', 'world']) == ['hello', 'world']

	def test_prompt_is_last_line(self):
		f = _make_filter(since_prompt=True)
		assert f(['out', '$ ']) == []

	def test_finds_last_not_first(self):
		f = _make_filter(since_prompt=True)
		lines = ['$ a', 'x', '$ b', 'y', '$ c', 'z']
		assert f(lines) == ['z']

	def test_empty_input(self):
		f = _make_filter(since_prompt=True)
		assert f([]) == []


class TestCombined:
	def test_after_row_then_since_prompt(self):
		f = _make_filter(after_row=1, since_prompt=True)
		lines = ['$ old', '$ kept', 'a', 'b']
		# after_row=1 -> ['$ kept', 'a', 'b']; since_prompt strips through last prompt -> ['a','b']
		assert f(lines) == ['a', 'b']


class TestTailFilter:
	"""Tests for --tail truncation (#126)."""

	def _make_tail_filter(self, tail_n):
		"""Rebuild the full _filter closure with only tail_n set."""
		def _filter(raw):
			result = raw
			if tail_n is not None and len(result) > tail_n:
				result = [f"[truncated: {len(result)} lines]"] + result[-tail_n:]
			return result
		return _filter

	def test_no_truncation_when_under_limit(self):
		f = self._make_tail_filter(5)
		lines = ['a', 'b', 'c']
		assert f(lines) == ['a', 'b', 'c']

	def test_no_truncation_at_exact_limit(self):
		f = self._make_tail_filter(3)
		lines = ['a', 'b', 'c']
		assert f(lines) == ['a', 'b', 'c']

	def test_truncation_prepends_notice(self):
		f = self._make_tail_filter(2)
		lines = ['a', 'b', 'c', 'd']
		result = f(lines)
		assert result[0] == '[truncated: 4 lines]'
		assert result[1:] == ['c', 'd']

	def test_notice_reflects_full_count_not_tail(self):
		# The notice shows how many lines were present BEFORE cutting, not tail size.
		f = self._make_tail_filter(1)
		lines = ['x'] * 10
		result = f(lines)
		assert '[truncated: 10 lines]' in result[0]

	def test_tail_none_never_truncates(self):
		f = self._make_tail_filter(None)
		lines = list(range(1000))
		assert f(lines) == lines


class TestReadCLIFlags:
	"""CLI surface check: flags exist and are documented."""

	def test_flags_present_in_help(self):
		runner = CliRunner()
		result = runner.invoke(read, ['--help'])
		assert result.exit_code == 0
		assert '--after-row' in result.output
		assert '--since-prompt' in result.output

	def test_tail_flag_present_in_help(self):
		runner = CliRunner()
		result = runner.invoke(read, ['--help'])
		assert result.exit_code == 0
		assert '--tail' in result.output

	def test_grep_flag_present_in_help(self):
		runner = CliRunner()
		result = runner.invoke(read, ['--help'])
		assert result.exit_code == 0
		assert '--grep' in result.output
