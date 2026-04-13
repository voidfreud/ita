"""#229 regression: `ita inject` text mode is UTF-8 end-to-end.

Every valid Unicode codepoint — including emoji (astral plane, >U+FFFF),
CJK ideographs, combining marks, and RTL — must round-trip verbatim
through the encoder. Un-encodable input (lone surrogates) must raise
`ItaError("bad-args")` (rc=6) rather than silently mangling the payload
(CONTRACT §14.2 — no silent corruption of caller input).

Tests the pure encoder `_encode_inject_payload` directly; no iTerm2
connection is required.
"""
import pytest

from ita._send import _encode_inject_payload
from ita._envelope import ItaError, EXIT_CODES


# ── text-mode Unicode fidelity ────────────────────────────────────────────────

@pytest.mark.parametrize('sample', [
	'hello',                       # plain ASCII
	'café',                        # latin-1 range (U+00E9)
	'Ω≈ç√∫',                       # BMP non-latin-1
	'日本語テスト',                  # CJK
	'👋🎉🚀',                       # emoji — astral plane (>U+FFFF) — the #229 smoking gun
	'👨\u200d👩\u200d👧',           # ZWJ emoji sequence
	'e\u0301',                     # combining acute (NFD 'é')
	'\U0001F600',                  # single astral codepoint (grinning face)
	'مرحبا',                        # RTL (Arabic)
	'a\u0000b',                    # embedded NUL — must not be stripped
])
def test_inject_utf8_roundtrip(sample):
	"""#229: every valid Unicode input round-trips as its UTF-8 encoding. No
	silent loss of astral-plane codepoints (previously mangled above U+00FF)."""
	raw = _encode_inject_payload(sample, is_hex=False)
	assert isinstance(raw, bytes)
	assert raw == sample.encode('utf-8')
	# Round-trip sanity: decoding the bytes back yields the original string.
	assert raw.decode('utf-8') == sample


def test_inject_astral_codepoint_not_latin1_mangled():
	"""#229 explicit guard: an astral codepoint must NOT be encoded via any
	8-bit path (latin-1, cp1252, etc) that would drop or replace it."""
	raw = _encode_inject_payload('🎉', is_hex=False)
	# latin-1 cannot represent U+1F389 — if someone re-introduced latin-1
	# encoding this would either raise or produce 1 byte.
	assert len(raw) == 4           # U+1F389 is 4 bytes in UTF-8
	assert raw == b'\xf0\x9f\x8e\x89'


# ── lone-surrogate rejection ──────────────────────────────────────────────────

def test_inject_lone_surrogate_raises_bad_args():
	"""A lone surrogate (U+D83D without its trailing low-surrogate) cannot
	be represented in UTF-8. It must be rejected loudly as bad-args (rc=6),
	not silently replaced with '?' or stripped."""
	with pytest.raises(ItaError) as ei:
		_encode_inject_payload('\ud83d', is_hex=False)
	assert ei.value.code == 'bad-args'
	assert ei.value.exit_code == EXIT_CODES['bad-args']
	assert ei.value.exit_code == 6


# ── hex mode still works & now raises ItaError on invalid input ──────────────

def test_inject_hex_empty_returns_empty_bytes():
	assert _encode_inject_payload('', is_hex=True) == b''
	assert _encode_inject_payload('  ', is_hex=True) == b''


def test_inject_hex_valid():
	assert _encode_inject_payload('03', is_hex=True) == b'\x03'
	assert _encode_inject_payload('68 65 6c 6c 6f', is_hex=True) == b'hello'


def test_inject_hex_invalid_is_bad_args():
	"""Hex parse failure used to raise `click.ClickException` (rc=1). Per
	CONTRACT §6 it is now `bad-args` (rc=6)."""
	with pytest.raises(ItaError) as ei:
		_encode_inject_payload('zz', is_hex=True)
	assert ei.value.code == 'bad-args'
	assert ei.value.exit_code == 6
