r"""
test_a_bought_in_has_no_sheet_gauge.py

A 12x32x10mm BALL BEARING WAS 1.5mm THICK, AND A 20mm CONCRETE SLAB WAS TOO.

part_index applies the document's primary thickness to any part that has none of its own.
For a fabricated part that is right — a detail sheet which does not repeat the gauge should
inherit the pack's. It was applied to every part, so it also reached things that are not cut
from sheet at all:

    12552-01-01X   62012RS Ball Bearing 12x32x10mm      ->  1.5mm
    12552-01-02X   CONCRETE SLAB (the drawing says 20)  ->  1.5mm

A gauge is not decoration. estimator._has_blank accepts a bare thickness as evidence of a
blank, so a gauge alone makes a part look like sheet metal; it also sets the material rate
and steps the cut time. The bearing carried 1.5mm through three runs while its borrowed
blank and its laser route were corrected one at a time, and it is the last thing holding it
in the "1.5mm MILD STEEL" laser group on the labour sheet.

WHAT THIS TEST CAN AND CANNOT DO. The rule lives inside build_part_index, which takes a
fully populated PartIndexDeps; the one existing test for that function
(test_an_assumption_is_born_saying_so) reads its source for the same reason rather than
driving it. So this checks two things that are genuinely checkable — the predicate the rule
turns on, and that the rule is wired to it — and the behavioural proof is the Gauge column
on the next run's sheet. That is stated plainly rather than dressed up: a green tick here is
not the same as a run.

STRUCTURAL, NOT A SUBSTRING. The check walks the AST and requires the bought-in call to be
inside the condition that guards the thickness fallback. A substring search would pass on
the words appearing anywhere in the function — including in the comment explaining the rule,
which is exactly the trap this codebase keeps falling into.
"""
from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import part_index  # noqa: E402
from bought_in_policy import is_bought_in  # noqa: E402


def _bearing() -> dict:
    return {"part_number": "12552-01-01X",
            "description": "62012RS Ball Bearing 12x32x10mm",
            "page_roles": ["assembly"]}


def _slab() -> dict:
    return {"part_number": "12552-01-02X", "description": "CONCRETE SLAB",
            "page_roles": ["detail"]}


def _cross_member() -> dict:
    return {"part_number": "12552-01-01M", "description": "CROSS MEMBERS",
            "page_roles": ["detail"]}


def test_the_predicate_separates_the_parts_this_rule_is_about():
    """What the gate decides, on this pack's own records."""
    assert is_bought_in(_bearing()), "the bearing must read as purchased from its -X number"
    assert is_bought_in(_slab()), "the concrete slab is bought, not cut"
    assert not is_bought_in(_cross_member()), "the cross member is a part SDI cuts"


def _thickness_fallback_condition() -> ast.expr:
    """The `if` test that guards the document-gauge fallback, from the real source."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(part_index.build_part_index)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if "document_primary_thickness" in names:
            return node.test
    raise AssertionError(
        "The document-gauge fallback is no longer an `if` mentioning "
        "document_primary_thickness. Find where the pack's gauge is now applied and move "
        "this check there — do not delete it; a bearing was 1.5mm thick for three runs."
    )


def test_the_fallback_asks_whether_the_part_is_bought():
    condition = _thickness_fallback_condition()
    called = {
        node.func.id for node in ast.walk(condition)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert any("bought_in" in name for name in called), (
        f"The document gauge is still applied without asking what the part is. Calls in that "
        f"condition: {sorted(called) or 'none'}. A purchased component has no sheet gauge, "
        f"and a gauge is what makes the estimator treat it as sheet metal."
    )


def test_the_fallback_still_fires_for_parts_we_cut():
    """The exclusion must be a NOT on the bought-in test, not a blanket disable.

    Written structurally because the failure it guards against — someone 'simplifying' the
    condition into something that never fires — would leave every fabricated part with no
    inherited gauge, which is a far more expensive bug than the one being fixed.
    """
    condition = _thickness_fallback_condition()
    assert any(isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not)
               for n in ast.walk(condition)), (
        "The bought-in call is not negated. As written the fallback would apply the pack's "
        "gauge ONLY to purchased parts and deny it to everything SDI cuts — the exact "
        "inversion of the rule."
    )
    assert isinstance(condition, ast.BoolOp) and isinstance(condition.op, ast.And), (
        "The bought-in test must be one AND-ed clause alongside the existing two (no "
        "thickness yet, and the document has one); replacing them would change when the "
        "fallback fires for every part in every job."
    )
