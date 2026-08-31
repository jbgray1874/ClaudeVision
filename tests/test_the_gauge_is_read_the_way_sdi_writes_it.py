"""SDI writes "1.5 THK". The reader looked for "THK: 1.5", and took the next number instead.

FOUND BEFORE THE 12552 RUN, by putting the real extractors over the real GA rather than
trusting a description of it. Every sheet in SDI's own drawing template states the gauge as a
dimension: "1.5 THK", "2 THK", "1.2 THK" — value first, label second, no "mm".

THICKNESS_PATTERN matched the label first and the number after it. Two failures came out of
that, and the second is far worse than the first.

  NOTHING READ. 12552's 02-05M, 02-09M, 01-03M and 02-03M all state their gauge and all
  returned nothing, so the thickness fell through to SolidWorks, a DXF, or inference. On a pack
  with no DXFs — which 12552 is — that is the whole of the evidence gone.

  THE WRONG NUMBER READ. On 01-04M the extracted text runs "1.5 THK" and then, on the following
  line, "39.5" — the box-section dimension. Label-then-number matched across the break and
  captured 39.5. A 1.5 mm corner upright would carry a title-block gauge of 39.5 mm, stamped
  drawing_deterministic at rank 70, where nothing below a model or a DXF can displace it — and
  12552 has neither unless the SolidWorks seat attaches. Twenty-six times the material, on four
  parts, because a regex was looking the wrong way round.

VALUE-FIRST IS TRIED FIRST, AND THAT ORDERING IS THE FIX. On "1.5 THK 39.5" the value-first
branch consumes through the label, so the trailing dimension is no longer available to the
label-first branch: the correct reading wins and the wrong one becomes unreachable in the same
step. The label-first form is kept, because other people's drawings do write it that way.

WHAT THIS DOES NOT DO. 02-07M states no gauge anywhere on its sheet — James's own table says
"same as 06M", and the drawing does not. None is the correct answer there, and the honest one:
it is a question for the drawing office, not a number to inherit from a sibling.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import THICKNESS_PATTERN                                   # noqa: E402
from extractor_patterns import extract_title_block_fields              # noqa: E402


def _thk(text: str):
    return extract_title_block_fields(text)["normalized"]["primary_thickness_mm"]


# ── the way SDI's own template writes it ─────────────────────────────────────

@pytest.mark.parametrize("text,expect", [
    ("1.5 THK", 1.5),
    ("2 THK", 2.0),
    ("1.2 THK", 1.2),
    ("1.5THK", 1.5),
    ("1.5 mm THK", 1.5),
])
def test_the_gauge_is_read_when_the_value_comes_first(text, expect):
    assert _thk(f"MATERIAL: MILD STEEL\n{text}\n") == expect


@pytest.mark.parametrize("text,expect", [
    ("THK: 1.5", 1.5),
    ("THICKNESS 2.0", 2.0),
    ("GAUGE: 1.2", 1.2),
])
def test_the_other_convention_still_works(text, expect):
    """Other people's drawings do write it label-first, and this reader serves those packs
    too."""
    assert _thk(f"MATERIAL: MILD STEEL\n{text}\n") == expect


# ── the one that was costing the money ───────────────────────────────────────

def test_the_next_dimension_on_the_page_is_not_the_gauge():
    """01-04M, EXACTLY AS THE PDF EXTRACTS IT. "1.5 THK" on one line, the box-section size on
    the next. The old pattern read across the break and returned 39.5."""
    sheet = "39.5\n1.5 THK\n39.5\n39.5\nMATERIAL:\nMILD STEEL\n"
    got = _thk(sheet)
    assert got == 1.5, f"read {got} instead of the stated gauge"
    assert got != 39.5, "the box-section dimension is being costed as sheet thickness"


def test_the_value_first_branch_consumes_the_label():
    """WHY ORDERING IS THE FIX RATHER THAN AN EXTRA RULE. Once "1.5 THK" is matched whole, the
    trailing number is behind the scan position and the label-first branch can never reach it.
    Stated against the pattern because it is a property of the regex, not of one sheet."""
    hits = re.findall(THICKNESS_PATTERN, "1.5 THK\n39.5\n", re.I)
    values = [v for pair in hits for v in pair if v]
    assert values == ["1.5"], values


# ── silence is an answer, and must stay one ──────────────────────────────────

def test_a_sheet_that_states_no_gauge_returns_nothing():
    """02-07M names no thickness anywhere. Inheriting 1.5 from its sibling would be the
    engine deciding something the drawing office has not, on a part whose blank is 1486 x 701
    — the error would be a whole sheet of steel."""
    sheet = "1330\n701.5 O/A\n1486.5 O/A\nMATERIAL:\nMILD STEEL\n"
    assert _thk(sheet) is None


def test_a_bare_number_near_no_label_is_not_a_gauge():
    """Every dimension on a drawing is a number. Only the one wearing the label is the gauge."""
    assert _thk("MATERIAL: MILD STEEL\n966\n123.7\n39.5\n") is None
