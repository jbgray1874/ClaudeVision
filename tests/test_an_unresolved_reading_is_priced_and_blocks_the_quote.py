"""A figure on an unresolved reading stays priced, says so, and blocks the quote (D-432).

8188-08, 9 Oct: fourteen magnets printed "50mm x 10mm x 2m" were priced as two-metre magnets,
£706.16 of a £1,814.22 unit. D-430 held the figure out of the price cell; that left the sheet
totalling a unit £706 lighter with nothing saying it was incomplete — more misleading than the
figure. Withdrawn: the working figure stays in, the line says the reading is open, and the
customer quote is blocked until it is confirmed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf                                             # noqa: E402
import estimator                                                      # noqa: E402
import invariants                                                     # noqa: E402
import wb_populate as wp                                              # noqa: E402

_MARK = {"reason": "the printed size 50mm x 10mm x 2m mixes m and mm", "units": ["m", "mm"],
         "source": "extractor_patterns.size_mixing_units"}


def _magnet():
    part = {"part_number": "KINGDOM", "description": "50mm x 10mm x 2m MAGNET", "quantity": 14,
            "is_bought_in": True, "page_roles": ["bought_in"], "unit_cost_gbp": 48.5}
    estimator.estimate_process_times(part, 14)
    return part


def test_the_figure_stays_priced_and_the_question_says_the_quote_is_blocked():
    part = _magnet()
    assert part["unit_cost_gbp"] == 48.5
    assert part["_price_unresolved"]["units"] == ["m", "mm"]
    q = [q for q in part["manufacturing_questions"]
         if q.get("source") == "extractor_patterns.size_mixing_units"][0]
    assert "working figure" in q["assumption"] and "quote is blocked" in q["assumption"]


def test_the_line_says_the_reading_is_open():
    note = wp.unresolved_reading_note({"_price_unresolved": _MARK})
    assert note.startswith("UNRESOLVED READING (m and mm in one size)")
    assert "priced as printed" in note and "quote blocked" in note
    assert wp.unresolved_reading_note({"part_number": "PSA1999C"}) == ""


def test_the_report_still_counts_it_as_a_market_figure_in_the_unit():
    part = {"part_number": "KINGDOM", "_price_unresolved": _MARK,
            "material_estimate": {"cost_method": "market_research",
                                  "price_source": {"source_name": "xAI Grok LLM"}}}
    o = cf._price_origin(part, "bought_in", None, 48.5, 48.5, None, False,
                         row_text="[AI ESTIMATE - INDICATIVE, NOT A QUOTE]")
    assert o["firmness"] == cf.INDICATIVE_MARKET


def test_an_unresolved_reading_blocks_the_customer_quote():
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "KINGDOM", "_price_unresolved": _MARK,       # priced: it carries money
         "material_estimate": {"unit_material_cost_gbp": 48.5}},
        {"part_number": "PSA1999C"}]}}
    v = invariants.check_an_unresolved_reading_blocks_the_quote(summary)
    assert len(v) == 1 and v[0]["severity"] == invariants.BLOCKING
    assert v[0]["code"] == "unresolved_reading_priced" and "KINGDOM" in v[0]["message"]
    assert invariants.check_an_unresolved_reading_blocks_the_quote(
        {"estimate_summary": {"part_estimates": [{"part_number": "PSA1999C"}]}}) == []
