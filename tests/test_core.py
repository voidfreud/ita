# tests/test_core.py
"""Unit tests for _core.py pure functions (no iTerm2 connection needed)."""
import sys
import types
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# Stub out heavy optional dependencies so _core.py can be imported without
# a real iTerm2 environment or click installation in the test venv.
# We use MagicMock so attribute access (e.g. @click.group()) works at import time.
from unittest.mock import MagicMock

for _mod in ('click', 'iterm2'):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


def test_strip_removes_null_bytes():
    from _core import strip
    assert strip("hello\x00world") == "helloworld"
    assert strip("\x00\x00\x00") == ""
    assert strip("clean") == "clean"
    assert strip("line\x00\x00  17%\x00tokens") == "line  17%tokens"


def test_strip_empty_string():
    from _core import strip
    assert strip("") == ""


def test_get_sticky_missing(tmp_path, monkeypatch):
    import _core
    monkeypatch.setattr(_core, 'CONTEXT_FILE', tmp_path / ".ita_context")
    assert _core.get_sticky() is None


def test_set_and_get_sticky(tmp_path, monkeypatch):
    import _core
    monkeypatch.setattr(_core, 'CONTEXT_FILE', tmp_path / ".ita_context")
    _core.set_sticky("SESSION-ABC")
    assert _core.get_sticky() == "SESSION-ABC"


def test_clear_sticky(tmp_path, monkeypatch):
    import _core
    monkeypatch.setattr(_core, 'CONTEXT_FILE', tmp_path / ".ita_context")
    _core.set_sticky("SESSION-ABC")
    _core.clear_sticky()
    assert _core.get_sticky() is None


def test_sticky_strips_whitespace(tmp_path, monkeypatch):
    import _core
    monkeypatch.setattr(_core, 'CONTEXT_FILE', tmp_path / ".ita_context")
    (tmp_path / ".ita_context").write_text("  SESSION-ID  \n")
    assert _core.get_sticky() == "SESSION-ID"


def test_sticky_empty_file_returns_none(tmp_path, monkeypatch):
    import _core
    monkeypatch.setattr(_core, 'CONTEXT_FILE', tmp_path / ".ita_context")
    (tmp_path / ".ita_context").write_text("   ")
    assert _core.get_sticky() is None
