r"""
test_a_weight_on_an_assembly_sheet_is_not_this_parts_weight.py

A GATE THAT RUNS BEFORE THE THING IT GATES.

file_scan clears stated_weight_g on assembly-only records, with the reason written beside it:
"to prevent double-counting sub-part weights into parent assembly material cost". Roughly a
hundred lines LATER in the same function, a text scan reads WEIGHT off the part's pages,
takes the LARGEST match, and writes stated_weight_g back. The guard was dead for every
weight the scan found.

11650-05-02M SLIDER is what it cost. Named only on a GA sheet, no detail drawing, no blank,
no thickness -- and it arrived at 11.694 kg, because the largest weight on an assembly sheet
is the assembly's own or its heaviest child, never this part's:

    11.694 kg  x  GBP 0.80/kg  x  1.04 scrap  =  GBP 9.73     x2  =  GBP 20.24

which was 38% of that job's entire material cost, on a part the same run's invariants
reported as never read. Three wrong diagnoses were spent on that figure before the trace
showed the mass: a powder-rate coincidence (GBP 9.73 is also POWDER_COST_PER_KG, and that
was chance), then a historical quote line, then a declined-price leak. The number was never
a bad rate. It was a real rate applied to somebody else's weight.

Taking the MAX is RIGHT on a detail drawing, where the candidates are one part's weight
written more than once. It is exactly wrong on a sheet describing many parts. One predicate
now answers that, and both readers ask it.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from file_scan import _weight_would_be_someone_elses as would_be_someone_elses  # noqa: E402


@pytest.mark.parametrize("part,expected,why", [
    ({"page_roles": ["assembly"], "description": "SLIDER", "pages": [3]}, True,
     "named only on an assembly sheet -- the biggest weight there is not this part's"),
    ({"page_roles": ["detail"], "description": "SLIDER", "pages": [7]}, False,
     "a detail drawing describes one part, so its weights are that part's"),
    ({"page_roles": ["detail"], "pages": [7]}, True,
     "no description means the record was never really read as a part"),
    ({"page_roles": ["detail"], "pages": [7, 8]}, True,
     "several pages and no description is not one part's drawing"),
    ({"page_roles": ["GENERAL ASSEMBLY"], "description": "X", "pages": [1]}, True,
     "the role test is case-insensitive and substring-based"),
    (None, False, "a malformed record must not crash the scan"),
    ({}, True, "an empty record has no description, so nothing on a page is safely its own"),
])
def test_whose_weight_is_it(part, expected, why):
    assert would_be_someone_elses(part) is expected, why


# ── the ordering fault itself ───────────────────────────────────────────────────────
def _scan_source() -> str:
    return (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")


def test_the_text_scan_asks_before_it_writes():
    """The fix is not "move the guard later" -- it is that the writer asks the question. A
    suppression pass placed after a writer is still two rules for one question, and the next
    person to add a third writer would have to know to move it again."""
    body = ast.unparse(ast.parse(_scan_source()))
    assert body.count("_weight_would_be_someone_elses") >= 3, (
        "the predicate should be defined once and asked by BOTH the suppression pass and "
        "the text scan that sets stated_weight_g")
    # The setter and its guard must sit together, not a hundred lines apart.
    src = _scan_source()
    setter = src.index('_part["stated_weight_g"] = round(_best * 1000, 2)')
    guard = src.rindex("_weight_would_be_someone_elses(_part)", 0, setter)
    assert setter - guard < 1200, (
        "the check that protects the stated_weight_g write is far from the write. That "
        "distance is exactly how the original guard came to run before the thing it gated.")


def test_the_suppression_pass_uses_the_same_predicate_not_its_own_copy():
    """It had its own inline copy of the test. Two copies drift, and the one that drifts is
    the one nobody is looking at."""
    src = _scan_source()
    suppress = src.index('_part["stated_weight_g"] = None')
    window = src[max(0, suppress - 400):suppress]
    assert "_weight_would_be_someone_elses" in window, \
        "the suppression pass no longer asks the shared predicate"
    assert "_is_assembly_page = (" not in window, \
        "the inline copy of the predicate is back"
