#!/usr/bin/env python3
"""Custom subagent status-line for Claude Code.

Renders each subagent row in the agent panel (below the prompt) with a compact
powerline chip group showing MODEL, effort level, and context-window usage,
followed by the task's label/description.

Input (stdin): a single JSON object with base hook fields, a `columns` field,
and a `tasks` array. Each task has: id, name, type, status, description, label,
startTime, model, effort, contextWindowSize, tokenCount, tokenSamples, cwd.
  - `model` / `contextWindowSize` require Claude Code v2.1.205+ (omitted until
    the task's model is resolved).
  - `effort` requires v2.1.214+ and is absent when the subagent inherits the
    session's effort level.

Output (stdout): one JSON line per row to override, `{"id": ..., "content": ...}`.
`content` is rendered as-is (ANSI colors supported). Omitting a task's id keeps
its default rendering; an empty content string hides the row.
"""
import hashlib
import json
import os
import re
import sys
import unicodedata

# ── Catppuccin Mocha palette (R, G, B) ───────────────────────────────────────
P = {
    "Mantle":   (24, 24, 37),
    "Base":     (30, 30, 46),
    "Surface0": (49, 50, 68),
    "Surface1": (69, 71, 90),
    "Overlay0": (108, 112, 134),
    "Overlay1": (127, 132, 156),
    "Subtext0": (166, 173, 200),
    "Subtext1": (186, 194, 222),
    "Text":     (205, 214, 244),
    "Blue":     (137, 180, 250),
    "Teal":     (148, 226, 213),
    "Green":    (166, 227, 161),
    "Yellow":   (249, 226, 175),
    "Red":      (243, 139, 168),
    "Mauve":    (203, 166, 247),
}

# ── ANSI helpers ─────────────────────────────────────────────────────────────
RST = "\033[0m"
BOLD = "\033[1m"
SEP = "\ue0b0"  # Powerline right arrow

def fg(rgb):
    r, g, b = rgb
    return f"\033[38;2;{r};{g};{b}m"

def bg(rgb):
    r, g, b = rgb
    return f"\033[48;2;{r};{g};{b}m"

_ANSI_RE = re.compile(r'\033\[[^m]*m')

def _char_width(c):
    return 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1

def visible_len(s):
    stripped = _ANSI_RE.sub('', s)
    return sum(_char_width(c) for c in stripped)

def render_powerline(segments, tail_bg=None):
    """Render (text, fg_rgb, bg_rgb, bold?) tuples with right-pointing arrows."""
    out = []
    for i, seg in enumerate(segments):
        text, fg_col, bg_col = seg[0], seg[1], seg[2]
        is_bold = seg[3] if len(seg) > 3 else False
        style = (f"{fg(fg_col)}{bg(bg_col)}" if fg_col is not None else bg(bg_col))
        if is_bold:
            style += BOLD
        out.append(f"{style}{text}{RST}")
        if i < len(segments) - 1:
            next_bg = segments[i + 1][2]
            out.append(f"{fg(bg_col)}{bg(next_bg)}{SEP}{RST}")
        else:
            tail = bg(tail_bg) if tail_bg else ""
            out.append(f"{fg(bg_col)}{tail}{SEP}{RST}")
    return "".join(out)

# ── Model id → friendly name + accent ────────────────────────────────────────
def model_family(model_id):
    """Return (label, accent) from a resolved model id like 'claude-opus-4-8'."""
    mid = (model_id or "").lower()
    if "opus" in mid:
        fam, accent = "Opus", P["Blue"]
    elif "sonnet" in mid:
        fam, accent = "Sonnet", P["Mauve"]
    elif "haiku" in mid:
        fam, accent = "Haiku", P["Teal"]
    elif "fable" in mid:
        fam, accent = "Fable", P["Green"]
    else:
        return (model_id.upper() if model_id else "CLAUDE"), P["Green"]
    # Collect up to two short numeric version tokens (skip long date-like tokens).
    ver = [t for t in re.split(r'[-_.]', mid) if t.isdigit() and len(t) <= 2][:2]
    label = f"{fam} {'.'.join(ver)}".strip() if ver else fam
    return label, accent

def pct_color(val):
    if val is None:
        return P["Overlay1"]
    if val > 80:
        return P["Red"]
    if val >= 50:
        return P["Yellow"]
    return P["Green"]

def effort_label(effort):
    """Normalise the effort field (string level or numeric token budget)."""
    if effort is None or effort == "":
        return ""
    if isinstance(effort, (int, float)):
        n = int(effort)
        return f"{n // 1000}k" if n >= 1000 else str(n)
    return str(effort).upper()

def _norm(s):
    return re.sub(r"[\s_-]+", "", (s or "").strip().lower())

# ── Resolve the real agent type from the session transcript ───────────────────
# The per-task `type` field is a generic transport label ("local_agent") — it is
# the SAME for Explore, claude-code-guide, general-purpose, etc., so it can't
# name the agent. The real `subagent_type` lives in the session transcript: a
# Task/Agent `tool_use` carries `input.subagent_type`, and its `tool_result`
# entry carries `toolUseResult.agentId` (== the per-task `id`). Joining those
# maps a task id to its real agent name. Cached by transcript mtime+size.
def _cache_dir():
    xdg = os.environ.get("XDG_CACHE_HOME", "")
    base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".cache")
    d = os.path.join(base, "claude-statusline")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d

def resolve_agent_types(tpath):
    """Return {agentId: subagent_type} parsed from the transcript, cached."""
    if not tpath or not os.path.isfile(tpath):
        return {}
    try:
        st = os.stat(tpath)
        cache_key = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return {}
    cache_file = os.path.join(
        _cache_dir(), f"agenttypes-{hashlib.md5(tpath.encode()).hexdigest()}.json")
    try:
        with open(cache_file) as f:
            cached = json.load(f)
        if cached.get("key") == cache_key:
            return cached.get("map", {})
    except Exception:
        pass

    tooluse_type = {}   # tool_use_id -> subagent_type
    agent_tooluse = {}  # agentId    -> tool_use_id
    try:
        with open(tpath) as f:
            for line in f:
                # Cheap pre-filter: only parse lines that can contribute.
                if "subagent_type" not in line and "agentId" not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                msg = d.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                if isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "tool_use" and b.get("name") in ("Task", "Agent"):
                            st_ = (b.get("input") or {}).get("subagent_type")
                            if st_:
                                tooluse_type[b.get("id")] = st_
                        elif b.get("type") == "tool_result":
                            tur = d.get("toolUseResult")
                            aid = tur.get("agentId") if isinstance(tur, dict) else None
                            if aid:
                                agent_tooluse[aid] = b.get("tool_use_id")
    except Exception:
        return {}

    result = {aid: tooluse_type.get(tuid)
              for aid, tuid in agent_tooluse.items() if tooluse_type.get(tuid)}
    try:
        with open(cache_file, "w") as f:
            json.dump({"key": cache_key, "map": result}, f)
    except Exception:
        pass
    return result

# ── Build one row's content ───────────────────────────────────────────────────
def render_task(task, columns, agent_types):
    model_id = task.get("model")
    model_label, accent = model_family(model_id)

    segs = []

    # Identity — agent name first.
    # `agent_types` maps this task's id to its real `subagent_type` from the
    # transcript (e.g. "Explore", "claude-code-guide"). The per-task `type` is a
    # generic label ("local_agent") — identical across agent kinds — so it's
    # only a fallback when the transcript hasn't recorded the spawn yet.
    # Other confirmed fields: `label` = rolling activity (never shown as a
    # name), `description` = stable task title (trailing text), `name` = absent
    # for normal subagents (shown as `name ↳ agent` if it ever appears).
    defn = (agent_types.get(task.get("id")) or task.get("type") or "").strip()
    name = (task.get("name") or "").strip()
    inst = name if name and _norm(name) != _norm(defn) else ""
    primary = inst or defn
    if primary:
        segs.append((f" {primary} ", P["Text"], P["Surface1"], True))
    if inst and defn:
        segs.append((f" ↳ {defn} ", P["Subtext0"], P["Surface0"]))

    # MODEL — bright accent anchor (omitted if model not yet resolved)
    if model_id:
        segs.append((f" {model_label.upper()} ", P["Mantle"], accent, True))

    # Effort — uniform dark chip (absent when inheriting the session's effort)
    eff = effort_label(task.get("effort"))
    if eff:
        segs.append((f" {eff} ", P["Text"], P["Surface0"]))

    # Context-window usage — % of the task's own window
    ctx_size = task.get("contextWindowSize") or 0
    tokens = task.get("tokenCount") or 0
    if ctx_size:
        pct = round(tokens / ctx_size * 100)
        segs.append((f" {pct}% ", pct_color(pct), P["Surface1"]))

    chips = render_powerline(segs) if segs else ""

    # Trailing text: the task description (a stable title). Fall back to the
    # live `label` activity string only when there's no description. Collapse
    # any newlines (activity strings can be multi-line) before truncating.
    tail = (task.get("description") or task.get("label") or "").strip()
    tail = re.sub(r"\s+", " ", tail)

    if tail:
        budget = max(0, (columns or 80) - visible_len(chips) - 1)
        if visible_len(tail) > budget:
            tail = tail[:max(0, budget - 1)].rstrip() + "…"
        sep = " " if chips else ""
        tail = f"{sep}{fg(P['Subtext0'])}{tail}{RST}"
    else:
        tail = ""

    return chips + tail

def _debug_dump(raw):
    """When CLAUDE_SUBAGENT_STATUSLINE_DEBUG is set, append each raw stdin
    payload to that path so the real field values can be inspected. This is the
    reliable way to confirm name/type/label semantics, which the docs leave
    unspecified. No-op (never raises) when unset or unwritable."""
    import os
    path = os.environ.get("CLAUDE_SUBAGENT_STATUSLINE_DEBUG", "").strip()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(raw.rstrip("\n") + "\n")
    except Exception:
        pass

def main():
    raw = sys.stdin.read()
    _debug_dump(raw)
    try:
        data = json.loads(raw)
    except Exception:
        return
    columns = data.get("columns") or 80
    agent_types = resolve_agent_types(data.get("transcript_path", ""))
    for task in data.get("tasks", []) or []:
        tid = task.get("id")
        if not tid:
            continue
        content = render_task(task, columns, agent_types)
        sys.stdout.write(json.dumps({"id": tid, "content": content}) + "\n")

if __name__ == "__main__":
    main()
