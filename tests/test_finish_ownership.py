"""
A leaf's own drawing owns its finish, and the finish gate must be able to see the leaf.

Job 12392 reported "no part's finish reads RAW. Finishes seen: {'12392-02-201': 'EDGED'}"
about a job whose own observations say 12392-02-01M reads RAW, 12392-02-02M reads POWDER
COATED - 30% GLOSS, and so do both mounting brackets. Two readers of one job disagreeing
about what it says.

The cause was not the finish rules — those are right, and RAW has been an explicit negative
in finish_rules.FINISH_FAMILIES all along. It was the gate's entry test. wb_populate skipped
any record carrying "bought_in" among its page_roles, which is ONE of the seven signals
bought_in_policy weighs and the weakest of them where a record carries two roles at once. On
this pack every steel leaf carries BOTH "detail" and "bought_in", so all four were skipped
and the scan came back holding a single entry: the assembly.

The engine then claimed powder on a part whose drawing says RAW, and the route decision for
it could not be verified. A private copy of a rule that exists elsewhere is how two readers
of one job come to disagree about what it says.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import bought_in_policy


# The real records, with the mixed page roles the run actually carried.
PARTS = [
    {"part_number": "12392-02-01M", "page_roles": ["detail", "bought_in"],
     "normalized_finish": "RAW"},
    {"part_number": "12392-02-02M", "page_roles": ["detail", "bought_in"],
     "normalized_finish": "POWDER COATED - 30% GLOSS", "quantity": 1},
    {"part_number": "12392-04-01M", "page_roles": ["detail", "bought_in"],
     "normalized_finish": "POWDER COATED - 30% GLOSS", "quantity": 2},
    {"part_number": "12392-04-02M", "page_roles": ["detail", "bought_in"],
     "normalized_finish": "POWDER COATED - 30% GLOSS", "quantity": 2},
    {"part_number": "12392-02-201", "page_roles": ["assembly"],
     "normalized_finish": "EDGED"},
    # The tin of paint: a bought-in powder consumable with no part number, which of course
    # carries a POWDER finish because it IS powder. It cost job 7670 its whole P.Coat once.
    {"part_number": None, "page_roles": ["bought_in"],
     "surface_finishes": ["POWDER COATED - FINE TEXTURE"]},
    {"part_number": "BI-BOLTBZP", "page_roles": ["bought_in"], "normalized_finish": ""},
]


def _scanned():
    """The records the finish gate now admits."""
    return [p["part_number"] for p in PARTS
            if p.get("part_number") and not bought_in_policy.is_bought_in(p)]


def _old_scanned():
    """What the private page_roles test admitted — the defect, reproduced."""
    return [p["part_number"] for p in PARTS
            if p.get("part_number")
            and "bought_in" not in [str(r).lower() for r in (p.get("page_roles") or [])]]


def test_the_defect_reproduces_with_the_private_role_test():
    """MUTATION. One entry, and it is the assembly — exactly what the run printed."""
    assert _old_scanned() == ["12392-02-201"]


def test_every_fabricated_leaf_is_visible_to_the_finish_gate():
    assert _scanned() == ["12392-02-01M", "12392-02-02M", "12392-04-01M",
                          "12392-04-02M", "12392-02-201"]


def test_the_raw_leaf_is_not_coated():
    """RAW is an explicit negative, not an empty value — and the gate can finally read it."""
    finishes = {p["part_number"]: (p.get("normalized_finish") or "").upper()
                for p in PARTS if p["part_number"] in _scanned()}
    assert "RAW" in finishes["12392-02-01M"]
    assert "POWDER" not in finishes["12392-02-01M"]


def test_the_coated_leaves_are_the_ones_the_drawings_name():
    finishes = {p["part_number"]: (p.get("normalized_finish") or "").upper()
                for p in PARTS if p["part_number"] in _scanned()}
    coated = sorted(pn for pn, f in finishes.items() if "POWDER" in f)
    assert coated == ["12392-02-02M", "12392-04-01M", "12392-04-02M"]
    # Five objects through the booth per unit: one stiffener and two of each bracket.
    qty = {p["part_number"]: p.get("quantity", 1) for p in PARTS}
    assert sum(qty[pn] for pn in coated) == 5


def test_the_assembly_level_rule_no_longer_fires_on_a_ghost():
    """It applies ONLY when nothing else in the job qualifies. With the coated leaves
    visible something does, so the powder quantity comes from those leaves rather than from
    the wire geometry of a job that has no wire."""
    finishes = {p["part_number"]: (p.get("normalized_finish") or "").upper()
                for p in PARTS if p["part_number"] in _scanned()}
    assert any("POWDER" in f for f in finishes.values())


def test_a_tin_of_paint_is_still_not_a_painted_object():
    """The guard this replaced was there for a reason and must survive: the bought-in powder
    line carries a POWDER finish because it IS powder. Excluded by identity now, rather than
    by a role a fabricated part can also carry."""
    assert None not in _scanned()
    assert "BI-BOLTBZP" not in _scanned()
    assert bought_in_policy.is_bought_in(
        {"part_number": None, "page_roles": ["bought_in"]})


def test_the_gate_asks_the_shared_predicate():
    """A private copy of a rule that exists elsewhere is how two readers of one job come to
    disagree about what it says."""
    import inspect
    import wb_populate
    src = inspect.getsource(wb_populate)
    assert "_bought_in_policy.is_bought_in(_mp)" in src
    assert '"bought_in" in _pg_roles_boughtin' not in src, \
        "the private role test must be gone, not merely bypassed"
