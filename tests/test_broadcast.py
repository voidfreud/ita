"""Integration tests for broadcast subcommands: add, set, send, list (contract)."""
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = pytest.mark.integration


# ── broadcast on / off ────────────────────────────────────────────────────────

def test_broadcast_on_session_flag(session):
	"""broadcast on should accept -s/--session flag (#50)."""
	r = ita('broadcast', 'on', '-s', session)
	assert r.returncode == 0
	ita('broadcast', 'off')


def test_broadcast_on_off_roundtrip(session):
	ita_ok('broadcast', 'on', '-s', session)
	r = ita('broadcast', 'off')
	assert r.returncode == 0


# ── broadcast add ─────────────────────────────────────────────────────────────

def test_broadcast_add_single_session(session):
	"""broadcast add with one session should succeed."""
	r = ita('broadcast', 'add', session)
	assert r.returncode == 0
	# Always clean up to avoid polluting other tests
	ita('broadcast', 'off')


def test_broadcast_add_two_sessions(session, shared_session):
	"""broadcast add with two distinct sessions should create a domain."""
	r = ita('broadcast', 'add', session, shared_session)
	assert r.returncode == 0
	ita('broadcast', 'off')


@pytest.mark.state
def test_broadcast_add_domain_visible_in_list(session, shared_session):
	"""After broadcast add, the domain should appear in broadcast list --json."""
	ita_ok('broadcast', 'add', session, shared_session)
	try:
		r = ita('broadcast', 'list', '--json')
		assert r.returncode == 0
		domains = json.loads(r.stdout)
		# At least one domain must include both session IDs
		all_ids = {m['session_id'] for d in domains for m in d}
		assert session in all_ids, "Added session not found in broadcast list"
		assert shared_session in all_ids, "Added shared_session not found in broadcast list"
	finally:
		ita('broadcast', 'off')


@pytest.mark.error
def test_broadcast_add_nonexistent_session():
	"""broadcast add with a bogus session ID should fail with a useful message."""
	r = ita('broadcast', 'add', 'not-a-real-session-id-xyz')
	assert r.returncode != 0
	assert 'not found' in r.stderr.lower() or 'not found' in r.stdout.lower()


@pytest.mark.error
def test_broadcast_add_duplicate_session_id(session):
	"""broadcast add with the same session ID twice should fail early."""
	r = ita('broadcast', 'add', session, session)
	assert r.returncode != 0
	assert 'duplicate' in r.stderr.lower() or 'Duplicate' in r.stderr


# ── broadcast set ─────────────────────────────────────────────────────────────

def test_broadcast_set_single_domain(session, shared_session):
	"""broadcast set with one comma-separated domain should succeed."""
	r = ita('broadcast', 'set', f'{session},{shared_session}')
	assert r.returncode == 0
	ita('broadcast', 'off')


@pytest.mark.state
def test_broadcast_set_replaces_existing(session, shared_session):
	"""broadcast set should atomically replace any prior domains."""
	# First establish a domain
	ita_ok('broadcast', 'on', '-s', session)
	# Now replace with a different explicit domain
	r = ita('broadcast', 'set', f'{session},{shared_session}')
	assert r.returncode == 0
	try:
		r2 = ita('broadcast', 'list', '--json')
		domains = json.loads(r2.stdout)
		# Exactly one domain containing both sessions
		assert len(domains) == 1
		ids = {m['session_id'] for m in domains[0]}
		assert session in ids
		assert shared_session in ids
	finally:
		ita('broadcast', 'off')


@pytest.mark.error
def test_broadcast_set_empty_domain_string():
	"""broadcast set with an all-whitespace domain should reject it."""
	r = ita('broadcast', 'set', '   ')
	assert r.returncode != 0
	assert 'empty' in r.stderr.lower() or 'Empty' in r.stderr


@pytest.mark.error
def test_broadcast_set_nonexistent_session(session):
	"""broadcast set with a bad session ID should fail with a message."""
	r = ita('broadcast', 'set', f'{session},not-a-real-session-zzz')
	assert r.returncode != 0
	assert 'not found' in r.stderr.lower() or 'not found' in r.stdout.lower()


# ── broadcast send ────────────────────────────────────────────────────────────

@pytest.mark.error
def test_broadcast_send_no_domain():
	"""broadcast send with no active domain should fail with a helpful message."""
	# Ensure no domains are active
	ita('broadcast', 'off')
	r = ita('broadcast', 'send', 'hello')
	assert r.returncode != 0
	assert 'broadcast on' in r.stderr.lower() or 'broadcast on' in r.stdout.lower()


def test_broadcast_send_with_active_domain(session):
	"""broadcast send with an active domain should report the sent count."""
	ita_ok('broadcast', 'on', '-s', session)
	try:
		r = ita('broadcast', 'send', 'echo ita_test_probe', '--no-newline')
		assert r.returncode == 0
		assert '1 session' in r.stdout
	finally:
		ita('broadcast', 'off')


# ── broadcast list (contract) ─────────────────────────────────────────────────

@pytest.mark.contract
def test_broadcast_list_json_schema_empty():
	"""broadcast list --json with no domains must be a valid empty JSON array."""
	import jsonschema
	ita('broadcast', 'off')
	r = ita('broadcast', 'list', '--json')
	assert r.returncode == 0
	data = json.loads(r.stdout)
	schema = {
		'type': 'array',
		'items': {
			'type': 'array',
			'items': {
				'type': 'object',
				'required': ['session_id', 'session_name'],
				'properties': {
					'session_id': {'type': 'string'},
					'session_name': {'type': 'string'},
				},
				'additionalProperties': False,
			},
		},
	}
	jsonschema.validate(data, schema)


@pytest.mark.contract
def test_broadcast_list_json_schema_with_domain(session):
	"""broadcast list --json with an active domain must conform to the schema."""
	import jsonschema
	ita_ok('broadcast', 'on', '-s', session)
	try:
		r = ita('broadcast', 'list', '--json')
		assert r.returncode == 0
		data = json.loads(r.stdout)
		schema = {
			'type': 'array',
			'items': {
				'type': 'array',
				'items': {
					'type': 'object',
					'required': ['session_id', 'session_name'],
					'properties': {
						'session_id': {'type': 'string'},
						'session_name': {'type': 'string'},
					},
					'additionalProperties': False,
				},
			},
		}
		jsonschema.validate(data, schema)
		# At minimum, the session we added should appear
		all_ids = {m['session_id'] for d in data for m in d}
		assert session in all_ids
	finally:
		ita('broadcast', 'off')


def test_broadcast_list_no_domains_text():
	"""broadcast list (plain text) with no domains should say so."""
	ita('broadcast', 'off')
	r = ita('broadcast', 'list')
	assert r.returncode == 0
	assert 'no broadcast domains' in r.stdout.lower()
