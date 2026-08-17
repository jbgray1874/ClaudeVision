"""A line the recogniser declined to price is not re-priced by the system-cost/LLM lookup.

The footplate phantom survived TWO earlier fixes because both worked on the wrong layer. The
prose recogniser correctly judged 'Foot Plate' a fabricated part under another name and left it
UNPRICED (a query). But an unpriced bought-in with no ops then reached _resolve_part_system_cost,
which looked 'Foot Plate' up through the UDEF/RAG/catalogue/LLM chain and applied the LLM's market
figure as system_unit_cost — a number that ENTERS the total and changes every run (£14 one run,
£26 the next). The recogniser's decision not to price was silently overturned one function later,
and the phantom walked back in through a different door.

estimate_part now honours the query at the point the money is applied: a part the recogniser
marked 'layer2_possible_fabricated_query' passes through unpriced — recognised, on the sheet, at
nothing, owned by the estimator — and the system-cost/LLM lookup never runs for it. A line the
recogniser did NOT so mark is untouched, so genuine bought-ins still price.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator  # noqa: E402


def _query_line():
    return {
        "part_number": "BI-FOOTPLATE",
        "description": "Foot Plate",
        "source": "prose_recogniser_layer2",
        "cost_source": "layer2_possible_fabricated_query",
        "_no_price_reason": "matches a fabricated part - possible double-count",
        "page_roles": ["bought_in"],
        "quantity": 1,
    }


def test_the_queried_footplate_is_not_priced():
    """THE PHANTOM. A recogniser query line comes back with no price and no money in the total."""
    out = estimator.estimate_part(_query_line(), job_quantity=40)
    assert out.get("unit_cost_gbp") is None
    assert out.get("extended_total_cost_gbp") is None
    assert out.get("costing_basis") == "recogniser_query_not_priced"


def test_the_query_line_says_why_it_is_not_priced():
    out = estimator.estimate_part(_query_line(), job_quantity=40)
    flags = " ".join(out.get("review_flags") or [])
    assert "NOT PRICED" in flags
    assert "double-count" in flags.lower() or "fabricated part under another name" in flags.lower()


def test_the_seal_does_not_touch_an_ordinary_bought_in():
    """A bought-in the recogniser priced (or any line without the query marker) is NOT sealed —
    so genuine hardware still carries its price."""
    ctrl = {
        "part_number": "BI-SCREW", "description": "Self Tapping Screw",
        "source": "prose_recogniser_layer2", "unit_cost_gbp": 0.02,
        "page_roles": ["bought_in"], "quantity": 6,
    }
    out = estimator.estimate_part(ctrl, job_quantity=40)
    assert out.get("unit_cost_gbp") == 0.02


def test_the_seal_keys_only_on_the_fabricated_query_marker():
    """A different cost_source must not be swept up by the seal — only the recogniser's explicit
    'possible fabricated' query is honoured, so no-price lines the estimator WANTS looked up are
    left free to be priced."""
    other = {
        "part_number": "BI-COVER", "description": "Cover",
        "source": "prose_recogniser_layer2", "cost_source": "layer2_no_price_match",
        "page_roles": ["bought_in"], "quantity": 1,
    }
    out = estimator.estimate_part(other, job_quantity=40)
    # Not sealed by this rule — costing_basis is whatever the normal path chose, not our seal.
    assert out.get("costing_basis") != "recogniser_query_not_priced"


def test_the_seal_is_wired_before_the_system_cost_lookup():
    """Wired at the right place: the seal returns before _resolve_part_system_cost can run, so the
    LLM figure can never be applied to a queried line."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "estimator.py"),
               encoding="utf-8").read()
    seal = src.index('part.get("cost_source") == "layer2_possible_fabricated_query"')
    lookup = src.index("_resolve_part_system_cost(part)")
    assert seal < lookup, "the seal must precede the system-cost lookup"
