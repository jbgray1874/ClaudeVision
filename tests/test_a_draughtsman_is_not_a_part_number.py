"""A name and a date in a title block must not be costed as a part.

On the 10575-02 Dyson pack the engine produced a part called `ANDREW-14`. It came from the title
block, which reads:

    DRAWN BY: P.Andrew - 14/11/2023

The draughtsman's surname and the day of the month. That "part" was then given the material MDF —
picked up from a revision note reading "MDF PANEL REMOVED" — measured against the geometry of the
entire GA sheet (39 paths, 663 line segments, a "cut length" of 12,232 mm), flagged
`no usable geometry` / `no_part_dxf` at confidence 0.38, and costed anyway at £108.73 material
plus £37.57 labour. Four other prose fragments were read as part numbers on the same drawing.

The flags were all raised correctly. The line was costed regardless, which is the deeper problem,
but the first thing to fix is that it should never have been a line.

WHERE IT COMES FROM. `PART_NUMBER_PATTERN` in config.py offers three shapes for the leading
segment of a code:

    \\d{4,5}[A-Z]?      |   [A-Z]{1,6}\\d{0,4}   |   FIXING\\d*

The middle one allows `\\d{0,4}` — ZERO digits. So any run of one to six letters is a valid part
number head, and `ANDREW` is six letters. Follow it with ` - 14` from the date and the pattern is
satisfied.

THE RULE THAT ACTUALLY HOLDS. Every real SDI part number carries a digit in its first segment:
10575-02, BE2030-10, 12173-02-GA. The catalogue codes that are alpha-led — FIXING591, VINYL03,
SUBPLAS72 — attach their digits directly and never take the hyphenated form this pattern reads.
So a hyphenated code whose head is pure letters is prose, every time we have seen it.

TWO DEFENCES, DELIBERATELY. Dates are masked out of the text before part numbers are scanned for,
AND the head must contain a digit. Either alone would have stopped ANDREW-14. Both are cheap, and
the title block is the one place where prose and part numbers sit closest together.

KNOWN LIMIT, recorded rather than hidden: a genuine part number of the form `1-2-03` would be
masked as a date. No such code exists in the corpus and the shape is not one SDI uses, but if one
ever appears this is where to look.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from extractor_patterns import (  # noqa: E402
    _extract_part_number_candidates,
    _looks_like_part_number,
)


def _kept(text: str):
    """What the pipeline would actually keep: extracted, then filtered."""
    return [c for c in _extract_part_number_candidates(text) if _looks_like_part_number(c)]


# ── The 10575-02 fault itself ──────────────────────────────────────────────────

_TITLE_BLOCK = "DRAWN BY: P.Andrew - 14/11/2023    CHECKED BY: J.Smith - 02/12/2023"


def test_the_draughtsman_and_the_date_are_not_a_part():
    got = _kept(_TITLE_BLOCK)
    assert got == [], f"title-block prose was read as part numbers: {got}"


@pytest.mark.parametrize("name", ["ANDREW", "SMITH", "Andrew", "Smith"])
def test_no_surname_survives_into_a_part_number(name):
    assert not any(name.upper() in c.upper() for c in _kept(_TITLE_BLOCK))


def test_a_bare_name_and_number_is_still_refused_without_the_date():
    """The digit rule stands on its own — masking the date is not the only defence."""
    assert _kept("APPROVED BY: P.Andrew - 14") == []


def test_a_date_alone_yields_nothing():
    assert _kept("ISSUED 14/11/2023") == []
    assert _kept("14-11-2023") == []


# ── The codes that must keep working ───────────────────────────────────────────

@pytest.mark.parametrize("code", ["10575-02", "BE2030-10", "12173-02-GA", "1282-01", "3886-02"])
def test_a_real_part_number_is_still_read(code):
    assert code in _kept(f"PART NO: {code}"), f"{code} stopped being recognised"


def test_a_real_code_beside_a_date_survives_the_masking():
    """Masking the date must remove the date, not the line it sits on."""
    got = _kept("10575-02  REV D  14/11/2023")
    assert "10575-02" in got
    assert not any("14" == c or c.endswith("- 14") for c in got)


def test_a_multi_segment_code_is_not_truncated():
    assert "12173-02-GA" in _kept("DWG NO 12173-02-GA SHEET 1/4")


def test_the_head_must_carry_a_digit():
    """The rule stated plainly, so a future widening of the pattern has to face it."""
    assert _looks_like_part_number("BE2030-10")
    assert _looks_like_part_number("10575-02")
    assert not _looks_like_part_number("ANDREW-14")
    assert not _looks_like_part_number("PANEL-02")


def test_prose_in_a_revision_note_is_not_a_part():
    """The same drawing read four other fragments as parts. This is the shape of them."""
    for prose in ("MDF PANEL REMOVED", "SEE DETAIL - A", "ISSUED FOR - CONSTRUCTION",
                  "NOTE - 2", "APPROVED - JS"):
        assert _kept(prose) == [], f"{prose!r} was read as a part number"
