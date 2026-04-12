"""Tests for layout/arrangement commands: save, restore, layouts list."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita

pytestmark = pytest.mark.integration

_ARRANGEMENT = 'ita-test-arrangement'


def _cleanup(name: str) -> None:
	"""Best-effort: iTerm2 has no public delete API, so we can't remove arrangements.
	Tests that create arrangements use a fixed name and rely on --force for idempotency."""
	pass


# ── save ──────────────────────────────────────────────────────────────────────

def test_save_happy():
	"""Happy: save an arrangement, confirm rc=0 and 'Saved:' in stdout."""
	r = ita('save', _ARRANGEMENT, '--force')
	assert r.returncode == 0
	assert 'Saved' in r.stdout


@pytest.mark.edge
def test_save_empty_name():
	"""Edge: empty name string is rejected with rc=1."""
	r = ita('save', '   ')
	assert r.returncode == 1
	assert 'empty' in r.stderr.lower() or 'name' in r.stderr.lower()


@pytest.mark.error
def test_save_duplicate_without_force():
	"""Error: saving over an existing arrangement without --force fails."""
	# Pre-create so the name exists
	ita('save', _ARRANGEMENT, '--force')
	r = ita('save', _ARRANGEMENT)
	assert r.returncode == 1
	assert 'already exists' in r.stderr or 'exists' in r.stderr.lower()


@pytest.mark.state
def test_save_force_overwrites():
	"""State: --force must succeed even when the arrangement already exists."""
	ita('save', _ARRANGEMENT, '--force')
	r = ita('save', _ARRANGEMENT, '--force')
	assert r.returncode == 0
	assert 'Saved' in r.stdout


@pytest.mark.state
def test_save_appears_in_list():
	"""State: arrangement saved with --force must appear in 'layouts list'."""
	ita('save', _ARRANGEMENT, '--force')
	r = ita('layouts', 'list')
	assert r.returncode == 0
	assert _ARRANGEMENT in r.stdout


# ── restore ───────────────────────────────────────────────────────────────────

def test_restore_happy():
	"""Happy: restore a known arrangement, rc=0, 'Restored:' in stdout."""
	ita('save', _ARRANGEMENT, '--force')
	r = ita('restore', _ARRANGEMENT)
	assert r.returncode == 0
	assert 'Restored' in r.stdout


@pytest.mark.error
def test_restore_not_found():
	"""Error: restore a non-existent arrangement → rc=1, 'not found' in stderr."""
	r = ita('restore', 'nonexistent_arrangement_ita_test_xyz')
	assert r.returncode == 1
	assert 'not found' in r.stderr.lower() or 'failed' in r.stderr.lower()


@pytest.mark.edge
def test_restore_dry_run():
	"""Edge: --dry-run prints what would be restored without actually restoring."""
	r = ita('restore', _ARRANGEMENT, '--dry-run')
	assert r.returncode == 0
	assert 'Would restore' in r.stdout
	assert _ARRANGEMENT in r.stdout


@pytest.mark.state
def test_restore_quiet_suppresses_output():
	"""State: -q suppresses the 'Restored:' confirmation line."""
	ita('save', _ARRANGEMENT, '--force')
	r = ita('restore', _ARRANGEMENT, '-q')
	assert r.returncode == 0
	assert 'Restored' not in r.stdout


# ── layouts list ──────────────────────────────────────────────────────────────

def test_layouts_list_happy():
	"""Happy: layouts list rc=0, output is lines of names (or empty)."""
	ita('save', _ARRANGEMENT, '--force')
	r = ita('layouts', 'list')
	assert r.returncode == 0
	names = [line.strip() for line in r.stdout.splitlines() if line.strip()]
	# The arrangement we just saved must appear
	assert _ARRANGEMENT in names


@pytest.mark.contract
def test_layouts_list_no_nulls():
	"""Contract: output contains no NUL bytes."""
	r = ita('layouts', 'list')
	assert r.returncode == 0
	assert '\x00' not in r.stdout


@pytest.mark.edge
def test_layouts_group_default_lists():
	"""Edge: bare 'layouts' (no subcommand) behaves identically to 'layouts list'."""
	ita('save', _ARRANGEMENT, '--force')
	r_sub = ita('layouts', 'list')
	r_bare = ita('layouts')
	assert r_sub.returncode == r_bare.returncode == 0
	assert r_sub.stdout.strip() == r_bare.stdout.strip()
