"""£0.09 a piece off the £4.50 UDEF roll, labelled "xAI Grok LLM - INDICATIVE".

The 16:07 10975-02 book, tape line, measured:

    J13   0.09         = 200 mm of a 10 000 mm roll at £4.50 — UDEF's price, to the penny
    I13   xAI Grok LLM - INDICATIVE
    C13   ... [AI ESTIMATE - INDICATIVE, NOT A QUOTE]

The money and the label came from two different stamps. The record carried an LLM answer
from the bought-in chain AND the roll-goods stamp whose figure is the one on the sheet, and
_price_origin prefers the system_cost path — right for the ordinary bought-in, where the
unit cost IS the line's price, and wrong the moment the material branch supersedes it.

A warning tag on a catalogue-priced figure is not caution, it is a wrong answer: it tells
the estimator to distrust the one number on the job that came off UDEF, and it stamps NOT A
QUOTE on a line that is exactly the thing a quote is made of.

THE RECORD SAYS WHICH BRANCH PUT THE MONEY ON — cost_method — so the label asks the record
instead of assuming.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import wb_populate as W                                             # noqa: E402


def _tape(roll_source="udef_sqlserver"):
    """The 10975 tape as the record actually carried it: both stamps present."""
    return {
        "part_number": "10975", "description": "EPDM TAPE 25X1MM - TAPE 113C",
        "quantity": 3,
        # the bought-in chain's answer, resolved earlier and still claiming the total
        "cost_breakdown": {"system_cost": {
            "applied_to_total": True,
            "source": {"source_name": "llm_market_estimate", "applied": True,
                       "affects_total": True,
                       "selected": {"source": "llm_market_estimate", "price": 0.85}}}},
        # the branch that actually priced the sheet's 0.09
        "material_estimate": {
            "cost_method": "roll_goods_by_length",
            "unit_material_cost_gbp": 0.09,
            "price_source": {"schema": "price_source.v1", "source": roll_source,
                             "source_name": roll_source, "applied": True,
                             "affects_total": True},
        },
    }


def test_the_roll_priced_line_is_not_labelled_as_the_llm():
    label, indicative = W._price_origin(_tape())
    assert "INDICATIVE" not in label, label
    assert indicative is False, "NOT A QUOTE must not be stamped on a UDEF-priced line"


def test_it_names_the_system_that_actually_answered():
    label, _ = W._price_origin(_tape())
    assert label == "SDI Live UDEF"


def test_an_estimator_stated_roll_price_says_so():
    label, indicative = W._price_origin(_tape(roll_source="estimator_stated"))
    assert label == "Estimator stated"
    assert indicative is False


def test_an_ordinary_bought_in_still_labels_from_its_unit_cost():
    """The preference this fix bends exists for a reason: on a part the bought-in chain
    priced, the material rate on the same record is NOT what the row charges."""
    pe = _tape()
    pe["material_estimate"]["cost_method"] = "per_kg_sheet"          # material did NOT charge
    label, indicative = W._price_origin(pe)
    assert indicative is True
    assert "INDICATIVE" in label


def test_a_withheld_roll_line_does_not_borrow_the_material_label():
    """roll_goods_withheld_* means the material branch REFUSED to price. Its stamp says
    applied False, so it cannot answer for the line — whatever else stamped it can."""
    pe = _tape()
    pe["material_estimate"]["cost_method"] = "roll_goods_withheld_estimator_to_price"
    pe["material_estimate"]["price_source"] = {"schema": "price_source.v1",
                                               "source": "roll_goods_withheld",
                                               "source_name": "roll_goods_withheld",
                                               "applied": False, "affects_total": False}
    label, indicative = W._price_origin(pe)
    assert indicative is True, "the LLM stamp is then the only money claiming the line"


def test_the_quantity_tab_no_longer_recommends_files_that_were_not_filed():
    """The 16:07 book's Quantity Breaks tab closed with "the per-quantity workbooks named
    above are the ones to send" over an empty Workbook row — no copies are filed since the
    one sheet took over, and a header over four empty cells reads as four files that failed
    to save."""
    src = (ROOT / "src" / "quantity_breaks_tab.py").read_text(encoding="utf-8")
    assert "if _any_wbk:" in src, "the Workbook row renders only when there are files"
    assert "There are no " in src and "per-quantity copies" in src, \
        "and the closing sentence matches what the run did"
