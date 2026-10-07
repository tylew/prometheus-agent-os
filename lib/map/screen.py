# ---
# name: map.screen
# description: Pure ANSI screen parser for the map's live preview — `herdr pane read --ansi` text → a grid of (char, Attr) cells cropped to the preview rect (SGR colors 16/256/truecolor + bold/dim/italic/underline/reverse; other CSI / OSC skipped; wide characters take two cells), and nearest-256 color mapping for curses.
# usage: imported (from map import screen); grid, clipped = screen.parse(text, width, height)
# ---
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple


class Attr(NamedTuple):
    fg: object = None  # None | 0–255 | (r, g, b)
    bg: object = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False


PLAIN = Attr()
BLANK = (" ", PLAIN)
TOKEN = re.compile(r"\x1b\[([0-9;:?]*)([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]|([^\x1b]+)")


def _color(params, i):
    """(color, params consumed after the 38/48) for an extended color, or (None, rest)."""
    if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
        return params[i + 2] & 255, 2
    if i + 1 < len(params) and params[i + 1] == 2 and i + 4 < len(params):
        return tuple(max(0, min(255, v)) for v in params[i + 2:i + 5]), 4
    return None, len(params)


def sgr(attr, raw):
    params = [int(p) if p.isdigit() else 0 for p in re.split(r"[;:]", raw)] if raw else [0]
    a = attr._asdict()
    i = 0
    while i < len(params):
        p = params[i]
        if p == 0:
            a = PLAIN._asdict()
        elif p == 1:
            a["bold"] = True
        elif p == 2:
            a["dim"] = True
        elif p == 3:
            a["italic"] = True
        elif p == 4:
            a["underline"] = True
        elif p == 7:
            a["reverse"] = True
        elif p == 22:
            a["bold"] = a["dim"] = False
        elif p == 23:
            a["italic"] = False
        elif p == 24:
            a["underline"] = False
        elif p == 27:
            a["reverse"] = False
        elif 30 <= p <= 37:
            a["fg"] = p - 30
        elif 90 <= p <= 97:
            a["fg"] = p - 90 + 8
        elif 40 <= p <= 47:
            a["bg"] = p - 40
        elif 100 <= p <= 107:
            a["bg"] = p - 100 + 8
        elif p == 39:
            a["fg"] = None
        elif p == 49:
            a["bg"] = None
        elif p in (38, 48):
            color, used = _color(params, i)
            if color is not None:
                a["fg" if p == 38 else "bg"] = color
            i += used
        i += 1
    return Attr(**a)


def char_width(ch):
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def parse(text, width, height):
    """(rows, clipped): `height` rows of `width` cells; clipped is True when a line ran past `width`."""
    rows, row, attr, clipped = [], [], PLAIN, False

    def end_row():
        nonlocal row
        rows.append((row + [BLANK] * width)[:width])
        row = []

    for m in TOKEN.finditer(text or ""):
        if m.group(3) is not None:
            for ch in m.group(3):
                if ch == "\n":
                    end_row()
                elif ch == "\r":
                    continue
                elif ch == "\t":
                    row.extend([(" ", attr)] * (8 - len(row) % 8))
                elif ch < " " or ch == "\x7f":
                    continue
                else:
                    w = char_width(ch)
                    if w == 0:
                        continue
                    if len(row) + w > width:
                        clipped = True
                        continue
                    row.append((ch, attr))
                    if w == 2:
                        row.append(("", attr))  # the second half of a wide character
        elif m.group(2) == "m":
            attr = sgr(attr, m.group(1))
    if row:
        end_row()
    rows = rows[-height:] if len(rows) > height else rows
    while len(rows) < height:
        rows.append([BLANK] * width)
    return rows, clipped


CUBE = (0, 95, 135, 175, 215, 255)


def nearest256(rgb):
    """xterm-256 index closest to an (r, g, b) color: the 6×6×6 cube or the gray ramp."""
    r, g, b = rgb

    def level(v):
        return min(range(6), key=lambda i: abs(CUBE[i] - v))

    ci = (level(r), level(g), level(b))
    cube = tuple(CUBE[i] for i in ci)
    gray_i = max(0, min(23, round((sum(rgb) / 3 - 8) / 10)))
    gray = 8 + 10 * gray_i

    def dist(c):
        return sum((x - y) ** 2 for x, y in zip(c, rgb))

    if dist((gray,) * 3) < dist(cube):
        return 232 + gray_i
    return 16 + 36 * ci[0] + 6 * ci[1] + ci[2]
