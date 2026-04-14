# src/_inject.py
"""`ita inject` (display-side raw bytes) and `ita key` (friendly-name keystrokes).

Both target the terminal emulator but at different layers: `inject` writes into
the emulator's output stream (what gets rendered on screen), while `key` delivers
bytes as user input (what the foreground process reads from its TTY). Task #13
will later convert `inject` to the `@ita_command` envelope; keeping it in its own
module makes that a single-file edit."""
import click
from ._core import cli, run_iterm, resolve_session, check_protected, session_writelock
from ._envelope import ItaError
from ._lock import resolve_force_flags
from ._force import _force_options


def _encode_inject_payload(data: str, is_hex: bool) -> bytes:
	"""Pure encoder for `ita inject`. Returns the raw bytes to hand to
	`session.async_inject`, or raises `ItaError("bad-args", ...)` (rc=6).

	Contract (#229, CONTRACT §14.2):
	- Text mode is UTF-8 end-to-end. Every valid Unicode codepoint survives
	  verbatim: emoji and other astral-plane chars (>U+FFFF), CJK, combining
	  marks, RTL, etc. No silent replacement or truncation.
	- `errors='strict'` means lone surrogates (U+D800..U+DFFF that leaked in
	  via `surrogateescape` or similar) fail loudly rather than being mangled.
	- Hex mode requires two-char pairs (spaces allowed); empty string is a no-op
	  (returns `b''` which the caller treats as "nothing to send")."""
	if is_hex:
		normalized = data.replace(' ', '')
		if not normalized:
			return b''
		try:
			return bytes.fromhex(normalized)
		except ValueError as e:
			raise ItaError("bad-args",
				f"invalid hex data: {data!r}. Use two-character pairs (e.g. '03' for Ctrl+C).") from e
	try:
		return data.encode('utf-8', errors='strict')
	except (UnicodeDecodeError, UnicodeEncodeError) as e:
		raise ItaError("bad-args",
			f"cannot encode input as UTF-8 ({e}). "
			f"Use --hex for raw bytes (e.g. `ita inject --hex 71` for 'q').") from e


@cli.command()
@click.argument('data')
@click.option('--hex', 'is_hex', is_flag=True, help='Interpret DATA as hex bytes')
@click.option('-s', '--session', 'session_id', default=None)
@_force_options
def inject(data, is_hex, session_id, force_protected, force_lock, force):
	"""Inject raw bytes into the terminal emulator's output stream (display side).
	For sending input to a running process (Ctrl+C, arrow keys, etc.) use 'ita key' instead.

	Text mode is UTF-8 end-to-end (full Unicode, including astral-plane codepoints
	like emoji). Un-encodable input (lone surrogates) fails with rc=6 `bad-args`
	rather than silently mangling the payload (#229, CONTRACT §14.2)."""
	# Encode up-front so invalid input fails before we touch iTerm2 (no
	# partial-write or lock-acquire side effects on bad-args).
	raw = _encode_inject_payload(data, is_hex)
	fp, fl = resolve_force_flags(force, force_protected, force_lock)
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		check_protected(session.session_id, force_protected=fp)
		with session_writelock(session.session_id, force_lock=fl):
			if raw:
				await session.async_inject(raw)
	run_iterm(_run)


# Friendly key names → literal byte sequences delivered as user input.
# Control chars are single bytes; special keys use the standard VT100/xterm
# escape sequences that iTerm2's shell consumers already understand.
_KEY_MAP = {
	'enter': '\r',
	'return': '\r',
	'tab': '\t',
	'backspace': '\x7f',
	'esc': '\x1b',
	'escape': '\x1b',
	'space': ' ',
	'up': '\x1b[A',
	'down': '\x1b[B',
	'right': '\x1b[C',
	'left': '\x1b[D',
	'home': '\x1b[H',
	'end': '\x1b[F',
	'pgup': '\x1b[5~',
	'pgdn': '\x1b[6~',
	'pagedown': '\x1b[6~',
	'pageup': '\x1b[5~',
	'delete': '\x1b[3~',
	'f1': '\x1bOP', 'f2': '\x1bOQ', 'f3': '\x1bOR', 'f4': '\x1bOS',
	'f5': '\x1b[15~', 'f6': '\x1b[17~', 'f7': '\x1b[18~', 'f8': '\x1b[19~',
	'f9': '\x1b[20~', 'f10': '\x1b[21~', 'f11': '\x1b[23~', 'f12': '\x1b[24~',
	'f13': '\x1b[25~', 'f14': '\x1b[26~', 'f15': '\x1b[28~', 'f16': '\x1b[29~',
	'f17': '\x1b[31~', 'f18': '\x1b[32~', 'f19': '\x1b[33~',
}


def _parse_key(token: str) -> bytes:
	"""Resolve 'ctrl+c', 'alt+f', 'f5', 'enter', etc. to the bytes iTerm2 should deliver as input."""
	t = token.strip().lower()
	if not t:
		raise click.ClickException("empty key token")
	# ctrl+<letter|number> → 0x01..0x1a (letters), 0x00 for @, 0x1b for [, etc.
	if t.startswith('ctrl+') or t.startswith('c-'):
		rest = t.split('+', 1)[1] if '+' in t else t[2:]
		if len(rest) == 1:
			ch = rest
			if 'a' <= ch <= 'z':
				return bytes([ord(ch) - ord('a') + 1])
			if ch == '@':
				return b'\x00'
			if ch == '[':
				return b'\x1b'
			if ch == '\\':
				return b'\x1c'
			if ch == ']':
				return b'\x1d'
			if ch == '^':
				return b'\x1e'
			if ch == '_':
				return b'\x1f'
		raise click.ClickException(f"unsupported ctrl combination: {token!r}")
	# alt+<key> → ESC followed by the key's bytes
	if t.startswith('alt+') or t.startswith('a-') or t.startswith('meta+') or t.startswith('m-'):
		rest = t.split('+', 1)[1] if '+' in t else t[2:]
		if len(rest) == 1:
			return b'\x1b' + rest.encode('utf-8')
		if rest in _KEY_MAP:
			return b'\x1b' + _KEY_MAP[rest].encode('latin-1')
		raise click.ClickException(f"unsupported alt combination: {token!r}")
	# Named key
	if t in _KEY_MAP:
		return _KEY_MAP[t].encode('latin-1')
	# Single literal character
	if len(t) == 1:
		return token.encode('utf-8')
	raise click.ClickException(
		f"unknown key: {token!r}. Try ctrl+c, alt+f, enter, esc, tab, up, f5, etc."
	)


@cli.command()
@click.argument('keys', nargs=-1, required=True)
@click.option('-s', '--session', 'session_id', default=None)
@_force_options
def key(keys, session_id, force_protected, force_lock, force):
	"""Send keystrokes as user input. Use friendly names: ctrl+c, ctrl+d, esc, enter,
	tab, space, backspace, up, down, left, right, home, end, pgup, pgdn, f1-f19.
	Multiple keys are sent in order: 'ita key ctrl+c ctrl+c' sends Ctrl+C twice."""
	try:
		payload = b''.join(_parse_key(k) for k in keys)
	except click.ClickException:
		raise
	fp, fl = resolve_force_flags(force, force_protected, force_lock)
	async def _run(connection):
		session = await resolve_session(connection, session_id)
		check_protected(session.session_id, force_protected=fp)
		with session_writelock(session.session_id, force_lock=fl):
			# Decode bytes back to a str for async_send_text (it takes text, not raw bytes —
			# iTerm2 internally encodes via the session's terminal encoding).
			await session.async_send_text(payload.decode('latin-1'))
	run_iterm(_run)
