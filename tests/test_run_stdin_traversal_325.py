"""#325 regression: `ita run --stdin PATH` rejects path-traversal.

`--stdin` used to accept any filesystem path (e.g. `/etc/passwd` or
`../../../secret`) without validation. Per CONTRACT §14.4 (protection &
safety never bypassed silently), the path must resolve under the caller's
CWD unless the explicit `--stdin-allow-outside-cwd` flag is passed. All
violations raise `ItaError("bad-args", ...)` (rc=6, CONTRACT §6).

Tests the pure loader `_load_stdin_script` directly; no iTerm2 connection
is required.
"""
import os
from pathlib import Path
import pytest

from ita._send import _load_stdin_script
from ita._envelope import ItaError


# ── happy path ────────────────────────────────────────────────────────────────

def test_stdin_under_cwd_ok(tmp_path, monkeypatch):
	script = tmp_path / "build.sh"
	script.write_text("echo hello\nls\n")
	monkeypatch.chdir(tmp_path)
	assert _load_stdin_script(str(script), allow_outside_cwd=False) == "echo hello\nls\n"


def test_stdin_under_cwd_relative_ok(tmp_path, monkeypatch):
	sub = tmp_path / "scripts"
	sub.mkdir()
	script = sub / "inner.sh"
	script.write_text("date\n")
	monkeypatch.chdir(tmp_path)
	assert _load_stdin_script("scripts/inner.sh", allow_outside_cwd=False) == "date\n"


# ── rejection: traversal / outside-CWD ────────────────────────────────────────

def test_stdin_etc_passwd_rejected(tmp_path, monkeypatch):
	"""#325: absolute path outside CWD is rejected by default."""
	monkeypatch.chdir(tmp_path)
	with pytest.raises(ItaError) as ei:
		_load_stdin_script("/etc/passwd", allow_outside_cwd=False)
	assert ei.value.code == "bad-args"
	assert ei.value.exit_code == 6


def test_stdin_dotdot_traversal_rejected(tmp_path, monkeypatch):
	"""#325: `..` sequences that realpath-escape CWD are rejected."""
	outside = tmp_path / "outside.sh"
	outside.write_text("echo leaked\n")
	inside = tmp_path / "work"
	inside.mkdir()
	monkeypatch.chdir(inside)
	with pytest.raises(ItaError) as ei:
		_load_stdin_script("../outside.sh", allow_outside_cwd=False)
	assert ei.value.code == "bad-args"
	assert "outside CWD" in ei.value.reason or "outside" in ei.value.reason.lower()


def test_stdin_symlink_escape_rejected(tmp_path, monkeypatch):
	"""#325: a symlink inside CWD that resolves to an outside path is rejected.
	realpath resolution — not just textual — closes this escape hatch."""
	outside_dir = tmp_path / "outside"
	outside_dir.mkdir()
	secret = outside_dir / "secret.sh"
	secret.write_text("echo secret\n")
	work = tmp_path / "work"
	work.mkdir()
	link = work / "inner.sh"
	try:
		link.symlink_to(secret)
	except (OSError, NotImplementedError):
		pytest.skip("symlink not supported on this platform")
	monkeypatch.chdir(work)
	with pytest.raises(ItaError) as ei:
		_load_stdin_script("inner.sh", allow_outside_cwd=False)
	assert ei.value.code == "bad-args"


def test_stdin_nonexistent_path_rejected(tmp_path, monkeypatch):
	monkeypatch.chdir(tmp_path)
	with pytest.raises(ItaError) as ei:
		_load_stdin_script("does-not-exist.sh", allow_outside_cwd=False)
	assert ei.value.code == "bad-args"
	assert "not found" in ei.value.reason.lower()


def test_stdin_directory_rejected(tmp_path, monkeypatch):
	monkeypatch.chdir(tmp_path)
	sub = tmp_path / "a-dir"
	sub.mkdir()
	with pytest.raises(ItaError) as ei:
		_load_stdin_script("a-dir", allow_outside_cwd=False)
	assert ei.value.code == "bad-args"
	assert "regular file" in ei.value.reason.lower()


# ── explicit opt-in ───────────────────────────────────────────────────────────

def test_stdin_outside_cwd_with_flag_ok(tmp_path, monkeypatch):
	"""#325: explicit --stdin-allow-outside-cwd lets callers load files
	outside CWD on purpose (agent-side opt-in; no interactive prompt)."""
	outside = tmp_path / "outside.sh"
	outside.write_text("echo opted-in\n")
	work = tmp_path / "work"
	work.mkdir()
	monkeypatch.chdir(work)
	out = _load_stdin_script(str(outside), allow_outside_cwd=True)
	assert out == "echo opted-in\n"
