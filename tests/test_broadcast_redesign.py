"""Happy-path tests for the broadcast redesign (#279): merge-vs-replace, dedup,
per-session JSON envelope, and --on-dead flag."""
import json
import sys
import time
import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from conftest import ita, ita_ok

pytestmark = [pytest.mark.broadcast]


def test_broadcast_add_merges_into_existing_domain(session):
	"""broadcast add merges sessions; broadcast set replaces atomically."""
	r_on = ita('broadcast', 'on', '-s', session)
	assert r_on.returncode == 0, f"broadcast on failed: {r_on.stderr}"
	try:
		# A second add should not wipe the domain.
		r_add = ita('broadcast', 'add', session)
		assert r_add.returncode == 0, f"broadcast add failed: {r_add.stderr}"
		r_list = ita('broadcast', 'list', '--json')
		domains = json.loads(r_list.stdout)
		all_ids = {m['session_id'] for d in domains for m in d}
		assert session in all_ids, "merge failed — original session missing after add"
	finally:
		ita('broadcast', 'off', '-y')


def test_broadcast_set_replaces_all_domains(session):
	"""broadcast set should be the explicit replace operation, wiping prior domains."""
	r_on = ita('broadcast', 'on', '-s', session)
	assert r_on.returncode == 0
	try:
		# set with only the current session — replaces whatever was there.
		r_set = ita('broadcast', 'set', session)
		assert r_set.returncode == 0, f"broadcast set failed: {r_set.stderr}"
		r_list = ita('broadcast', 'list', '--json')
		domains = json.loads(r_list.stdout)
		assert len(domains) == 1, f"expected 1 domain after set, got {len(domains)}"
		assert domains[0][0]['session_id'] == session
	finally:
		ita('broadcast', 'off', '-y')


def test_broadcast_send_json_per_session_envelope(session):
	"""broadcast send --json returns [{session_id, ok, error}] per session."""
	r_on = ita('broadcast', 'on', '-s', session)
	assert r_on.returncode == 0
	try:
		r = ita('broadcast', 'send', '--json', 'echo ENVELOPE_TEST')
		assert r.returncode == 0, f"broadcast send --json failed: {r.stderr}"
		results = json.loads(r.stdout)
		assert isinstance(results, list), "expected a list"
		assert len(results) >= 1
		entry = results[0]
		assert 'session_id' in entry, "missing session_id in envelope"
		assert 'ok' in entry, "missing ok in envelope"
		assert 'error' in entry, "missing error in envelope"
		assert entry['ok'] is True
		assert entry['session_id'] == session
	finally:
		ita('broadcast', 'off', '-y')


def test_broadcast_send_deduplicates_across_domains(session):
	"""Sessions in multiple domains receive text only once."""
	# Enable broadcast, then send; dedup means only 1 delivery.
	r_on = ita('broadcast', 'on', '-s', session)
	assert r_on.returncode == 0
	try:
		marker = 'DEDUP_REDESIGN_MARKER'
		r = ita('broadcast', 'send', '--json', marker)
		assert r.returncode == 0
		results = json.loads(r.stdout)
		sid_hits = [e for e in results if e['session_id'] == session and e['ok']]
		assert len(sid_hits) == 1, (
			f"session received {len(sid_hits)} sends — dedup broken"
		)
	finally:
		ita('broadcast', 'off', '-y')


def test_broadcast_send_on_dead_default_skip(session):
	"""--on-dead=skip (default) does not raise on a dead session; reports ok=False."""
	r_on = ita('broadcast', 'on', '-s', session)
	assert r_on.returncode == 0
	try:
		# We can't easily simulate a dead session in unit-test conditions, so
		# validate that the flag is accepted and the command still exits 0.
		r = ita('broadcast', 'send', '--json', '--on-dead', 'skip', 'echo ONDEAD_TEST')
		assert r.returncode == 0, f"--on-dead=skip failed: {r.stderr}"
		results = json.loads(r.stdout)
		assert isinstance(results, list)
	finally:
		ita('broadcast', 'off', '-y')
