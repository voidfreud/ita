# ita — iTerm Agent Design Spec

**Date:** 2026-04-10  
**Status:** Approved for implementation  
**Author:** Alex Bass + Claude  

---

## Vision

`ita` is an agent-first iTerm2 control tool built directly on the iTerm2 Python API. It replaces cli-anything-iterm2 entirely and is designed specifically for Claude to use naturally — every default is the right one for an agent, output is always clean, and operations are atomic where possible.

**Core principle:** Designed for how Claude thinks, not how humans type.

---

## Architecture

### Tool structure

`ita` is a single Python script using uv's inline script dependencies — no separate install step, runs anywhere uv is present.

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["iterm2", "click"]
# ///
```

### Delivery

A Claude Code plugin — self-contained, portable, hostable. Everything lives inside the plugin:

```
ita/
├── plugin.json                    # plugin manifest
├── skills/
│   └── ita/
│       └── SKILL.md               # Claude's reference — complete command docs
├── src/
│   └── ita.py                     # the tool (uv inline script)
├── docs/
│   └── specs/
│       └── 2026-04-10-ita-design.md
├── .gitignore
├── README.md
└── LICENSE
```

### Dependencies

| Dependency | Version | Purpose |
|-----------|---------|---------|
| Python | ≥3.11 | Runtime |
| uv | any | Script runner (already installed) |
| `iterm2` (PyPI) | ≥2.14 | iTerm2 Python API |
| `click` | ≥8.0 | CLI framework |
| iTerm2 (app) | ≥3.6 | Target application |
| macOS | any | Platform |

**iTerm2 prerequisite:** Python API must be enabled:  
`iTerm2 → Settings → General → Magic → Enable Python API` ✓

**Shell integration** (for `ita wait` and `ita run` wait-for-completion):  
Already installed at `~/.iterm2_shell_integration.zsh`, sourced in `~/.zshrc` ✓

---

## Session Targeting

The single most important design decision. `ita` uses a **sticky context** model:

1. **Sticky target** — persisted in `~/.ita_context` (session ID)
2. **Auto-set** — `ita new` and `ita new --window` automatically set the sticky target
3. **Manual set** — `ita use SESSION_ID` overrides
4. **Per-command override** — any command accepts `-s SESSION_ID`
5. **Clear** — `ita use --clear` removes sticky target

**Precedence:** `-s FLAG` > sticky context > error (never silently targets wrong session)

---

## Output Design

| Situation | Format | Notes |
|-----------|--------|-------|
| Default | Plain text | Always stripped, no null bytes, no JSON wrapping |
| Need IDs | `--json` | Machine-readable, minimal fields |
| `ita run` | stdout of command | Exit code only on `--json` |
| `ita read` | plain text lines | Stripped at source |
| `ita status` | aligned text table | Columns: id \| name \| process \| path \| current |
| `ita new` | session ID only | Just the ID, one line |

**Null bytes:** stripped at the Python API level before any output — never reach the caller.

---

## Complete Command Surface

### ORIENTATION
```bash
ita status                              # all sessions: id | name | process | path | current*
ita status --json                       # structured for ID parsing
ita focus                               # what has keyboard focus right now (window/tab/session)
ita version                             # iTerm2 app version
```

### SESSION TARGETING
```bash
ita use SESSION_ID                      # set sticky target
ita use --clear                         # clear sticky target
```

### SESSION LIFECYCLE
```bash
ita new                                 # new tab → sets sticky target → returns session ID
ita new --window                        # new window
ita new --profile NAME                  # with specific profile
ita close                               # close current/target session
ita close -s SESSION_ID                 # close specific session
ita activate SESSION_ID                 # focus/bring to front
ita restart                             # restart session
ita resize --cols N --rows N            # resize pane
ita name "title"                        # rename session
ita clear                               # clear screen
ita capture [FILE]                      # save screen to file (default: stdout)
```

### SENDING INPUT
```bash
ita run "cmd"                           # send + wait for completion + return clean output (ATOMIC)
ita run "cmd" -t 60                     # custom timeout seconds (default: 30)
ita run "cmd" --json                    # output + exit_code + duration_ms
ita send "text"                         # fire and forget (appends newline)
ita send "text" --raw                   # no newline
ita inject $'\x03'                      # raw bytes — Ctrl+C, escape sequences
ita inject "1b5b324a" --hex             # hex bytes
```

### READING OUTPUT
```bash
ita read [N]                            # last N lines, stripped, clean (default: 20)
ita read --json                         # + session metadata
ita watch                               # ScreenStreamer → stream until prompt (zero polling)
ita wait                                # block until next shell prompt appears
ita wait --pattern "Server ready"       # block until pattern appears in output
ita selection                           # get currently selected text
ita copy                                # copy selection to clipboard
ita get-prompt                          # last prompt info: cwd, command, exit status
```

### PANES
```bash
ita split                               # horizontal split, new pane becomes target
ita split -v                            # vertical split
ita split --profile NAME                # split with specific profile
ita pane right|left|above|below         # navigate to adjacent pane
ita move SESSION_ID DEST                # move pane to different window/split position
```

### TABS
```bash
ita tab new                             # new tab
ita tab new --window WINDOW_ID
ita tab close [TAB_ID]
ita tab activate TAB_ID                 # focus tab
ita tab next                            # next tab
ita tab prev                            # previous tab
ita tab goto INDEX                      # tab by index (0-based)
ita tab list
ita tab info [TAB_ID]
ita tab move                            # detach current tab to own window
ita tab title "name"                    # set tab title
```

### WINDOWS
```bash
ita window new
ita window close [WINDOW_ID]
ita window activate [WINDOW_ID]
ita window title "name"
ita window fullscreen on|off|toggle
ita window frame                        # get position and size
ita window frame --x X --y Y --w W --h H   # set position and size
ita window list
```

### ARRANGEMENTS (SAVED LAYOUTS)
```bash
ita save NAME                           # save all windows as arrangement
ita save --window NAME                  # save current window only
ita restore NAME                        # restore arrangement
ita layouts                             # list all saved arrangements
```

### PROFILES & VISUAL FEEDBACK
```bash
ita profile list                        # all profiles
ita profile show [NAME]                 # profile details
ita profile apply NAME                  # apply profile to current session
ita profile set PROPERTY VALUE          # set profile property on current session
ita presets                             # list available color presets
ita theme PRESET                        # apply color preset to current session
ita theme red                           # shortcut: visual failure indicator
ita theme green                         # shortcut: visual success indicator
ita app theme                           # current UI theme (light/dark/auto)
```

### VARIABLES
```bash
ita var get NAME                        # get session variable (default scope: session)
ita var get NAME --scope tab|window|app
ita var set NAME VALUE                  # set variable
ita var set NAME VALUE --scope tab|window|app
ita var list                            # list all variables in scope
ita var list --scope tab|window|app
```

### APP CONTROL
```bash
ita app activate                        # bring iTerm2 to front
ita app hide                            # hide iTerm2
ita app quit                            # quit iTerm2
```

### DIALOGS
```bash
ita alert "Title" "Message"
ita alert "Deploy?" "Push to prod?" --button Yes --button No
ita ask "Title" "Message"               # text input dialog, returns entered text
ita ask "Title" "Message" --default "value"
ita pick                                # macOS open dialog, returns path(s)
ita pick --ext py --ext txt --multi
ita save-dialog                         # macOS save dialog, returns path
ita save-dialog --name output.txt
```

### BROADCAST
```bash
ita broadcast on                        # all panes in current window receive same input
ita broadcast on --window WINDOW_ID     # specific window
ita broadcast off                       # stop broadcasting
ita broadcast add SESSION_ID SESSION_ID # group specific sessions
ita broadcast set "S1,S2" "S3,S4"      # set all broadcast domains at once
ita broadcast list                      # list current domains
```

### MENU
```bash
ita menu list                           # list common menu items
ita menu "Shell/Split Vertically with Current Profile"   # invoke menu item
ita menu state "View/Enter Full Screen"  # check if item is checked/enabled
```

### TMUX -CC INTEGRATION
```bash
ita tmux start                          # bootstrap tmux -CC connection
ita tmux start --attach                 # attach to existing tmux session
ita tmux "list-sessions"                # send tmux protocol command, returns output
ita tmux windows                        # tmux windows → iTerm2 tab IDs
ita tmux connections                    # list active tmux -CC connections
ita tmux visible @1 on|off              # show/hide a tmux window's iTerm2 tab
```

### PREFERENCES
```bash
ita pref get KEY
ita pref set KEY VALUE
ita pref list                           # all valid preference keys
ita pref list --filter TEXT             # filter by substring
ita pref tmux                           # all tmux preferences at once
ita pref tmux set PROPERTY VALUE        # set tmux preference
ita pref theme                          # current theme tags + is_dark bool
```

### EVENT MONITORING (powered by ScreenStreamer + Notifications API)
```bash
ita watch                               # stream screen updates until prompt (ScreenStreamer)
ita wait                                # block until next prompt
ita wait --pattern "text"               # block until pattern appears in output
ita on output "pattern"                 # one-shot: block until pattern in output
ita on prompt                           # one-shot: block until next prompt
ita on session-new                      # one-shot: block until new session created
ita on session-end                      # one-shot: block until session terminates
ita on focus                            # one-shot: block until focus changes
ita on layout                           # one-shot: block until layout changes
ita on keystroke PATTERN                # one-shot: block until keystroke matches
```

### ADVANCED
```bash
ita coprocess start "cmd"               # attach subprocess to session I/O
ita coprocess stop
ita annotate "text"                     # add annotation to current screen content
ita annotate "text" --range START END
ita rpc "function()"                    # invoke RPC function in session context
```

### REPL MODE
```bash
ita repl                                # interactive mode, maintains sticky context
```

---

## Event System Design

`ita on` and `ita watch` are backed by the iTerm2 Python notifications API — fully push-based, zero polling:

- `ita watch` → `ScreenStreamer` — yields on every screen update, exits on prompt detection
- `ita wait --pattern` → `ScreenStreamer` with regex match, exits when matched
- `ita on prompt` → `async_subscribe_to_prompt_notification`
- `ita on session-new` → `async_subscribe_to_new_session_notification` via `NewSessionMonitor`
- `ita on session-end` → `SessionTerminationMonitor`
- `ita on focus` → `FocusMonitor`
- `ita on layout` → `LayoutChangeMonitor`
- `ita on keystroke` → `async_subscribe_to_keystroke_notification`

All `ita on` commands are **one-shot** — subscribe, wait for one event, print result, exit. For continuous monitoring, the caller (Claude) loops or uses the Monitor tool on a background Bash process.

---

## The `ita run` Atomic Operation

This is the core innovation. A single call that replaces the cli-anything three-step pattern:

**Before (cli-anything):**
```bash
cli-anything-iterm2 session send "npm install"
cli-anything-iterm2 session wait-command-end --timeout 120
cli-anything-iterm2 session scrollback --tail 20 --strip
```

**After (ita):**
```bash
ita run "npm install" -t 120
```

Implementation: uses shell integration's `async_wait_for_prompt` if available, falls back to polling scrollback for prompt character (`❯`) with 2-second intervals, max timeout. Returns clean stdout. Reports exit status on `--json`.

---

## Plugin Manifest (plugin.json)

```json
{
  "name": "ita",
  "version": "1.0.0",
  "description": "Agent-first iTerm2 control — full API access optimized for Claude",
  "author": "voidfreud",
  "skills": ["skills/ita"],
  "bin": {
    "ita": "src/ita.py"
  }
}
```

---

## Git Setup

```bash
cd ~/Developer/ita
git init
git branch -M main
```

`.gitignore`:
```
__pycache__/
*.pyc
.DS_Store
~/.ita_context        # excluded — runtime state, not source
```

Remote: `github.com/voidfreud/ita` (when ready to publish)

---

## What This Replaces

| Replaced | By |
|----------|-----|
| `cli-anything-iterm2` | `ita` — full superset |
| `it2 monitor output/prompt` | `ita watch`, `ita on prompt` |
| `it2 session list` | `ita status` |
| jq filter workaround | not needed — no null bytes at source |
| wait-command-end + scrollback pattern | `ita run` atomic |
| fresh tab detection logic | `ita new` handles internally |
| polling loops | `ita watch`, `ita wait`, `ita on *` |

---

## Success Criteria

- `ita run "cmd"` works atomically — no extra calls needed
- `ita status` output never contains null bytes
- `ita watch` uses ScreenStreamer — verified zero Bash polling
- Every cli-anything capability has a corresponding `ita` command
- New session ID returned by `ita new` works immediately as `-s` target
- Plugin installs cleanly via Claude Code plugin system
- `ita repl` maintains context across commands in one session
