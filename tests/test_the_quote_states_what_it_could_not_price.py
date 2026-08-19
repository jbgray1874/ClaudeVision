"""The customer's quotation says which parts the price excludes, and why.

The practice is to price what the pack contains and state what is missing. The engine did the
first half and only half of the second: the internal report named the four Dyson assemblies
nobody had sent drawings for — the back, the base, the base plate and the lens, which is most of
the physical product — in language nobody outside SDI would ever see, while the quotation showed a
unit price under a heading reading "What's included" and said nothing about them. Dyson would read
that as a price for the display.

An exclusion the estimator knows about and the customer does not is the expensive kind. The
exclusions are READ from the invariant that already found them, so the quotation and the internal
report can never name different parts.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from client_quote_html import (  # noqa: E402
    build_quote_html,
    excluded_for_want_of_a_drawing,
)

_MISSING = [
    {"part_number": "10575-01-101", "description": "VERSION 1 - BACK WELDED ASSEMBLY"},
    {"part_number": "10575-01-102", "description": "VERSION 1 - BASE WELDED ASSEMBLY"},
    {"part_number": "10575-01-104", "description": "BASE PLATE - WELDED ASSEMBLY"},
    {"part_number": "10575-01-103", "description": "VERTICAL LENS ASSEMBLY"},
]


def _summary(missing=None, qty=1, unit=146.0):
    violations = []
    if missing is not None:
        violations.append({"code": "bom_names_a_drawing_the_pack_does_not_contain",
                           "severity": "blocking", "message": "x",
                           "detail": {"missing": missing}})
    # an unrelated finding must not leak into the exclusions
    violations.append({"code": "price_not_reproducible", "severity": "blocking",
                       "message": "y", "detail": {}})
    return {"invariants": {"violations": violations},
            "estimate_summary": {
                "workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": unit},
                "estimate_workbook_inputs": {"assumed_job_quantity": qty}}}


# ── the reader ───────────────────────────────────────────────────────────────────────
def test_the_undrawn_assemblies_are_collected():
    rows = excluded_for_want_of_a_drawing(_summary(_MISSING))
    assert [r["part_number"] for r in rows] == [m["part_number"] for m in _MISSING]


def test_unrelated_findings_are_ignored():
    assert excluded_for_want_of_a_drawing(_summary(missing=None)) == []


def test_a_summary_with_nothing_in_it_is_safe():
    assert excluded_for_want_of_a_drawing({}) == []
    assert excluded_for_want_of_a_drawing(None) == []


# ── the quotation ────────────────────────────────────────────────────────────────────
def test_the_quote_states_the_exclusions_and_names_them():
    html = build_quote_html(_summary(_MISSING), job_stem="10575-02", customer="Dyson")
    assert "Not included in this price" in html
    for m in _MISSING:
        assert m["part_number"] in html
    assert "BACK WELDED ASSEMBLY" in html


def test_the_quote_tells_the_customer_how_to_resolve_it():
    """An exclusion without a remedy invites a phone call; this says send the drawings."""
    html = build_quote_html(_summary(_MISSING), job_stem="10575-02", customer="Dyson")
    assert "Send the drawings" in html


def test_no_engine_language_reaches_the_customer():
    """The internal reasoning stays internal — no invariant codes on a document that leaves
    the building."""
    html = build_quote_html(_summary(_MISSING), job_stem="10575-02", customer="Dyson")
    assert "bom_names_a_drawing" not in html
    assert "invariant" not in html.lower()
    assert "BLOCKING" not in html


def test_a_complete_pack_carries_no_exclusions_block():
    """A job that could price everything must not gain an empty, worrying section."""
    html = build_quote_html(_summary(missing=None, qty=400, unit=100.0),
                            job_stem="8352", customer="M&S")
    assert "Not included in this price" not in html
