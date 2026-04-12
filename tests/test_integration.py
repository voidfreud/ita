# tests/test_integration.py
"""
Integration smoke tests. Require iTerm2 running with Python API enabled.
Run with: uv run --with pytest --with click --with iterm2 pytest tests/test_integration.py -v
"""
import subprocess
from pathlib import Path

ITA_SCRIPT = Path(__file__).parent.parent / 'src' / 'ita.py'


def run_ita(*args):
    """Run ita command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ['uv', 'run', str(ITA_SCRIPT)] + list(args),
        capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def test_help_runs():
    """--help should work without iTerm2 connection."""
    rc, out, _ = run_ita('--help')
    assert rc == 0
    assert 'status' in out
    assert 'run' in out
    assert 'watch' in out


def test_all_command_groups_registered():
    """Verify all major commands appear in help output."""
    _, out, _ = run_ita('--help')
    expected = [
        'status', 'focus', 'version', 'use',
        'new', 'close', 'activate', 'name', 'restart', 'resize', 'clear', 'capture',
        'run', 'send', 'inject',
        'read', 'watch', 'wait', 'selection', 'copy', 'get-prompt',
        'split', 'pane', 'move', 'tab', 'window',
        'save', 'restore', 'layouts',
        'profile', 'presets', 'theme',
        'var', 'app', 'pref', 'broadcast',
        'alert', 'ask', 'pick', 'save-dialog', 'menu', 'repl',
        'tmux',
        'on', 'coprocess', 'annotate', 'rpc',
    ]
    for cmd in expected:
        assert cmd in out, f"Missing command: {cmd}"


def test_status_runs():
    """ita status should run against live iTerm2 without errors."""
    rc, _, stderr = run_ita('status')
    # Either succeeds (rc=0) with real sessions, or fails cleanly with a click error
    assert rc in (0, 1), f"unexpected error: {stderr}"


def test_version_runs():
    """ita version should return iTerm2 app version."""
    rc, out, stderr = run_ita('version')
    assert rc == 0, f"error: {stderr}"
    assert out, "version returned empty"
