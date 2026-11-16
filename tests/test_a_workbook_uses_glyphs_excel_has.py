"""No cell depends on a character the estimators' Excel cannot draw.

The AI Provenance tab's summary line read

    Engine read the drawing & model:  🟢 0 measured/confirmed   🟡 1 reported
    🔴 1 needs a look   |   Pricing:  💷 3 priced   ⏳ 1 awaiting your rate

and a reviewer reported "visible replacement characters in headings and CURRENCY LABELS"
on 10975-02's workbook. The currency label was an emoji pound note. Nothing was corrupt —
the file is valid UTF-8 and carries no U+FFFD anywhere — but every one of those five is an
ASTRAL-PLANE codepoint (above U+FFFF), and Excel's Calibri has no glyph for any of them.
On the machines that matter they drew as empty boxes, and through a console that is not
UTF-8 they extract as `?`.

A status a reader cannot see is not a status. The counts were always the content, so the
line says them in words; the two marker cells further up the same tab say nothing their
own row does not already say in column B, and the fill colour still marks them.

BMP symbols are left alone deliberately — £, —, ×, ·, Ø, ⚠ all draw in the workbook's own
fonts. The rule is about the plane, not about punctuation.
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

# The modules that write cells into the workbook the estimators open. A report that only
# ever becomes HTML in a browser is not bound by this — a browser has the fonts.
_WORKBOOK_WRITERS = ("estimation_report.py", "wb_populate.py", "quantity_breaks_tab.py",
                     "material_price_break.py", "estimator_inputs.py")


def _astral(text: str):
    return sorted({ch for ch in text if ord(ch) > 0xFFFF})


def test_no_workbook_writer_depends_on_an_astral_glyph():
    offenders = {}
    for name in _WORKBOOK_WRITERS:
        path = _SRC / name
        if not path.is_file():
            continue
        found = _astral(path.read_text(encoding="utf-8"))
        if found:
            offenders[name] = [f"U+{ord(c):04X} {c}" for c in found]
    assert not offenders, (
        f"These write cells an estimator's Excel cannot draw: {offenders}. Say it in "
        f"words, or use a BMP symbol the workbook's own fonts carry.")


def test_the_provenance_banner_still_states_every_count():
    """Removing the glyphs must not remove the information. The counts are the content."""
    src = (_SRC / "estimation_report.py").read_text(encoding="utf-8")
    for phrase in ("measured/confirmed", "reported", "needs a look",
                   "priced", "awaiting your rate"):
        assert phrase in src, phrase


def test_the_pound_sign_and_the_em_dash_are_left_alone():
    """The rule is about the PLANE, not about punctuation — £ and — draw everywhere, and a
    test that banned them would strip the workbook of its own voice."""
    assert _astral("£1,234.56 — 3050 × 2050 · Ø6 ⚠") == []
