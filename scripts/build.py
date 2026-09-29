#!/usr/bin/env python3
"""
Renders every image used by the profile README into ./dist.

    python scripts/build.py                       # live GitHub data (needs GITHUB_TOKEN)
    python scripts/build.py --demo                # made-up numbers, for local previews
    python scripts/build.py --snake dist/snake-raw.svg   # also restyle the snk output

Every SVG carries its own subset of the fonts (Doto + Martian Mono, both OFL) as
base64 WOFF2, so the README looks the same everywhere and doesn't depend on a
third-party card service staying online.

Only dependency: fonttools + brotli  (pip install fonttools brotli)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import json
import os
import random
import re
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools import subset
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# ── palette: amber phosphor on warm black ────────────────────────────────────
BG = "#0B0908"
PANEL = "#110E0C"
RAISED = "#17130F"
EDGE = "#2C2119"
GRID = "#1E1813"
MUTE = "#6B5A4B"
DIM = "#9A8471"
TEXT = "#EDE2D6"
AMBER = "#FF9A3C"
DEEP = "#E6813A"
HOT = "#FFDDB0"
LEVELS = ["#1C1612", "#4E2B11", "#8F4614", "#DB6B1D", "#FFB55F"]  # contribution 0..4

W = 860  # design width of full-width cards


# ── fonts ────────────────────────────────────────────────────────────────────
class Font:
    def __init__(self, family: str, file: str):
        self.family = family
        self.path = HERE / "fonts" / file
        self.tt = TTFont(self.path)
        self.upm = self.tt["head"].unitsPerEm
        self.cmap = self.tt.getBestCmap()
        self.hmtx = self.tt["hmtx"]
        self.fallback = self.hmtx[self.cmap[ord(" ")]][0]

    def width(self, s: str, size: float, ls: float = 0.0) -> float:
        units = sum(self.hmtx[self.cmap[ord(c)]][0] if ord(c) in self.cmap else self.fallback for c in s)
        return units * size / self.upm + ls * len(s)

    def face(self, chars: set[str]) -> str:
        f = TTFont(self.path)
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["kern", "liga", "calt", "tnum"]
        opts.notdef_outline = True
        sub = subset.Subsetter(opts)
        sub.populate(text="".join(sorted(chars | {" "})))
        sub.subset(f)
        buf = io.BytesIO()
        f.flavor = "woff2"
        f.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"@font-face{{font-family:'{self.family}';src:url(data:font/woff2;base64,{b64}) format('woff2')}}"


FONTS = {
    "dot": Font("kv-dot", "Doto-Black.ttf"),
    "mono": Font("kv-mono", "MartianMono-Regular.ttf"),
    "bold": Font("kv-mono-b", "MartianMono-Bold.ttf"),
}


def tw(s: str, font: str = "mono", size: float = 12, ls: float = 0) -> float:
    return FONTS[font].width(s, size, ls)


def wrap(s: str, maxw: float, font: str = "mono", size: float = 12) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        trial = f"{cur} {word}".strip()
        if cur and tw(trial, font, size) > maxw:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def n(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


# ── svg builder ──────────────────────────────────────────────────────────────
class Svg:
    def __init__(self, w: float, h: float, label: str, viewbox: str | None = None):
        self.w, self.h, self.label = w, h, label
        self.viewbox = viewbox or f"0 0 {n(w)} {n(h)}"
        self.body: list[str] = []
        self.defs: list[str] = []
        self.css: list[str] = []
        self.used: dict[str, set[str]] = {k: set() for k in FONTS}

    def add(self, *parts: str) -> "Svg":
        self.body.extend(parts)
        return self

    def t(self, x, y, s, font="mono", size=12, fill=TEXT, anchor="start", ls=0.0, extra="") -> str:
        self.used[font].update(s)
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        spacing = f' letter-spacing="{n(ls)}"' if ls else ""
        return (f'<text x="{n(x)}" y="{n(y)}" class="{font}" font-size="{n(size)}" fill="{fill}"'
                f'{a}{spacing}{extra}>{escape(s)}</text>')

    def text(self, *a, **k) -> "Svg":
        return self.add(self.t(*a, **k))

    def render(self) -> str:
        faces = "".join(FONTS[k].face(ch) for k, ch in self.used.items() if ch)
        classes = "".join(f".{k}{{font-family:'{f.family}',ui-monospace,monospace}}" for k, f in FONTS.items())
        vb = [float(v) for v in self.viewbox.split()]
        big = f'x="{n(vb[0] - vb[2])}" y="{n(vb[1] - vb[3])}" width="{n(vb[2] * 3)}" height="{n(vb[3] * 3)}"'
        defs = (
            f'<filter id="glow" filterUnits="userSpaceOnUse" {big} color-interpolation-filters="sRGB">'
            '<feGaussianBlur stdDeviation="2.2" result="a"/>'
            '<feMerge><feMergeNode in="a"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
            f'<filter id="bloom" filterUnits="userSpaceOnUse" {big} color-interpolation-filters="sRGB">'
            '<feGaussianBlur stdDeviation="9" result="a"/>'
            '<feGaussianBlur in="SourceGraphic" stdDeviation="2.4" result="b"/>'
            '<feComponentTransfer in="a" result="a2"><feFuncA type="linear" slope="0.8"/></feComponentTransfer>'
            '<feMerge><feMergeNode in="a2"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
            '<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">'
            '<rect width="4" height="1" fill="#FFFFFF" opacity=".022"/></pattern>'
            f'<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">'
            f'<circle cx="1.5" cy="1.5" r="1.1" fill="{GRID}"/></pattern>'
            + "".join(self.defs)
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{n(self.w)}" height="{n(self.h)}" '
            f'viewBox="{self.viewbox}" role="img" aria-label="{escape(self.label)}" fill="none">'
            f"<title>{escape(self.label)}</title>"
            f"<style>{faces}{classes}{''.join(self.css)}</style>"
            f"<defs>{defs}</defs>{''.join(self.body)}</svg>"
        )


def panel(s: Svg, x, y, w, h, label=None, right=None, r=14, dots=False):
    s.add(f'<rect x="{n(x + .5)}" y="{n(y + .5)}" width="{n(w - 1)}" height="{n(h - 1)}" rx="{r}" fill="{PANEL}" stroke="{EDGE}"/>')
    if dots:
        s.add(f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="{r}" fill="url(#dots)"/>')
    s.add(f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="{r}" fill="url(#scan)"/>')
    # HUD corner ticks
    k, o = 9, 7
    ticks = [
        f"M{x + o} {y + o + k}V{y + o}H{x + o + k}",
        f"M{x + w - o - k} {y + o}H{x + w - o}V{y + o + k}",
        f"M{x + o} {y + h - o - k}V{y + h - o}H{x + o + k}",
        f"M{x + w - o - k} {y + h - o}H{x + w - o}V{y + h - o - k}",
    ]
    s.add(f'<path d="{" ".join(ticks)}" stroke="{AMBER}" stroke-width="1.2" opacity=".55"/>')
    if label:
        s.add(f'<rect x="{n(x + 24)}" y="{n(y + 21)}" width="6" height="6" fill="{AMBER}" filter="url(#glow)"/>')
        s.text(x + 38, y + 28, label.upper(), "mono", 10, DIM, ls=1.6)
    if right:
        s.text(x + w - 24, y + 28, right.upper(), "mono", 10, MUTE, "end", ls=1.2)


def icon(slug: str, x, y, size, fill) -> str:
    """Simple Icons glyph (24×24 viewBox) placed at x,y. Missing icons are fetched once."""
    path = HERE / "icons" / f"{slug}.svg"
    if not path.exists():
        try:
            url = f"https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/{slug}.svg"
            path.write_bytes(urllib.request.urlopen(url, timeout=20).read())
        except Exception as e:  # noqa: BLE001
            print(f"  ! icon '{slug}' unavailable ({e}); drawing a placeholder", file=sys.stderr)
            return square(x + size * .3, y + size * .3, size * .4, fill)
    d = re.search(r'<path d="([^"]+)"', path.read_text()).group(1)
    return f'<path transform="translate({n(x)} {n(y)}) scale({n(size / 24)})" d="{d}" fill="{fill}"/>'


GLOW = ' filter="url(#glow)"'
BLOOM = ' filter="url(#bloom)"'
DASH = ' stroke-dasharray="2 4"'


def square(x, y, size, fill) -> str:
    return f'<rect x="{n(x)}" y="{n(y)}" width="{n(size)}" height="{n(size)}" fill="{fill}"/>'


# ── static cards ─────────────────────────────────────────────────────────────
def hero(cfg) -> Svg:
    H = 300
    s = Svg(W, H, f"{' '.join(cfg['name']).title()} — {cfg['roles'][0]}")
    s.defs.append(
        f'<radialGradient id="halo" cx=".22" cy=".5" r=".55"><stop offset="0" stop-color="{AMBER}" stop-opacity=".13"/>'
        f'<stop offset="1" stop-color="{AMBER}" stop-opacity="0"/></radialGradient>'
    )
    s.add(f'<rect width="{W}" height="{H}" rx="16" fill="{BG}"/>')
    s.add(f'<rect width="{W}" height="{H}" rx="16" fill="url(#dots)"/>')
    s.add(f'<rect width="{W}" height="{H}" rx="16" fill="url(#halo)"/>')
    s.add(f'<rect width="{W}" height="{H}" rx="16" fill="url(#scan)"/>')
    s.add(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="16" stroke="{EDGE}"/>')
    k, o = 10, 8
    s.add(f'<path d="M{o} {o + k}V{o}H{o + k} M{W - o - k} {o}H{W - o}V{o + k} M{o} {H - o - k}V{H - o}H{o + k} '
          f'M{W - o - k} {H - o}H{W - o}V{H - o - k}" stroke="{AMBER}" stroke-width="1.3" opacity=".6"/>')

    x0 = 36
    user, _, cmd = cfg["prompt"].partition("$")
    s.add(f'<text x="{x0}" y="46" class="mono" font-size="11.5">'
          f'<tspan fill="{AMBER}">{escape(user)}</tspan><tspan fill="{MUTE}">$</tspan>'
          f'<tspan fill="{DIM}">{escape(cmd)}</tspan></text>')
    s.used["mono"].update(cfg["prompt"])

    # name — dot-matrix, bloomed
    size = 78
    s.add('<g filter="url(#bloom)">',
          s.t(x0 - 3, 124, cfg["name"][0], "dot", size, AMBER, ls=3),
          s.t(x0 - 3, 196, cfg["name"][1], "dot", size, AMBER, ls=3),
          "</g>")

    # typing roles (SMIL, discrete steps → works in <img> on every major browser)
    ty, tsize = 240, 14
    prefix = "> "
    px = x0 + tw(prefix, "bold", tsize)
    cw = tw("M", "mono", tsize)
    roles = cfg["roles"]
    slots, t = [], 0.0
    TYPE, HOLD, ERASE, GAP = .055, 1.9, .022, .35
    for r in roles:
        dur = len(r) * TYPE + HOLD + len(r) * ERASE + GAP
        slots.append((t, t + dur, r))
        t += dur
    total = t
    times, widths = [0.0], [0.0]
    for start, _end, r in slots:
        for k2 in range(len(r) + 1):
            times.append(start + k2 * TYPE)
            widths.append(k2 * cw)
        e0 = start + len(r) * TYPE + HOLD
        for j in range(1, len(r) + 1):
            times.append(e0 + j * ERASE)
            widths.append((len(r) - j) * cw)
    pairs = sorted({round(tt / total, 5): w for tt, w in zip(times, widths)}.items())
    kt = ";".join(n(p[0]) for p in pairs)
    wv = ";".join(n(p[1]) for p in pairs)
    xv = ";".join(n(px + p[1]) for p in pairs)
    s.defs.append(f'<clipPath id="type"><rect x="{n(px)}" y="{ty - 18}" height="26" width="0">'
                  f'<animate attributeName="width" dur="{n(total)}s" repeatCount="indefinite" calcMode="discrete" '
                  f'keyTimes="{kt}" values="{wv}"/></rect></clipPath>')
    s.text(x0, ty, prefix, "bold", tsize, AMBER)
    lines = []
    for start, end, r in slots:
        a, b = round(start / total, 5), round(end / total, 5)
        if a == 0:
            kt2, vals = f"0;{n(b)}", "1;0"
        else:
            kt2, vals = f"0;{n(a)};{n(b)}", "0;1;0"
        lines.append(s.t(px, ty, r, "mono", tsize, HOT,
                         extra=f' opacity="{1 if a == 0 else 0}"').replace(
            "</text>", f'<animate attributeName="opacity" dur="{n(total)}s" repeatCount="indefinite" '
                       f'calcMode="discrete" keyTimes="{kt2}" values="{vals}"/></text>'))
    s.add('<g clip-path="url(#type)" filter="url(#glow)">', *lines, "</g>")
    s.add(f'<rect x="{n(px)}" y="{ty - 13}" width="{n(cw * .62)}" height="16" fill="{AMBER}" filter="url(#glow)">'
          f'<animate attributeName="x" dur="{n(total)}s" repeatCount="indefinite" calcMode="discrete" keyTimes="{kt}" values="{xv}"/>'
          f'<animate attributeName="opacity" dur="1s" repeatCount="indefinite" calcMode="discrete" keyTimes="0;.5" values="1;0"/></rect>')

    s.text(x0, 276, cfg["meta"], "mono", 9.5, DIM, ls=1.3)

    # right: live request path (Proxima topology)
    topology(s, 540, 40)
    return s


def topology(s: Svg, ox, oy):
    s.add(f'<rect x="{ox}" y="{oy}" width="292" height="222" rx="10" fill="{PANEL}" fill-opacity=".72" '
          f'stroke="{EDGE}" stroke-dasharray="3 4"/>')
    s.text(ox + 14, oy + 22, "PROXIMA · REQUEST PATH", "mono", 9, DIM, ls=1.4)
    led_live = (f'<circle cx="{ox + 272}" cy="{oy + 19}" r="3" fill="{AMBER}" filter="url(#glow)">'
                '<animate attributeName="opacity" values="1;.25;1" dur="1.6s" repeatCount="indefinite"/></circle>')
    s.add(led_live)

    cy = oy + 128
    clients = [(ox + 24, cy - 52), (ox + 24, cy), (ox + 24, cy + 52)]
    lb = (ox + 64, cy - 24, 62, 48)                      # nginx
    nodes = [(ox + 152, cy - 58), (ox + 152, cy - 15), (ox + 152, cy + 28)]  # node boxes (x,y top)
    NW, NH = 54, 30
    redis = (ox + 228, cy - 52, 52, 34)
    pg = (ox + 228, cy + 18, 52, 34)

    def box(x, y, w, h, label, sub=None, hot=False):
        s.add(f'<rect x="{n(x)}" y="{n(y)}" width="{w}" height="{h}" rx="5" fill="{RAISED}" '
              f'stroke="{AMBER if hot else EDGE}" stroke-opacity="{.8 if hot else 1}"/>')
        s.text(x + w / 2, y + (h / 2 + (0 if sub else 3.5)), label, "bold", 9.5, TEXT, "middle")
        if sub:
            s.text(x + w / 2, y + h / 2 + 11, sub, "mono", 8, DIM, "middle")

    wires = []
    for cx_, cy_ in clients:
        wires.append(f"M{cx_ + 8} {cy_}L{lb[0]} {lb[1] + lb[3] / 2}")
    for nx, ny in nodes:
        wires.append(f"M{lb[0] + lb[2]} {lb[1] + lb[3] / 2}L{nx} {ny + NH / 2}")
        wires.append(f"M{nx + NW} {ny + NH / 2}L{redis[0]} {redis[1] + redis[3] / 2}")
        wires.append(f"M{nx + NW} {ny + NH / 2}L{pg[0]} {pg[1] + pg[3] / 2}")
    s.add(f'<path d="{" ".join(wires)}" stroke="{EDGE}" stroke-width="1.2"/>')

    def mid(b):
        return b[0], b[1] + b[3] / 2

    lbin, lbout = (lb[0], lb[1] + lb[3] / 2), (lb[0] + lb[2], lb[1] + lb[3] / 2)
    nin = [(x, y + NH / 2) for x, y in nodes]
    nout = [(x + NW, y + NH / 2) for x, y in nodes]
    rin, pin = mid(redis), mid(pg)

    def route(*pts):
        return "M" + " L".join(f"{n(a)} {n(b)}" for a, b in pts)

    c = [(x + 8, y) for x, y in clients]
    packets = [
        (route(c[0], lbin, lbout, nin[0], nout[0], rin), 2.6, 0, HOT),
        (route(c[2], lbin, lbout, nin[1], nout[1], pin), 2.6, .9, HOT),
        (route(c[1], lbin, lbout, nin[2], nout[2], rin), 2.6, 1.8, HOT),
        # pub/sub fan-out: redis → every replica
        (route(rin, nout[0]), 1.3, 1.3, AMBER),
        (route(rin, nout[1]), 1.3, 1.3, AMBER),
        (route(rin, nout[2]), 1.3, 1.3, AMBER),
    ]
    for d, dur, begin, col in packets:
        s.add(f'<circle r="2.6" fill="{col}" filter="url(#glow)" opacity="0">'
              f'<animateMotion path="{d}" dur="{dur}s" begin="{begin}s" repeatCount="indefinite"/>'
              f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.08;.9;1" dur="{dur}s" '
              f'begin="{begin}s" repeatCount="indefinite"/></circle>')
    for cx_, cy_ in clients:
        s.add(f'<circle cx="{cx_}" cy="{cy_}" r="8" fill="{RAISED}" stroke="{EDGE}"/>'
              f'<circle cx="{cx_}" cy="{cy_}" r="2.4" fill="{DIM}"/>')
    s.text(ox + 26, oy + 50, "clients", "mono", 8.5, DIM, "middle")
    box(*lb, "nginx", "L7 · tls", hot=True)
    for i, (nx, ny) in enumerate(nodes):
        box(nx, ny, NW, NH, f"node·{i + 1}")
    box(*redis, "redis", "pub/sub")
    box(*pg, "postgres", "primary")

    s.text(ox + 14, oy + 210, "stateless replicas · sticky sessions · fan-out", "mono", 8, DIM, ls=.2)


def section(num: int, title: str, note: str) -> Svg:
    H = 56
    s = Svg(W, H, f"{num:02d} {title}")
    s.add(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="12" fill="{PANEL}" stroke="{EDGE}"/>',
          f'<rect width="{W}" height="{H}" rx="12" fill="url(#scan)"/>')
    s.add('<g filter="url(#bloom)">', s.t(24, 39, f"{num:02d}", "dot", 30, AMBER, ls=1), "</g>")
    tx = 24 + tw(f"{num:02d}", "dot", 30, 1) + 16
    s.text(tx, 33, title.upper(), "bold", 14, TEXT, ls=3.2)
    lx = tx + tw(title.upper(), "bold", 14, 3.2) + 18
    nx = W - 24 - tw(note, "mono", 10.5)
    s.add(f'<path d="M{n(lx)} 28.5H{n(nx - 18)}" stroke="{EDGE}" stroke-dasharray="2 5"/>')
    s.text(W - 24, 32, note, "mono", 10.5, DIM, "end")
    return s


def about(cfg) -> Svg:
    """Full-width terminal card: about.txt on the left, now.txt on the right."""
    size, lh = 11.5, 19
    lx, split, rx = 28, 454, 486          # left text x, divider x, right column x
    summary = wrap(cfg["about"]["summary"], split - lx - 26, "mono", size)
    keyw = max(tw(k, "bold", size) for k, _ in cfg["about"]["now"]) + 16
    vx = rx + 14 + keyw
    now_rows = [(k, wrap(v, W - 28 - vx, "mono", size)) for k, v in cfg["about"]["now"]]
    rows_left = 1 + len(summary)
    rows_right = 1 + sum(len(v) for _, v in now_rows) + 1
    H = 62 + max(rows_left, rows_right) * lh + 18
    s = Svg(W, H, "about: " + cfg["about"]["summary"] + " Now: "
            + "; ".join(f"{k} {v}" for k, v in cfg["about"]["now"]))
    panel(s, 0, 0, W, H, "~/about", "zsh")
    s.add(f'<path d="M{split} 52V{H - 22}" stroke="{EDGE}" stroke-dasharray="2 4"/>')

    def prompt(x, y, cmd):
        s.add(f'<text x="{x}" y="{y}" class="mono" font-size="{size}"><tspan fill="{AMBER}">$</tspan>'
              f'<tspan fill="{DIM}"> {escape(cmd)}</tspan></text>')
        s.used["mono"].update("$ " + cmd)

    y = 66
    prompt(lx, y, "cat about.txt")
    for line in summary:
        y += lh
        s.text(lx, y, line, "mono", size, TEXT)

    y = 66
    prompt(rx, y, "cat now.txt")
    for k, vals in now_rows:
        y += lh
        s.add(f'<path d="M{rx} {y - 8.5}l5 3.5-5 3.5z" fill="{AMBER}" filter="url(#glow)"/>')
        s.text(rx + 14, y, k, "bold", size, AMBER)
        for i, v in enumerate(vals):
            if i:
                y += lh
            s.text(vx, y, v, "mono", size, TEXT)
    y += lh
    s.add(f'<text x="{rx}" y="{y}" class="mono" font-size="{size}" fill="{AMBER}">$</text>')
    s.add(f'<rect x="{n(rx + tw("$ ", "mono", size))}" y="{y - 11}" width="7" height="14" fill="{AMBER}" filter="url(#glow)">'
          '<animate attributeName="opacity" dur="1.05s" repeatCount="indefinite" calcMode="discrete" keyTimes="0;.5" values="1;0"/></rect>')
    return s


def stack(cfg) -> Svg:
    x0, lw, ph, gap, rowgap, isz, fsz = 26, 124, 28, 8, 10, 13, 11
    maxx = W - 26
    rows, y = [], 60
    for cat, items in cfg["stack"]:
        pills, x = [], x0 + lw
        for slug, label in items:
            pw = 12 + isz + 8 + tw(label, "mono", fsz) + 12
            if x + pw > maxx:
                y += ph + gap
                x = x0 + lw
            pills.append((x, y, pw, slug, label))
            x += pw + gap
        rows.append((cat, pills, pills[0][1]))
        y += ph + rowgap + 6
    H = y + 8
    count = sum(len(i) for _, i in cfg["stack"])
    s = Svg(W, H, "tech stack: " + ", ".join(l for _, items in cfg["stack"] for _, l in items))
    panel(s, 0, 0, W, H, "backend-first", f"{count} tools")
    for i, (cat, pills, ry) in enumerate(rows):
        s.text(x0 + 2, ry + 18.5, cat.upper(), "mono", 9.5, DIM if i else AMBER, ls=1.5)
        for x, y2, pw, slug, label in pills:
            s.add(f'<rect x="{n(x + .5)}" y="{n(y2 + .5)}" width="{n(pw - 1)}" height="{ph - 1}" rx="6" fill="{RAISED}" stroke="{EDGE}"/>')
            if slug:
                s.add(f'<g filter="url(#glow)">{icon(slug, x + 12, y2 + (ph - isz) / 2, isz, AMBER)}</g>')
            else:
                s.add(f'<g filter="url(#glow)">{square(x + 12 + 3.5, y2 + ph / 2 - 3, 6, AMBER)}</g>')
            s.text(x + 12 + isz + 8, y2 + ph / 2 + 4, label, "mono", fsz, TEXT)
        if i < len(rows) - 1:
            s.add(f'<path d="M{x0} {n(pills[-1][1] + ph + rowgap / 2 + 4)}H{maxx}" stroke="{GRID}"/>')
    return s


def experience(cfg) -> Svg:
    x0, size, lh = 64, 11.5, 18.5
    maxw = W - x0 - 32
    blocks, y = [], 64
    for e in cfg["experience"]:
        pts = [wrap(p, maxw - 16, "mono", size) for p in e["points"]]
        h = 22 + 20 + sum(len(p) for p in pts) * lh + 6 * (len(pts) - 1)
        blocks.append((e, pts, y, h))
        y += h + 26
    H = y - 6
    s = Svg(W, H, "experience: " + "; ".join(f"{e['role']} at {e['org']} ({e['when']})" for e in cfg["experience"]))
    panel(s, 0, 0, W, H, "git log --graph", f"{len(blocks)} roles")
    s.add(f'<path d="M36 {blocks[0][2] - 4}V{blocks[-1][2] + 8}" stroke="{EDGE}" stroke-width="1.5"/>')
    for e, pts, y, h in blocks:
        live = "now" in e["when"].lower()
        if live:
            s.add(f'<circle cx="36" cy="{y - 4}" r="5" fill="{AMBER}" filter="url(#glow)">'
                  '<animate attributeName="opacity" values="1;.35;1" dur="1.8s" repeatCount="indefinite"/></circle>')
        else:
            s.add(f'<circle cx="36" cy="{y - 4}" r="4.5" fill="{PANEL}" stroke="{AMBER}" stroke-width="1.5"/>')
        s.text(x0, y, e["org"], "bold", 13, TEXT, ls=1.4)
        s.text(W - 32, y, f"{e['when']}  ·  {e['where']}", "mono", 10, DIM, "end")
        s.text(x0, y + 21, e["role"], "mono", 11.5, AMBER)
        yy = y + 21 + 22
        for lines in pts:
            s.text(x0, yy, "›", "mono", size, MUTE)
            for ln in lines:
                s.text(x0 + 16, yy, ln, "mono", size, TEXT if ln == lines[0] else TEXT)
                yy += lh
            yy += 6
    return s


def tag_row(s: Svg, x, y, tags, maxx, size=9.5) -> float:
    for tag in tags:
        w = tw(tag, "mono", size) + 16
        if x + w > maxx:
            break
        s.add(f'<rect x="{n(x + .5)}" y="{n(y + .5)}" width="{n(w - 1)}" height="21" rx="10.5" fill="none" stroke="{EDGE}"/>')
        s.text(x + 8, y + 14.5, tag, "mono", size, DIM)
        x += w + 6
    return x


def project_featured(p) -> Svg:
    size, lh = 11.5, 19
    lines = [wrap(pt, W - 60 - 32, "mono", size) for pt in p["points"]]
    H = 146 + sum(len(l) for l in lines) * lh + 4 * len(lines) + 52
    s = Svg(W, H, f"{p['name']}: {p['tagline']}. " + " ".join(p["points"]))
    panel(s, 0, 0, W, H, "featured system", p["url"].replace("https://", "") + "  ↗")
    s.add('<g filter="url(#bloom)">', s.t(26, 90, p["name"], "dot", 46, AMBER, ls=2), "</g>")
    s.text(28, 114, "// " + p["tagline"], "mono", 12, DIM)
    # highlight chips (right)
    cx = W - 26
    for chip in reversed(p.get("chips", [])):
        w = tw(chip.upper(), "bold", 9, 1) + 22
        cx -= w
        s.add(f'<rect x="{n(cx + .5)}" y="62.5" width="{n(w - 1)}" height="23" rx="4" fill="{AMBER}" fill-opacity=".08" stroke="{AMBER}" stroke-opacity=".55"/>')
        s.text(cx + 11, 78, chip.upper(), "bold", 9, HOT, ls=1)
        cx -= 8
    y = 152
    for ls_ in lines:
        s.add(f'<path d="M30 {y - 8.5}l5 3.5-5 3.5z" fill="{AMBER}"/>')
        for ln in ls_:
            s.text(44, y, ln, "mono", size, TEXT)
            y += lh
        y += 4
    tag_row(s, 26, H - 44, p["tags"], W - 26)
    return s


def project_cards(projects) -> list[tuple[str, Svg]]:
    CW, size, lh = 424, 11, 17.5
    prepared = []
    for p in projects:
        pts = [wrap(pt, CW - 70, "mono", size) for pt in p["points"]]
        prepared.append((p, pts))
    H = max(124 + sum(len(l) for l in pts) * lh + 4 * len(pts) + 58 for _, pts in prepared)
    out = []
    for p, pts in prepared:
        s = Svg(CW, H, f"{p['name']}: {p['tagline']}. " + " ".join(p["points"]))
        panel(s, 0, 0, CW, H, "project", "↗")
        s.add('<g filter="url(#bloom)">', s.t(24, 78, p["name"], "dot", 27, AMBER, ls=1), "</g>")
        s.text(24, 100, "// " + p["tagline"], "mono", 10.5, DIM)
        y = 130
        for ls_ in pts:
            s.add(f'<path d="M28 {y - 8}l4.5 3.2-4.5 3.2z" fill="{AMBER}"/>')
            for ln in ls_:
                s.text(40, y, ln, "mono", size, TEXT)
                y += lh
            y += 4
        tag_row(s, 24, H - 42, p["tags"], CW - 24, 9)
        out.append((p["id"], s))
    return out


def achievements(cfg) -> Svg:
    rows = cfg["achievements"]
    x_date, x_rank, x_event = 30, 116, 290
    rh = 38
    H = 62 + len(rows) * rh + 12
    s = Svg(W, H, "achievements: " + "; ".join(f"{r[1].title()}, {r[2]}" + (f" ({r[3]})" if r[3] else "") for r in rows))
    panel(s, 0, 0, W, H, "hackathons", f"{len(rows)} podiums & finals")
    y = 62
    for date, rank, event, note, star in rows:
        if star:
            s.add(f'<rect x="14" y="{y - 1}" width="{W - 28}" height="{rh - 4}" rx="8" fill="{AMBER}" fill-opacity=".07" stroke="{AMBER}" stroke-opacity=".35"/>')
        cy = y + rh / 2 - 2
        s.text(x_date, cy + 4, date, "mono", 10.5, DIM)
        s.text(x_rank, cy + 4, rank, "bold", 11, HOT if star else AMBER, ls=1.2,
               extra=' filter="url(#glow)"' if star else "")
        ev = event
        room = (W - 30 - (tw(note, "mono", 10.5) + 20 if note else 0)) - x_event
        while tw(ev, "mono", 11.5) > room and len(ev) > 4:
            ev = ev[:-2].rstrip() + "…"
        s.text(x_event, cy + 4, ev, "mono", 11.5, TEXT)
        if note:
            s.text(W - 30, cy + 4, note, "mono", 10.5, AMBER if star else DIM, "end")
        if star:
            cx0, cy0, r1, r2 = x_rank - 16, cy, 6, 2.6
            import math
            pts = " ".join(
                f"{n(cx0 + (r1 if i % 2 == 0 else r2) * math.sin(i * math.pi / 5))},{n(cy0 - (r1 if i % 2 == 0 else r2) * math.cos(i * math.pi / 5))}"
                for i in range(10))
            s.add(f'<polygon points="{pts}" fill="{AMBER}" filter="url(#glow)"/>')
        y += rh
    return s


def buttons(cfg) -> list[tuple[str, Svg]]:
    out = []
    for key, slug, label, _url in cfg["links"]:
        isz, fsz, H = 13, 10, 30
        w = 12 + isz + 9 + tw(label, "bold", fsz, 1.3) + 8 + tw("↗", "mono", fsz) + 12
        s = Svg(w, H, label.title())
        s.add(f'<rect x=".5" y=".5" width="{n(w - 1)}" height="{H - 1}" rx="8" fill="{PANEL}" stroke="{EDGE}"/>')
        ix, iy = 12, (H - isz) / 2
        if slug:
            s.add(f'<g filter="url(#glow)">{icon(slug, ix, iy, isz, AMBER)}</g>')
        elif key == "linkedin":
            s.add(f'<g filter="url(#glow)"><rect x="{ix}" y="{n(iy)}" width="{isz}" height="{isz}" rx="2.5" fill="{AMBER}"/></g>',
                  s.t(ix + isz / 2, iy + isz - 3, "in", "bold", 8.5, PANEL, "middle"))
        else:  # globe
            c = ix + isz / 2
            s.add(f'<g filter="url(#glow)" stroke="{AMBER}" stroke-width="1.3" fill="none">'
                  f'<circle cx="{n(c)}" cy="{H / 2}" r="{n(isz / 2 - .5)}"/>'
                  f'<ellipse cx="{n(c)}" cy="{H / 2}" rx="{n(isz / 4)}" ry="{n(isz / 2 - .5)}"/>'
                  f'<path d="M{n(ix + .5)} {H / 2}H{n(ix + isz - .5)}"/></g>')
        s.text(ix + isz + 9, H / 2 + 3.6, label, "bold", fsz, TEXT, ls=1.3)
        s.text(w - 12, H / 2 + 3.6, "↗", "mono", fsz, DIM, "end")
        out.append((key, s))
    return out


# ── live data ────────────────────────────────────────────────────────────────
def gql(query: str, token: str, variables: dict | None = None) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "profile-readme-renderer"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    if payload.get("errors"):
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    return payload["data"]


PROFILE_Q = """
query($login: String!) {
  user(login: $login) {
    login createdAt
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name } } }
      }
    }
  }
}"""

YEAR_FRAGMENT = """
fragment F on ContributionsCollection {
  totalCommitContributions totalPullRequestReviewContributions
  contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
}"""


def fetch(login: str, token: str) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    u = gql(PROFILE_Q, token, {"login": login})["user"]
    first = int(u["createdAt"][:4])
    parts = []
    for yr in range(first, now.year + 1):
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ") if yr == now.year else f"{yr}-12-31T23:59:59Z"
        parts.append(f'y{yr}: contributionsCollection(from: "{yr}-01-01T00:00:00Z", to: "{end}") {{ ...F }}')
    parts.append("recent: contributionsCollection { ...F }")
    q = "query($login: String!) { user(login: $login) { " + " ".join(parts) + " } }" + YEAR_FRAGMENT
    cc = gql(q, token, {"login": login})["user"]

    days: dict[str, int] = {}
    total = reviews = 0
    for yr in range(first, now.year + 1):
        c = cc[f"y{yr}"]
        total += c["contributionCalendar"]["totalContributions"]
        reviews += c["totalPullRequestReviewContributions"]
        for w in c["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                if d["date"].startswith(str(yr)):
                    days[d["date"]] = d["contributionCount"]
    cutoff = (now.date() - dt.timedelta(days=364)).isoformat()
    recent = [(d["date"], d["contributionCount"])
              for w in cc["recent"]["contributionCalendar"]["weeks"] for d in w["contributionDays"]
              if d["date"] >= cutoff]

    langs: dict[str, int] = {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]

    return {
        "login": u["login"], "since": first, "now": now.isoformat(),
        "total": total, "year_commits": cc[f"y{now.year}"]["totalCommitContributions"],
        "year_total": cc[f"y{now.year}"]["contributionCalendar"]["totalContributions"],
        "last_year_total": cc["recent"]["contributionCalendar"]["totalContributions"],
        "prs": u["pullRequests"]["totalCount"], "issues": u["issues"]["totalCount"], "reviews": reviews,
        "stars": sum(r["stargazerCount"] for r in u["repositories"]["nodes"]),
        "repos": u["repositories"]["totalCount"], "followers": u["followers"]["totalCount"],
        "days": sorted(days.items()), "recent": recent,
        "langs": sorted(langs.items(), key=lambda kv: -kv[1]),
    }


def demo_data(login: str) -> dict:
    rnd = random.Random(610)
    now = dt.datetime.now(dt.timezone.utc)
    start = dt.date(2023, 7, 1)
    days = []
    d = start
    while d <= now.date():
        busy = 0.35 + 0.45 * (d.weekday() < 5) + 0.15 * ((d - start).days / 1200)
        c = 0 if rnd.random() > busy else int(rnd.expovariate(1 / 4.5)) + 1
        days.append((d.isoformat(), c))
        d += dt.timedelta(days=1)
    # guarantee a recent streak so the demo shows something alive
    for i in range(9):
        idx = len(days) - 1 - i
        days[idx] = (days[idx][0], max(days[idx][1], rnd.randint(1, 7)))
    recent = days[-365:]
    return {
        "login": login, "since": 2023, "now": now.isoformat(),
        "total": sum(c for _, c in days), "year_commits": 612,
        "year_total": sum(c for day, c in days if day.startswith(str(now.year))),
        "last_year_total": sum(c for _, c in recent),
        "prs": 48, "issues": 17, "reviews": 23, "stars": 64, "repos": 31, "followers": 57,
        "days": days, "recent": recent,
        "langs": [("TypeScript", 912000), ("JavaScript", 604000), ("Python", 488000),
                  ("C++", 140000), ("EJS", 52000), ("Dockerfile", 12000), ("Shell", 9000)],
    }


def streaks(days: list[tuple[str, int]]):
    best = (0, None, None)
    run, run_start = 0, None
    for date, c in days:
        if c > 0:
            run_start = date if run == 0 else run_start
            run += 1
            if run > best[0]:
                best = (run, run_start, date)
        else:
            run = 0
    # current: ending today, or yesterday if today has nothing yet
    cur, i = 0, len(days) - 1
    if i >= 0 and days[i][1] == 0:
        i -= 1
    end = days[i][0] if i >= 0 else None
    while i >= 0 and days[i][1] > 0:
        cur += 1
        i -= 1
    start = days[i + 1][0] if cur else None
    return (cur, start, end), best


def fmt_day(iso: str | None, year=False) -> str:
    if not iso:
        return "—"
    d = dt.date.fromisoformat(iso)
    return d.strftime("%d %b %Y" if year else "%d %b").lower()


# ── live cards ───────────────────────────────────────────────────────────────
def stats_card(data) -> Svg:
    H = 200
    now = dt.datetime.fromisoformat(data["now"])
    (cur, cs, _ce), (best, bs, be) = streaks(data["days"])
    s = Svg(W, H, f"GitHub stats: {data['total']} contributions since {data['since']}, current streak {cur} days, "
                  f"longest streak {best} days, {data['year_commits']} commits in {now.year}")
    panel(s, 0, 0, W, H, f"github · @{data['login']}", "synced " + now.strftime("%d %b %Y · %H:%M utc"))
    cols = [
        ("CONTRIBUTIONS", f"{data['total']:,}", f"all-time · since {data['since']}"),
        ("CURRENT STREAK", f"{cur}", f"days · since {fmt_day(cs)}" if cur else "days · next commit starts one"),
        ("LONGEST STREAK", f"{best}", f"days · {fmt_day(bs)} → {fmt_day(be, True)}" if best else "days"),
        (f"COMMITS · {now.year}", f"{data['year_commits']:,}", f"{data['year_total']:,} contributions ytd"),
    ]
    cw = (W - 48) / 4
    for i, (label, value, sub) in enumerate(cols):
        x = 24 + i * cw
        if i:
            s.add(f'<path d="M{n(x)} 52V150" stroke="{EDGE}"/>')
        cx = x + cw / 2
        s.text(cx, 66, label, "mono", 9.5, DIM, "middle", ls=1.6)
        s.add('<g filter="url(#bloom)">', s.t(cx, 117, value, "dot", 46, AMBER if i != 1 else HOT, "middle", ls=1), "</g>")
        size = 9.5
        while tw(sub, "mono", size) > cw - 16 and size > 7.5:
            size -= .5
        s.text(cx, 142, sub, "mono", size, MUTE, "middle")
    s.add(f'<path d="M24 162.5H{W - 24}" stroke="{EDGE}"/>')
    items = [("PRS", data["prs"]), ("ISSUES", data["issues"]), ("REVIEWS", data["reviews"]),
             ("STARS", data["stars"]), ("PUBLIC REPOS", data["repos"]), ("FOLLOWERS", data["followers"])]
    iw = (W - 48) / len(items)
    for i, (k, v) in enumerate(items):
        cx = 24 + i * iw + iw / 2
        kw, vw = tw(k, "mono", 9, 1.2), tw(f"{v:,}", "bold", 11)
        x = cx - (kw + 8 + vw) / 2
        s.text(x, 185, k, "mono", 9, DIM, ls=1.2)
        s.text(x + kw + 8, 185, f"{v:,}", "bold", 11, TEXT)
    return s


def monotone(pts):
    """Fritsch–Carlson monotone cubic → SVG path (no overshoot below zero)."""
    if len(pts) < 3:
        return "M" + " L".join(f"{n(x)} {n(y)}" for x, y in pts)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(len(pts) - 1)]
    m = [d[0]] + [0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2 for i in range(1, len(d))] + [d[-1]]
    for i in range(len(d)):
        if d[i] == 0:
            m[i] = m[i + 1] = 0
        else:
            a, b = m[i] / d[i], m[i + 1] / d[i]
            h = a * a + b * b
            if h > 9:
                t = 3 / h ** .5
                m[i], m[i + 1] = t * a * d[i], t * b * d[i]
    out = [f"M{n(xs[0])} {n(ys[0])}"]
    for i in range(len(d)):
        dx = (xs[i + 1] - xs[i]) / 3
        out.append(f"C{n(xs[i] + dx)} {n(ys[i] + m[i] * dx)} {n(xs[i + 1] - dx)} {n(ys[i + 1] - m[i + 1] * dx)} "
                   f"{n(xs[i + 1])} {n(ys[i + 1])}")
    return "".join(out)


def activity_card(data) -> Svg:
    H = 260
    last = data["days"][-31:]
    counts = [c for _, c in last]
    peak = max(counts) if counts else 0
    peak_i = counts.index(peak) if counts else 0
    top = max(4, -(-peak // 4) * 4)
    s = Svg(W, H, f"Contribution activity over the last 31 days: {sum(counts)} contributions, peak {peak}")
    s.defs.append(f'<linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{AMBER}" stop-opacity=".32"/>'
                  f'<stop offset="1" stop-color="{AMBER}" stop-opacity="0"/></linearGradient>')
    panel(s, 0, 0, W, H, "commit activity · last 31 days",
          f"Σ {sum(counts)} · peak {peak} on {fmt_day(last[peak_i][0]) if last else '—'}")
    L, R, T, B = 58, W - 30, 58, H - 52
    for k in range(5):
        y = B - (B - T) * k / 4
        s.add(f'<path d="M{L} {n(y)}H{R}" stroke="{GRID if k else EDGE}"{DASH if k else ""}/>')
        s.text(L - 12, y + 3.5, str(int(top * k / 4)), "mono", 9, MUTE, "end")
    step = (R - L) / max(1, len(counts) - 1)
    pts = [(L + i * step, B - (B - T) * c / top) for i, c in enumerate(counts)]
    line = monotone(pts)
    s.add(f'<path d="{line}L{n(R)} {B}L{L} {B}Z" fill="url(#area)"/>')
    s.add(f'<path d="{line}" stroke="{AMBER}" stroke-width="2.2" stroke-linecap="round" pathLength="1" '
          f'stroke-dasharray="1" stroke-dashoffset="0" filter="url(#bloom)" class="draw"/>')
    s.css.append(".draw{animation:draw 2.2s cubic-bezier(.6,0,.2,1) both}@keyframes draw{from{stroke-dashoffset:1}}")
    for i, (x, y) in enumerate(pts):
        hot = i == peak_i and peak
        s.add(f'<circle cx="{n(x)}" cy="{n(y)}" r="{3.6 if hot else 2.3}" fill="{HOT if hot else PANEL}" '
              f'stroke="{AMBER}" stroke-width="1.4"{GLOW if hot else ""}/>')
        if i % 5 == 0 or i == len(pts) - 1:
            s.text(x, B + 20, dt.date.fromisoformat(last[i][0]).strftime("%d %b").lower(), "mono", 9, MUTE, "middle")
    if peak:
        x, y = pts[peak_i]
        s.text(min(max(x, L + 20), R - 20), y - 12, str(peak), "bold", 10, HOT, "middle")
    return s


def langs_card(data) -> Svg:
    CW, H = 424, 250
    top = data["langs"][:6]
    total = sum(v for _, v in data["langs"]) or 1
    s = Svg(CW, H, "Top languages by bytes: " + ", ".join(f"{k} {v / total:.0%}" for k, v in top))
    panel(s, 0, 0, CW, H, "languages · by bytes", f"{data['repos']} repos")
    y = 70
    bx, bw = 142, CW - 142 - 72
    for i, (name, v) in enumerate(top):
        pct = v / total
        op = [1, .78, .62, .5, .4, .32][i]
        label = name if tw(name, "mono", 11) < bx - 32 else name[:12] + "…"
        s.text(26, y + 4, label, "mono", 11, TEXT)
        s.add(f'<rect x="{bx}" y="{y - 4}" width="{bw}" height="8" rx="4" fill="{GRID}"/>')
        s.add(f'<rect x="{bx}" y="{y - 4}" width="{n(max(6, bw * pct))}" height="8" rx="4" fill="{AMBER}" '
              f'fill-opacity="{op}"{GLOW if i == 0 else ""}/>')
        s.text(CW - 26, y + 4, f"{pct * 100:.1f}%", "bold", 10.5, AMBER if i == 0 else DIM, "end")
        y += 28
    return s


def weekday_card(data) -> Svg:
    CW, H = 424, 250
    sums = [0] * 7
    for date, c in data["recent"]:
        sums[dt.date.fromisoformat(date).weekday()] += c
    names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    peak = max(range(7), key=lambda i: sums[i])
    s = Svg(CW, H, "Contributions by weekday over the last year: " + ", ".join(f"{d} {v}" for d, v in zip(names, sums)))
    panel(s, 0, 0, CW, H, "ship days · last 365d", f"peak · {names[peak]}")
    L, R, T, B = 30, CW - 30, 64, H - 44
    slot = (R - L) / 7
    bw = slot * .52
    top = max(sums) or 1
    s.add(f'<path d="M{L} {B + .5}H{R}" stroke="{EDGE}"/>')
    for i, v in enumerate(sums):
        cx = L + slot * i + slot / 2
        h = max(3, (B - T - 18) * v / top)
        s.add(f'<rect x="{n(cx - bw / 2)}" y="{T + 18}" width="{n(bw)}" height="{n(B - T - 18)}" rx="3" fill="{GRID}" fill-opacity=".6"/>')
        s.add(f'<rect x="{n(cx - bw / 2)}" y="{n(B - h)}" width="{n(bw)}" height="{n(h)}" rx="3" '
              f'fill="{AMBER if i == peak else DEEP}" fill-opacity="{1 if i == peak else .5}"'
              f'{BLOOM if i == peak else ""}/>')
        s.text(cx, B - h - 8, str(v), "bold" if i == peak else "mono", 9.5, HOT if i == peak else DIM, "middle")
        s.text(cx, B + 18, names[i], "mono", 9, AMBER if i == peak else MUTE, "middle", ls=1)
    return s


def footer(data) -> Svg:
    H = 58
    now = dt.datetime.fromisoformat(data["now"])
    s = Svg(W, H, "rendered by a GitHub Action")
    s.add(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="12" fill="{PANEL}" stroke="{EDGE}"/>',
          f'<rect width="{W}" height="{H}" rx="12" fill="url(#scan)"/>')
    s.add('<g filter="url(#bloom)">', s.t(24, 38, "EOF", "dot", 24, AMBER, ls=2), "</g>")
    s.text(96, 34, "rendered by .github/workflows/profile.yml · every 12h · last build "
           + now.strftime("%d %b %Y %H:%M utc").lower(), "mono", 9.5, DIM)
    s.text(W - 24, 34, "doto + martian mono · ofl", "mono", 9.5, MUTE, "end")
    return s


def snake(raw_path: Path, data) -> str:
    raw = raw_path.read_text()
    vb = "-28 -76 904 248"
    s = Svg(904, 248, "", viewbox=vb)
    s.text(10, -44, "COMMIT GRAPH · SNAKE MODE", "mono", 9.5, DIM, ls=1.6)
    s.text(852, -44, f"{data['last_year_total']:,} contributions in the last year".upper(), "mono", 9.5, MUTE, "end", ls=1.2)
    faces = "".join(FONTS[k].face(ch) for k, ch in s.used.items() if ch)
    palette = (f":root{{--cb:#FFFFFF08;--cs:{HOT};--ce:{LEVELS[0]};--c0:{LEVELS[0]};--c1:{LEVELS[1]};"
               f"--c2:{LEVELS[2]};--c3:{LEVELS[3]};--c4:{LEVELS[4]}}}"
               ".mono{font-family:'kv-mono',ui-monospace,monospace}")
    head_end = raw.index("</style>")
    body = raw[head_end + len("</style>"):raw.rindex("</svg>")]
    style = raw[raw.index("<style>") + 7:head_end]
    header = "".join(s.body)
    filt = (
        '<filter id="sg" filterUnits="userSpaceOnUse" x="-28" y="-76" width="904" height="248" color-interpolation-filters="sRGB">'
        '<feGaussianBlur stdDeviation="3.2" result="a"/><feGaussianBlur in="SourceGraphic" stdDeviation="1.2" result="b"/>'
        '<feComponentTransfer in="a" result="a2"><feFuncA type="linear" slope="1.4"/></feComponentTransfer>'
        '<feMerge><feMergeNode in="a2"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        '<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="1" fill="#FFFFFF" opacity=".022"/></pattern>'
    )
    k, o = 9, 7
    x0, y0, x1, y1 = -28, -76, 876, 172
    ticks = (f"M{x0 + o} {y0 + o + k}V{y0 + o}H{x0 + o + k} M{x1 - o - k} {y0 + o}H{x1 - o}V{y0 + o + k} "
             f"M{x0 + o} {y1 - o - k}V{y1 - o}H{x0 + o + k} M{x1 - o - k} {y1 - o}H{x1 - o}V{y1 - o - k}")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="904" height="248" viewBox="{vb}" role="img" '
        f'aria-label="Contribution graph being eaten by a snake"><title>Contribution graph being eaten by a snake</title>'
        f"<style>{faces}{style}{palette}</style><defs>{filt}</defs>"
        f'<rect x="-27.5" y="-75.5" width="903" height="247" rx="14" fill="{PANEL}" stroke="{EDGE}"/>'
        f'<rect x="-28" y="-76" width="904" height="248" rx="14" fill="url(#scan)"/>'
        f'<path d="{ticks}" stroke="{AMBER}" stroke-width="1.2" opacity=".55" fill="none"/>'
        f'<rect x="-4" y="-50.5" width="6" height="6" fill="{AMBER}"/>'
        f'{header}'
        f'<g filter="url(#sg)">{body}</g></svg>'
    )


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--demo", action="store_true", help="use made-up numbers instead of the GitHub API")
    ap.add_argument("--snake", help="path to the raw snk SVG to restyle")
    args = ap.parse_args()

    cfg = json.loads((ROOT / "profile.json").read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def save(name: str, svg: Svg | str):
        (out / name).write_text(svg if isinstance(svg, str) else svg.render())
        print(f"  {name:28s} {(out / name).stat().st_size / 1024:6.1f} KB")

    print("static")
    save("hero.svg", hero(cfg))
    save("about.svg", about(cfg))
    for i, (title, note) in enumerate([
        ("stack", "// tools i reach for"),
        ("experience", "// where i've shipped"),
        ("systems", "// things i've built"),
        ("recognition", "// hackathons"),
        ("telemetry", "// live · rebuilt every 12h"),
    ], 1):
        save(f"sec-{title}.svg", section(i, title, note))
    save("stack.svg", stack(cfg))
    save("experience.svg", experience(cfg))
    feat = [p for p in cfg["projects"] if p.get("featured")]
    rest = [p for p in cfg["projects"] if not p.get("featured")]
    for p in feat:
        save(f"project-{p['id']}.svg", project_featured(p))
    for pid, svg in project_cards(rest):
        save(f"project-{pid}.svg", svg)
    save("achievements.svg", achievements(cfg))
    for key, svg in buttons(cfg):
        save(f"btn-{key}.svg", svg)

    print("live")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if args.demo or not token:
        if not args.demo:
            if os.environ.get("CI"):
                raise SystemExit("GITHUB_TOKEN is missing; refusing to publish demo numbers")
            print("  ! no GITHUB_TOKEN; falling back to demo data", file=sys.stderr)
        data = demo_data(cfg["github"])
    else:
        data = fetch(cfg["github"], token)
    save("stats.svg", stats_card(data))
    save("activity.svg", activity_card(data))
    save("languages.svg", langs_card(data))
    save("weekdays.svg", weekday_card(data))
    save("footer.svg", footer(data))
    if args.snake and Path(args.snake).exists():
        save("snake.svg", snake(Path(args.snake), data))


if __name__ == "__main__":
    main()