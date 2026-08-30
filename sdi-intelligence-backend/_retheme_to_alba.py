"""Retheme the SDI Intelligence portal to the Alba PIP design system.

The portal was already token-based and used the same variable NAMES as Alba, so this is a value
migration rather than a rewrite. Every colour is mapped in ONE simultaneous pass — chained
replacement would corrupt the palette, because Alba's rail colour (#0d0d0f) is the portal's old
page ground, so a sequential map would rewrite it twice.

Run from sdi-intelligence-backend/.
"""
import re
import sys
from pathlib import Path

TARGETS = [
    "sdi-intelligence-portal.html",
    "sdi-estimating-intelligence.html",
    "sdi-estimating-guide.html",
    "SDI_Intelligence_FAQ.html",
    "SDI_Intelligence_RD_Capture.html",
    "SDI_Intelligence_Technical_Reference.html",
    "SDI_Intelligence_Worked_Example.html",
    "_inject_sidebar.py",
]

# --- hex, old -> Alba ------------------------------------------------------------------------
HEX = {
    "#0d0d0f": "#0a0a0b",   # page ground
    "#141417": "#0d0d0f",   # secondary ground -> Alba rail
    "#17171b": "#121214",   # surface
    "#1d1d22": "#17171a",   # surface-2
    "#2a2a31": "#26262b",   # line
    "#202026": "#1e1e22",   # line-soft
    "#f3f2ee": "#f0efec",   # ink
    "#a3a3aa": "#9b9ba3",   # ink-dim
    "#6b6b73": "#6a6a72",   # ink-faint
    "#ffd400": "#e8a33d",   # accent  (pure yellow -> Alba amber)
    "#e6be00": "#cf8c26",   # accent-deep
    "#5fd08a": "#4ec97f",   # ok
    "#ff9d42": "#e8a33d",   # warn — Alba deliberately uses the accent for "attention"
    "#ff5d5d": "#e8544f",   # fail
    "#6db3ff": "#6da8e8",   # info
}

# --- rgb triplets inside rgba(), old -> Alba -------------------------------------------------
RGB = {
    ("255", "212", "0"):   ("232", "163", "61"),
    ("230", "190", "0"):   ("207", "140", "38"),
    ("95", "208", "138"):  ("78", "201", "127"),
    ("255", "157", "66"):  ("232", "163", "61"),
    ("255", "93", "93"):   ("232", "84", "79"),
    ("109", "179", "255"): ("109", "168", "232"),
    ("13", "13", "15"):    ("10", "10", "11"),
}

FONT_LINK = ("https://fonts.googleapis.com/css2?"
             "family=Inter:wght@400;500;600;700;800"
             "&family=JetBrains+Mono:wght@400;500;600"
             "&family=Spectral:wght@400;600"
             "&display=swap")

_hex_re = re.compile("|".join(re.escape(k) for k in HEX), re.IGNORECASE)
_rgb_re = re.compile(r"(rgba?\(\s*)(\d+)(\s*,\s*)(\d+)(\s*,\s*)(\d+)")
_link_re = re.compile(r"https://fonts\.googleapis\.com/css2\?[^\"'\s>]+")


def migrate_colours(text):
    text = _hex_re.sub(lambda m: HEX[m.group(0).lower()], text)

    def rgb(m):
        key = (m.group(2), m.group(4), m.group(6))
        if key in RGB:
            r, g, b = RGB[key]
            return m.group(1) + r + m.group(3) + g + m.group(5) + b
        return m.group(0)

    return _rgb_re.sub(rgb, text)


def migrate_fonts(text):
    text = _link_re.sub(FONT_LINK, text)

    # Alba runs the whole application on Inter; the display face goes with it. Spectral is added
    # for document-style content (the report sheets) so the token exists wherever it is wanted.
    text = re.sub(r"--disp:\s*'[^']*'\s*,\s*sans-serif",
                  "--disp:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif", text)
    text = re.sub(r"--body:\s*'[^']*'\s*,\s*sans-serif",
                  "--body:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif", text)
    text = text.replace("'Hanken Grotesk',sans-serif",
                        "'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif")
    text = text.replace("'Archivo',sans-serif",
                        "'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif")

    # Add --serif next to --mono if the file has a token block and does not already carry it.
    if "--mono:" in text and "--serif:" not in text:
        text = re.sub(r"(--mono:[^;]+;)",
                      r"\1\n    --serif:'Spectral','Source Serif 4',Georgia,serif;",
                      text, count=1)
    return text


def main():
    changed = []
    for name in TARGETS:
        p = Path(name)
        if not p.exists():
            print(f"  SKIP (missing): {name}")
            continue
        before = p.read_text(encoding="utf-8", errors="strict")
        after = migrate_fonts(migrate_colours(before))
        if after != before:
            p.write_text(after, encoding="utf-8")
            changed.append(name)
            print(f"  rethemed: {name}")
        else:
            print(f"  no change: {name}")
    print(f"\n{len(changed)} file(s) rethemed.")


if __name__ == "__main__":
    sys.exit(main())
