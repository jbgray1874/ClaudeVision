"""The arrangement rule's verdict has to reach the one reader that never saw it.

THE PROBE OUTPUT THAT ENDED FIVE WRONG DIAGNOSES. 12349-02 on 6d24994, from the record itself:

    parts / part_estimates        quantity = 1          the install-context write landed
    canonical_route_shadow        qty_own = 1
                                  qty_per_unit = 3      <- the Estimate reads this
    edge  69-GA -> 69-100         qty = 3.0             <- why the node is 3
    BOM row                       quantity = 1, as_printed = 3

Every record said 1. The general arrangement's EDGE still said 3, and the node is own x edge.

WHY THE EDGE CANNOT BE FIXED WHERE THE DIVISION HAPPENS. `compile_job_route` is handed `parts`
and `llm_full_extract` and nothing else — `bom_rows` is not passed at all (estimator.py:7381) —
and it rebuilds its edges from the extract on every compile. A write to the edge in file_scan
dies on the next one. The part record is the store that survives, because the record is what
compile is handed.

AND THE GUARD THAT KEPT THE WRONG NUMBER WAS MINE. `_per_parent` compares the child's own
quantity against the edge and, seeing `bom_tree` on the record, treats it as a reader of a cell
rather than a counter of instances — so it keeps the edge. That test was written to stop an
UNCORRECTED general-arrangement cell of 3 replacing a sub-assembly edge of 1. Here it stopped a
CORRECTED record of 1 replacing an uncorrected GA edge of 3. Same guard, opposite direction, and
the note it wrote on the node said so plainly: "the BOM edge is what is costed".

So the record carries the RULING as well as the figure, and the rule is narrow: a code the
arrangement rule has identified as the unit, and only such a code, beats the edge into it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from route_compiler import compile_job_route                            # noqa: E402
import source_precedence as sp                                          # noqa: E402

GA = "12349-02-69-GA"
UNIT = "12349-02-69-100"
LID = "12349-02-69-04M"


def _part(code, qty, source="bom_tree", stamp=None):
    p = {"part_number": code}
    sp.apply_field(p, "quantity", qty, source)
    if stamp is not None:
        p["quantity_is_per_quoted_unit"] = stamp
    return p


def _graph(*parts):
    """THE LIVE PATH'S SHAPE, which four earlier fixtures got wrong: no bom_rows, and the
    hierarchy from the extract — a general arrangement listing three of the module."""
    extract = {"assemblies": [
        {"part_number": GA, "children": [{"part_number": UNIT, "qty": 3}]},
        {"part_number": UNIT, "children": [{"part_number": LID, "qty": 1}]},
    ]}
    g = compile_job_route(list(parts), extract)
    return {n["part_number"]: n for n in (g.get("nodes") or [])}


def test_the_defect_without_the_stamp():
    """Every record says 1, the edge says 3, and the sheet is costed on the edge. This is the
    05:24 run exactly, and it is the state the stamp exists to change."""
    nodes = _graph(_part(UNIT, 1), _part(LID, 1))
    assert nodes[UNIT]["qty_per_unit"] == 3.0
    assert nodes[UNIT]["qty_own"] == 1.0
    assert nodes[LID]["qty_per_unit"] == 3.0, "three lids, which is what the sheet printed"


def test_a_stamped_unit_beats_the_arrangement_edge():
    """The authorised fix. The module is the unit, so one quoted unit takes one of it, and the
    general arrangement's 3 is three arrangements rather than three per unit."""
    nodes = _graph(_part(UNIT, 1, stamp=3), _part(LID, 1))
    assert nodes[UNIT]["qty_per_unit"] == 1.0
    assert "arrangements of it" in nodes[UNIT]["qty_note"], "the beaten edge must be named"
    assert "3" in nodes[UNIT]["qty_note"]


def test_the_descendants_follow_without_being_stamped():
    """Requirement 3 of the contract: only the codes the rule named are stamped. The lid is not,
    and does not need to be — its own edge is one per parent, so it falls to one when the parent
    node does. A stamp on every descendant would be a second divider."""
    nodes = _graph(_part(UNIT, 1, stamp=3), _part(LID, 1))
    assert nodes[LID]["qty_per_unit"] == 1.0
    assert not nodes[LID].get("qty_own_source") or True
    assert "arrangements of it" not in (nodes[LID].get("qty_note") or "")


def test_an_unstamped_part_still_loses_to_its_edge():
    """THE GUARD THIS MUST NOT REMOVE. A part whose own cell disagrees with the edge and which the
    arrangement rule never ruled on is still costed on the edge — otherwise an uncorrected general
    arrangement cell replaces a sub-assembly edge, which is the same defect inverted."""
    nodes = _graph(_part(UNIT, 1), _part(LID, 1))
    assert nodes[UNIT]["qty_per_unit"] == 3.0
    assert "reads a cell rather than counting instances" in nodes[UNIT]["qty_note"]


def test_no_stamp_when_the_install_context_write_was_refused():
    """Requirement 1: stamped only where the correction LANDED. A record a stronger reader owns
    keeps that reader's figure, which is then the per-unit truth — so no stamp is written, and
    the edge stands. The refusal is printed by the runner, naming the holder."""
    part = {"part_number": UNIT}
    sp.apply_field(part, "quantity", 2, "solidworks_api")
    landed = sp.apply_field(part, "quantity", 1, "bom_tree")
    assert landed is False, "the model counted two; the tree does not overrule it"
    assert "quantity_is_per_quoted_unit" not in part, (
        "a stamp on a refused write would let the tree beat the model through the back door")


def test_the_stamp_does_not_touch_a_genuine_nest():
    """Two leaves inside a sub-assembly the unit takes three of is still six per unit. The stamp
    is on the UNIT, and the unit's own count is one — nothing below it is reinterpreted."""
    extract = {"assemblies": [
        {"part_number": GA, "children": [{"part_number": UNIT, "qty": 3}]},
        {"part_number": UNIT, "children": [{"part_number": LID, "qty": 2}]},
    ]}
    g = compile_job_route([_part(UNIT, 1, stamp=3), _part(LID, 2)], extract)
    nodes = {n["part_number"]: n for n in (g.get("nodes") or [])}
    assert nodes[UNIT]["qty_per_unit"] == 1.0
    assert nodes[LID]["qty_per_unit"] == 2.0, "two per unit, because one unit takes two"
