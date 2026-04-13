# ita — iTerm Agent

Agent-first iTerm2 control for Claude Code. Built directly on the iTerm2 Python API.

**Authors:** Void Freud ([@voidfreud](https://github.com/voidfreud)) + Claude (Anthropic), co-designed and co-implemented.

## What it does

`ita` gives Claude complete, clean control over iTerm2 — creating sessions, running commands atomically with wait-for-completion, streaming output via ScreenStreamer, managing layouts, arrangements, profiles, tmux -CC workflows, and reacting to events. All with minimal context pollution.

The core innovation is `ita run "cmd"` — a single call that sends the command, waits for completion, and returns clean output. No polling, no chaining, no null bytes.

**North star:** [`docs/CONTRACT.md`](docs/CONTRACT.md) is the authoritative spec — output shape, exit codes, session state machine, protection/lock invariants. Every PR amends it.

## Requirements

- macOS with iTerm2 3.6+
- iTerm2 Python API enabled: Settings → General → Magic → Enable Python API
- [`uv`](https://github.com/astral-sh/uv) installed
- Shell integration (optional, for `ita get-prompt`): `curl -L https://iterm2.com/shell_integration/install_shell_integration.sh | bash`

## Install

### As a Claude Code plugin

Install via Claude Code's plugin system (`/plugin` command). The plugin provides the `ita` skill which documents every command for Claude to use.

### Add `ita` to your PATH

The plugin ships the `ita` CLI at `src/ita.py`. To make it available globally:

```bash
cd /path/to/ita  # wherever the plugin installed it, or the cloned repo
./install.sh     # symlinks src/ita.py → ~/.local/bin/ita
```

Then verify: `ita --help`

## Development

```bash
uv run src/ita.py --help                                    # run directly
uv run --with pytest --with click --with iterm2 pytest      # run tests
```

## Architecture

Single entry point (`src/ita.py`) using uv inline script metadata, importing focused modules.

**Core / shared helpers** (no commands — imported by everything else):

| Module | Responsibility |
|--------|---------------|
| `_core.py` | `run_iterm`, `resolve_session`, `emit`, `confirm_or_skip`, writelock, CLI root |
| `_protect.py` | Protected-session set (`~/.ita_protected`), `check_protected` |
| `_screen.py` | `_is_prompt_line`, `strip`, `read_session_lines`, prompt-char set |
| `_filter.py` | `--where KEY=VALUE` parse / match |
| `_envelope.py` | CONTRACT §4/§6 — `SCHEMA_VERSION`, exit-code taxonomy, `ItaError` |
| `_readiness.py` | `stabilize` — canonical wait-until-ready helper |

**Command modules** (register commands on the shared `cli` group):

| Module | Commands |
|--------|---------|
| `_orientation.py` | `status`, `focus`, `version`, `protect`, `unprotect` |
| `_overview.py` | `overview` (single-call world model) |
| `_session.py` | `new`, `close`, `activate`, `name`, `restart`, `resize`, `clear`, `capture` |
| `_send.py` | `run` (atomic), `send`, `inject`, `key` |
| `_output.py` | `read` |
| `_stream.py` | `watch` |
| `_query.py` | `wait`, `selection`, `copy`, `get-prompt` |
| `_pane.py` | `split`, `pane`, `move`, `swap` |
| `_tab.py` | `tab` group |
| `_layout.py` | `window` group |
| `_layouts.py` | `layouts` group (save / restore / list / delete / rename / export) |
| `_management.py` | `profile` group, `presets` |
| `_config.py` | `var`, `app`, `pref`, `broadcast` groups |
| `_interactive.py` | `alert`, `ask`, `pick`, `save-dialog`, `menu` group, `repl` |
| `_tmux.py` | `tmux -CC` group |
| `_events.py` | `on` group, `coprocess`, `annotate`, `rpc` |
| `_lock.py` | `lock`, `unlock` |
| `_meta.py` | `commands`, `doctor` |

Target: every module ≤ ~250–300 lines, one clear responsibility. All mutators go through `_core` primitives (`check_protected`, `session_writelock`, `emit`, `run_iterm`).

## License

MIT — see LICENSE
