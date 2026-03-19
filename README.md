# Claude Code Statusline

A LazyVim lualine-style powerline statusbar for Claude Code, rendered with Catppuccin Mocha colors and true-color ANSI escape sequences.

## Example

![Claude Code Statusline](screenshot.png)

- **Line 1** — model, context window, git branch, working directory, session stats, version
- **Line 2** — API usage with 5-hour and 7-day utilization (fetched from Anthropic API)
- **Line 3** — loaded skills (only appears when skills are active in the session)

All segments use powerline arrow separators with a gradient from bright accent colors to dark backgrounds.

## Features

### Line 1: Main Status Bar

| Segment | Description |
|---------|-------------|
| **Sandbox indicator** | Lock icon when sandbox enabled, warning triangle (red) when disabled. Reads `.claude/settings.local.json` > `.claude/settings.json` > `~/.claude/settings.json` with scope precedence. |
| **Model indicator** | Active model name (OPUS/SONNET/HAIKU) with accent color — blue for Opus, mauve for Sonnet, teal for Haiku. |
| **Context window** | Percentage + visual progress bar (10 chars). Color-coded: green <50%, yellow 50-80%, red >80%. |
| **Git branch** | Current branch via `git branch --show-current`. |
| **Working directory** | CWD with `~` prefix, abbreviated to fit 30 characters (intermediate segments shortened to first char, e.g. `~/W/t/2026-03-19-statusline`). |
| **Session duration** | Elapsed time formatted as `Xh Ym`, `Xm Ys`, or `Xs`. |
| **Lines changed** | `+added -removed` from session cost data. |
| **Token counts** | Input/output tokens formatted as k/M (e.g. `125.0k/8.5k`). |
| **Version badge** | Claude Code version, accent-colored to match the model. |
| **Remote control** | "RC" badge (peach) when a `claude --remote-control` process is detected via `pgrep`. |

### Line 2: Usage Bar

| Segment | Description |
|---------|-------------|
| **Plan badge** | Detected plan tier: Pro, Max 5x, Max 20x, Teams Standard, Teams Premium, Free, or API. |
| **5-hour utilization** | Percentage with color coding + reset countdown (e.g. `5h 42%`, `↻ 3h 22m`). |
| **7-day utilization** | Percentage with color coding + reset countdown (e.g. `7d 12%`, `↻ 1d 17h`). |

Usage data details:
- Credentials read from **macOS Keychain** (service `Claude Code-credentials`) or `.credentials.json` on Linux
- Cached with **5-minute TTL** to reduce API calls
- **429 backoff**: 10-minute cooldown on rate limit errors (stale values shown with `~` prefix)
- **Multi-account support**: cache and keychain service keyed by `CLAUDE_CONFIG_DIR`

### Line 3: Skills Bar

| Segment | Description |
|---------|-------------|
| **SKILLS label** | Header badge, always shown when skills are loaded. |
| **Skill names** | Alternating Surface1/Surface0 backgrounds for readability. |
| **Overflow indicator** | `+N` when too many skills to fit terminal width. |

Skills are extracted from the session transcript file by scanning for skill loading markers. Cached by file mtime+size to avoid re-scanning unchanged transcripts.

### Cross-cutting

- **Catppuccin Mocha palette** — full 24-color theme (Mantle through Rosewater)
- **Powerline rendering** — right arrows (``) for left segments, left arrows (``) for right-aligned segments
- **Terminal width detection** — tries stdio fds 2/1/0, then `/dev/tty` via `ioctl`, then process tree walk for subprocess contexts
- **ANSI true-color** — 24-bit RGB escape sequences (`\033[38;2;R;G;Bm`)

## Requirements

- Python 3.6+
- A terminal with true-color (24-bit) support
- A [Nerd Font](https://www.nerdfonts.com/) for powerline separators and icons
- `git` on PATH (for branch detection)
- `pgrep` on PATH (for remote control detection)
- macOS Keychain access (for usage data on macOS) or `.credentials.json` (Linux)

No third-party Python packages required — uses only the standard library.

## Installation

Add to your Claude Code settings (`~/.claude/settings.json` or project `.claude/settings.json`):

```json
{
  "statusLine": {
    "type": "command",
    "command": "/path/to/statusline.py",
    "padding": 2
  }
}
```

Make the script executable:

```bash
chmod +x statusline.py
```

## Testing / Previewing

Run the script manually with mock JSON on stdin:

```bash
echo '{"model":{"display_name":"Opus"},"context_window":{"used_percentage":45,"total_input_tokens":125000,"total_output_tokens":8500},"workspace":{"current_dir":"/Users/you/project"},"version":"1.0.30","cost":{"total_duration_ms":360000,"total_lines_added":42,"total_lines_removed":7}}' | python3 statusline.py
```

Notes:
- Line 2 (usage) fetches real API data from your Keychain credentials, so values will vary
- Line 3 (skills) only appears when `transcript_path` is provided and contains skill markers
- Sandbox indicator reflects your actual `.claude/settings*.json` files in the mock CWD

## Configuration

| Environment Variable | Purpose |
|---------------------|---------|
| `CLAUDE_CONFIG_DIR` | Override the Claude config directory (default: `~/.claude`). Affects keychain service name, credential file path, and usage cache path. |
| `HOME` | Used to abbreviate CWD with `~` prefix. |
| `COLUMNS` | Fallback terminal width when no tty is available (default: 80). |

### Settings File Precedence (Sandbox)

The sandbox indicator reads from settings files in this order (first match wins):

1. `<cwd>/.claude/settings.local.json` — local project (highest priority)
2. `<cwd>/.claude/settings.json` — shared project
3. `~/.claude/settings.json` — user global (lowest priority)

## How It Works

```
stdin (JSON) → parse fields → build segments → render powerline → stdout (ANSI)
```

1. Claude Code pipes a JSON object to stdin on each status update
2. The script parses model info, context window stats, workspace, version, and cost data
3. Three lines of powerline segments are built with the Catppuccin Mocha color palette
4. Left segments use right-pointing arrows (``) and right segments use left-pointing arrows (``)
5. Lines are right-aligned using terminal width detection
6. Usage data (line 2) is fetched from `api.anthropic.com` with caching and backoff
7. Skills (line 3) are scanned from the transcript file with mtime-based caching
8. Rendered ANSI output is printed to stdout

## Input JSON Reference

The script reads the following fields from the JSON object piped to stdin:

```json
{
  "model": {
    "display_name": "Opus"          // Model name — used for label and accent color
  },
  "context_window": {
    "used_percentage": 45,           // Context window usage (0-100)
    "total_input_tokens": 125000,    // Total input tokens consumed
    "total_output_tokens": 8500      // Total output tokens consumed
  },
  "workspace": {
    "current_dir": "/Users/you/project"  // Absolute working directory path
  },
  "version": "1.0.30",              // Claude Code version string
  "cost": {
    "total_duration_ms": 360000,     // Session duration in milliseconds
    "total_lines_added": 42,         // Lines added during session
    "total_lines_removed": 7         // Lines removed during session
  },
  "transcript_path": "/path/to/transcript.jsonl"  // Session transcript (for skills detection)
}
```

All fields are optional — the script gracefully handles missing data with sensible defaults.
