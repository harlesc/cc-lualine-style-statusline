# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Optional sandbox indicator. The leftmost sandbox icon can now be hidden via
  config: set `CLAUDE_STATUSLINE_SANDBOX` to `false`/`0`/`off` (recommended via
  the `env` block in `settings.json`), or add `{"show_sandbox": false}` to
  `~/.claude/statusline.json`. The env var wins over the file; the icon is shown
  by default. When hidden, sandbox detection is skipped entirely.

- Effort level badge on line 1, shown right of the model name and before the
  context window. Reads the `effort.level` field from the statusline JSON
  (`low`/`medium`/`high`/`xhigh`). Rendered as a uniform dark chip — Text
  (`#cdd6f4`) on Surface0 (`#313244`) — so it stays distinct from the colored
  model badge; the level word carries the meaning. The badge is hidden when the
  current model doesn't support reasoning effort.
- Companion subagent status line (`subagent-statusline.py`). This is a *separate*
  Claude Code feature from the main `statusLine` — it is wired via the
  `subagentStatusLine` setting and renders a custom row body for each subagent
  shown in the agent panel below the prompt (not the main status bar). It reuses
  the same Catppuccin Mocha palette and powerline styling and shows, per
  subagent: model name (accent-colored, e.g. `OPUS 4.8`), effort level, and
  context-window usage (`NN%`, green/yellow/red at the 50/80 thresholds),
  followed by the task's label/description. Unlike the main statusline, the
  input is a `tasks` array and the output is one JSON line per row
  (`{"id": ..., "content": ...}`). Chips degrade gracefully when fields are
  absent (model not yet resolved, or effort inherited from the session).
  Requires Claude Code v2.1.205+ for `model`/`contextWindowSize` and v2.1.214+
  for `effort`. Enable by adding a `subagentStatusLine` block to
  `settings.json` (see README).

- Subagent status line now shows the agent **name first**, resolved to the real
  agent type (`Explore`, `claude-code-guide`, `general-purpose`, or a custom
  `.claude/agents/*.md` name). Field semantics were confirmed by capturing real
  subagent payloads: the per-task `type` field is a generic transport label
  that is `local_agent` for *every* agent kind, so it can't name the agent;
  `label` is a rolling *activity* string (not a name); `description` is a stable
  task title; and `name` is absent for normal Task subagents. Because no
  per-task field carries the real name, the script reads the session
  `transcript_path` and joins a `Task`/`Agent` `tool_use`'s
  `input.subagent_type` to its `tool_result`'s `toolUseResult.agentId`
  (== the per-task `id`) to map each task to its real `subagent_type`. This
  mapping is cached in `~/.cache/claude-statusline/agenttypes-<hash>.json` by
  transcript mtime+size, with a substring pre-filter so only relevant lines are
  parsed. The row falls back to `type` when the spawn isn't in the transcript
  yet, uses `description` as the trailing title (falling back to the live
  `label` activity), never renders `label` as identity, and shows `name ↳ agent`
  if a distinct instance `name` ever appears. Added a
  `CLAUDE_SUBAGENT_STATUSLINE_DEBUG` env var (append each raw stdin payload to a
  file) that was used to confirm all of this.

