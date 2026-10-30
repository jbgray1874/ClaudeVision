r"""
test_a_withheld_price_is_not_an_unexplained_blank.py

THE SHEET EXPLAINED IT AND EVERY CHECK SAID IT HAD NO REASON.

One screen of 11650-04 carried both of these:

    BI-SCREW  Binding Screw  [AI ESTIMATE - INDICATIVE, NOT A QUOTE] — NOT PRICED — an AI
    market estimate suggested £3.12, which changes every run and is NOT a quote.

    unpriced_line_says_why: 1 line(s) carry no price and no reason: BI-SCREW. A blank on an
    estimate reads as free.

Both were describing the same line and only one of them had been told anything.

WHY. bom_line_pricing decided to withhold the figure, and set its two markers —
_price_explicitly_withheld and _ai_indicative_gbp — on a COPY of the part. The copy became
the spreadsheet row and was then dropped. estimator_inputs.unpriced_reason_for_row reads
_ai_indicative_gbp to classify exactly this case as POLICY_WITHHELD, but it asks the record
in the job summary, which had never been marked. So it fell through the whole ladder to
UNEXPLAINED — the category that means "nobody knows", on the one line where somebody did.

The distinction is not cosmetic. POLICY_WITHHELD is owned by the estimator and is not an
under-charge: a figure exists and we have decided not to stand behind it. UNEXPLAINED is
owned by nobody and is the category that says this engine has lost track. One goes on a
list to price; the other goes on a list to investigate.

Same family as the handed pair: one fact recorded in two places, and they disagree.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import price_provenance as pp  # noqa: E402
import wb_populate as wb  # noqa: E402
from estimator_inputs import unpriced_reason_for_row  # noqa: E402


def _screw():
    return {"part_number": "BI-SCREW", "description": "Binding Screw"}


def test_the_record_itself_carries_the_decision():
    """THE ORIGINAL, not the row. Everything that checks or reports on this job reads the
    record; the row exists only to be written into a spreadsheet."""
    part = _screw()
    wb.bom_line_pricing(part, True, 3.12)
    assert part.get("_ai_indicative_gbp") == 3.12
    assert part.get("_price_explicitly_withheld") is True


def test_the_reason_is_policy_and_not_unexplained():
    """The two categories send the line to different people. POLICY_WITHHELD is an estimator
    input; UNEXPLAINED is an engine fault."""
    part = _screw()
    wb.bom_line_pricing(part, True, 3.12)
    reason = unpriced_reason_for_row(part)
    assert reason["category"] == pp.POLICY_WITHHELD
    assert reason["owner"] == "estimator"
    assert reason["undercharging"] is False, (
        "a figure we chose not to stand behind is not money quietly missing from the job")
    assert "3.12" in reason["detail"], (
        "the withheld figure is the hint — a reason that will not name it is not much of one")


def test_the_price_itself_is_still_withheld():
    """THE FIX MUST NOT GO THE OTHER WAY. The whole point is that the number is kept OFF the
    price column: it changes every run and is not a quote. Marking the record explains the
    blank; it must not fill it."""
    part = _screw()
    out = wb.bom_line_pricing(part, True, 3.12)
    assert out["withheld_gbp"] == 3.12
    assert out["status"] == "unpriced"
    assert part.get("price_gbp") is None and part.get("unit_price_gbp") is None


def test_the_row_that_goes_on_the_sheet_is_still_a_copy():
    """So nothing downstream can edit the job record by editing a spreadsheet row."""
    part = _screw()
    out = wb.bom_line_pricing(part, True, 3.12)
    assert out["part"] is not part
    out["part"]["description"] = "edited on the sheet"
    assert part["description"] == "Binding Screw"


def test_a_line_that_was_not_withheld_is_not_marked():
    """A marker that appears on every line explains nothing. Only a line where the decision
    was actually taken carries it."""
    part = {"part_number": "FIXING1659", "description": "M6 KNURLED KNOB"}
    wb.bom_line_pricing(part, False, 0.27)
    assert "_ai_indicative_gbp" not in part
    assert "_price_explicitly_withheld" not in part


def test_the_categories_this_is_distinguished_from_still_answer_first():
    """The ladder's order is the design. A cross-referenced fabricated part is NOT_APPLICABLE
    — its material is costed in the Sheet Steel block — and reaching the AI rung for one of
    those would put sixteen deliberate blanks on somebody's list to price."""
    part = dict(_screw(), _bom_cross_reference=True, _ai_indicative_gbp=3.12)
    assert unpriced_reason_for_row(part)["category"] == pp.NOT_APPLICABLE


def test_an_unmarked_line_does_not_get_the_policy_answer():
    """The category has to keep meaning something. POLICY_WITHHELD says a figure exists and
    we chose not to stand behind it; a line where no such decision was taken must land
    somewhere else, or the check stops finding the lines it exists for.

    (A bare record lands on NO_PRICE_SOURCE — nobody has a price for it — rather than
    UNEXPLAINED. Both are honest; only the first is actionable, which is the ladder doing
    its job.)"""
    reason = unpriced_reason_for_row({"part_number": "X"})
    assert reason["category"] != pp.POLICY_WITHHELD
    assert reason["category"] in {pp.NO_PRICE_SOURCE, pp.UNEXPLAINED}
