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
