"""Regression for #330 — keymap must emit the standard xterm sequences for
Shift+Up/Down, Shift+PgUp/PgDn, and Meta+<digit> (tmux window switching).

Fast-lane: no iTerm2 connection; we drive `_parse_key` directly and assert
the exact byte sequence."""
import pytest

from ita._inject import _parse_key


class TestShiftArrows:
	"""xterm DECCKM modifier-2 form: `\\e[1;2<letter>`."""

	def test_shift_up(self):
		assert _parse_key('shift+up') == b'\x1b[1;2A'

	def test_shift_down(self):
		assert _parse_key('shift+down') == b'\x1b[1;2B'

	def test_shift_right(self):
		assert _parse_key('shift+right') == b'\x1b[1;2C'

	def test_shift_left(self):
		assert _parse_key('shift+left') == b'\x1b[1;2D'

	def test_shift_home(self):
		assert _parse_key('shift+home') == b'\x1b[1;2H'

	def test_shift_end(self):
		assert _parse_key('shift+end') == b'\x1b[1;2F'

	def test_short_alias_s_prefix(self):
		assert _parse_key('s-up') == b'\x1b[1;2A'


class TestShiftPageKeys:
	"""Tilde-terminated form: `\\e[<code>;2~`."""

	def test_shift_pgup(self):
		assert _parse_key('shift+pgup') == b'\x1b[5;2~'

	def test_shift_pgdn(self):
		assert _parse_key('shift+pgdn') == b'\x1b[6;2~'

	def test_shift_pageup_alias(self):
		assert _parse_key('shift+pageup') == b'\x1b[5;2~'

	def test_shift_pagedown_alias(self):
		assert _parse_key('shift+pagedown') == b'\x1b[6;2~'


class TestMetaDigits:
	"""Meta+<n> is ESC prefix + digit, matching tmux window-switch bindings."""

	@pytest.mark.parametrize('digit', list('0123456789'))
	def test_meta_digit(self, digit):
		assert _parse_key(f'meta+{digit}') == b'\x1b' + digit.encode('ascii')

	@pytest.mark.parametrize('digit', list('0123456789'))
	def test_alt_digit_alias(self, digit):
		assert _parse_key(f'alt+{digit}') == b'\x1b' + digit.encode('ascii')

	def test_m_prefix_alias(self):
		assert _parse_key('m-1') == b'\x1b1'


class TestShiftRejectsUnsupported:
	def test_shift_plain_letter_goes_uppercase(self):
		# shift+a is just 'A'; no escape sequence involved.
		assert _parse_key('shift+a') == b'A'

	def test_shift_unknown_key_errors(self):
		from ita._envelope import ItaError
		with pytest.raises(ItaError):
			_parse_key('shift+nonexistent')
