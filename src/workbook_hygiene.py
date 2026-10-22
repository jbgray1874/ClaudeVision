"""Nothing reaches an estimator as a character Excel cannot draw, or a broken reference.

James, on the 7332-01 six-off book: "Remove the visible replacement characters from
workbook/report text", and "Estimate!J20 contains the invalid Material Price Break!#REF!;
M20 inherits the error... It must never produce #REF!."

WHY THESE ARE BOUNDARY QUESTIONS AND NOT BUG HUNTS. Both faults are made downstream of the
code that would be blamed for them.

  A REPLACEMENT CHARACTER   There is no U+FFFD anywhere in this source tree. It is
                            manufactured at RUN TIME, and by more than one route: a drawing
                            note decoded from cp1252 as UTF-8, a supplier description
                            carried through a console that is not UTF-8, a string read back
                            out of the estimators' own .xls. A grep for the character can
                            never find the cause, because the mangling is at render time.

  A #REF!                   Comes from the TEMPLATE, not from us. openpyxl's
                            ws.cell(..., value=None) assigns nothing, so a price cell the
                            engine believed it had left blank keeps whatever formula the
                            blank template held -- and one of those formulas is broken.
                            The engine already clears the cells it knows about; this is for
                            the ones it does not, which by definition cannot be enumerated.

So both are asked ONCE, at the last point every deliverable passes through, on the VALUE
rather than on the source. That is the standard the rest of this engine is held to: it has
to fire on every drawing, not on the job that exposed it.

WHAT IS REMOVED, AND ONLY THIS:

  U+FFFD            Already damage when it arrives. The original character is gone and
                    cannot be recovered here, so the honest thing is to drop the box rather
                    than print it: it tells the estimator nothing except that we mishandled
                    something.

  ASTRAL PICTOGRAPHS  Emoji and their kin, above U+FFFF. Valid UTF-8, and Excel's Calibri
                    has no glyph for any of them, so on the machines that matter they draw
                    as empty boxes and through a non-UTF-8 console they extract as "?".

  #REF! FORMULAS    A formula containing #REF! is broken by definition -- Excel can never
                    evaluate it, and every cell that reads it inherits the error, which is
                    how one bad price cell took out its extended-cost column too. It is
                    replaced with nothing, which is what an unpriced line should show, and
                    the run says loudly which cell it was so the template gets repaired at
                    source rather than papered over here every run.

BMP SYMBOLS ARE LEFT ALONE, DELIBERATELY. The pound sign, em dash, multiplication sign,
middle dot, diameter sign and warning sign all draw in the workbook's own fonts. The rule
is about the plane, not about punctuation -- stripping those would damage real content to
fix a problem they do not have.

NOTHING IS TRANSLITERATED INTO WORDS. A dropped pictograph was decoration beside text that
already said the thing; inventing a word for it would put this engine's wording into a cell
an estimator reads as the shop's.

THE SOURCE OF THIS MODULE IS PURE ASCII, and a test asserts it. Every character it removes
is named by chr(0xNNNN), never pasted -- including U+FFFD and the variation selectors, which are
in the BMP and so would slip past a test that only looks above U+FFFF. An earlier version of
this docstring claimed as much while the file itself carried literal copies of them; the
claim is now true and checked rather than asserted.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

__all__ = [
    "repair",
    "needs_repair",
    "scrub_workbook",
    "scrub_report_text",
    "is_broken_formula",
]

_REPLACEMENT = chr(0xFFFD)
# The invisible modifiers that ask for emoji presentation. Removed alongside the
# pictographs they qualify: left behind on their own they are a zero-width character that
# some fonts draw as a box of their own.
_INVISIBLE = (chr(0xFE0F),   # VARIATION SELECTOR-16, "draw the one before me as emoji"
              chr(0xFE0E),   # VARIATION SELECTOR-15, its text-presentation twin
              chr(0x200D))   # ZERO WIDTH JOINER, which glues emoji sequences

_BROKEN_REF = "#REF!"


def _is_astral_pictograph(ch: str) -> bool:
    """True for a codepoint above the BMP that no spreadsheet font is going to carry.

    Everything above U+FFFF is treated this way EXCEPT the supplementary planes that hold
    real writing -- a CJK extension or a historic script is somebody's actual text, and a
    cell carrying it is not our business to edit.
    """
    cp = ord(ch)
    if cp <= 0xFFFF:
        return False
    if 0x20000 <= cp <= 0x3FFFF:        # CJK ideograph extensions - real text
        return False
    if 0x10000 <= cp <= 0x1CFFF and not (0x1F000 <= cp <= 0x1FAFF):
        # Plane 1 below the symbol blocks is ancient scripts, music and maths alphanumerics:
        # letters somebody chose, even where a font may not carry them.
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
    collapsed -- a leading gap where an icon used to be reads as a formatting fault of its
    own -- but only runs of SPACES are touched, never newlines or the tab alignment the
    text reports depend on.
    """
    if not isinstance(text, str) or not needs_repair(text):
        return text

    kept: List[str] = []
    for ch in text:
        if ch == _REPLACEMENT or ch in _INVISIBLE or _is_astral_pictograph(ch):
            continue
        kept.append(ch)

    lines = []
    for line in "".join(kept).split("\n"):
        while "  " in line:
            line = line.replace("  ", " ")
        lines.append(line.strip())
    return "\n".join(lines)


def is_broken_formula(value: Any) -> bool:
    """A formula Excel can never evaluate, and every cell reading it inherits the error."""
    return isinstance(value, str) and value.startswith("=") and _BROKEN_REF in value


def scrub_report_text(text: Any) -> Any:
    """The same pass for a rendered report, which is text rather than cells.

    A browser has the fonts a spreadsheet does not, so a pictograph in an HTML report is
    not the fault this fixes -- a REPLACEMENT CHARACTER is, and it renders as a black
    diamond in every browser there is. The whole document is one string here, so the
    space-collapsing in `repair` would reflow the markup; only the damaged characters are
    dropped, and the layout is left exactly as the builder wrote it.
    """
    if not isinstance(text, str):
        return text
    if not any(ch == _REPLACEMENT or ch in _INVISIBLE or _is_astral_pictograph(ch)
               for ch in text):
        return text
    return "".join(
        ch for ch in text
        if not (ch == _REPLACEMENT or ch in _INVISIBLE or _is_astral_pictograph(ch))
    )


def scrub_workbook(wb: Any) -> Tuple[int, Dict[str, int], List[str]]:
    """Repair every string cell in every sheet, and blank every broken formula.

    Returns (cells changed, count per sheet, the broken-formula cells by address). The
    third is returned separately and named cell by cell BECAUSE IT IS NOT OUR BUG: a
    #REF! comes from the template, and a run that quietly cleaned it every time would hide
    a fault that wants fixing in the template itself.

    Merged continuation cells are skipped rather than written: openpyxl exposes them and
    refuses the assignment, and the value lives on the anchor anyway, which this walk
    reaches in its own right.
    """
    changed = 0
    per_sheet: Dict[str, int] = {}
    broken: List[str] = []
    for ws in getattr(wb, "worksheets", []) or []:
        here = 0
        try:
            rows = ws.iter_rows()
        except Exception:
            continue
        for row in rows:
            for cell in row:
                value = getattr(cell, "value", None)
                if not isinstance(value, str):
                    continue
                if cell.__class__.__name__ == "MergedCell":
                    continue
                if is_broken_formula(value):
                    try:
                        cell.value = None
                    except Exception:
                        continue
                    broken.append(f"{getattr(ws, 'title', '?')}!{cell.coordinate}")
                    here += 1
                    continue
                if not needs_repair(value):
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
    return changed, per_sheet, broken
