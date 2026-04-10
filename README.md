# ita — iTerm Agent

Agent-first iTerm2 control for Claude Code. Built directly on the iTerm2 Python API.

**Authors:** Void Freud ([@voidfreud](https://github.com/voidfreud)) + Claude (Anthropic), co-designed and co-implemented.

## What it does

`ita` gives Claude complete, clean control over iTerm2 — creating sessions, running commands atomically with wait-for-completion, streaming output via ScreenStreamer, managing layouts, arrangements, profiles, tmux -CC workflows, and reacting to events. All with minimal context pollution.

The core innovation is `ita run "cmd"` — a single call that sends the command, waits for completion, and returns clean output. No polling, no chaining, no null bytes.

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

Single entry point (`src/ita.py`) using uv inline script metadata, importing focused modules:

| Module | Responsibility |
|--------|---------------|
| `_core.py` | Helpers: `run_iterm`, `resolve_session`, `strip`, sticky context, CLI root |
| `_orientation.py` | `status`, `focus`, `version`, `use` |
| `_session.py` | `new`, `close`, `activate`, `name`, `restart`, `resize`, `clear`, `capture` |
| `_send.py` | `run` (atomic), `send`, `inject` |
| `_output.py` | `read`, `watch` (ScreenStreamer), `wait`, `selection`, `copy`, `get-prompt` |
| `_layout.py` | `split`, `pane`, `move`, `tab` group, `window` group |
| `_management.py` | `save`, `restore`, `layouts`, `profile` group, `presets`, `theme` |
| `_config.py` | `var`, `app`, `pref`, `broadcast` groups |
| `_interactive.py` | `alert`, `ask`, `pick`, `save-dialog`, `menu` group, `repl` |
| `_tmux.py` | `tmux` -CC group |
| `_events.py` | `on` group, `coprocess`, `annotate`, `rpc` |

Every module ≤200 lines, one clear responsibility, all registering commands on the shared `cli` group from `_core`.

## License

MIT — see LICENSE
