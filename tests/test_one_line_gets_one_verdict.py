"""A line the record has priced is not also a line carrying no price.

10975-02's AI Explanation tab listed PACKAGING twice, three rows apart:

    PACKAGING | ... | not readable from the sheet — an SDI house rate marked INDICATIVE
              |     | Verify it, or accept it deliberately. priced by the estimator's
              |     | stated method, consumables live from SDI Live
    PACKAGING | ... | £0.00 — the line is costing nothing
              |     | A rate. Nothing we can query holds a price for this code.

and then summarised the job as "2 line(s) carry no price at all — PACKAGING, DELIVERY"
on a sheet where packaging is priced at £1.91 by Howard's own stated method.

ONE CAUSE. The sheet prices packaging with a FORMULA — it re-prices itself when the order
quantity changes — and a formula cell reads back as no number. The unpriced test reads
exactly that, so a priced line fell into it, while the firmness split (which reads the
RECORD) correctly called it a house rate. Two tests, two answers, one line.

The record is the authority on whether a line is priced. A read-back is a fact about a
cell. So a line the record has already classified comes off the unpriced list — in the
Explanation tab and in the covering note, which had the same fault from the same cause.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimate_explained as ee                                       # noqa: E402


def _bom():
    """Three lines: one priced by a formula the read-back cannot resolve, one genuinely
    waiting on a rate, one ordinary priced line."""
    return [
        {"code": "PACKAGING", "text": "PACKAGING  Packaging — bagged (PACK56) + boxed",
         "price": "=IF('Material Price Break'!D8=\"\",1.91,LOOKUP($D$6,...))", "qty": 1},
        {"code": "DELIVERY", "text": "DELIVERY  Delivery — estimator to price",
         "price": 0, "qty": 1},
        {"code": "10975", "text": "10975  EPDM TAPE", "price": 0.09, "qty": 3},
    ]


def _gaps():
    return {"indicative_house": ["PACKAGING"], "indicative_market": [],
            "indicative_house_gbp": 1.91, "indicative_market_gbp": 0.0}


def _record_lines():
    return {"PACKAGING": {"price_origin": {"class": "stated_method",
                                           "firmness": "indicative_house",
                                           "label": "priced by the estimator's stated "
                                                    "method, consumables live from SDI Live"}},
            "DELIVERY": {"price_origin": {"firmness": "unpriced"}},
            "10975": {"price_origin": {"firmness": "indicative_house"}}}


def test_the_split_calls_the_formula_priced_line_a_house_rate():
    house, market = ee._split_by_firmness(_bom(), _record_lines(), _gaps())
    assert [r["code"] for r in house] == ["PACKAGING"], house
    assert market == []


def test_a_formula_cell_reads_back_as_no_number():
    """The condition that caused it — stated so the fix is not mistaken for a fix to
    something else. A formula is not money the read-back can see."""
    assert ee._money(_bom()[0]["price"]) is None


def test_the_priced_line_comes_off_the_unpriced_list():
    """THE DEFECT. The unpriced test and the firmness split disagreed about one line, and
    both verdicts were printed."""
    bom = _bom()
    unpriced = [r for r in bom if not ee._money(r.get("price"))]
    assert {r["code"] for r in unpriced} == {"PACKAGING", "DELIVERY"}, "before"

    house, market = ee._split_by_firmness(bom, _record_lines(), _gaps())
    classified = {id(r) for r in house + market}
    unpriced = [r for r in unpriced if id(r) not in classified]
    assert [r["code"] for r in unpriced] == ["DELIVERY"], \
        "packaging is priced; delivery is the one genuinely waiting on a rate"


def test_both_writers_apply_the_rule():
    """The Explanation tab and the covering note computed this separately and drifted
    apart. Stated against the source because the drift, not the logic, is the defect."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src",
                            "estimate_explained.py"), encoding="utf-8").read()
    assert src.count("id(r) not in _classified}") == 0          # not a set literal typo
    assert src.count("id(r) not in _classified]") == 1           # the Explanation tab
    assert src.count("id(r) not in _classified_ids]") == 1       # the covering note
