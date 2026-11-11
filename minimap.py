#!/usr/bin/env python3
"""The fleet minimap: the first mate, its crew, and each crewmate's own agents, fanned out like a chart.

  minimap.py            draw it in this terminal and keep it live (the plugin pane; q closes it)
  minimap.py --once     print one frame and exit
  minimap.py --line     one plain line for herdr's tab bar (tools/herdr.toml, ui.tab_bar_right)
  minimap.py --toggle   open the pane at the right of the first mate's tab, or close it (prefix+m)

Read-only: herdr's live snapshot names each pane and its agent state, firstmate's state/<id>.meta ties a pane to
its task and state/<id>.status says whether it waits on the captain, and Claude's subagent transcripts
(~/.claude*/projects/*/<session>/subagents) show the agents a crewmate has fanned out. Python 3.9, standard library.
"""
import glob
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
import unicodedata

FM_HOME = os.environ.get("FM_HOME") or os.path.expanduser("~/dev")
HERDR = os.environ.get("HERDR_BIN_PATH") or "herdr"
PLUGIN = "qd.minimap"
ACTIVE_SECONDS = 90      # a subagent transcript written this recently is still at work
RECENT_SECONDS = 600     # one finished this recently still shows, dimmed
RECENT_SHOWN = 2         # at most this many finished agents per crewmate
WIDTH = 64               # the pane's width in cells when --toggle opens it

# tools/herdr.toml's night colors
GOLD, TEXT, DIM, GREEN, RED, BLUE, YELLOW, MAUVE, TEAL = (
    "e5b850", "ece4d2", "7d7a73", "86c99a", "ef6a5a", "8fb8e0", "e0b25c", "b99bd0", "6fb3b0")
SPIN = "◐◓◑◒"
SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def herdr(*args, timeout=5):
    try:
        out = subprocess.run([HERDR, *args], capture_output=True, text=True, timeout=timeout)
        return json.loads(out.stdout).get("result") or {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def panes():
    snap = herdr("api", "snapshot").get("snapshot") or {}
    return {p["pane_id"]: p for p in snap.get("panes", []) if p.get("pane_id")}


def meta(path):
    out = {}
    try:
        for line in open(path, encoding="utf-8"):
            key, sep, value = line.rstrip("\n").partition("=")
            if sep:
                out[key] = value
    except OSError:
        pass
    return out


def task_wait(task):
    """'decision' while the task's last event asks the first mate or the captain, else its last state word."""
    try:
        lines = open(os.path.join(FM_HOME, "state", task + ".status"), encoding="utf-8").read().splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        word = re.match(r"\s*([a-z-]+)", line)
        if not word or word[1] in ("note", "working"):
            continue
        if word[1] == "resolved":
            return ""
        return "decision" if word[1] in ("needs-decision", "blocked") else word[1]
    return ""


def subagents(session, now):
    """A Claude session's fanned-out agents: (description, active, depth), at work first, newest first."""
    if not session:
        return []
    found = []
    for spec in glob.glob(os.path.expanduser(f"~/.claude*/projects/*/{session}/subagents/agent-*.meta.json")):
        transcript = spec[:-len(".meta.json")] + ".jsonl"
        try:
            age = now - os.path.getmtime(transcript if os.path.exists(transcript) else spec)
            info = json.load(open(spec, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if age > RECENT_SECONDS:
            continue
        what = info.get("description") or info.get("agentType") or "agent"
        found.append((what, age <= ACTIVE_SECONDS, max(1, int(info.get("spawnDepth") or 1)), age))
    found.sort(key=lambda a: (not a[1], a[3]))
    active = [a for a in found if a[1]]
    return [a[:3] for a in active + [a for a in found if not a[1]][:RECENT_SHOWN]]


def roster_name(task):
    """The Straw Hat tools/herdr-names.sh gave this task, for a crewmate whose pane is gone."""
    here = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    try:
        crew = re.findall(r'"([^"]+)"', re.search(r"CREW=\((.*?)\)", open(os.path.join(here, "herdr-names.sh"),
                                                                       encoding="utf-8").read(), re.S)[1])
        roster = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "qd",
                              "crew-roster")
        n = next(int(line.split()[1]) for line in open(roster, encoding="utf-8") if line.split()[:1] == [task])
        return crew[n % len(crew)]
    except (OSError, TypeError, IndexError, ValueError, StopIteration):
        return "⚓ crew"


def split_label(label, fallback):
    """'🌸 Robin: ci-tidy' -> ('🌸 Robin', 'ci-tidy')."""
    name, sep, rest = (label or "").partition(": ")
    return (name, rest) if sep else (label or fallback, "")


def fleet(now=None):
    """The root and its crew as plain data, so the drawing is testable without herdr."""
    now = now or time.time()
    live = panes()
    root = next((p for p in live.values() if "first mate" in (p.get("label") or "")), None) or next(
        (p for p in live.values() if (p.get("cwd") or "").rstrip("/").endswith("/firstmate")), None)
    crew = []
    for path in sorted(glob.glob(os.path.join(FM_HOME, "state", "*.meta"))):
        task = os.path.basename(path)[:-len(".meta")]
        m = meta(path)
        if "secondmate" in m.get("kind", ""):
            continue
        pane = live.get(m.get("herdr_pane_id") or "") or live.get((m.get("window") or "").split(":", 1)[-1])
        name = split_label(pane["label"], "")[0] if pane and pane.get("label") else roster_name(task)
        session = ((pane or {}).get("agent_session") or {}).get("value")
        spawned = re.match(r"s(\d+)", m.get("spawn_gen") or "")
        log = events(task)
        crew.append({"task": task, "name": name, "kind": m.get("kind") or "ship",
                     "state": state_of(pane, task_wait(task)), "agents": subagents(session, now),
                     "project": os.path.basename(m.get("project") or ""), "model": m.get("model") or "",
                     "effort": m.get("effort") or "", "age": now - int(spawned[1]) if spawned else None,
                     "prs": list(dict.fromkeys(pr for _, _, text in reversed(log)
                                               for pr in re.findall(r"#\d+", text)))[:2],
                     "events": log[-3:]})
    return {"root": split_label(root and root.get("label"), "👒 first mate")[0],
            "root_state": state_of(root, ""), "crew": crew}


def events(task):
    """A task's status log as (epoch, word, short text), oldest first; PR links shortened to #N."""
    try:
        lines = open(os.path.join(FM_HOME, "state", task + ".status"), encoding="utf-8").read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-12:]:
        m = re.match(r"\s*([a-z-]+)((?:\s*\[[^\]]*\])*)\s*:\s*(.*)", line)
        if not m:
            continue
        at = re.search(r"at=(\d+)", m[2])
        text = re.sub(r"https://github\.com/[^/\s]+/[^/\s]+/pull/(\d+)", r"#\1", m[3])
        out.append((int(at[1]) if at else 0, m[1], re.sub(r"\s+", " ", text).strip()))
    return out


def state_of(pane, wait):
    if pane is None:
        return "adrift"
    if wait == "decision":
        return "decision"
    status = pane.get("agent_status") or ""
    if status == "blocked":
        return "decision"
    if status == "working":
        return "working"
    if wait in ("paused", "done", "failed"):
        return wait
    return "done" if status == "done" else "idle"


# ---- drawing ----------------------------------------------------------------------------------------------------

def cells(text):
    return sum(0 if unicodedata.combining(c) or c in "‍️" else
               2 if unicodedata.east_asian_width(c) in "WF" or ord(c) >= 0x1F000 else 1 for c in text)


def clip(text, width):
    if cells(text) <= width:
        return text
    out = ""
    for c in text:
        if cells(out + c) > width - 1:
            return out + "…"
        out += c
    return out


def paint(rgb, text, bold=False, dim=False):
    if not COLOR:
        return text
    r, g, b = (int(rgb[i:i + 2], 16) for i in (0, 2, 4))
    return f"\x1b[{'1;' if bold else ''}{'2;' if dim else ''}38;2;{r};{g};{b}m{text}\x1b[0m"


COLOR = True
GLYPH = {"working": ("◐", GREEN), "decision": ("◆", RED), "paused": ("‖", YELLOW), "done": ("✔", BLUE),
         "failed": ("✗", RED), "idle": ("○", DIM), "adrift": ("✕", DIM)}


WORD = {"working": "working", "decision": "needs you", "paused": "waiting", "done": "done", "failed": "failed",
        "idle": "idle", "adrift": "adrift"}
EVENT = {"needs-decision": RED, "blocked": RED, "failed": RED, "paused": YELLOW, "done": BLUE, "resolved": GREEN,
         "working": GREEN}


def glyph(state, frame):
    mark, color = GLYPH.get(state, GLYPH["idle"])
    return paint(color, SPIN[frame % len(SPIN)] if state == "working" else mark, bold=state == "decision")


def mark(state, frame):
    """A state's symbol and color as a part for row()."""
    symbol, color = GLYPH.get(state, GLYPH["idle"])
    return (SPIN[frame % len(SPIN)] if state == "working" else symbol, color, state == "decision", False)


def part(text, color=TEXT, bold=False, dim=False):
    return (text, color, bold, dim)


def row(parts, width, align="center"):
    """Parts clipped to width as one painted line, padded to exactly width cells."""
    out, used = "", 0
    for text, color, bold, dim in parts:
        if used >= width:
            break
        text = clip(text, width - used)
        out += paint(color, text, bold, dim)
        used += cells(text)
    left = (width - used) // 2 if align == "center" else 0 if align == "left" else \
        max(0, min(width - used, align - used // 2))  # a number centers the line on that column
    return " " * left + out + " " * (width - used - left)


def ago(seconds):
    if seconds is None:
        return ""
    minutes = int(seconds // 60)
    return f"{minutes}m" if minutes < 60 else f"{minutes // 60}h{minutes % 60:02d}" if minutes < 1440 \
        else f"{minutes // 1440}d"


def column(c, width, frame):
    """One crewmate's block under the fan: who, state, task, where and on what, then its agents."""
    symbol = mark(c["state"], frame)
    rows = [row([part(c["name"], GOLD, bold=True)], width),
            row([symbol, part(" " + WORD.get(c["state"], c["state"]), symbol[1], dim=c["state"] == "adrift")], width),
            row([part(c["task"], TEXT if c["state"] != "adrift" else DIM)], width),
            row([part(" · ".join(x for x in (c["project"], c["model"] + (f" {c['effort']}" if c["effort"] else ""))
                                  if x), DIM)], width)]
    facts = " · ".join(x for x in (("⏱ " + ago(c["age"])) if c["age"] is not None else "", " ".join(c["prs"])) if x)
    if facts:
        rows.append(row([part(facts, BLUE if c["prs"] else DIM)], width))
    if c["agents"]:
        rows.append(row([part("┊", TEAL)], width))
    shown = c["agents"][:AGENTS_SHOWN]
    for what, active, depth in shown:
        dot = ("●" if frame % 2 or not COLOR else "◉") if active else "○"
        rows.append(row([part(" " * (depth - 1) + dot + " ", MAUVE if active else DIM),
                         part(what, TEXT if active else DIM, dim=not active)], width))
    if len(c["agents"]) > len(shown):
        rows.append(row([part(f"+{len(c['agents']) - len(shown)} more", DIM)], width))
    return rows


AGENTS_SHOWN = 6


def fan(n, width):
    """The bar from the root's stem down to each column's center: ╭──┬──┴──╮."""
    centers = [i * width // n + width // n // 2 for i in range(n)]
    stem = stem_at(centers)
    if n == 1:
        return centers, [stem]
    line = [" "] * width
    for x in range(centers[0], centers[-1] + 1):
        line[x] = "─"
    for i, x in enumerate(centers):
        line[x] = "╭" if i == 0 else "╮" if i == n - 1 else "┬"
    line[stem] = "┼" if line[stem] == "┬" else "┴" if line[stem] == "─" else line[stem]
    return centers, "".join(line)


def stem_at(centers):
    """Where the root's stem meets the bar: on the middle column, or halfway between the middle two."""
    mid = len(centers) // 2
    return centers[mid] if len(centers) % 2 else (centers[mid - 1] + centers[mid]) // 2


def frame_lines(data, width, frame=0):
    crew = data["crew"]
    hands = sum(1 for c in crew for a in c["agents"] if a[1])
    waiting = sum(1 for c in crew if c["state"] == "decision")
    n = max(1, min(len(crew), width // 14))  # columns narrower than 14 cells stop being readable
    first = min(len(crew), n) or 1
    stem = stem_at([i * width // first + width // first // 2 for i in range(first)])
    lines = [row([part(data["root"], GOLD, bold=True), part(" "), mark(data["root_state"], frame)], width, stem),
             row([part("first mate", DIM)], width, stem),
             row([part(f"{len(crew)} crew · {hands} agents at work", DIM)]
                 + ([part(f" · {waiting} need you", RED, bold=True)] if waiting else []), width, stem)]
    if not crew:
        return lines + ["", row([part("calm seas, no crew out", DIM)], width)]
    lines.append(row([part("│", TEAL)], width, stem))
    for start in range(0, len(crew), n):
        group = crew[start:start + n]
        colw = width // len(group)
        centers, bar = fan(len(group), width)
        if isinstance(bar, str):
            lines.append(paint(TEAL, bar))
            drops = [" "] * width
            for x in centers:
                drops[x] = "│"
            lines.append(paint(TEAL, "".join(drops)))
        else:
            lines.append(row([part("│", TEAL)], width))
        blocks = [column(c, colw, frame) for c in group]
        for r in range(max(len(b) for b in blocks)):
            lines.append("".join(b[r] if r < len(b) else " " * colw for b in blocks))
        lines.append("")
    log = sorted(((at, c["name"], word, text) for c in crew for at, word, text in c["events"] if at),
                 reverse=True)[:LOG_SHOWN]
    if log:
        lines.append(paint(TEAL, "─── deck log " + "─" * (width - 13)))
        for at, name, word, text in log:
            stamp = time.strftime("%H:%M", time.localtime(at))
            lines.append(row([part(stamp + " ", DIM), part(name.split(" ")[0] + " ", GOLD),
                              part(word + " ", EVENT.get(word, DIM)), part(text, TEXT)], width, align="left"))
        lines.append("")
    legend = [part("◐ working  ", GREEN), part("◆ needs you  ", RED), part("‖ waiting  ", YELLOW),
              part("✕ adrift  ", DIM), part("● agent", MAUVE)]
    lines.append(row(legend, width, align="left"))
    return lines


LOG_SHOWN = 5


def line_text(data):
    """The tab bar's one-liner: the root fanning out to each crewmate, with its agents at work as a superscript."""
    if not data["crew"]:
        return ""
    marks = []
    for c in data["crew"]:
        mark = SPIN[0] if c["state"] == "working" else GLYPH.get(c["state"], GLYPH["idle"])[0]
        busy = sum(1 for a in c["agents"] if a[1])
        marks.append(f"{c['name'].split(' ')[0]}{mark}{str(busy).translate(SUPERSCRIPT) if busy else ''}")
    return "⛵⇉ " + " ".join(marks)


# ---- modes ------------------------------------------------------------------------------------------------------

def run_pane():
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd) if os.isatty(fd) else None
    if saved:
        tty.setcbreak(fd)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    sys.stdout.write("\x1b[?25l")
    frame, data, fetched = 0, None, 0.0
    try:
        while True:
            if time.time() - fetched >= 2:
                data, fetched = fleet(), time.time()
            size = os.get_terminal_size()
            # two cells spare: herdr draws some of these symbols wider than Python counts them
            lines = frame_lines(data, size.columns - 2, frame)[:size.lines]
            sys.stdout.write("\x1b[H" + "".join(f"{l}\x1b[K\n" for l in lines[:-1]) + lines[-1] + "\x1b[K\x1b[J")
            sys.stdout.flush()
            frame += 1
            if saved and select.select([fd], [], [], 0.5)[0] and os.read(fd, 16)[:1] in (b"q", b"Q"):
                return
            if not saved:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h")
        if saved:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def state_file():
    root = os.environ.get("HERDR_PLUGIN_STATE_DIR") or os.path.expanduser("~/.local/state/qd")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, "minimap-pane")


def toggle():
    live = panes()
    try:
        open_id = open(state_file()).read().strip()
    except OSError:
        open_id = ""
    if open_id in live:
        herdr("plugin", "pane", "close", open_id)
        os.remove(state_file())
        return
    root = next((p for p in live.values() if "first mate" in (p.get("label") or "")), None)
    target = root["pane_id"] if root else os.environ.get("HERDR_PANE_ID", "")
    args = ["plugin", "pane", "open", "--plugin", PLUGIN, "--entrypoint", "map", "--placement", "split",
            "--direction", "right", "--no-focus"] + (["--target-pane", target] if target else [])
    before = set(live)
    herdr(*args)
    new = [p for p in panes() if p not in before]
    if not new:
        return
    open(state_file(), "w").write(new[0])
    layout = herdr("pane", "layout", "--pane", new[0]).get("layout") or {}
    rect = next((p["rect"] for p in layout.get("panes", []) if p["pane_id"] == new[0]), None)
    area = layout.get("area") or {}
    if rect and area.get("width"):
        # herdr resizes a split by a share of the tab's width; move the edge right until the map is WIDTH wide
        herdr("pane", "resize", "--pane", new[0], "--direction", "right",
              "--amount", f"{max(0.0, (rect['width'] - WIDTH) / area['width']):.3f}")


def main(argv):
    global COLOR
    if "--toggle" in argv:
        return toggle()
    if "--line" in argv:
        COLOR = False
        print(line_text(fleet()))
        return
    if "--once" in argv:
        COLOR = sys.stdout.isatty() or "--color" in argv
        width = os.get_terminal_size().columns if sys.stdout.isatty() else WIDTH
        print("\n".join(frame_lines(fleet(), width)))
        return
    run_pane()


if __name__ == "__main__":
    main(sys.argv[1:])
