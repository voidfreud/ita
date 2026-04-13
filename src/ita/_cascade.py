# src/ita/_cascade.py
"""Destructive-blast-radius helpers (CONTRACT §10, #340).

A close is a *window cascade* when the act of closing a smaller unit also
takes down the containing window — because that unit was the last of its
kind inside the window. Window cascades are forbidden by default: the
caller must pass `--allow-window-close` to opt in.

Two shapes:
  - `session_close_would_cascade_window(session)`: True when closing this
	session also closes its tab (last session in tab) AND closing that
	tab also closes its window (last tab in window).
  - `tab_close_would_cascade_window(tab)`: True when closing this tab
	also closes its window (last tab in window).
"""


def session_close_would_cascade_window(session) -> bool:
	"""Return True when closing `session` would cascade-close its window."""
	tab = session.tab if hasattr(session, 'tab') else None
	if tab is None:
		return False
	# Last session in tab?
	if len(tab.sessions) != 1:
		return False
	window = tab.window if hasattr(tab, 'window') else None
	if window is None:
		return False
	# Last tab in window?
	return len(window.tabs) == 1


def tab_close_would_cascade_window(tab) -> bool:
	"""Return True when closing `tab` would cascade-close its window."""
	window = tab.window if hasattr(tab, 'window') else None
	if window is None:
		return False
	return len(window.tabs) == 1
