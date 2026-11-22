"""The PURCHASE PRICE MISSING question is for a part the pack says we buy, with or without a
supplier code, and never for a board that merely has nothing to cut because its gauge is unknown.

The reviewer's offline check of 12713's charging module (22 Nov 2026): the module was flagged
bought in on the record, had no supplier article, priced at £0, and said nothing. And
tests/test_the_checks_read_the_finish_the_sheet_charges.py: a board with no gauge asks for
the gauge once, not for a supplier quote as well.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "sdi-intelligence-backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import estimator  # noqa: E402


def _questions(e):
    return [q.get("issue") for q in (e.get("manufacturing_questions") or []) if isinstance(q, dict)]


def test_a_charging_module_flagged_bought_in_with_no_supplier_code_and_no_price_is_asked_for():
    p = {"part_number": "12713-05-07", "description": "CHARGING MODULE", "quantity": 30,
         "is_bought_in": True, "operations": [], "page_roles": ["bought_in"]}
    e = estimator.estimate_part(p, job_quantity=1)
    assert e.get("purchase_price_missing") is True
    assert any("PURCHASE PRICE MISSING" in str(q) for q in _questions(e)), _questions(e)


def test_a_board_with_no_gauge_is_not_asked_for_a_supplier_quote():
    p = {"part_number": "B-01J", "description": "BASE", "normalized_material": "MDF",
         "normalized_thickness_mm": 1.0, "thickness_source": "drawing_deterministic",
         "thicknesses_mm": [1.0, 3.0], "quantity": 1,
         "overall_length_mm": 630, "overall_width_mm": 630}
    e = estimator.estimate_part(p, job_quantity=1)
    assert not e.get("purchase_price_missing")
    assert not any("PURCHASE PRICE MISSING" in str(q) for q in _questions(e)), _questions(e)


def test_an_article_the_bom_names_is_asked_for_even_without_a_flag():
    p = {"part_number": "LED-L", "description": "LED STRIP LEFT HAND", "quantity": 2,
         "operations": [], "purchase_reference": {"supplier": "ACME", "code": "LS-400-L",
                                                  "source": "exact_bom_description"}}
    e = estimator.estimate_part(p, job_quantity=1)
    assert e.get("purchase_price_missing") is True
