"""Nothing reaches an estimator's screen as a character their Excel cannot draw.

James, on the 7332-01 six-off book: "Remove the visible replacement characters from
workbook/report text."

WHY THIS IS A BOUNDARY AND NOT A BUG HUNT. There is no U+FFFD anywhere in this source
tree — the substitution happens at RUN TIME, downstream of us, and there is more than one
way in: a drawing note decoded from cp1252 bytes as UTF-8, a supplier description carried
through a console that is not UTF-8, a value read back out of the estimators' own .xls
template. Chasing whichever one produced a given book fixes that book. Asking the question
once, at the last point every book passes through, fixes the class — which is the standard
everything else here is held to: it has to fire on every drawing, not on this job.

Two kinds of character are removed, and only two:

  U+FFFD REPLACEMENT CHARACTER   Already damage when it arrives. Some byte failed to
                                 decode upstream and the decoder wrote a box. The original
                                 character is gone and cannot be recovered here, so the
                                 honest thing is to drop the box rather than print it: it
                                 tells the estimator nothing except that we mishandled it.

  ASTRAL PICTOGRAPHS (> U+FFFF)  Emoji and their kin. Not corrupt, and valid UTF-8, but
                                 Excel's Calibri has no glyph for any of them, so on the
                                 machines that matter they draw as empty boxes and through
                                 a non-UTF-8 console they extract as "?". This is the rule
                                 test_a_workbook_uses_glyphs_excel_has.py already holds the
                                 five known writers to; here it is enforced on the VALUE
                                 rather than on the source, so a pictograph that arrives
                                 from a price source, a drawing note or a module nobody
                                 thought to add to that list is caught just the same.

BMP SYMBOLS ARE LEFT ALONE, DELIBERATELY. £, —, ×, ·, Ø, ⚠, ° and the rest all draw in the
workbook's own fonts. The rule is about the plane, not about punctuation — stripping those
would damage real content to fix a problem they do not have.

NOTHING IS TRANSLITERATED INTO WORDS. A dropped pictograph was decoration beside text that
already said the thing; inventing a word for it would put this engine's wording into a cell
an estimator reads as the shop's. Where a count or a status mattered, its own row says it.

The source of this module is deliberately plain ASCII — the characters it removes are named
by codepoint escape, never pasted in — so that the module which enforces the glyph rule can
itself be added to the list the glyph rule checks.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

__all__ = [
    "repair",
    "needs_repair",
    "scrub_workbook",
]

# U+FFFD, and the invisible modifiers that ask for emoji presentation. The selectors are
# removed alongside the pictographs they qualify: left behind on their own they are a
# zero-width character that some fonts draw as a box of their own.
_REPLACEMENT = "�"
_INVISIBLE = ("️", "︎", "‍")


def _is_astral_pictograph(ch: str) -> bool:
    """True for a codepoint above the BMP that no spreadsheet font is going to carry.

    Everything above U+FFFF is treated this way EXCEPT the supplementary planes that hold
    real writing — a CJK extension or a historic script is somebody's actual text, and a
    cell carrying it is not our business to edit. Planes 1 and 14 are where the
    pictographs, the tags and the variation supplements live.
    """
    cp = ord(ch)
    if cp <= 0xFFFF:
        return False
    if 0x20000 <= cp <= 0x3FFFF:        # CJK ideograph extensions - real text
        return False
    if 0x10000 <= cp <= 0x1CFFF and not (0x1F000 <= cp <= 0x1FAFF):
        # Plane 1 below the symbol blocks is ancient scripts, music and maths alphanumerics.
        # Maths alphanumerics (1D400-1D7FF) do not draw either, but they are letters
        # somebody chose; leave them and let the caller see them in the report.
        return False
    return True


def needs_repair(text: Any) -> bool:
    """Whether `repair` would change this value. Cheap enough to ask of every cell."""
    if not isinstance(text, str):
        return False
    return any(
        ch == _REPLACEMENT or ch in _INVISIBLE or _is_astral_pictograph(ch)
        for ch in text
    )


def repair(text: Any) -> Any:
    """The same text with the undrawable characters gone, or the value untouched.

    Non-strings pass straight through, so this can be asked of any cell value without the
    caller testing the type first. Whitespace left stranded by a dropped character is
    collapsed, because "  12 parts" with a leading gap where an icon used to be reads as a
    formatting fault of its own -- but only runs of SPACES are touched, never newlines or
    the tab alignment the text reports depend on.
    """
    if not isinstance(text, str) or not needs_repair(text):
        return text

    kept: List[str] = []
    for ch in text:
        if ch == _REPLACEMENT or ch in _INVISIBLE or _is_astral_pictograph(ch):
            continue
        kept.append(ch)
    out = "".join(kept)

    # Collapse the gaps the removals left, line by line so no newline is eaten.
    lines = []
    for line in out.split("\n"):
        while "  " in line:
            line = line.replace("  ", " ")
        lines.append(line.strip())
    return "\n".join(lines)


def scrub_workbook(wb: Any) -> Tuple[int, Dict[str, int]]:
    """Repair every string cell in every sheet. Returns (cells changed, count per sheet).

    Merged continuation cells are skipped rather than written: openpyxl exposes them and
    refuses the assignment, and the value lives on the anchor anyway, which this walk
    reaches in its own right.

    A workbook that needs nothing is walked and left exactly as it was -- the assignment
    only happens where the value actually differs, so nothing is marked dirty for free.
    """
    changed = 0
    per_sheet: Dict[str, int] = {}
    for ws in getattr(wb, "worksheets", []) or []:
        here = 0
        try:
            rows = ws.iter_rows()
        except Exception:
            continue
        for row in rows:
            for cell in row:
                value = getattr(cell, "value", None)
                if not isinstance(value, str) or not needs_repair(value):
                    continue
                if cell.__class__.__name__ == "MergedCell":
                    continue
                try:
                    cell.value = repair(value)
                except Exception:
                    # Read-only or otherwise refused: leave it rather than fail the save.
                    continue
                here += 1
        if here:
            per_sheet[str(getattr(ws, "title", "?"))] = here
            changed += here
    return changed, per_sheet
