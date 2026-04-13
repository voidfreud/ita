# src/ita/_claudecode.py
"""Auto-protect the Claude Code session driving this ita invocation.

CONTRACT §10 "Auto-protect the Claude Code session (#340)": on every ita
invocation, detect the Claude Code session (env var `CLAUDECODE` set by
Claude Code itself) and add its iTerm2 session UUID to `~/.ita_protected`.
Idempotent. Never removed on exit — the user controls that via `unprotect`.

Detection signal: the `ITERM_SESSION_ID` env var is set by iTerm2 for every
shell it spawns. Its format is `w<win>t<tab>p<pane>:<UUID>`. The UUID
suffix is identical to the `session_id` reported by the Python API, so a
pure-env-var match is both reliable and cheap — no iTerm2 API roundtrip.

Best-effort throughout: any failure (no env vars, malformed value, unreadable
~/.ita_protected) is swallowed so command dispatch is never blocked by the
auto-protect hook.
"""
import os

from ._protect import add_protected, get_protected


def auto_protect_claudecode_session() -> bool:
	"""If this ita invocation is driven by Claude Code, add its iTerm2
	session UUID to ~/.ita_protected.

	Returns True if a session id was added, False otherwise (not under
	Claude Code, no ITERM_SESSION_ID, already protected, or any failure).
	"""
	try:
		if not os.environ.get("CLAUDECODE"):
			return False
		raw = os.environ.get("ITERM_SESSION_ID", "")
		# Format: `w<win>t<tab>p<pane>:<UUID>`. Take the UUID suffix.
		if ":" not in raw:
			return False
		session_id = raw.split(":", 1)[1].strip()
		if not session_id:
			return False
		if session_id in get_protected():
			return False  # idempotent no-op
		add_protected(session_id)
		return True
	except Exception:
		# Never block command dispatch on a detection failure.
		return False
