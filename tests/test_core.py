# tests/test_core.py
"""Unit tests for _core.py pure functions (no iTerm2 connection needed)."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


def test_strip_removes_null_bytes():
    from _core import strip
    assert strip("hello\x00world") == "helloworld"
    assert strip("\x00\x00\x00") == ""
    assert strip("clean") == "clean"
    assert strip("line\x00\x00  17%\x00tokens") == "line  17%tokens"


def test_strip_empty_string():
    from _core import strip
    assert strip("") == ""


# ── Hypothesis property tests ─────────────────────────────────────────────────

from hypothesis import given, settings, strategies as st


def _is_float(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


@given(st.text())
def test_strip_never_raises(s):
    from _core import strip
    result = strip(s)
    assert isinstance(result, str)
    assert '\x00' not in result


@given(st.text())
def test_strip_idempotent(s):
    from _core import strip
    assert strip(strip(s)) == strip(s)


@given(st.text(alphabet=st.characters(blacklist_characters='\x00')))
def test_strip_passthrough_when_no_nulls(s):
    from _core import strip
    assert strip(s) == s


@given(st.text(min_size=1, max_size=1,
               alphabet='abcdefghijklmnopqrstuvwxyz'))
def test_parse_key_single_lowercase(ch):
    from _send import _parse_key
    result = _parse_key(ch)
    assert isinstance(result, bytes)
    assert len(result) == 1
    assert result == ch.encode('utf-8')


@given(st.text(min_size=1, max_size=1,
               alphabet='abcdefghijklmnopqrstuvwxyz'))
def test_parse_key_ctrl_letter(ch):
    from _send import _parse_key
    result = _parse_key(f'ctrl+{ch}')
    assert isinstance(result, bytes)
    assert len(result) == 1
    assert 1 <= result[0] <= 26


@given(st.sampled_from(['true', 'false', 'True', 'False', 'TRUE', 'FALSE']))
def test_coerce_pref_bool(val):
    from _config import _coerce_pref_value
    result = _coerce_pref_value(val)
    assert isinstance(result, bool)
    assert result == (val.lower() == 'true')


@given(st.integers(min_value=-(2**31), max_value=2**31))
def test_coerce_pref_int(val):
    from _config import _coerce_pref_value
    result = _coerce_pref_value(str(val))
    assert result == val
    assert isinstance(result, int)


@given(st.text(min_size=1).filter(
    lambda s: s.lower() not in ('true', 'false')
    and not s.lstrip('-').isdigit()
    and not _is_float(s)
))
@settings(max_examples=50)
def test_coerce_pref_string_passthrough(val):
    from _config import _coerce_pref_value
    result = _coerce_pref_value(val)
    assert result == val
