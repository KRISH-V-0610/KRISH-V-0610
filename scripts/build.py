#!/usr/bin/env python3
"""
Renders every image used by the profile README into ./dist.

    python scripts/build.py                       # live GitHub data (needs GITHUB_TOKEN)
    python scripts/build.py --demo                # made-up numbers, for local previews
    python scripts/build.py --snake .snk/snake.svg  # also restyle the snk output

Colours follow GitHub's own dark theme (Primer), so every card sits flush on the
dark-mode page. Each SVG carries a subset of its fonts (Doto + Martian Mono, both
OFL) as base64 WOFF2, so it renders the same everywhere and doesn't depend on a
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

# ── palette: GitHub dark (Primer) ────────────────────────────────────────────
CANVAS = "#0D1117"   # page background in dark mode
SUBTLE = "#161B22"   # box headers, tracks
INSET = "#21262D"    # buttons, hairlines
BORDER = "#30363D"
FG = "#E6EDF3"
FG2 = "#C9D1D9"
MUTED = "#8B949E"
FAINT = "#6E7681"
GREEN = "#3FB950"
BLUE = "#58A6FF"     # GitHub accent
BLUE_HI = "#79C0FF"
PURPLE = "#BC8CFF"
PURPLE_HI = "#D2A8FF"
LEVELS = ["#161B22", "#0E4429", "#006D32", "#26A641", "#39D353"]  # contribution 0..4

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

    def t(self, x, y, s, font="mono", size=12, fill=FG, anchor="start", ls=0.0, extra="") -> str:
        self.used[font].update(s)
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        spacing = f' letter-spacing="{n(ls)}"' if ls else ""
        return (f'<text x="{n(x)}" y="{n(y)}" class="{font}" font-size="{n(size)}" fill="{fill}"'
                f'{a}{spacing}{extra}>{escape(s)}</text>')

    def text(self, *a, **k) -> "Svg":
        return self.add(self.t(*a, **k))

    def faces(self) -> str:
        return "".join(FONTS[k].face(ch) for k, ch in self.used.items() if ch)

    def render(self) -> str:
        classes = "".join(f".{k}{{font-family:'{f.family}',ui-monospace,monospace}}" for k, f in FONTS.items())
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{n(self.w)}" height="{n(self.h)}" '
            f'viewBox="{self.viewbox}" role="img" aria-label="{escape(self.label)}" fill="none">'
            f"<title>{escape(self.label)}</title>"
            f"<style>{self.faces()}{classes}{''.join(self.css)}</style>"
            f"<defs>{''.join(self.defs)}</defs>{''.join(self.body)}</svg>"
        )


def box(s: Svg, x, y, w, h, label=None, right=None, head=40):
    """A GitHub-style Box: canvas body, subtle header strip, 6px corners."""
    r = 6
    s.add(f'<rect x="{n(x + .5)}" y="{n(y + .5)}" width="{n(w - 1)}" height="{n(h - 1)}" rx="{r}" fill="{CANVAS}" stroke="{BORDER}"/>')
    if label is None and right is None:
        return
    x0, x1, y0, yb = x + .5, x + w - .5, y + .5, y + head
    s.add(f'<path d="M{n(x0)} {n(yb)}V{n(y0 + r)}Q{n(x0)} {n(y0)} {n(x0 + r)} {n(y0)}H{n(x1 - r)}'
          f'Q{n(x1)} {n(y0)} {n(x1)} {n(y0 + r)}V{n(yb)}Z" fill="{SUBTLE}"/>')
    s.add(f'<path d="M{n(x0)} {n(yb + .5)}H{n(x1)}" stroke="{BORDER}"/>')
    if label:
        s.text(x + 20, y + 25, label, "mono", 10.5, MUTED)
    if right:
        s.text(x + w - 20, y + 25, right, "mono", 10.5, FAINT, "end")


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



_BRAND = json.loads((HERE / "icons" / "colors.json").read_text()) if (HERE / "icons" / "colors.json").exists() else {}


def _lum(hexc: str) -> float:
    c = [int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4 for v in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]


def brand(slug: str, fallback: str = FG2) -> str:
    """The brand colour for a Simple Icons slug, lifted toward white until it reads on the dark canvas."""
    col = _BRAND.get(slug)
    if not col:
        return fallback
    bg = _lum(CANVAS)
    r, g, b = (int(col[i:i + 2], 16) for i in (1, 3, 5))
    for _ in range(20):
        c = f"#{r:02X}{g:02X}{b:02X}"
        if (_lum(c) + .05) / (bg + .05) >= 4.5:
            return c
        r, g, b = (int(v + (255 - v) * .18) for v in (r, g, b))
    return fallback


def brand_hex(col: str) -> str:
    _BRAND["_tmp"] = col.upper() if col.startswith("#") else "#" + col.upper()
    out = brand("_tmp", GREEN)
    del _BRAND["_tmp"]
    return out


def square(x, y, size, fill) -> str:
    return f'<rect x="{n(x)}" y="{n(y)}" width="{n(size)}" height="{n(size)}" rx="1" fill="{fill}"/>'


def chips(s: Svg, x, y, items, maxx, size=9.5, label=None) -> float:
    if label:
        s.text(x, y + 14.5, label, "mono", size, FAINT)
        x += tw(label, "mono", size) + 12
    for item in items:
        w = tw(item, "mono", size) + 18
        if x + w > maxx:
            break
        s.add(f'<rect x="{n(x + .5)}" y="{n(y + .5)}" width="{n(w - 1)}" height="21" rx="10.5" fill="{SUBTLE}" stroke="{BORDER}"/>')
        s.text(x + 9, y + 14.5, item, "mono", size, MUTED)
        x += w + 6
    return x


# ── static cards ─────────────────────────────────────────────────────────────
def hero(cfg) -> Svg:
    H = 300
    s = Svg(W, H, f"{' '.join(cfg['name']).title()} — {cfg['roles'][0]}")
    box(s, 0, 0, W, H)

    x0 = 36
    user, _, cmd = cfg["prompt"].partition("$")
    s.add(f'<text x="{x0}" y="50" class="mono" font-size="11.5">'
          f'<tspan fill="{BLUE}">{escape(user)}</tspan><tspan fill="{FAINT}">$</tspan>'
          f'<tspan fill="{MUTED}">{escape(cmd)}</tspan></text>')
    s.used["mono"].update(cfg["prompt"])

    s.defs.append(f'<linearGradient id="name" x1="0" y1="0" x2="1" y2=".35"><stop offset="0" stop-color="{BLUE_HI}"/>'
                  f'<stop offset=".55" stop-color="{BLUE}"/><stop offset="1" stop-color="{PURPLE}"/></linearGradient>')
    s.text(x0 - 3, 128, cfg["name"][0], "dot", 78, "url(#name)", ls=3)
    s.text(x0 - 3, 200, cfg["name"][1], "dot", 78, "url(#name)", ls=3)

    # typing roles (SMIL, discrete steps → animates inside <img> on every major browser)
    ty, tsize = 244, 14
    prefix = "> "
    px = x0 + tw(prefix, "bold", tsize)
    cw = tw("M", "mono", tsize)
    slots, t = [], 0.0
    TYPE, HOLD, ERASE, GAP = .055, 1.9, .022, .35
    for r in cfg["roles"]:
        dur = len(r) * TYPE + HOLD + len(r) * ERASE + GAP
        slots.append((t, t + dur, r))
        t += dur
    total = t
    times, widths = [0.0], [0.0]
    for start, _end, r in slots:
        for k in range(len(r) + 1):
            times.append(start + k * TYPE)
            widths.append(k * cw)
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
    s.text(x0, ty, prefix, "bold", tsize, GREEN)
    lines = []
    for start, end, r in slots:
        a, b = round(start / total, 5), round(end / total, 5)
        kt2, vals = (f"0;{n(b)}", "1;0") if a == 0 else (f"0;{n(a)};{n(b)}", "0;1;0")
        lines.append(s.t(px, ty, r, "mono", tsize, BLUE_HI, extra=f' opacity="{1 if a == 0 else 0}"').replace(
            "</text>", f'<animate attributeName="opacity" dur="{n(total)}s" repeatCount="indefinite" '
                       f'calcMode="discrete" keyTimes="{kt2}" values="{vals}"/></text>'))
    s.add('<g clip-path="url(#type)">', *lines, "</g>")
    s.add(f'<rect x="{n(px)}" y="{ty - 13}" width="{n(cw * .62)}" height="16" fill="{BLUE_HI}">'
          f'<animate attributeName="x" dur="{n(total)}s" repeatCount="indefinite" calcMode="discrete" keyTimes="{kt}" values="{xv}"/>'
          f'<animate attributeName="opacity" dur="1s" repeatCount="indefinite" calcMode="discrete" keyTimes="0;.5" values="1;0"/></rect>')
    s.text(x0, 278, cfg["meta"], "mono", 9.5, FAINT, ls=1.3)

    contents(s, cfg, 548, 36)
    return s


def contents(s: Svg, cfg, ox, oy):
    """Right side of the hero: a table of contents for the story below."""
    w, h = 280, 228
    s.add(f'<rect x="{ox + .5}" y="{oy + .5}" width="{w - 1}" height="{h - 1}" rx="6" fill="{CANVAS}" stroke="{INSET}"/>')
    s.text(ox + 18, oy + 28, "CONTENTS", "mono", 9.5, PURPLE_HI, ls=2.4)
    s.add(f'<path d="M{ox + 18} {oy + 42.5}H{ox + w - 18}" stroke="{INSET}"/>')
    y = oy + 68
    for i, ch in enumerate(cfg["story"]["chapters"]):
        num = f"{i:02d}"
        year = ch["year"]
        s.text(ox + 18, y, num, "mono", 10, PURPLE)
        tx = ox + 46
        s.text(tx, y, ch["short"], "mono", 11, GREEN if ch.get("now") else FG2)
        yx = ox + w - 18
        lead_a = tx + tw(ch["short"], "mono", 11) + 8
        lead_b = yx - tw(year, "mono", 10) - 8
        if lead_b > lead_a:
            s.add(f'<path d="M{n(lead_a)} {y - 3}H{n(lead_b)}" stroke="{BORDER}" stroke-dasharray="1 4" stroke-linecap="round"/>')
        s.text(yx, y, year, "mono", 10, FAINT, "end")
        y += 30
    s.text(ox + 18, oy + h - 18, "then: the toolbox · the commit log", "mono", 9, FAINT)


def section(numeral: str, title: str, note: str) -> Svg:
    H = 76
    s = Svg(W, H, f"Part {numeral}: {title}")
    s.add(f'<rect width="{W}" height="{H}" fill="{CANVAS}"/>')
    s.text(2, 26, f"PART {numeral}", "mono", 10, PURPLE, ls=2.4)
    s.text(2, 56, title, "bold", 20, FG)
    s.text(W - 2, 56, note, "mono", 11, MUTED, "end")
    s.add(f'<path d="M0 {H - .5}H{W}" stroke="{INSET}"/>')
    return s


def story(cfg) -> Svg:
    st = cfg["story"]
    cx, tx, rx = 24, 142, 168          # date column, timeline, text column
    tmax = W - 28
    size, lh = 11.5, 19.5
    intro = [ln for para in st["intro"].split("\n") for ln in wrap(para, W - 48, "mono", 13)]
    blocks, y = [], 76 + (len(intro) - 1) * 22 + 66
    for ch in st["chapters"]:
        para = wrap(ch["text"], tmax - rx, "mono", size)
        h = 26 + 22 + len(para) * lh + (36 if ch.get("chips") else 6)
        blocks.append((ch, para, y, h))
        y += h + 34
    H = y - 10
    s = Svg(W, H, st["intro"].replace("\n", " ") + " " + " ".join(f"{c['title']} ({c['year']}): {c['text']}" for c in st["chapters"]))
    box(s, 0, 0, W, H, "~/story.md", f"{len(blocks)} chapters")
    for i, line in enumerate(intro):
        s.text(24, 76 + i * 22, line, "mono", 13, FG)

    first, last = blocks[0][2] - 4, blocks[-1][2] - 4
    s.add(f'<path d="M{tx} {first}V{last}" stroke="{BORDER}" stroke-width="1.5"/>')
    for i, (ch, para, y0, h) in enumerate(blocks):
        now = ch.get("now")
        s.text(cx, y0 - 18, f"CH {i:02d}", "mono", 9, FAINT, ls=1.6)
        s.text(cx - 1, y0 + 12, ch["year"].upper(), "dot", 26, GREEN if now else BLUE, ls=1)
        if ch.get("month"):
            s.text(cx, y0 + 30, ch["month"], "mono", 10, FAINT)
        if now:
            s.add(f'<circle cx="{tx}" cy="{y0 - 4}" r="9" fill="{GREEN}" opacity=".18">'
                  '<animate attributeName="opacity" values=".28;.05;.28" dur="2.4s" repeatCount="indefinite"/></circle>',
                  f'<circle cx="{tx}" cy="{y0 - 4}" r="5" fill="{GREEN}"/>')
        else:
            s.add(f'<circle cx="{tx}" cy="{y0 - 4}" r="5" fill="{CANVAS}" stroke="{BLUE}" stroke-width="1.5"/>')
        s.text(rx, y0 - 18, ch["kicker"].upper(), "mono", 9, PURPLE_HI, ls=1.1)
        s.text(rx, y0 + 4, ch["title"], "bold", 15, FG)
        yy = y0 + 32
        for ln in para:
            s.text(rx, yy, ln, "mono", size, FG2)
            yy += lh
        if ch.get("chips"):
            chips(s, rx, yy - 4, ch["chips"], tmax, label=ch.get("chips_label"))
    return s


def stack(cfg) -> Svg:
    x0, lw, ph, gap, rowgap, isz, fsz = 24, 128, 28, 8, 10, 13, 11
    maxx = W - 24
    rows, y = [], 64
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
    H = y + 6
    count = sum(len(i) for _, i in cfg["stack"])
    s = Svg(W, H, "tech stack: " + ", ".join(l for _, items in cfg["stack"] for _, l in items))
    box(s, 0, 0, W, H, "~/toolbox", f"{count} tools")
    for i, (cat, pills, ry) in enumerate(rows):
        s.text(x0, ry + 18.5, cat, "mono", 10.5, BLUE)
        for x, y2, pw, slug, label in pills:
            s.add(f'<rect x="{n(x + .5)}" y="{n(y2 + .5)}" width="{n(pw - 1)}" height="{ph - 1}" rx="6" fill="{SUBTLE}" stroke="{BORDER}"/>')
            if slug:
                s.add(icon(slug, x + 12, y2 + (ph - isz) / 2, isz, brand(slug, MUTED)))
            else:
                s.add(square(x + 12 + 3.5, y2 + ph / 2 - 3, 6, FAINT))
            s.text(x + 12 + isz + 8, y2 + ph / 2 + 4, label, "mono", fsz, FG2)
        if i < len(rows) - 1:
            s.add(f'<path d="M{x0} {n(pills[-1][1] + ph + rowgap / 2 + 4)}H{maxx}" stroke="{INSET}"/>')
    return s


def buttons(cfg) -> list[tuple[str, Svg]]:
    out = []
    for key, slug, label, _url in cfg["links"]:
        isz, fsz, H = 13, 10, 30
        w = 12 + isz + 9 + tw(label, "bold", fsz, 1.2) + 8 + tw("↗", "mono", fsz) + 12
        s = Svg(w, H, label.title())
        s.add(f'<rect x=".5" y=".5" width="{n(w - 1)}" height="{H - 1}" rx="6" fill="{INSET}" stroke="{BORDER}"/>')
        ix, iy = 12, (H - isz) / 2
        if slug:
            s.add(icon(slug, ix, iy, isz, brand(slug)))
        elif key == "linkedin":
            s.add(f'<rect x="{ix}" y="{n(iy)}" width="{isz}" height="{isz}" rx="2.5" fill="#0A66C2"/>',
                  s.t(ix + isz / 2, iy + isz - 3, "in", "bold", 8.5, "#FFFFFF", "middle"))
        else:  # globe
            c = ix + isz / 2
            s.add(f'<g stroke="{BLUE}" stroke-width="1.3" fill="none">'
                  f'<circle cx="{n(c)}" cy="{H / 2}" r="{n(isz / 2 - .5)}"/>'
                  f'<ellipse cx="{n(c)}" cy="{H / 2}" rx="{n(isz / 4)}" ry="{n(isz / 2 - .5)}"/>'
                  f'<path d="M{n(ix + .5)} {H / 2}H{n(ix + isz - .5)}"/></g>')
        s.text(ix + isz + 9, H / 2 + 3.6, label, "bold", fsz, FG, ls=1.2)
        s.text(w - 12, H / 2 + 3.6, "↗", "mono", fsz, MUTED, "end")
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
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } }
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
    lang_colors: dict[str, str] = {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
            if e["node"].get("color"):
                lang_colors[e["node"]["name"]] = e["node"]["color"]

    return {
        "login": u["login"], "since": first, "now": now.isoformat(),
        "total": total, "year_commits": cc[f"y{now.year}"]["totalCommitContributions"],
        "year_total": cc[f"y{now.year}"]["contributionCalendar"]["totalContributions"],
        "last_year_total": cc["recent"]["contributionCalendar"]["totalContributions"],
        "prs": u["pullRequests"]["totalCount"], "issues": u["issues"]["totalCount"], "reviews": reviews,
        "stars": sum(r["stargazerCount"] for r in u["repositories"]["nodes"]),
        "repos": u["repositories"]["totalCount"], "followers": u["followers"]["totalCount"],
        "days": sorted(days.items()), "recent": recent,
        "langs": sorted(langs.items(), key=lambda kv: -kv[1]), "lang_colors": lang_colors,
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
        "lang_colors": {"TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Python": "#3572A5", "C++": "#f34b7d",
                        "EJS": "#a91e50", "Dockerfile": "#384d54", "Shell": "#89e051"},
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
    H = 210
    now = dt.datetime.fromisoformat(data["now"])
    (cur, cs, _ce), (best, bs, be) = streaks(data["days"])
    s = Svg(W, H, f"GitHub stats: {data['total']} contributions since {data['since']}, current streak {cur} days, "
                  f"longest streak {best} days, {data['year_commits']} commits in {now.year}")
    box(s, 0, 0, W, H, f"github · @{data['login']}", "synced " + now.strftime("%d %b %Y, %H:%M UTC"))
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
            s.add(f'<path d="M{n(x)} 62V158" stroke="{INSET}"/>')
        cx = x + cw / 2
        s.text(cx, 76, label, "mono", 9.5, MUTED, "middle", ls=1.4)
        s.text(cx, 124, value, "dot", 42, GREEN if i == 1 and cur else BLUE, "middle", ls=1)
        size = 9.5
        while tw(sub, "mono", size) > cw - 16 and size > 7.5:
            size -= .5
        s.text(cx, 150, sub, "mono", size, FAINT, "middle")
    s.add(f'<path d="M24 172.5H{W - 24}" stroke="{INSET}"/>')
    items = [("PRS", data["prs"]), ("ISSUES", data["issues"]), ("REVIEWS", data["reviews"]),
             ("STARS", data["stars"]), ("PUBLIC REPOS", data["repos"]), ("FOLLOWERS", data["followers"])]
    iw = (W - 48) / len(items)
    for i, (k, v) in enumerate(items):
        cx = 24 + i * iw + iw / 2
        kw, vw = tw(k, "mono", 9, 1.2), tw(f"{v:,}", "bold", 11)
        x = cx - (kw + 8 + vw) / 2
        s.text(x, 195, k, "mono", 9, FAINT, ls=1.2)
        s.text(x + kw + 8, 195, f"{v:,}", "bold", 11, FG)
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
    H = 270
    last = data["days"][-31:]
    counts = [c for _, c in last]
    peak = max(counts) if counts else 0
    peak_i = counts.index(peak) if counts else 0
    top = max(4, -(-peak // 4) * 4)
    s = Svg(W, H, f"Contribution activity over the last 31 days: {sum(counts)} contributions, peak {peak}")
    s.defs.append(f'<linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{LEVELS[4]}" stop-opacity=".18"/>'
                  f'<stop offset="1" stop-color="{LEVELS[4]}" stop-opacity="0"/></linearGradient>')
    box(s, 0, 0, W, H, "contribution activity · last 31 days",
        f"{sum(counts)} total · peak {peak} on {fmt_day(last[peak_i][0]) if last else '—'}")
    L, R, T, B = 56, W - 28, 66, H - 50
    for k in range(5):
        y = B - (B - T) * k / 4
        s.add(f'<path d="M{L} {n(y)}H{R}" stroke="{BORDER if k == 0 else INSET}"/>')
        s.text(L - 12, y + 3.5, str(int(top * k / 4)), "mono", 9, FAINT, "end")
    step = (R - L) / max(1, len(counts) - 1)
    pts = [(L + i * step, B - (B - T) * c / top) for i, c in enumerate(counts)]
    line = monotone(pts)
    s.add(f'<path d="{line}L{n(R)} {B}L{L} {B}Z" fill="url(#area)"/>')
    s.add(f'<path d="{line}" stroke="{LEVELS[4]}" stroke-width="2" stroke-linecap="round" pathLength="1" '
          f'stroke-dasharray="1" stroke-dashoffset="0" class="draw"/>')
    s.css.append(".draw{animation:draw 2.2s cubic-bezier(.6,0,.2,1) both}@keyframes draw{from{stroke-dashoffset:1}}")
    for i, (x, y) in enumerate(pts):
        hot = i == peak_i and peak
        s.add(f'<circle cx="{n(x)}" cy="{n(y)}" r="{3.4 if hot else 2.2}" fill="{LEVELS[4] if hot else CANVAS}" '
              f'stroke="{LEVELS[4]}" stroke-width="1.4"/>')
        if i % 5 == 0 or i == len(pts) - 1:
            s.text(x, B + 20, dt.date.fromisoformat(last[i][0]).strftime("%d %b").lower(), "mono", 9, FAINT, "middle")
    if peak:
        x, y = pts[peak_i]
        s.text(min(max(x, L + 20), R - 20), y - 12, str(peak), "bold", 10, FG, "middle")
    return s


def langs_card(data) -> Svg:
    CW, H = 424, 250
    top = data["langs"][:6]
    total = sum(v for _, v in data["langs"]) or 1
    s = Svg(CW, H, "Top languages by bytes: " + ", ".join(f"{k} {v / total:.0%}" for k, v in top))
    box(s, 0, 0, CW, H, "languages · by bytes", f"{data['repos']} repos")
    y = 78
    bx, bw = 138, CW - 138 - 70
    for i, (name, v) in enumerate(top):
        pct = v / total
        label = name if tw(name, "mono", 11) < bx - 32 else name[:12] + "…"
        s.text(22, y + 4, label, "mono", 11, FG2)
        s.add(f'<rect x="{bx}" y="{y - 3}" width="{bw}" height="6" rx="3" fill="{INSET}"/>')
        col = data.get("lang_colors", {}).get(name)
        fill = brand_hex(col) if col else GREEN
        s.add(f'<rect x="{bx}" y="{y - 3}" width="{n(max(6, bw * pct))}" height="6" rx="3" fill="{fill}"/>')
        s.text(CW - 22, y + 4, f"{pct * 100:.1f}%", "mono", 10.5, FG if i == 0 else MUTED, "end")
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
    box(s, 0, 0, CW, H, "ship days · last 365d", f"peak · {names[peak].lower()}")
    L, R, T, B = 26, CW - 26, 66, H - 42
    slot = (R - L) / 7
    bw = slot * .5
    top = max(sums) or 1
    s.add(f'<path d="M{L} {B + .5}H{R}" stroke="{BORDER}"/>')
    for i, v in enumerate(sums):
        cx = L + slot * i + slot / 2
        h = max(3, (B - T - 18) * v / top)
        s.add(f'<rect x="{n(cx - bw / 2)}" y="{T + 18}" width="{n(bw)}" height="{n(B - T - 18)}" rx="3" fill="{SUBTLE}"/>')
        s.add(f'<rect x="{n(cx - bw / 2)}" y="{n(B - h)}" width="{n(bw)}" height="{n(h)}" rx="3" '
              f'fill="{LEVELS[4] if i == peak else LEVELS[2]}"/>')
        s.text(cx, B - h - 8, str(v), "bold" if i == peak else "mono", 9.5, FG if i == peak else MUTED, "middle")
        s.text(cx, B + 18, names[i], "mono", 9, FG2 if i == peak else FAINT, "middle", ls=1)
    return s


def footer(data) -> Svg:
    H = 56
    now = dt.datetime.fromisoformat(data["now"])
    s = Svg(W, H, "rendered by a GitHub Action")
    box(s, 0, 0, W, H)
    s.text(22, 36, "EOF", "dot", 20, BLUE, ls=2)
    s.text(86, 32, "rendered by .github/workflows/profile.yml · every 12h · last build "
           + now.strftime("%d %b %Y %H:%M UTC"), "mono", 9.5, FAINT)
    s.text(W - 22, 32, "doto + martian mono · ofl", "mono", 9.5, FAINT, "end")
    return s


def snake(raw_path: Path, data) -> str:
    """Restyle snk's output: GitHub dark greens, a light snake, a Box frame and header."""
    raw = raw_path.read_text()
    vb = "-28 -84 904 256"
    hdr = Svg(904, 256, "", viewbox=vb)
    hdr.text(-8, -55, "commit graph · snake mode", "mono", 10.5, MUTED)
    hdr.text(868, -55, f"{data['last_year_total']:,} contributions in the last year", "mono", 10.5, FAINT, "end")
    palette = (f":root{{--cb:#1B1F230A;--cs:{PURPLE};--ce:{LEVELS[0]};--c0:{LEVELS[0]};--c1:{LEVELS[1]};"
               f"--c2:{LEVELS[2]};--c3:{LEVELS[3]};--c4:{LEVELS[4]}}}"
               ".mono{font-family:'kv-mono',ui-monospace,monospace}")
    head_end = raw.index("</style>")
    style = raw[raw.index("<style>") + 7:head_end]
    body = raw[head_end + len("</style>"):raw.rindex("</svg>")]
    x0, y0, w, h, r, hb = -28, -84, 904, 256, 6, -44
    frame = (
        f'<rect x="{x0 + .5}" y="{y0 + .5}" width="{w - 1}" height="{h - 1}" rx="{r}" fill="{CANVAS}" stroke="{BORDER}"/>'
        f'<path d="M{x0 + .5} {hb}V{y0 + .5 + r}Q{x0 + .5} {y0 + .5} {x0 + .5 + r} {y0 + .5}H{x0 + w - .5 - r}'
        f'Q{x0 + w - .5} {y0 + .5} {x0 + w - .5} {y0 + .5 + r}V{hb}Z" fill="{SUBTLE}"/>'
        f'<path d="M{x0 + .5} {hb + .5}H{x0 + w - .5}" stroke="{BORDER}"/>'
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="{vb}" role="img" '
        f'aria-label="Contribution graph being eaten by a snake"><title>Contribution graph being eaten by a snake</title>'
        f"<style>{hdr.faces()}{style}{palette}</style>"
        f"{frame}{''.join(hdr.body)}<g>{body}</g></svg>"
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
        print(f"  {name:22s} {(out / name).stat().st_size / 1024:6.1f} KB")

    print("static")
    save("hero.svg", hero(cfg))
    save("sec-story.svg", section("I", "The story so far", "2023 → now"))
    save("story.svg", story(cfg))
    save("sec-toolbox.svg", section("II", "The toolbox", "picked up along the way"))
    save("stack.svg", stack(cfg))
    save("sec-log.svg", section("III", "The commit log", "live · rebuilt every 12h"))
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
