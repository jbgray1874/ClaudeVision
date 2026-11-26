"""A drawing reference printed beside a stock code, in its pack's spellings (Hotel Chocolat).

Some drawing offices number a part twice on its parts list: ITEM NO | FINISHED PART NO. |
DRG NO. | DESCRIPTION | QTY -- "1 | 10100530 | B.34109 | LOW TABLE GA | 1". The finished
part number is a stock code; the drawing number is the sheet that details the part, the
title block that sheet carries (DRG No. B.34109) and the name of its cut file
(nc1-b34109.DXF). The bill reader anchors one code column, so the two arrived glued
together ("10100438B.33579") and nothing in the pack could join a part to its own sheet,
its DXF or the parent line that counts it.

A line with a drawing reference is identified by that reference -- the drawing IS the part
-- and keeps its stock code beside it. A line whose drawing column says N/A is a purchase,
identified by its stock code.

Shape only: one letter, a dot or hyphen, five digits. One letter so a word or a
standard is never read as a sheet; five digits so a size or a quantity is never one either.
"""
import re
from typing import Optional, Tuple

# In drawing text and on a bill the separator is required: a letter and five digits with
# none ("J13092", an M&S catalogue item) is somebody's stock code. A cut file's name may
# drop it, because its name is nothing but the reference ("nc1-b33579").
# Never M: M is a thread, and an M-something is a fastener, whatever follows it.
_REF = r"([A-LN-Z])[.\-](\d{5})"
_ANY_REF = r"([A-LN-Z])[.\-]?(\d{5})"
_WHOLE_REF = re.compile(rf"^{_REF}$", re.I)
_WHOLE_ANY = re.compile(rf"^{_ANY_REF}$", re.I)
_STOCK = r"(\d{6,10})"
# Stock code then drawing reference, or the reverse, with or without a space between.
_GLUED = re.compile(rf"^{_STOCK}\s*{_REF}$", re.I)
_GLUED_REV = re.compile(rf"^{_REF}\s*{_STOCK}$", re.I)
# Stock code with an empty drawing column written as N/A, or a dash for the stock code.
_STOCK_NA = re.compile(rf"^{_STOCK}\s*N/?A$", re.I)
_DASH_REF = re.compile(rf"^(?:-+|N/?A)\s*{_REF}$", re.I)
# A drawing reference inside a cut file's name: "nc1-b33579.DXF", "nc1-b33519_3 Person ...".
_IN_NAME = re.compile(rf"(?:^|[\-_\s]){_ANY_REF}(?=$|[\-_\s.])", re.I)


def is_drawing_reference(text) -> bool:
    return bool(_WHOLE_REF.match(str(text or "").strip()))


def compact(text) -> str:
    """One spelling for B.33579, B-33579 and B33579: B33579. Anything else unchanged."""
    s = str(text or "").strip()
    m = _WHOLE_ANY.match(s)
    return f"{m.group(1).upper()}{m.group(2)}" if m else s


def split_line_code(raw) -> Tuple[str, Optional[str], Optional[str]]:
    """(identity, stock code, drawing reference) for a bill line's code cell.

    The identity is the drawing reference as printed when there is one, else the stock
    code; a cell this does not recognise comes back unchanged with neither half.
    """
    s = re.sub(r"\s+", " ", str(raw or "").strip())
    m = _WHOLE_REF.match(s)
    if m:
        ref = _printed(s, m.group(1), m.group(2))
        return ref, None, ref
    for rx, stock_first in ((_GLUED, True), (_GLUED_REV, False)):
        m = rx.match(s)
        if m:
            g = m.groups()
            stock, letter, digits = (g[0], g[1], g[2]) if stock_first else (g[2], g[0], g[1])
            ref = _printed(s, letter, digits)
            return ref, stock, ref
    m = _STOCK_NA.match(s)
    if m:
        return m.group(1), m.group(1), None
    m = _DASH_REF.match(s)
    if m:
        ref = _printed(s, m.group(1), m.group(2))
        return ref, None, ref
    return str(raw or "").strip(), None, None


def _printed(text: str, letter: str, digits: str) -> str:
    """The reference as the drawing office wrote it (B.33579 stays dotted)."""
    m = re.search(rf"{letter}([.\-]?){digits}", text, re.I)
    return f"{letter.upper()}{m.group(1) if m else ''}{digits}"


def reference_in_file_name(stem) -> Optional[str]:
    """The drawing reference a cut file is named by, compacted ("nc1-b33579" -> B33579)."""
    m = _IN_NAME.search(str(stem or ""))
    return f"{m.group(1).upper()}{m.group(2)}" if m else None
