#!/usr/bin/env python3
"""The fleet minimap, the nav column that stands in for herdr's sidebar: every space and agent to jump to, then
the first mate, its crew and each crewmate's own agents, fanned out like a chart.

  minimap.py            the nav column (plugin pane "map"), which follows focus into every tab
  minimap.py --popup    the same nav as a popup (plugin pane "pick"); exits once a choice is made
  minimap.py --tree     the bonsai under the nav column (plugin pane "tree")
  minimap.py --once     print one frame and exit
  minimap.py --line     one plain line for herdr's tab bar (tools/herdr.toml, ui.tab_bar_right)
  minimap.py --toggle   prefix+m: focus the nav here, or step back out of it; over a zoomed tab, the popup
  minimap.py --deck     prefix+d: Captain's Deck in a space of its own, opened the first time
  minimap.py --ensure   the plugin's startup hook: open the nav column when none is open

In the nav: up/down or the wheel picks, enter or a click goes, 1-9 jumps to that space, d opens the deck, f goes to
the first mate, esc or q steps back. Like herdr's sidebar it stays in view: it moves into whichever tab has focus,
crew spaces included (only while the captain looks at one, and firstmate's teardown never closes the tab in view),
and pops up instead over a zoomed tab. Under the nav, in a pane of its own that moves with the column and keeps the
height the captain gives it, a pixel bonsai grows with the captain's Claude tokens, drawn as large as its pane holds:
the day's tree (bonsai.py), sprouting at midnight, or the broader lifetime tree (elder.py); a click or any key in the
pane switches between them, and the pane keeps the one last shown. It reads herdr's live snapshot, firstmate's
state/<id>.meta and .status, and Claude's transcripts (~/.claude*/projects); it changes only focus, its own panes, the
bonsai's token store and the tree last shown.
Python 3.9, standard library.
"""
import glob
import json
import os
import re
import select
import signal
import socket
import subprocess
import sys
import threading
import time
import unicodedata

import bonsai
import elder

FM_HOME = os.environ.get("FM_HOME") or os.path.expanduser("~/dev")
HERDR = os.environ.get("HERDR_BIN_PATH") or "herdr"
PLUGIN = "qd.minimap"
ACTIVE_SECONDS = 90      # a subagent transcript written this recently is still at work
RECENT_SECONDS = 600     # one finished this recently still shows, dimmed
RECENT_SHOWN = 2         # at most this many finished agents per crewmate
AGENTS_SHOWN = 6         # agents listed under a crewmate before "+N more"
LOG_SHOWN = 4            # events in the deck log
WIDTH = 56               # the nav column's width in cells
NAV_TITLE = "⛵ nav"      # the map pane's title in herdr-plugin.toml, which is how a live nav is found
TREE_TITLE = "🌳 bonsai"  # the tree pane's title there, found the same way
DECK = "herdr-firstmate-flow"  # Captain's Deck (deimantasnork/captains-deck)
DECK_SPACE = "⚓ captain's deck"  # the deck's own space
POLL = 0.2               # seconds between looks at herdr's focus, so the column keeps up with a switch
COUNT_EVERY = 60         # seconds between token counts, each reading only what the transcripts gained since
VIEWS = {"today": bonsai, "lifetime": elder}  # the bonsai pane's trees, in the order a switch steps through
TREE_HEIGHT = bonsai.ROWS + 3  # the bonsai pane's least height: either tree, its caption and the pane's two-row frame
SETTLE = 0.3             # focus the nav did not move rests this long before the column follows: a spawn's brief
                         # flick to a new crew space (fm-spawn restores focus) never carries the column into it

# tools/herdr.toml's night colors
GOLD, TEXT, DIM, GREEN, RED, BLUE, YELLOW, MAUVE, TEAL, SUBTEXT = (
    "e5b850", "ece4d2", "7d7a73", "86c99a", "ef6a5a", "8fb8e0", "e0b25c", "b99bd0", "6fb3b0", "b2aa98")
SPIN = "◐◓◑◒"
SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def herdr(*args, timeout=5):
    try:
        out = subprocess.run([HERDR, *args], capture_output=True, text=True, timeout=timeout)
        return json.loads(out.stdout).get("result") or {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def api(method, **params):
    """One request over herdr's socket (newline-delimited JSON), for calls its CLI lacks; {} on any failure."""
    path = os.environ.get("HERDR_SOCKET_PATH") or os.path.expanduser("~/.config/herdr/herdr.sock")
    try:
        with socket.socket(socket.AF_UNIX) as conn:
            conn.settimeout(5)
            conn.connect(path)
            conn.sendall((json.dumps({"id": f"qd.minimap:{method}", "method": method, "params": params}) + "\n")
                         .encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = conn.recv(1 << 20)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf).get("result") or {}
    except (OSError, ValueError):
        return {}


def snapshot():
    return (api("session.snapshot") or herdr("api", "snapshot")).get("snapshot") or {}


def focus_pane(pane):
    return bool(api("pane.focus", pane_id=pane))


def panes(snap=None):
    snap = snapshot() if snap is None else snap
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


def root_of(live):
    """The first mate's pane: the one labelled so, else one sitting in the firstmate checkout."""
    return next((p for p in live.values() if "first mate" in (p.get("label") or "")), None) or next(
        (p for p in live.values() if (p.get("cwd") or "").rstrip("/").endswith("/firstmate")), None)


def split_label(label, fallback):
    """'🌸 Robin: ci-tidy' -> ('🌸 Robin', 'ci-tidy')."""
    name, sep, rest = (label or "").partition(": ")
    return (name, rest) if sep else (label or fallback, "")


def fleet(snap=None, now=None):
    """The root and its crew, then the spaces and agents to jump to, as plain data, so the drawing is testable
    without herdr."""
    now = now or time.time()
    snap = snapshot() if snap is None else snap
    live = panes(snap)
    root = root_of(live)
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
        crew.append({"task": task, "name": name, "kind": m.get("kind") or "ship", "pane": (pane or {}).get("pane_id"),
                     "space": m.get("herdr_workspace_id") or (pane or {}).get("workspace_id"),
                     "state": state_of(pane, task_wait(task)), "agents": subagents(session, now),
                     "project": os.path.basename(m.get("project") or ""), "model": m.get("model") or "",
                     "effort": m.get("effort") or "", "age": now - int(spawned[1]) if spawned else None,
                     "prs": list(dict.fromkeys(pr for _, _, text in reversed(log)
                                               for pr in re.findall(r"#\d+", text)))[:2],
                     "events": log[-3:]})
    data = {"root": split_label(root and root.get("label"), "👒 first mate")[0],
            "root_pane": (root or {}).get("pane_id"), "root_state": state_of(root, ""), "crew": crew}
    data.update(places(snap, crew, (root or {}).get("pane_id")))
    return data


HERDR_STATE = {"working": "working", "blocked": "decision", "done": "done"}


def crew_space(ws, crew):
    """A space firstmate made for a crewmate."""
    return (ws.get("label") or "").startswith("└") or any(c.get("space") == ws.get("workspace_id") for c in crew)


def space_label(ws, crew):
    """A space's name: the crewmate's own for a crew space, else herdr's label without firstmate's group suffix."""
    c = next((c for c in crew if c.get("space") and c["space"] == ws.get("workspace_id")), None)
    if c:
        return f"{c['name']} · {c['task']}"
    label = re.sub(r"\s+·\s+p:\S+$", "", ws.get("label") or "").lstrip("└ ").strip()
    return label or f"space {ws.get('number')}"


def tree(rows, parent):
    """Rows in display order, each parent followed by its children; a child gets depth 1 and last (└ or ├)."""
    keys = [r["key"] for r in rows]
    kids = {}
    for r in rows:
        if parent.get(r["key"]) in keys:
            kids.setdefault(parent[r["key"]], []).append(r)
    out = []
    for r in rows:
        if parent.get(r["key"]) in keys:
            continue  # drawn under its parent
        out.append(dict(r, depth=0, last=False))
        children = kids.get(r["key"], [])
        out += [dict(c, depth=1, last=i == len(children) - 1) for i, c in enumerate(children)]
    return out


def places(snap, crew, root_pane=None):
    """The spaces and agents the nav lists as firstmate's tree: a crew space under the space of the first mate that
    launched it (a └ space under the nearest owner above it, as firstmate orders them), and each agent in a crew
    space under the agent of that owner's space."""
    here_ws, here_pane = snap.get("focused_workspace_id"), snap.get("focused_pane_id")
    workspaces = snap.get("workspaces", [])
    numbers = {w.get("workspace_id"): w.get("number") for w in workspaces}
    root_ws = next((p.get("workspace_id") for p in snap.get("panes", []) if p.get("pane_id") == root_pane), None)
    owner, owner_of = None, {}
    for w in workspaces:
        wid = w.get("workspace_id")
        if not crew_space(w, crew):
            owner = wid
        elif any(c.get("space") == wid for c in crew) and root_ws:
            owner_of[wid] = root_ws  # this home's crew: launched by this first mate
        elif owner:
            owner_of[wid] = owner
    spaces = [{"key": w.get("workspace_id"), "id": w.get("workspace_id"), "n": w.get("number"),
               "label": space_label(w, crew), "state": HERDR_STATE.get(w.get("agent_status"), "idle"),
               "here": w.get("workspace_id") == here_ws, "crew": crew_space(w, crew),
               "deck": w.get("label") == DECK_SPACE} for w in workspaces]
    raw = snap.get("agents", [])
    lead = {}  # each space's own agent, the first mate's pane first, that its crew spaces' agents hang under
    for a in sorted(raw, key=lambda a: a.get("pane_id") != root_pane):
        lead.setdefault(a.get("workspace_id"), a.get("pane_id"))
    agents = [{"key": a.get("pane_id"), "pane": a.get("pane_id"), "name": a.get("display_agent") or a.get("agent")
               or "agent", "state": HERDR_STATE.get(a.get("agent_status"), "idle"),
               "doing": a.get("terminal_title_stripped") or "", "n": numbers.get(a.get("workspace_id")),
               "here": a.get("pane_id") == here_pane} for a in raw]
    agent_parent = {a.get("pane_id"): lead.get(owner_of.get(a.get("workspace_id"))) for a in raw}
    return {"spaces": tree(spaces, owner_of), "agents": tree(agents, agent_parent)}


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


def fan(n, width):
    """The bar from the root's stem down to each column's center (╭──┬──┴──╮), or None for a single column."""
    centers = [i * width // n + width // n // 2 for i in range(n)]
    stem = stem_at(centers)
    if n == 1:
        return centers, None
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


def frame_lines(data, width, frame=0, hits=None, top=0):
    """The fleet chart. With a hits list, each clickable stretch is recorded as (line, x0, x1, ("agent", pane)),
    counting lines from top."""
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
    if hits is not None and data.get("root_pane"):
        hits.extend((top + y, 0, width, ("agent", data["root_pane"])) for y in range(2))
    if not crew:
        return lines + ["", row([part("calm seas, no crew out", DIM)], width)]
    lines.append(row([part("│", TEAL)], width, stem))
    for start in range(0, len(crew), n):
        group = crew[start:start + n]
        colw = width // len(group)
        centers, bar = fan(len(group), width)
        if bar:
            lines.append(paint(TEAL, bar))
            drops = [" "] * width
            for x in centers:
                drops[x] = "│"
            lines.append(paint(TEAL, "".join(drops)))
        else:
            lines.append(row([part("│", TEAL)], width))
        blocks = [column(c, colw, frame) for c in group]
        for r in range(max(len(b) for b in blocks)):
            if hits is not None:
                hits.extend((top + len(lines), i * colw, (i + 1) * colw, ("agent", c["pane"]))
                            for i, c in enumerate(group) if c.get("pane") and r < len(blocks[i]))
            lines.append("".join(b[r] if r < len(b) else " " * colw for b in blocks))
        lines.append("")
    log = sorted(((at, c["name"], word, text) for c in crew for at, word, text in c["events"] if at),
                 reverse=True)[:LOG_SHOWN]
    if log:
        lines.append(paint(TEAL, "─── deck log " + "─" * (width - 13)))
        for at, name, word, text in log:
            stamp = time.strftime("%H:%M" if time.time() - at < 43200 else "%b %d", time.localtime(at))
            lines.append(row([part(stamp + " ", DIM), part(name.split(" ")[0] + " ", GOLD),
                              part(word + " ", EVENT.get(word, DIM)), part(text, TEXT)], width, align="left"))
        lines.append("")
    legend = [part("◐ working  ", GREEN), part("◆ needs you  ", RED), part("‖ waiting  ", YELLOW),
              part("✕ adrift  ", DIM), part("● agent", MAUVE)]
    lines.append(row(legend, width, align="left"))
    return lines


def rule(title, width):
    return paint(TEAL, f"─── {title} " + "─" * max(0, width - cells(title) - 5))


def branch(r):
    """The tree connector before a child row: ├ for one with siblings below it, └ for the last."""
    return part(("└ " if r.get("last") else "├ ") if r.get("depth") else "", TEAL)


def nav_lines(data, width, frame=0, cursor=None, hits=None):
    """The nav: spaces, then agents, then the fleet chart. Returns (lines, items): items are the pickable places
    in order, and hits (when given) maps each clickable stretch to one."""
    hits = [] if hits is None else hits
    lines, items = [rule("spaces", width)], []
    for s in data.get("spaces", []):
        picked = cursor == len(items)
        hits.append((len(lines), 0, width, ("space", s["id"])))
        items.append(("space", s["id"]))
        lines.append(row([part("▸ " if picked else "  ", GOLD, bold=True), branch(s),
                          part(f"{s['n']} ", GOLD if s["here"] else DIM, bold=s["here"]), mark(s["state"], frame),
                          part(" " + s["label"], TEXT if s["here"] or picked else SUBTEXT, bold=s["here"])],
                         width, align="left"))
    lines += ["", rule("agents", width)]
    for a in data.get("agents", []):
        picked = cursor == len(items)
        hits.append((len(lines), 0, width, ("agent", a["pane"])))
        items.append(("agent", a["pane"]))
        lines.append(row([part("▸ " if picked else "  ", GOLD, bold=True), branch(a), mark(a["state"], frame),
                          part(" " + a["name"] + " ", GOLD, bold=a["here"]),
                          part(f"{a['n']} · " if a["n"] else "", DIM), part(a["doing"], SUBTEXT)],
                         width, align="left"))
    if not data.get("agents"):
        lines.append(row([part("  no agents running", DIM)], width, align="left"))
    lines += ["", rule("fleet", width)]
    lines += frame_lines(data, width, frame, hits, len(lines))
    return lines, items


def amount(n):
    """1234567 -> '1.2M'."""
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= size:
            return f"{n / size:.1f}{unit}"
    return str(int(n))


def tree_lines(count, width, height, view="today"):
    """The bonsai pane's lines: the view's tree for this many tokens at the largest whole scale the pane holds,
    centered over its stage, token count and view at the foot; the caption alone when the tree does not fit."""
    tree = VIEWS[view]
    g = tree.growth(count)
    caption = row([part(bonsai.stage(g), SUBTEXT), part(f" · {amount(count)} tokens ", DIM), part(view, GOLD),
                   part(" ⇄", DIM)], width)
    size = min(width // tree.W, (height - 1) // tree.ROWS) if COLOR else 0
    art = [" " * ((width - tree.W * size) // 2) + line
           for line in bonsai.rows(tree.pixels(g), size=size, w=tree.W, h=tree.H)] if size > 0 else []
    return ([""] * height + art + [caption])[-height:] if height > 0 else []


def switched(view, events):
    """The view after this input: a click or key steps to the next tree, the wheel leaves it be."""
    if any(e[0] != "wheel" for e in events):
        names = list(VIEWS)
        return names[(names.index(view) + 1) % len(names)]
    return view


def screen(lines, height, hint):
    """The pane's lines: the nav cut to fit above the hint line at the foot."""
    lines = lines[:max(0, height - 1)]
    return lines + [""] * (height - 1 - len(lines)) + [hint]


def hint_line(width, focused):
    if not focused:
        return row([part("prefix+m nav · prefix+d deck", DIM)], width, align="left")
    keys = (("↑↓", "pick"), ("⏎", "go"), ("1-9", "space"), ("d", "deck"), ("f", "first mate"), ("esc", "back"))
    parts = []
    for key, what in keys:
        parts += [part(key, GOLD, bold=True), part(f" {what}  ", DIM)]
    return row(parts, width, align="left")


def line_text(data):
    """The tab bar's one-liner: the root fanning out to each crewmate, with its agents at work as a superscript."""
    if not data["crew"]:
        return ""
    marks = []
    for c in data["crew"]:
        busy = sum(1 for a in c["agents"] if a[1])
        marks.append(f"{c['name'].split(' ')[0]}{mark(c['state'], 0)[0]}"
                     f"{str(busy).translate(SUPERSCRIPT) if busy else ''}")
    return "⛵⇉ " + " ".join(marks)


# ---- modes ------------------------------------------------------------------------------------------------------

CSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z~]")
MOUSE = re.compile(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
ARROWS = {b"\x1b[A": "up", b"\x1b[B": "down", b"\x1bOA": "up", b"\x1bOB": "down"}


def keys_of(data):
    """Terminal input as events: (up,) (down,) (enter,) (esc,) (char, c), (click, x, y) zero-based, (wheel, ±1)."""
    out, i = [], 0
    while i < len(data):
        m = MOUSE.match(data, i)
        if m:
            button = int(m[1])
            if m[4] == b"M" and button == 0:
                out.append(("click", int(m[2]) - 1, int(m[3]) - 1))
            elif button in (64, 65):
                out.append(("wheel", -1 if button == 64 else 1))
            i = m.end()
            continue
        arrow = next((k for k in ARROWS if data.startswith(k, i)), None)
        if arrow:
            out.append((ARROWS[arrow],))
            i += len(arrow)
            continue
        m = CSI.match(data, i)
        if m:  # focus reports and other keys the nav does not use
            i = m.end()
            continue
        c = data[i:i + 1]
        if c == b"\x1b":
            out.append(("esc",))
        elif c in (b"\r", b"\n"):
            out.append(("enter",))
        elif c.isascii():  # a byte of a wider character is no key the nav uses
            out.append(("char", c.decode()))
        i += 1
    return out


def hit_at(hits, x, y):
    return next((place for line, x0, x1, place in hits if line == y and x0 <= x < x1), None)


def go(place):
    """Focus a space or an agent's pane; herdr switches space and tab to it."""
    kind, target = place
    if kind == "space":
        herdr("workspace", "focus", target)
    else:
        focus_pane(target)


def hostable(snap, tab):
    """Whether the nav column can sit in this tab: any tab with panes that is not zoomed."""
    layout = next((l for l in snap.get("layouts", []) if l.get("tab_id") == tab), None)
    return bool(layout and layout.get("panes") and not layout.get("zoomed")), layout


def follow(snap, mine):
    """Move the nav column into the focused tab beside its right-edge pane, the bonsai under it; the column's pane
    afterwards."""
    tab = snap.get("focused_tab_id")
    if not mine or not tab or mine.get("tab_id") == tab:
        return mine
    ok, layout = hostable(snap, tab)
    if not ok:
        return mine
    target = right_edge(layout, trees(snap))
    moved = herdr("pane", "move", mine["pane_id"], "--tab", tab, "--target-pane", target["pane_id"], "--split",
                  "right", "--ratio", f"{ratio_for(target['rect']['width']):.3f}", "--no-focus")
    new = (moved.get("move_result") or {}).get("pane")
    if new:
        carry(snap, mine["pane_id"], new)
    return new or mine


def carry(snap, nav, new):
    """Put the bonsai under the nav column's new pane, keeping the share of the column it had under the old one
    (nav) in snap, the look from before the move. A bonsai the captain closed stays closed. herdr moves a pane only
    into another tab (within its own tab it reports no change), so a bonsai already in the column's tab but not under
    it is replaced by a fresh one there."""
    tree = next(iter(trees(snap)), None)
    if not tree:
        return
    tab = new.get("tab_id") or snap.get("focused_tab_id")
    if tree.get("tab_id") != tab:
        herdr("pane", "move", tree["pane_id"], "--tab", tab, "--target-pane", new["pane_id"], "--split", "down",
              "--ratio", f"{nav_share(snap, nav, tree['pane_id']):.3f}", "--no-focus")
    elif not stacked(snapshot(), new["pane_id"], tree["pane_id"]):
        herdr("pane", "close", tree["pane_id"])
        open_tree(new["pane_id"])


def stacked(snap, nav, tree):
    """Whether the bonsai sits directly under the nav, the column's full width."""
    a, b = rect_of(snap, nav), rect_of(snap, tree)
    return bool(a and b and a["tab"] == b["tab"] and a["x"] == b["x"] and a["width"] == b["width"]
                and a["y"] + a["height"] == b["y"])


def rect_of(snap, pane):
    """A pane's rect with its tab id, or None."""
    return next((dict(p["rect"], tab=l.get("tab_id")) for l in snap.get("layouts", []) for p in l.get("panes", [])
                 if p.get("pane_id") == pane and p.get("rect")), None)


def nav_share(snap, nav, tree):
    """The share of the column the nav keeps above the bonsai: as the two stand when stacked, else enough to leave
    the smallest tree its room."""
    a, b = rect_of(snap, nav), rect_of(snap, tree)
    if a and b and a["tab"] == b["tab"] and a["x"] == b["x"] and a["y"] < b["y"]:
        return a["height"] / (a["height"] + b["height"])
    tall = (a or {}).get("height") or 0
    return max(0.3, 1 - TREE_HEIGHT / tall) if tall else 0.7


def right_edge(layout, skip=()):
    """The pane to split from: the one on the tab's right edge, tallest, then topmost, passing over the panes in
    skip (a bonsai, which the column would otherwise open beside) unless they are all there is."""
    ids = {p["pane_id"] for p in skip}
    panes = [p for p in layout["panes"] if p["pane_id"] not in ids] or layout["panes"]
    return max(panes, key=lambda p: (p["rect"]["x"] + p["rect"]["width"], p["rect"]["height"], -p["rect"]["y"]))


def ratio_for(width):
    """The share a pane of this width keeps when the nav splits off its right side."""
    return max(0.5, min(0.85, 1 - WIDTH / width)) if width else 0.7


def state_path(name):
    root = os.environ.get("HERDR_PLUGIN_STATE_DIR") or os.path.expanduser("~/.local/state/qd")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, name)


def remember(name, value):
    try:
        with open(state_path(name), "w", encoding="utf-8") as f:
            f.write(value + "\n")
    except OSError:
        pass


def recall(name):
    try:
        with open(state_path(name), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def navs(snap):
    return [p for p in snap.get("panes", []) if p.get("label") == NAV_TITLE]


def trees(snap):
    return [p for p in snap.get("panes", []) if p.get("label") == TREE_TITLE]


def run_pane(popup=False):
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd) if os.isatty(fd) else None
    if saved:
        tty.setcbreak(fd)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    sys.stdout.write("\x1b[?25l\x1b[?1000h\x1b[?1006h")  # hide the cursor; report clicks and the wheel
    first = snapshot()
    me = next((p.get("terminal_id") for p in first.get("panes", [])
               if p.get("pane_id") == os.environ.get("HERDR_PANE_ID")), None)
    data, fetched, cursor, seen, last = None, 0.0, None, (None, 0.0), recall("last-pane")
    shown, drew = None, 0.0

    def mine_in(snap):
        return next((p for p in snap.get("panes", []) if me and p.get("terminal_id") == me), None)
    try:
        while True:
            now = time.time()
            frame = int(now * 2)  # animations at two steps a second, however often the column redraws
            snap = snapshot()
            mine = mine_in(snap)
            focused = bool(mine) and snap.get("focused_pane_id") == mine["pane_id"]
            if not popup and snap.get("focused_pane_id") and not focused and \
                    snap["focused_pane_id"] not in {t["pane_id"] for t in trees(snap)} and \
                    snap["focused_pane_id"] != last:
                last = snap["focused_pane_id"]
                remember("last-pane", last)
            if data is None or now - fetched >= 2:
                data, fetched = fleet(snap, now), now
            else:
                data.update(places(snap, data["crew"], data.get("root_pane")))
            if snap.get("focused_tab_id") != seen[0]:
                seen = (snap.get("focused_tab_id"), now)
            if not popup and now - seen[1] >= SETTLE:
                mine = follow(snap, mine)
            if not (focused or popup):  # unfocused, the pointer rests on the space in view
                cursor = next((i for i, s in enumerate(data["spaces"]) if s["here"]), None)
            size = os.get_terminal_size()
            width = size.columns - 2  # two cells spare: herdr draws some symbols wider than Python counts them
            hits = []
            lines, items = nav_lines(data, width, frame, cursor, hits)
            lines = screen(lines, size.lines, hint_line(width, focused or popup))
            out = "\x1b[H" + "".join(f"{l}\x1b[K\n" for l in lines[:-1]) + lines[-1] + "\x1b[K\x1b[J"
            # herdr repaints whatever is written, so an unchanged frame is not sent, save a full one every few seconds
            # in case something drew over the pane
            if out != shown or now - drew >= 5:
                sys.stdout.write(out)
                sys.stdout.flush()
                shown, drew = out, now
            if not saved:
                time.sleep(POLL)
                continue
            if not select.select([fd], [], [], POLL)[0]:
                continue
            for key in keys_of(os.read(fd, 256)):
                place = None
                if key[0] in ("up", "down", "wheel") and items:
                    step = -1 if key[0] == "up" else 1 if key[0] == "down" else key[1]
                    cursor = min(len(items) - 1, max(0, (cursor if cursor is not None else -step) + step))
                elif key[0] == "enter" and cursor is not None and cursor < len(items):
                    place = items[cursor]
                elif key[0] == "click":
                    place = hit_at(hits, key[1], key[2])
                elif key[0] == "char" and key[1].isdigit():
                    place = next((("space", s["id"]) for s in data["spaces"] if str(s["n"]) == key[1]), None)
                elif key[0] == "char" and key[1] == "d":
                    deck()
                    if popup:
                        return
                elif key[0] == "char" and key[1] == "f" and data.get("root_pane"):
                    place = ("agent", data["root_pane"])
                elif key[0] == "esc" or (key[0] == "char" and key[1] in ("q", "Q")):
                    if popup:
                        return
                    last = recall("last-pane")
                    if last and last in panes(snap):
                        focus_pane(last)
                if place:
                    go(place)
                    if popup:
                        return
                    after = snapshot()  # follow at once rather than at the next look
                    follow(after, mine_in(after))
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[0m\x1b[?25h")
        if saved:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def run_tree():
    """The bonsai pane: the day's or the lifetime tree as large as the pane holds it, redrawn when its size, view or
    token count changes; a click or key switches the view. Tokens are counted every COUNT_EVERY seconds."""
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd) if os.isatty(fd) else None
    if saved:
        tty.setcbreak(fd)  # keys switch the view rather than echo over the tree
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    sys.stdout.write("\x1b[?25l\x1b[?1000h\x1b[?1006h")  # hide the cursor; report clicks
    counts, drawn = {"today": 0, "lifetime": bonsai.stored()}, None
    view = recall("bonsai-view") if recall("bonsai-view") in VIEWS else "today"

    def recount():
        ledger = bonsai.Ledger()  # the first update reads every transcript; later ones only what was appended
        while True:
            ledger.update()
            counts["today"], counts["lifetime"] = bonsai.today(ledger=ledger), bonsai.tokens(ledger)
            time.sleep(COUNT_EVERY)
    threading.Thread(target=recount, daemon=True).start()
    try:
        while True:
            size = os.get_terminal_size()
            if drawn != (view, counts[view], size):
                drawn = (view, counts[view], size)
                lines = tree_lines(counts[view], size.columns - 2, size.lines, view)
                sys.stdout.write("\x1b[H" + "\x1b[K\n".join(lines) + "\x1b[K\x1b[J")
                sys.stdout.flush()
            if not saved:
                time.sleep(1)
            elif select.select([fd], [], [], 1)[0]:
                new = switched(view, keys_of(os.read(fd, 256)))
                if new != view:
                    view = new
                    remember("bonsai-view", view)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[0m\x1b[?25h")
        if saved:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def fit(pane, edge, along, size):
    """Resize a pane to size cells of its width or height by moving its inner edge toward edge; herdr resizes a
    split by a share of the tab."""
    for layout in snapshot().get("layouts") or []:
        rect = next((p["rect"] for p in layout.get("panes", []) if p.get("pane_id") == pane), None)
        whole = (layout.get("area") or {}).get(along)
        if rect and whole:
            herdr("pane", "resize", "--pane", pane, "--direction", edge,
                  "--amount", f"{max(0.0, (rect[along] - size) / whole):.3f}")


def open_tree(nav):
    """Open the bonsai under the nav column, tall enough for the smallest tree and its caption."""
    before = set(panes())
    herdr("plugin", "pane", "open", "--plugin", PLUGIN, "--entrypoint", "tree", "--placement", "split",
          "--direction", "down", "--target-pane", nav, "--no-focus")
    new = next((p for p in panes() if p not in before), "")
    if new:
        fit(new, "down", "height", TREE_HEIGHT)


def open_nav(snap, layout):
    """Open the nav column at the right of a tab with the bonsai under it; its pane id, or '' when herdr refused."""
    target = right_edge(layout, trees(snap))
    before = set(panes(snap))
    herdr("plugin", "pane", "open", "--plugin", PLUGIN, "--entrypoint", "map", "--placement", "split",
          "--direction", "right", "--target-pane", target["pane_id"], "--no-focus")
    new = next((p for p in panes() if p not in before), "")
    if new:
        fit(new, "right", "width", WIDTH)
        if trees(snap):
            carry(snap, None, {"pane_id": new, "tab_id": layout.get("tab_id")})
        else:
            open_tree(new)
    return new


def home_layout(snap):
    """The tab the nav column opens in: the focused one, else the first mate's, else any that can hold it."""
    root_tab = (root_of(panes(snap)) or {}).get("tab_id")
    for tab in [snap.get("focused_tab_id"), root_tab] + [l.get("tab_id") for l in snap.get("layouts", [])]:
        ok, layout = hostable(snap, tab)
        if ok:
            return layout
    return None


def toggle():
    """prefix+m: focus the nav in this tab (bringing it here first), step back out of it when it has focus, or pop
    it up over a zoomed tab."""
    snap = snapshot()
    tab, live = snap.get("focused_tab_id"), navs(snap)
    here = next((p for p in live if p.get("tab_id") == tab), None)
    if here and here["pane_id"] == snap.get("focused_pane_id"):
        last = recall("last-pane")
        if last and last in panes(snap):
            focus_pane(last)
        return
    if here:
        focus_pane(here["pane_id"])
        return
    ok, layout = hostable(snap, tab)
    if ok:
        moved = follow(snap, live[0]) if live else None
        new = moved["pane_id"] if moved else open_nav(snap, layout)
        if new:
            focus_pane(new)
        return
    layout = None if live else home_layout(snap)
    if layout:
        open_nav(snap, layout)
    herdr("plugin", "pane", "open", "--plugin", PLUGIN, "--entrypoint", "pick", "--focus")


def deck():
    """prefix+d: Captain's Deck in its own space, opened beside the focused pane and moved there the first time."""
    snap = snapshot()
    space = next((w for w in snap.get("workspaces", []) if w.get("label") == DECK_SPACE), None)
    if space:
        herdr("workspace", "focus", space["workspace_id"])
        return
    before = set(panes(snap))
    herdr("plugin", "pane", "open", "--plugin", DECK, "--entrypoint", "flow", "--placement", "split", "--no-focus")
    new = next((p for p in panes() if p not in before), "")
    if new:
        herdr("pane", "move", new, "--new-workspace", "--label", DECK_SPACE, "--focus")


def ensure(startup=True):
    """Open the nav column if none is open: at startup once herdr has restored its spaces, and after a space or tab
    closes, which takes the column with it when it was there. At startup the column and its bonsai open fresh: herdr
    restores both as bare shells under their titles, so those panes are closed rather than kept; a bonsai the captain
    closes otherwise stays closed until then. One run at a time, so a space closed by that cleanup opens one column."""
    import fcntl
    for _ in range(30 if startup else 1):
        time.sleep(1)
        snap = snapshot()
        if snap.get("workspaces"):
            break
    else:
        return
    with open(state_path("ensure.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if startup:
            time.sleep(2)  # let restored panes settle, so every restored shell is seen
            snap = snapshot()
            for p in trees(snap) + navs(snap):
                herdr("pane", "close", p["pane_id"])
            time.sleep(0.5)  # a space that held only the column closes with it
        snap = snapshot()
        layout = home_layout(snap)
        if not navs(snap) and layout:
            open_nav(snap, layout)


def main(argv):
    global COLOR
    if "--toggle" in argv:
        return toggle()
    if "--deck" in argv:
        return deck()
    if "--ensure" in argv:
        return ensure(startup=os.environ.get("HERDR_PLUGIN_EVENT", "startup") == "startup")
    if "--tree" in argv:
        return run_tree()
    if "--line" in argv:
        COLOR = False
        print(line_text(fleet()))
        return
    if "--once" in argv:
        COLOR = sys.stdout.isatty()
        width = os.get_terminal_size().columns if sys.stdout.isatty() else WIDTH
        print("\n".join(nav_lines(fleet(), width)[0]))
        return
    run_pane(popup="--popup" in argv)


if __name__ == "__main__":
    main(sys.argv[1:])
