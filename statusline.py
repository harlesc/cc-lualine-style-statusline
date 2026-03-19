#!/usr/bin/env python3
"""LazyVim lualine-style powerline statusline for Claude Code.

Renders two or three lines with Catppuccin Mocha colors and powerline arrow separators.
"""
import fcntl, hashlib, json, os, re, struct, subprocess, sys, termios, time, unicodedata
from datetime import datetime, timezone
from urllib.request import Request, urlopen

def _is_remote_control_active():
    """Check if Claude Code remote control is active by looking for the process."""
    try:
        result = subprocess.check_output(
            ["pgrep", "-f", "claude.*remote-control"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        return bool(result)
    except Exception:
        return False


def get_sandbox_state():
    """Read sandbox enabled state from settings files, respecting scope precedence.
    Precedence (highest to lowest): local project > shared project > user
    Returns True if sandbox is enabled, False otherwise.
    """
    import os, json

    def read_sandbox(path):
        try:
            with open(os.path.expanduser(path)) as f:
                return json.load(f).get("sandbox", {}).get("enabled")
        except Exception:
            return None

    cwd = os.getcwd()
    for path in [
        os.path.join(cwd, ".claude/settings.local.json"),  # highest: local project
        os.path.join(cwd, ".claude/settings.json"),         # shared project
        "~/.claude/settings.json",                          # lowest: user global
    ]:
        val = read_sandbox(path)
        if val is not None:
            return val
    return False  # default: not enabled


# ── Catppuccin Mocha palette (R, G, B) ──────────────────────────────────────
P = {
    "Mantle":   (24, 24, 37),
    "Base":     (30, 30, 46),
    "Surface0": (49, 50, 68),
    "Surface1": (69, 71, 90),
    "Surface2": (88, 91, 112),
    "Overlay0": (108, 112, 134),
    "Overlay1": (127, 132, 156),
    "Subtext0": (166, 173, 200),
    "Subtext1": (186, 194, 222),
    "Text":     (205, 214, 244),
    "Lavender": (180, 190, 254),
    "Blue":     (137, 180, 250),
    "Sapphire": (116, 199, 236),
    "Sky":      (137, 220, 235),
    "Teal":     (148, 226, 213),
    "Green":    (166, 227, 161),
    "Yellow":   (249, 226, 175),
    "Peach":    (250, 179, 135),
    "Maroon":   (235, 160, 172),
    "Red":      (243, 139, 168),
    "Mauve":    (203, 166, 247),
    "Pink":     (245, 194, 231),
    "Flamingo": (242, 205, 205),
    "Rosewater":(245, 224, 220),
}

# ── ANSI helpers ─────────────────────────────────────────────────────────────
RST = "\033[0m"

def fg(rgb):
    r, g, b = rgb
    return f"\033[38;2;{r};{g};{b}m"

def bg(rgb):
    r, g, b = rgb
    return f"\033[48;2;{r};{g};{b}m"

BOLD = "\033[1m"
SEP = "\ue0b0"  # Powerline right arrow
SEP_REV = "\ue0b2"  # Powerline left arrow (reverse)

_ANSI_RE = re.compile(r'\033\[[^m]*m')

def _char_width(c):
    """Return display width of a character using Unicode East Asian Width."""
    return 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1

def visible_len(s):
    """Return the display column width of a string, stripping ANSI escapes."""
    stripped = _ANSI_RE.sub('', s)
    return sum(_char_width(c) for c in stripped)

# ── Segment rendering ────────────────────────────────────────────────────────

def render_powerline(segments, tail_bg=None):
    """Render a list of (text, fg_rgb, bg_rgb, bold?) tuples with powerline arrows."""
    out = []
    for i, seg in enumerate(segments):
        text, fg_col, bg_col = seg[0], seg[1], seg[2]
        is_bold = seg[3] if len(seg) > 3 else False

        # Segment content
        if fg_col is not None:
            style = f"{fg(fg_col)}{bg(bg_col)}"
        else:
            style = f"{bg(bg_col)}"
        if is_bold:
            style += BOLD
        out.append(f"{style}{text}{RST}")

        # Separator: fg = this segment's bg, bg = next segment's bg (or tail_bg)
        if i < len(segments) - 1:
            next_bg = segments[i + 1][2]
            out.append(f"{fg(bg_col)}{bg(next_bg)}{SEP}{RST}")
        else:
            tail = bg(tail_bg) if tail_bg else ""
            out.append(f"{fg(bg_col)}{tail}{SEP}{RST}")

    return "".join(out)


def render_powerline_reverse(segments, head_bg=None):
    """Render segments with left-pointing powerline arrows (right-section lualine style)."""
    out = []
    for i, seg in enumerate(segments):
        text, fg_col, bg_col = seg[0], seg[1], seg[2]
        is_bold = seg[3] if len(seg) > 3 else False

        # Arrow before segment: fg = this segment's bg, bg = previous segment's bg (or head_bg)
        if i == 0:
            head = bg(head_bg) if head_bg else ""
            out.append(f"{fg(bg_col)}{head}{SEP_REV}{RST}")
        else:
            prev_bg = segments[i - 1][2]
            out.append(f"{fg(bg_col)}{bg(prev_bg)}{SEP_REV}{RST}")

        # Segment content
        if fg_col is not None:
            style = f"{fg(fg_col)}{bg(bg_col)}"
        else:
            style = f"{bg(bg_col)}"
        if is_bold:
            style += BOLD
        out.append(f"{style}{text}{RST}")

    return "".join(out)


def _get_terminal_cols():
    """Get terminal width even when all fds are piped (Claude Code subprocess).

    Walks up the process tree via /proc to find an ancestor with a real tty,
    then queries its terminal size directly.
    """
    # Fast path: try standard fds
    for fd_num in (2, 1, 0):
        try:
            return os.get_terminal_size(fd_num).columns
        except (OSError, ValueError):
            pass
    # macOS / any POSIX: open /dev/tty directly (works in subprocess contexts)
    try:
        fd = os.open("/dev/tty", os.O_RDONLY | os.O_NOCTTY)
        try:
            result = fcntl.ioctl(fd, termios.TIOCGWINSZ, b'\x00' * 8)
            cols = struct.unpack('HHHH', result)[1]
            if cols > 0:
                return cols
        finally:
            os.close(fd)
    except OSError:
        pass
    # Walk up the process tree to find an ancestor with a real tty
    try:
        pid = os.getpid()
        for _ in range(16):  # max depth to avoid infinite loop
            pid = int(open(f"/proc/{pid}/stat").read().split()[3])  # ppid
            if pid <= 1:
                break
            for fd_name in ("0", "1", "2"):
                try:
                    tty_path = os.readlink(f"/proc/{pid}/fd/{fd_name}")
                except OSError:
                    continue
                if not tty_path.startswith("/dev/"):
                    continue
                try:
                    fd = os.open(tty_path, os.O_RDONLY | os.O_NOCTTY)
                    try:
                        result = fcntl.ioctl(fd, termios.TIOCGWINSZ, b'\x00' * 8)
                        return struct.unpack('HHHH', result)[1]
                    finally:
                        os.close(fd)
                except OSError:
                    continue
    except (OSError, ValueError):
        pass
    return int(os.environ.get("COLUMNS", 80))


def render_two_groups(left, right, right_align=False, right_renderer=None, gap_bg=None):
    """Render left and right segment groups separated by a gap.

    If right_align=True, pad with spaces to push the right group flush-right.
    right_renderer overrides render_powerline for the right group (e.g. reverse arrows).
    gap_bg fills the gap between groups with a background color.
    """
    right_render = right_renderer or render_powerline
    left_str = render_powerline(left, tail_bg=gap_bg) if left else ""
    if right:
        if right_renderer:
            right_str = right_renderer(right, head_bg=gap_bg)
        else:
            right_str = render_powerline(right, tail_bg=gap_bg)
    else:
        right_str = ""

    if right_align:
        cols = _get_terminal_cols() - 5
        gap = cols - visible_len(left_str) - visible_len(right_str)
        gap_str = " " * max(gap, 2)
        if gap_bg:
            gap_str = f"{bg(gap_bg)}{gap_str}{RST}"
        return left_str + gap_str + right_str
    else:
        gap_str = "  "
        if gap_bg:
            gap_str = f"{bg(gap_bg)}{gap_str}{RST}"
        return left_str + gap_str + right_str


def _abbreviate_cwd(path, max_len):
    """Abbreviate intermediate path segments to first char to fit max_len.

    e.g. ~/Work/tries/2026-02-28-statusline → ~/W/t/2026-02-28-statusline
    """
    if len(path) <= max_len:
        return path
    # Split into segments, preserve ~ prefix
    if path.startswith("~/"):
        prefix = "~"
        rest = path[2:]
    elif path.startswith("/"):
        prefix = ""
        rest = path[1:]
    else:
        prefix = ""
        rest = path
    parts = rest.split("/")
    if len(parts) <= 1:
        return path
    # Always keep the last segment intact, abbreviate from the left
    for i in range(len(parts) - 1):
        if len(prefix + "/" + "/".join(parts)) <= max_len:
            break
        if parts[i]:
            parts[i] = parts[i][0]
    result = prefix + "/" + "/".join(parts)
    return result


# ── Parse input JSON ─────────────────────────────────────────────────────────
data = json.load(sys.stdin)
ctx = data.get("context_window", {})
pct = ctx.get("used_percentage")
total_in = ctx.get("total_input_tokens", 0) or 0
total_out = ctx.get("total_output_tokens", 0) or 0
model_name = data.get("model", {}).get("display_name", "")
cwd = data.get("workspace", {}).get("current_dir", "")
ver = data.get("version", "")
cost = data.get("cost", {})
total_dur_ms = cost.get("total_duration_ms", 0) if cost else 0
lines_added = cost.get("total_lines_added", 0) if cost else 0
lines_removed = cost.get("total_lines_removed", 0) if cost else 0
transcript_path = data.get("transcript_path", "")

# Detect remote control
_rc_active = _is_remote_control_active()

# Detect sandbox state
_sandbox_on = get_sandbox_state()
if _sandbox_on:
    _sandbox_fg = P["Green"]
    _sandbox_label = " \uf023 "   # Nerd Font lock icon
else:
    _sandbox_fg = P["Red"]
    _sandbox_label = " \uf071 "   # Nerd Font warning triangle

# Shorten home dir
cwd = cwd.replace(os.environ.get("HOME", ""), "~", 1)
cwd = _abbreviate_cwd(cwd, 30)

# Git branch
branch = ""
try:
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        stderr=subprocess.DEVNULL, text=True
    ).strip()
except Exception:
    pass

# Format token counts
def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)

# Format duration
def fmt_duration(ms):
    if not ms:
        return "0s"
    secs = int(ms / 1000)
    if secs >= 3600:
        h, rem = divmod(secs, 3600)
        m = rem // 60
        return f"{h}h{m}m"
    if secs >= 60:
        m, s = divmod(secs, 60)
        return f"{m}m{s}s"
    return f"{secs}s"

# ── Model accent color ───────────────────────────────────────────────────────
model_lower = model_name.lower()
if "opus" in model_lower:
    model_accent = P["Blue"]
elif "sonnet" in model_lower:
    model_accent = P["Mauve"]
elif "haiku" in model_lower:
    model_accent = P["Teal"]
else:
    model_accent = P["Green"]

# Context % dynamic color
def pct_color(val):
    if val is None:
        return P["Overlay1"]
    if val > 80:
        return P["Red"]
    if val >= 50:
        return P["Yellow"]
    return P["Green"]

# ── Line 1: Main bar ────────────────────────────────────────────────────────
# Layout: MODEL → progress bar → branch → cwd  ...  duration → version
# Gradient: accent → Surface1 → Surface0 → Base (bright to dark, left to right)
left1 = []

# Sandbox indicator — leftmost anchor
left1.append((_sandbox_label, model_accent if _sandbox_on else P["Red"], P["Base"], True))

# Model — bright accent anchor
model_label = model_name.upper() if model_name else "CLAUDE"
left1.append((f" {model_label} ", P["Mantle"], model_accent, True))

# Context progress bar — thin line style on Surface1
pct_val = pct if pct is not None else 0
pct_str = f"{pct}%" if pct is not None else "--"
bar_w = 10
filled = round(pct_val / 100 * bar_w)
bar_text = (
    f"{fg(P['Subtext1'])} {pct_str} "
    f"{fg(P['Green'])}{'\u2501' * filled}"
    f"{fg(P['Overlay0'])}{'\u2501' * (bar_w - filled)} "
)
left1.append((bar_text, None, P["Surface1"]))

# Git branch + CWD — smooth gradient step-down
if branch:
    left1.append((f" \ue0a0 {branch} ", P["Lavender"], P["Surface0"]))
    if cwd:
        left1.append((f" {cwd} ", P["Subtext0"], P["Base"]))
elif cwd:
    left1.append((f" {cwd} ", P["Subtext0"], P["Surface0"]))

# Build right segments (text + fg only), then assign gradient backgrounds
# Gradient (left to right): darkest → brightest → accent
right1_raw = []

# Duration — always present
dur_str = fmt_duration(total_dur_ms)
right1_raw.append((f" \u25f7 {dur_str} ", P["Subtext0"], False))

# Lines changed
if lines_added or lines_removed:
    right1_raw.append((f" \ue0a0 +{lines_added} -{lines_removed} ", P["Green"], False))

# Tokens
if total_in or total_out:
    right1_raw.append((f" 󰈙 {fmt_tokens(total_in)}/{fmt_tokens(total_out)} ", P["Overlay1"], False))

# Version — rightmost (accent bg, mirrors model on left)
if ver:
    right1_raw.append((f" 󰏗 {ver} ", P["Mantle"], True))

# Remote Control indicator — rightmost, distinct color
if _rc_active:
    right1_raw.append((" 󰑔 RC ", P["Mantle"], True))

# Assign gradient backgrounds dynamically based on segment count
gradient_bgs = [P["Base"], P["Surface0"], P["Surface1"]]
n = len(right1_raw)
right1 = []
for i, (text, fg_col, is_bold) in enumerate(right1_raw):
    if _rc_active and i == n - 1:
        right1.append((text, fg_col, P["Peach"], is_bold))
    elif ver and ((_rc_active and i == n - 2) or (not _rc_active and i == n - 1)):
        right1.append((text, fg_col, model_accent, is_bold))
    else:
        bg_idx = min(i, len(gradient_bgs) - 1)
        right1.append((text, fg_col, gradient_bgs[bg_idx], is_bold))

line1 = render_two_groups(left1, right1, right_align=True,
    right_renderer=render_powerline_reverse, gap_bg=P["Base"])

# ── Usage logic (line 2) ────────────────────────────────────────────────────
def _keychain_service_name():
    """Derive the macOS Keychain service name for the active CLAUDE_CONFIG_DIR.

    Claude Code uses "Claude Code-credentials" for the default config dir (~/.claude)
    and appends a hash suffix for non-default dirs, e.g. "Claude Code-credentials-72a2d2c1".
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "")
    if not config_dir:
        return "Claude Code-credentials"
    config_dir = os.path.expanduser(config_dir)
    default_dir = os.path.expanduser("~/.claude")
    if os.path.realpath(config_dir) == os.path.realpath(default_dir):
        return "Claude Code-credentials"
    suffix = hashlib.sha256(config_dir.encode()).hexdigest()[:8]
    return f"Claude Code-credentials-{suffix}"


def _cache_dir():
    """Return a user-private cache directory (mode 700), respecting XDG on Linux."""
    xdg = os.environ.get("XDG_CACHE_HOME", "")
    base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".cache")
    d = os.path.join(base, "claude-statusline")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _cache_path():
    """Per-account usage cache path, keyed by CLAUDE_CONFIG_DIR."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "")
    if config_dir:
        suffix = hashlib.sha256(os.path.expanduser(config_dir).encode()).hexdigest()[:8]
        return os.path.join(_cache_dir(), f"usage-{suffix}.json")
    return os.path.join(_cache_dir(), "usage.json")


CACHE_TTL = 300  # 5 minutes — reduces frequency of API calls → fewer 429s


def _read_credentials_raw():
    if sys.platform == "darwin":
        svc = _keychain_service_name()
        raw = subprocess.check_output(
            ["security", "find-generic-password",
             "-s", svc,
             "-a", os.environ.get("USER", ""), "-w"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        return json.loads(raw)
    else:
        config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "")
        if config_dir:
            cred_path = os.path.join(
                os.path.expanduser(config_dir), ".credentials.json"
            )
        else:
            cred_path = os.path.join(
                os.path.expanduser("~"), ".claude", ".credentials.json"
            )
        with open(cred_path) as f:
            return json.load(f)


def get_credentials_info():
    creds = _read_credentials_raw()
    oauth = creds.get("claudeAiOauth", {})
    token = oauth.get("accessToken", "")
    tier = oauth.get("rateLimitTier", "")
    sub = oauth.get("subscriptionType", "").lower()

    if "team" in tier or "team" in sub:
        if "premium" in tier or "premium" in sub or "5x" in tier:
            plan = "Teams Premium"
        else:
            plan = "Teams Standard"
    elif "20x" in tier:
        plan = "Max 20x"
    elif "5x" in tier:
        plan = "Max 5x"
    elif sub == "pro":
        plan = "Pro"
    elif sub == "max":
        plan = "Max"
    elif sub == "free":
        plan = "Free"
    elif sub:
        plan = sub.capitalize()
    else:
        plan = "API"

    return token, plan


def fetch_usage(token):
    req = Request("https://api.anthropic.com/api/oauth/usage")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("anthropic-beta", "oauth-2025-04-20")
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def load_cache():
    try:
        with open(_cache_path()) as f:
            return json.load(f)
    except Exception:
        return None


def save_cache(data, plan):
    try:
        with open(_cache_path(), "w") as f:
            json.dump({"ts": time.time(), "data": data, "plan": plan}, f)
    except Exception:
        pass


def get_usage():
    cached = load_cache()
    now = time.time()

    # Honour 429 backoff
    if cached and now < cached.get("retry_after", 0):
        return cached["data"], cached.get("plan", ""), True  # stale=True

    if cached and now - cached.get("ts", 0) < CACHE_TTL:
        return cached["data"], cached.get("plan", ""), False

    try:
        token, plan = get_credentials_info()
        usage = fetch_usage(token)
        save_cache(usage, plan)
        return usage, plan, False
    except Exception as e:
        if cached:
            if "429" in str(e) or "Too Many" in str(e):
                # Back off 10 minutes
                cached["retry_after"] = now + 600
                try:
                    with open(_cache_path(), "w") as f:
                        json.dump(cached, f)
                except Exception:
                    pass
            return cached["data"], cached.get("plan", ""), True
        return None, "", False


def fmt_remaining(resets_at):
    reset = datetime.fromisoformat(resets_at)
    now = datetime.now(timezone.utc)
    mins = max(0, int((reset - now).total_seconds() / 60))
    if mins >= 1440:
        d, h = divmod(mins, 1440)
        return f"{d}d {h // 60}h"
    if mins >= 60:
        h, m = divmod(mins, 60)
        return f"{h}h {m}m"
    return f"{mins}m"


# ── Line 2: Usage bar ───────────────────────────────────────────────────────
usage, plan, stale = get_usage()
line2 = ""
if usage:
    try:
        fh = usage["five_hour"]
        sd = usage["seven_day"]

        left2 = []
        right2 = []

        # Plan badge — accent anchor (mirrors model on line 1)
        if plan:
            left2.append((f" \u25c6 {plan} ", P["Mauve"], P["Surface1"], True))

        # 5h usage
        fh_util = fh["utilization"]
        fh_color = P["Overlay0"] if stale else pct_color(fh_util)
        fh_label = "~5h" if stale else "5h"
        left2.append((f" {fh_label} {fh_util:.0f}% ", fh_color, P["Surface0"]))

        # 5h reset
        left2.append((f" \u21bb {fmt_remaining(fh['resets_at'])} ", P["Overlay0"], P["Base"]))

        # 7d usage
        sd_util = sd["utilization"]
        sd_color = P["Overlay0"] if stale else pct_color(sd_util)
        sd_label = "~7d" if stale else "7d"
        right2.append((f" {sd_label} {sd_util:.0f}% ", sd_color, P["Surface1"]))

        # 7d reset
        right2.append((f" \u21bb {fmt_remaining(sd['resets_at'])} ", P["Overlay0"], P["Base"]))

        line2 = render_two_groups(left2, right2, right_align=True,
            right_renderer=render_powerline_reverse, gap_bg=P["Base"])
    except Exception:
        pass

# ── Line 3: Skills bar ─────────────────────────────────────────────────────
SKILL_DIR_RE = re.compile(r'Base directory for this skill: [^\s"]+/skills/([a-zA-Z0-9][-a-zA-Z0-9]*)')

def _get_loaded_skills(tpath):
    """Extract loaded skill names from the session transcript, with caching."""
    if not tpath or not os.path.isfile(tpath):
        return []
    # Use file mtime + size as cache key to avoid re-scanning unchanged transcripts
    try:
        st = os.stat(tpath)
        cache_key = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return []
    cache_file = os.path.join(_cache_dir(), f"skills-{hashlib.md5(tpath.encode()).hexdigest()}.json")
    try:
        with open(cache_file) as f:
            cached = json.load(f)
        if cached.get("key") == cache_key:
            return cached.get("skills", [])
    except Exception:
        pass
    # Scan transcript for skill loading markers
    skills = []
    seen = set()
    try:
        with open(tpath) as f:
            for line in f:
                for m in SKILL_DIR_RE.finditer(line):
                    name = m.group(1)
                    if name not in seen:
                        seen.add(name)
                        skills.append(name)
    except Exception:
        return []
    # Write cache
    try:
        with open(cache_file, "w") as f:
            json.dump({"key": cache_key, "skills": skills}, f)
    except Exception:
        pass
    return skills

loaded_skills = _get_loaded_skills(transcript_path)
line3 = ""
if loaded_skills:
    try:
        cols = _get_terminal_cols() - 5
        # Build segments: label + skill names with dividers
        left3 = []
        left3.append((" SKILLS ", P["Mantle"], P["Overlay0"], True))
        # Calculate how much space the label uses
        label_width = 11  # " SKILLS " + separator
        available = cols - label_width
        shown = []
        overflow = 0
        width_so_far = 0
        for i, skill in enumerate(loaded_skills):
            # Each skill segment: " name " = len(name) + 2, plus separator ~1
            seg_width = len(skill) + 2 + (3 if i > 0 else 1)  # " │ name " vs " name "
            if width_so_far + seg_width > available and shown:
                overflow = len(loaded_skills) - i
                break
            shown.append(skill)
            width_so_far += seg_width
        # Build skill segments
        for i, skill in enumerate(shown):
            if i % 2 == 0:
                left3.append((f" {skill} ", P["Text"], P["Surface1"]))
            else:
                left3.append((f" {skill} ", P["Subtext1"], P["Surface0"]))
        # Overflow indicator
        if overflow > 0:
            left3.append((f" +{overflow} ", P["Overlay0"], P["Base"]))
        line3 = render_powerline(left3)
    except Exception:
        pass

# ── Output ───────────────────────────────────────────────────────────────────
print(line1)
if line2:
    print(line2)
if line3:
    print(line3)
