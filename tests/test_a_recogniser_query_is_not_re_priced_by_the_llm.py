"""A possible-double-count line is PRICED and flagged, never left as a blank £0.

Earlier this line was zeroed to avoid paying twice for a plate already costed on the sheet. But
the duplicate judgement is a heuristic (the prose 'Foot Plate' may be a genuine separate part),
and a £0 reads as free — the error nobody catches. The mandate is a price on every line until
catalogues/APIs replace the guesses. So a line the recogniser marks a possible fabricated
duplicate is priced through the normal chain and carries a LOUD possible-double-count flag: the
estimator sees the number AND the warning, and strikes it if it duplicates a made part.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator  # noqa: E402


def _query_line(**over):
    line = {
        "part_number": "BI-FOOTPLATE",
        "description": "Foot Plate",
        "source": "prose_recogniser_layer2",
        "cost_source": "layer2_possible_fabricated_query",
        "_no_price_reason": "matches a fabricated part - possible double-count",
        "page_roles": ["bought_in"],
        "quantity": 1,
    }
    line.update(over)
    return line


def test_a_possible_duplicate_line_is_flagged_loudly():
    """The estimator must SEE the double-count risk on the line, whatever the price turns out
    to be — the flag is added regardless of what the downstream lookup returns."""
    out = estimator.estimate_part(_query_line(), job_quantity=40)
    flags = " ".join(str(f) for f in (out.get("review_flags") or []))
    assert "POSSIBLE DOUBLE-COUNT" in flags
    assert "STRIKE" in flags


def test_the_line_is_not_forced_to_zero_by_a_seal():
    """The old behaviour zeroed the line; it must no longer be pinned to a blank. costing_basis
    is whatever the normal chain produced — never the old suppression marker."""
    out = estimator.estimate_part(_query_line(), job_quantity=40)
    assert out.get("costing_basis") != "recogniser_query_not_priced"


def test_the_flag_is_added_before_the_normal_costing_runs():
    """Wired: the possible-double-count flag is attached and the line falls through to normal
    costing (it is not early-returned unpriced)."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "estimator.py"),
               encoding="utf-8").read()
    marker = src.index('if part.get("cost_source") == "layer2_possible_fabricated_query":')
    seg = src[marker:marker + 700]
    assert "POSSIBLE DOUBLE-COUNT" in seg
    assert "fall through to normal costing" in seg
    # It must NOT early-return an unpriced blank from this branch.
    assert "recogniser_query_not_priced" not in seg
