#!/usr/bin/env python3
"""Render ANSI truecolor text to a PNG, one cell per character, for README screenshots.

Usage:
  bash statusline.sh --demo | python3 tools/render_png.py docs/demo.png --font /path/to/font.ttf

Requires Pillow (pip install pillow) and a monospace font file (.ttf/.otf/.ttc). Powerline arrows
(U+E0B0-U+E0B3) are drawn as shapes that fill the cell, the way terminals such as xterm.js do.
"""
import argparse
import re
import sys
import unicodedata

from PIL import Image, ImageDraw, ImageFont

THEMES = {"dark": ((40, 44, 52), (255, 255, 255)), "light": ((255, 255, 255), (46, 52, 54))}


def parse(text, fg0):
    lines, fg, bg, bold, faint = [[]], fg0, None, False, False
    i = 0
    while i < len(text):
        if text.startswith("\x1b[", i):
            m = re.match(r"\x1b\[([0-9;]*)m", text[i:])
            ps = [int(p) if p else 0 for p in m.group(1).split(";")]
            j = 0
            while j < len(ps):
                p = ps[j]
                if p == 0:
                    fg, bg, bold, faint = fg0, None, False, False
                elif p == 1:
                    bold = True
                elif p == 2:
                    faint = True
                elif p == 22:
                    bold = faint = False
                elif p == 39:
                    fg = fg0
                elif p == 49:
                    bg = None
                elif p in (38, 48) and j + 4 < len(ps) and ps[j + 1] == 2:
                    rgb = tuple(ps[j + 2:j + 5])
                    if p == 38:
                        fg = rgb
                    else:
                        bg = rgb
                    j += 4
                j += 1
            i += len(m.group(0))
            continue
        if text.startswith("\x1b]", i):
            m = re.match(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", text[i:])
            i += len(m.group(0))
            continue
        c = text[i]
        if c == "\n":
            lines.append([])
        else:
            color = tuple(v // 2 + 60 for v in fg) if faint else fg
            lines[-1].append((c, color, bg, bold))
        i += 1
    return lines


def cells(c):
    return 2 if unicodedata.east_asian_width(c) in "WF" else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", help="PNG file to write")
    ap.add_argument("--font", required=True, help="monospace font file")
    ap.add_argument("--bold-index", type=int, default=None, help="face index of the bold style in a .ttc")
    ap.add_argument("--theme", choices=THEMES, default="dark", help="terminal background (default: dark)")
    ap.add_argument("--size", type=int, default=30, help="font size in pixels (default: 30)")
    args = ap.parse_args()

    bg0, fg0 = THEMES[args.theme]
    lines = parse(sys.stdin.read(), fg0)
    regular = ImageFont.truetype(args.font, args.size)
    bold = ImageFont.truetype(args.font, args.size, index=args.bold_index) if args.bold_index is not None else regular
    ascent, descent = regular.getmetrics()
    cw, ch = int(regular.getlength("W")), ascent + descent
    cols = max((sum(cells(c[0]) for c in ln) for ln in lines), default=1)
    pad = 16
    img = Image.new("RGB", (cols * cw + 2 * pad, len(lines) * ch + 2 * pad), bg0)
    draw = ImageDraw.Draw(img)
    for row, ln in enumerate(lines):
        x, y = pad, pad + row * ch
        for c, fg, bg, is_bold in ln:
            w = cw * cells(c)
            if bg:
                draw.rectangle([x, y, x + w - 1, y + ch - 1], fill=bg)
            if 0xE0B0 <= ord(c) <= 0xE0B3:
                right = ord(c) in (0xE0B0, 0xE0B1)
                pts = [(x, y), (x + w - 1, y + ch // 2), (x, y + ch - 1)] if right else \
                      [(x + w - 1, y), (x, y + ch // 2), (x + w - 1, y + ch - 1)]
                if ord(c) in (0xE0B0, 0xE0B2):
                    draw.polygon(pts, fill=fg)
                else:
                    draw.line(pts, fill=fg, width=2)
            else:
                draw.text((x, y + ascent), c, font=bold if is_bold else regular, fill=fg, anchor="ls")
            x += w
    img.save(args.out)
    print(args.out, img.size)


if __name__ == "__main__":
    main()
