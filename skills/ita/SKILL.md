---
name: ita
description: "Agent-first iTerm2 control. Full command reference for sending text to iTerm2 sessions, reading output via ScreenStreamer, managing tabs/windows/split panes, running commands atomically with wait-for-completion, event monitoring, tmux -CC workflows, macOS dialogs, arrangements, profiles, visual feedback, and preferences. Read this skill whenever you need to DO anything with iTerm2 — orient, send a command, check what's running, read output, set up a layout, react to events, use tmux, or configure the terminal. Don't answer iTerm2 action requests from memory — read this skill first."
---

# ita — iTerm Agent

Agent-first iTerm2 control built directly on the iTerm2 Python API. Replaces cli-anything-iterm2 entirely. Every default is the right one for an agent: clean text output, atomic operations, event-driven where possible, null bytes stripped at source.

```bash
ita <command> [OPTIONS] [ARGS]
```

---

## CRITICAL RULES

1. **Never send commands to the Claude Code session.** The active iTerm2 session is usually running Claude Code. Sending there injects text into the prompt. Always `ita status` first to identify sessions, or `ita new` to create a fresh one — `ita new` automatically sets it as the sticky target.

2. **Sticky context model.** `ita new` sets the sticky target. All subsequent commands target it by default. Override per-command with `-s SESSION_ID`, change permanently with `ita use SESSION_ID`, clear with `ita use --clear`. The sticky target is stored in `~/.ita_context`.

3. **Plain text by default. `--json` only when parsing.** Use `--json` only when you need to extract structured data (IDs, exit codes, etc.). Otherwise, plain text is much smaller in context.

4. **Null bytes are stripped at source.** You'll never see `\u0000` garbage in `ita` output — the tool handles it internally.

5. **Use `ita run` for atomic execution.** `ita run "cmd"` does send + wait for completion + return clean output in one call. Don't poll, don't chain multiple commands — `run` handles it all.

6. **Use `ita watch` / `ita wait` / `ita on *` for event-driven waiting.** All powered by ScreenStreamer and the iTerm2 notifications API. Zero polling.

---

## Orientation

```bash
ita status                      # all sessions: id | name | process | path | current*
ita status --json               # structured for parsing IDs
ita focus                       # which element has keyboard focus
ita version                     # iTerm2 app version
```

`ita status` output marks the sticky target with `*`. The first column is the short session ID — use it with `-s` to target explicitly.

---

## Session Targeting

```bash
ita use SESSION_ID              # set sticky target
ita use                         # show current sticky target
ita use --clear                 # clear sticky target
```

Every command accepts `-s SESSION_ID` to override the sticky target for that one call without changing the default.

---

## Session Lifecycle

```bash
ita new                         # new tab → sets sticky → prints session ID
ita new --window                # new window instead of tab
ita new --profile NAME          # with specific profile
ita close                       # close current/target session
ita close -s SESSION_ID         # close specific session
ita activate SESSION_ID         # focus/bring a session to front
ita name "title"                # rename current session
ita restart                     # restart current session
ita resize --cols 120 --rows 40 # resize pane in cells
ita clear                       # clear screen (Ctrl+L)
ita capture                     # print screen contents
ita capture out.txt             # save screen contents to file
```

---

## Sending Input

### `ita run` — atomic execution (the core innovation)

```bash
ita run "npm install"           # send + wait for completion + return clean output
ita run "make build" -t 120     # custom timeout (default: 30s)
ita run "ls" -n 100             # return more output lines (default: 50)
ita run "echo hello" --json     # {"output": "...", "elapsed_ms": 123}
```

Use this for any command where you want the result. It handles the entire cycle in one call.

### `ita send` — fire and forget

```bash
ita send "ls"                   # send text + newline, don't wait
ita send "cd /tmp" --raw        # no newline appended
```

### `ita inject` — raw bytes

```bash
ita inject $'\x03'              # Ctrl+C (interrupt running process)
ita inject $'\x1b'              # Escape
ita inject "03" --hex           # same as Ctrl+C, via hex
ita inject "1b5b324a" --hex     # clear screen escape sequence
```

---

## Reading Output

```bash
ita read                        # last 20 lines, stripped, clean
ita read 50                     # last 50 lines
ita read --json                 # {"lines": [...], "count": N}

ita watch                       # stream via ScreenStreamer until prompt — zero polling
ita wait                        # block until next shell prompt
ita wait --pattern "Server ready"  # block until pattern in output
ita wait -t 60                  # custom timeout

ita selection                   # get currently selected text
ita copy                        # copy selection to macOS clipboard
ita get-prompt                  # last prompt info: cwd, command, exit code
```

**`ita read` is always clean** — null bytes stripped, trailing blank lines trimmed. Prefer over `ita capture` unless you need the whole screen.

**`ita watch` uses ScreenStreamer** — the terminal pushes updates to you in real time. Exits automatically when a prompt character appears.

---

## Panes

```bash
ita split                       # horizontal split, new pane becomes sticky target
ita split -v                    # vertical split (side-by-side)
ita split --profile NAME        # split with specific profile
ita pane right                  # navigate to adjacent pane (updates sticky)
ita pane left|above|below
ita move SESSION_ID WINDOW_ID   # move pane between windows
ita move SESSION_ID WINDOW_ID --vertical
```

---

## Tabs

```bash
ita tab new                     # new tab, sets sticky target
ita tab close                   # close current tab
ita tab close TAB_ID            # close specific tab
ita tab activate TAB_ID         # focus tab
ita tab next / ita tab prev     # navigate tabs
ita tab goto 0                  # tab by index
ita tab list                    # list tabs
ita tab info                    # current tab details
ita tab info TAB_ID             # specific tab details
ita tab move                    # detach current tab into own window
ita tab title "name"            # set tab title
```

---

## Windows

```bash
ita window new                  # new window
ita window close                # close current window
ita window activate WINDOW_ID   # focus window
ita window title "name"         # set window title
ita window fullscreen on|off|toggle
ita window frame                # get position/size
ita window frame --x 0 --y 0 --w 1200 --h 800
ita window list                 # list all windows
```

---

## Saved Layouts (Arrangements)

```bash
ita save dev-workspace          # save all windows as named arrangement
ita save my-layout --window     # save current window only
ita restore dev-workspace       # restore arrangement
ita layouts                     # list all saved arrangements
```

**Pattern — project workspace setup:**
```bash
ita new                         # commands pane
ita split -v                    # server pane
ita split                       # logs pane
ita save dev-workspace          # save it
# Later:
ita restore dev-workspace       # instant workspace restore
```

---

## Profiles & Visual Feedback

```bash
ita profile list                # all profiles
ita profile show NAME           # profile details
ita profile apply NAME          # apply profile to current session
ita profile set PROPERTY VALUE  # set profile property on current session

ita presets                     # list color presets
ita theme PRESET                # apply color preset
ita theme red                   # shortcut: visual failure indicator
ita theme green                 # shortcut: success
ita theme dark / ita theme light

ita app theme                   # current UI theme (light/dark)
```

**Pattern — visual feedback on command result:**
```bash
ita run "make test" || ita theme red
ita run "make test" && ita theme green
```

---

## Variables

```bash
ita var get NAME                        # default scope: session
ita var get NAME --scope tab|window|app
ita var set NAME VALUE                  # default scope: session
ita var set NAME VALUE --scope tab|window|app
```

---

## App Control

```bash
ita app activate                # bring iTerm2 to front
ita app hide                    # minimize windows
ita app quit                    # quit iTerm2
ita app theme                   # current UI theme
```

---

## Dialogs (macOS native)

```bash
ita alert "Title" "Message"
ita alert "Deploy?" "Push to prod?" --button Yes --button No

ita ask "Title" "Message"              # text input, returns entered text
ita ask "Rename" "New name:" --default "myapp"

ita pick                        # file open dialog, returns path
ita pick --ext py --ext txt     # filter by extension
ita pick --multi                # allow multiple files

ita save-dialog                 # file save dialog
ita save-dialog --name out.txt  # pre-filled filename
```

---

## Broadcast (Sync Input to Multiple Panes)

```bash
ita broadcast on                # all panes in current window receive same input
ita broadcast on --window WINDOW_ID
ita broadcast off               # stop
ita broadcast add SID1 SID2     # group specific sessions
ita broadcast list              # current domains
```

**Pattern — set env var in all panes:**
```bash
ita broadcast on
ita send "export ENV=staging"
ita broadcast off
```

---

## Menu

```bash
ita menu list                   # list common menu item paths
ita menu "Shell/Split Vertically with Current Profile"
ita menu state "View/Enter Full Screen"
```

---

## tmux -CC Integration

tmux -CC renders each tmux window as a native iTerm2 tab — controllable via `ita`.

```bash
ita tmux start                  # bootstrap tmux -CC connection
ita tmux start --attach         # attach to existing tmux session
ita tmux connections            # list active connections
ita tmux windows                # tmux windows → iTerm2 tab IDs
ita tmux "list-sessions"        # send tmux protocol command, get output
ita tmux visible @1 off         # hide a tmux window's tab
ita tmux visible @1 on          # show it
```

---

## Preferences

```bash
ita pref get KEY
ita pref set KEY VALUE
ita pref list                   # all valid keys
ita pref list --filter tmux     # filter by substring
ita pref theme                  # current theme + is_dark
ita pref tmux                   # all tmux prefs at once
ita pref tmux set OpenWindowsIn 2
```

---

## Event Monitoring (One-Shot Wait)

All `ita on *` commands are **one-shot** — subscribe, wait for one event, print result, exit. They use the iTerm2 notifications API (push-based, zero polling).

```bash
ita on output "Server ready"    # block until pattern in session output
ita on prompt                   # block until next shell prompt
ita on session-new              # block until a new session is created
ita on session-end              # block until current session terminates
ita on focus                    # block until keyboard focus changes
ita on layout                   # block until layout changes

# All support -t / --timeout in seconds
ita on output "done" -t 300
```

---

## Advanced

```bash
ita coprocess start "log-parser.py"    # attach subprocess to session I/O
ita coprocess stop

ita annotate "this line has the bug"
ita annotate "range marker" --start 0 --end 80

ita rpc "my_function(arg=1)"           # invoke an RPC function in session context
```

---

## REPL Mode

```bash
ita repl                        # interactive mode, maintains sticky context
```

Type commands without the `ita` prefix. Maintains sticky target across all commands. Type `exit` to quit.

---

## Common Recipes

**Run a command and get its output:**
```bash
ita new
ita run "npm test"
```

**Set up a project workspace:**
```bash
ita new
ita name "commands"
ita split -v
ita name "server"
ita send "npm run dev"
ita split
ita name "logs"
ita send "tail -f logs/app.log"
ita save project-workspace
```

**Wait for a server to be ready:**
```bash
ita split
ita send "npm run dev"
ita on output "Server listening on"   # blocks until ready
```

**Visual feedback on failure:**
```bash
ita run "make test" || ita theme red
```

**Interrupt a stuck process:**
```bash
ita inject $'\x03'    # Ctrl+C
```

**Read only the last few lines of output:**
```bash
ita read 5
```

---

## Prerequisites

- macOS with iTerm2 3.6+
- iTerm2 Python API enabled: Settings → General → Magic → Enable Python API
- `uv` installed
- Shell integration (for `ita get-prompt`, `ita wait`):
  `curl -L https://iterm2.com/shell_integration/install_shell_integration.sh | bash`

---

## Implementation Notes

- `ita` is a uv inline script: `src/ita.py` with dependencies declared in the shebang
- Imports 10 modules under `src/`: `_orientation`, `_session`, `_send`, `_output`, `_layout`, `_management`, `_config`, `_interactive`, `_tmux`, `_events`
- Each module registers its commands on the shared `cli` click group from `_core`
- Sticky context persisted to `~/.ita_context`
- Built directly on the iTerm2 Python API (`iterm2` package) — no cli-anything dependency
