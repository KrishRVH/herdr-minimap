"""The lifetime bonsai: an old, broad tree in the day tree's pixel style, grown by every token the captain has used.
It has more to grow into than the day's tree: ramified branches ending in layered foliage pads, fissured bark with a
deadwood vein and jin, roots spreading over a stone, blossoms and fallen petals, and an accent planting beside it.

  growth(tokens)  0..1: (tokens / MATURE) ** 0.3, quick while young and slower with age; at autumn 2026's pace
                  (about 0.4B tokens a day) it reaches full size in about two years
  pixels(g)       {(x, y): color} for the tree at growth g; one tree at every size, so later growth only adds
Python 3.9, standard library.
"""
import math
import random

from bonsai import noise, ramp

W, H = 48, 30            # the canvas in pixels: 48 cells wide, 15 rows tall
ROWS = H // 2
MATURE = 250e9           # tokens for a full-grown tree
SEED = 11                # which tree: the same one at every size
TRUNK_TOP = 0.45         # growth at which the trunk reaches its full height
BASE_Y, APEX_Y = 25, 2   # where the trunk meets the soil, and its full height

BARK = ("3a281c", "5a3f2c", "7b5a40", "a07d5e")              # shadow, bark, lit, highlight
DEADWOOD = ("aaa190", "e2dccd")                              # shaded, lit
LEAF = ("1b3a27", "2a5535", "3c7242", "5a9552", "8cc170")    # shadow, deep, mid, light, lit
BLOSSOM = ("e79ab3", "f8d6e0")
POT = ("4a2620", "6e3a2c", "93553f")                         # shadow, clay, rim light
SOIL, MOSS, STONE = "3b2a1e", ("4d7432", "7ea548"), ("5f5d58", "86837c", "aba79e")


def growth(tokens):
    return max(0.0, min(1.0, (max(0.0, tokens) / MATURE) ** 0.3))


def trunk_x(y):
    """The trunk's line: a broad informal upright that sweeps right, then back over its roots toward the apex."""
    f = (BASE_Y - y) / (BASE_Y - APEX_Y)
    return W / 2 - 4.5 + 5.5 * math.sin(math.pi * 1.3 * f + 0.15) * (1 - 0.45 * f)


def plan():
    """The grown tree as data: each main branch with its birth, side, attach height, length, droop and rise, and
    its side branches, each with the twigs that come last."""
    rng = random.Random(SEED)
    side, branches = rng.choice((-1, 1)), []
    for i in range(10):
        f = 0.2 + i * 0.075 + rng.uniform(-0.015, 0.015)       # height on the trunk, as a share of its full height
        born = TRUNK_TOP * f ** 1.2 + 0.02 + i * 0.008          # just after the trunk passes it
        length = round(15 - i * 1.1 + rng.uniform(-2, 1.5))
        subs = []
        for j in range(2 if i < 7 else 1):
            twigs = [(rng.uniform(0.4, 0.7), rng.choice((-1, 1)), rng.randint(2, 3)) for _ in range(rng.randint(1, 2))]
            subs.append({"at": 0.38 + j * 0.3 + rng.uniform(-0.05, 0.05), "born": born + 0.12 + j * 0.06,
                         "length": rng.randint(3, 5) if i < 6 else rng.randint(2, 3),
                         "lift": rng.uniform(0.6, 1.2), "pad": rng.uniform(2.2, 3.2), "twigs": twigs})
        branches.append({"y": round(BASE_Y - f * (BASE_Y - APEX_Y)), "born": born, "side": side, "length": length,
                         "droop": rng.uniform(0.5, 2.2) * (1 - i / 11),
                         "rise": 0.1 + i * 0.06 + rng.uniform(-0.05, 0.1),
                         "pad": 4 - i * 0.2 + rng.uniform(-0.3, 0.4), "subs": subs})
        side = -side
    return branches


PLAN = plan()


def pot_span(g):
    width = 20 if g < 0.25 else 28 if g < 0.55 else 36
    return (W - width) // 2 - 2, width


def pot(px, g):
    """A shallow clay tray, repotted wider as the tree grows, with its soil, a moss carpet and, once old, an accent
    planting in a small pot of its own."""
    x0, width = pot_span(g)
    for x in range(x0, x0 + width):                                    # rim
        px[(x, H - 4)] = POT[2] if x < x0 + width // 3 else POT[1]
    for y in (H - 3, H - 2):                                           # body, tapering
        inset = 1 if y == H - 2 else 0
        for x in range(x0 + inset, x0 + width - inset):
            px[(x, y)] = POT[0] if x >= x0 + width - inset - 3 or y == H - 2 else POT[1]
    for x in (x0 + 2, x0 + 3, x0 + width - 4, x0 + width - 3):         # feet
        px[(x, H - 1)] = POT[0]
    moss = ramp(g, 0.25, 0.35)
    for x in range(x0 + 1, x0 + width - 1):                            # soil, then moss, then tufts above it
        px[(x, BASE_Y)] = MOSS[noise(x, BASE_Y, 4) < 0.35] if noise(x, BASE_Y, 3) < 0.85 * moss else SOIL
        if moss > 0.6 and noise(x, BASE_Y - 1, 6) < 0.18 * moss:
            px[(x, BASE_Y - 1)] = MOSS[1]
    if g >= 0.85:                                                      # the accent planting
        ax = x0 + width + 2
        for x in range(ax, ax + 5):
            px[(x, H - 3)] = POT[2] if x == ax else POT[1]
            px[(x, H - 2)] = POT[0]
        for k, x in enumerate(range(ax, ax + 5)):
            for y in range(H - 4, H - 4 - (1, 3, 2, 4, 1)[k], -1):
                px[(x + (y % 2 and k > 2), y)] = MOSS[(k + y) % 2]


def line(wood, start, end, tone):
    """Wood along a straight run, a pixel per step of its longer side."""
    (x0, y0), (x1, y1) = start, end
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    for k in range(steps + 1):
        wood[(round(x0 + (x1 - x0) * k / steps), round(y0 + (y1 - y0) * k / steps))] = tone


def pad(px, cx, cy, rx, g, salt):
    """A cloud of foliage: three lumps around a flattened center, lit from the upper left, in more shades and with
    gaps of sky through it as the tree ages, blossoming last."""
    if rx < 0.6:
        return
    ry = max(1.0, rx * 0.5 + 0.3)
    crown = 0.05 + 0.3 * (noise(salt, 1) - 0.5)                      # where the top lump sits, a little off center
    lumps = [(cx, cy, rx, ry)] + [(cx + dx * rx, cy + dy * ry, rx * 0.62, ry * 0.75)
                                   for dx, dy in ((-0.5, 0.15), (0.5, 0.2), (crown, -0.55))]
    tones = 2 + (g >= 0.3) + (g >= 0.5) + (g >= 0.7)
    bloom = 0.16 * ramp(g, 0.75, 0.25)
    sky = 0.07 * ramp(g, 0.6, 0.2) if rx > 2 else 0
    for y in range(int(cy - 2 * ry - 1), int(cy + ry) + 2):
        for x in range(int(cx - 1.6 * rx), int(cx + 1.6 * rx) + 2):
            if not (0 <= x < W and 0 <= y < H) or not any(((x - lx) / lr) ** 2 + ((y - ly) / lq) ** 2 <= 1
                                                          for lx, ly, lr, lq in lumps):
                continue
            if sky and noise(x, y, 17) < sky and abs(x - cx) < rx * 0.8 and abs(y - cy) < ry * 0.7:
                continue
            v = (y - cy) / ry + (x - cx) / rx * 0.25 + (noise(x, y, 11) - 0.5) * 0.55  # -1 lit .. 1 shade
            shade = 4 if v < -0.8 else 3 if v < -0.25 else 2 if v < 0.3 else 1 if v < 0.75 else 0
            shade = min(max(shade, 0 if tones >= 4 else 1), 4 if tones == 5 else 3 if tones >= 3 else 2)
            px[(x, y)] = BLOSSOM[noise(x, y, 19) < 0.4] if v < 0 and noise(x, y, 13) < bloom else LEAF[shade]


def pixels(g):
    """The lifetime bonsai at growth g in [0, 1]."""
    px = {}
    pot(px, g)
    height = (BASE_Y - APEX_Y) * max(0.06, ramp(g, 0, TRUNK_TOP)) ** 0.8
    top = BASE_Y - max(1, round(height))
    base = 1 + 6 * ramp(g, 0.1, 0.8)
    wood, pads = {}, []
    shari = ramp(g, 0.7, 0.2)                                         # a deadwood vein climbing the trunk
    for y in range(BASE_Y, top - 1, -1):                              # trunk, tapering and flaring at the soil
        f = (BASE_Y - y) / max(height, 1)
        width = max(1, round(base * (1 - 0.78 * f) + 1.5 * ramp(g, 0.5, 0.3) * max(0, 1 - f / 0.15)))
        x0 = round(trunk_x(y)) - (width - 1) // 2
        vein = round(width * (0.5 + 0.2 * math.sin(f * 4))) if width > 3 and f < 0.6 * shari else None
        for i in range(width):
            fissure = g >= 0.5 and 0 < i < width - 1 and noise(x0 + i, y // 2, 5) < 0.28
            tone = BARK[3] if i == 0 and width > 2 else BARK[2] if i <= width // 4 else \
                BARK[0] if i == width - 1 and width > 1 or fissure else BARK[1]
            wood[(x0 + i, y)] = DEADWOOD[i < vein] if vein is not None and vein - 1 <= i <= vein else tone
    spread = round(6 * ramp(g, 0.45, 0.4))                            # roots over the soil
    for dy, reach in ((0, spread), (-1, spread - 3)):
        xs = [x for (x, yy) in wood if yy == BASE_Y + dy]
        for i in range(1, max(0, reach) + 1):
            wood[(min(xs) - i, BASE_Y + dy + (i > reach - 2))] = BARK[2]
            wood[(max(xs) + i, BASE_Y + dy + (i > reach - 2))] = BARK[0]
    if g >= 0.55:                                                     # a stone the roots grip
        sx = round(trunk_x(BASE_Y)) - 9
        for (x, y), tone in {(sx, BASE_Y): 1, (sx + 1, BASE_Y): 1, (sx + 2, BASE_Y): 0, (sx + 1, BASE_Y - 1): 2,
                             (sx, BASE_Y - 1): 2}.items():
            px[(x, y)] = STONE[tone]
    for k in range(1, 1 + round(4 * ramp(g, 0.8, 0.15))):            # jin: an old leader, bleached
        wood[(round(trunk_x(top)) + k // 2, top - k)] = DEADWOOD[k % 2]
    for b in PLAN:
        reach = round(b["length"] * ramp(g, b["born"], 0.18))
        if reach < 1 or b["y"] < top:
            continue
        x0, length = round(trunk_x(b["y"])), b["length"]
        path = [(x0 + b["side"] * k, b["y"] + round(b["droop"] * math.sin(math.pi * k / length) - b["rise"] * k))
                for k in range(1, reach + 1)]                          # dipping, then lifting to its pad
        for k, (x, y) in enumerate(path):
            wood[(x, y)] = BARK[1]
            if g >= 0.45 and k < len(path) * (0.25 + 0.3 * ramp(g, 0.45, 0.4)):
                wood[(x, y + 1)] = BARK[0]                             # thicker toward the trunk
        tip = path[-1]
        pads.append((tip[0] + b["side"], tip[1] - 1, 1.2 + (b["pad"] - 1.2) * ramp(g, b["born"] + 0.04, 0.3)))
        for s in b["subs"]:
            grown = round(s["length"] * ramp(g, s["born"], 0.12))
            if grown < 1 or len(path) < 3:
                continue
            start = path[min(len(path) - 1, int(len(path) * s["at"]))]
            end = (start[0] + b["side"] * round(grown * 0.7), start[1] - round(grown * s["lift"]))
            line(wood, start, end, BARK[1])
            pads.append((end[0], end[1] - 1, 1 + (s["pad"] - 1) * ramp(g, s["born"] + 0.04, 0.2)))
            for at, turn, twig in s["twigs"]:
                grown = round(twig * ramp(g, s["born"] + 0.2, 0.12))
                if grown < 1:
                    continue
                fork = (round(start[0] + (end[0] - start[0]) * at), round(start[1] + (end[1] - start[1]) * at))
                tip = (fork[0] + b["side"] * turn * grown, fork[1] - grown)
                line(wood, fork, tip, BARK[2])
                pads.append((tip[0], tip[1] - 1, 1 + 0.9 * ramp(g, s["born"] + 0.24, 0.15)))
    pads.append((round(trunk_x(top)) - 1, top - 1, 1 + 3.6 * ramp(g, 0.0, 0.7)))  # the apex, first a sprout's leaves
    px.update((p, c) for p, c in wood.items() if 0 <= p[0] < W and 0 <= p[1] < H)
    for n, (cx, cy, rx) in enumerate(sorted(pads, key=lambda p: -p[1])):  # lower pads first, higher ones in front
        pad(px, cx, cy, rx, g, n)
    if g >= 0.9:                                                      # petals fallen on the moss
        x0, width = pot_span(g)
        for x in range(x0 + 1, x0 + width - 1):
            if noise(x, BASE_Y, 23) < 0.08 and px.get((x, BASE_Y)) in MOSS + (SOIL,):
                px[(x, BASE_Y)] = BLOSSOM[1]
    return px
