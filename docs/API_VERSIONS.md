# ita × iTerm2 API version matrix

## Current
- iTerm2 Python API: 2.15
- Python: >=3.11 (from pyproject.toml)
- ita: 0.7.0 (from pyproject.toml)

## Tested against
- macOS: current developer machine only (no matrix)
- iTerm2 app: ? (no formal lower bound; whatever ships in current Homebrew `iterm2` cask)

## Notable API usage
Features ita depends on (see `grep -r "iterm2\." src/ita/`):

- `iterm2.async_get_app` — app/session discovery (core)
- `iterm2.Transaction` — atomic screen reads (`_screen.py`)
- `iterm2.PromptMonitor` with `Mode.COMMAND_END` — command completion / exit code (`_run.py`)
- `iterm2.PartialProfile.async_query`, `iterm2.LocalWriteOnlyProfile`, `iterm2.WriteOnlyProfile` — profile management (`_management.py`)
- `iterm2.ColorPreset.async_get` / `async_get_list`, `iterm2.Color` — color presets (`_management.py`)
- `iterm2.PreferenceKey`, `iterm2.async_get_preference`, `iterm2.async_set_preference` — app preferences (`_config.py`)
- `iterm2.BroadcastDomain`, `iterm2.async_set_broadcast_domains` — broadcast input (`_config.py`)
- Session UUIDs via `session.session_id` — session identity (`_management.py`)

Introduction versions: ? — not tracked upstream in a machine-readable way; add notes here only when a feature gets a runtime version gate.

## Version policy
- ita pins the `iterm2` Python package via `pyproject.toml` (currently unpinned range: `"iterm2"`).
- Supported iTerm2 app version: whatever ships with the current Homebrew `iterm2` cask. No formal lower bound unless a regression is found.
- This file updates whenever a feature gates on iTerm2 version (i.e. gets a runtime check).
