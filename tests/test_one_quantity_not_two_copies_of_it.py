"""The workbook quantity and the quantity apply_field owns have to be the same number.

WHAT WENT WRONG. `apply_field` arbitrates a part's quantity and names the reader that won:

    [bom_tree] 12349-02-69-04M qty 1 KEPT (GA tree said 3) — stronger source

The part record held 1. The Estimate sheet printed 3. It printed 3 because `wb_populate` takes
the workbook quantity from the ROUTE GRAPH's node, and the graph runs its own cascade that has
never heard of the precedence layer — so the sheet was costed on a figure the arbitration had
already rejected, and the log even said so.

Correcting the general-arrangement ROW (the child edge both cascades read) fixed that job. This
is the rule underneath it, and it is about the EDGE rather than the product:

    effective(child) = effective(parent) x how many of the child ONE parent takes

"How many one parent takes" is a per-parent statement two readers can disagree about — the BOM
edge says one number, the model's instance count says another — so rank settles that, and the
product follows. Settled while the cascade runs, because a correction at a parent has to reach
everything below it.

WHAT THIS MUST NOT DO, and each case is a test below:

  * It must not promote the BOM tree over the model. The tree still loses to SolidWorks.
  * It must not let a CELL reader replace an edge. `bom_table` outranks the tree, and a general
    arrangement's cell is the context figure this whole fix exists to stop multiplying by.
  * It must not touch genuine nesting. A 2-off inside a 3-off sub-assembly is six per unit.
  * It must not guess at a part with two parents that each take a different count.
  * It must not silently drop the loser. Both numbers stay on the node, with the reason.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from route_compiler import compile_job_route                            # noqa: E402
import source_precedence                                                # noqa: E402

GA = "12349-02-69-GA"
SUB = "12349-02-69-100"
LEAF = "12349-02-69-04M"


def _nodes(parts, rows):
    graph = compile_job_route(parts, {}, rows, [GA], {})
    return {n["part_number"]: n for n in (graph.get("nodes") or [])}


def _part(code: str, quantity, source: str):
    """A part record whose quantity arrived through the precedence layer, as a real one does."""
    part = {"part_number": code}
    source_precedence.apply_field(part, "quantity", quantity, source)
    return part


def test_a_reader_that_outranks_the_tree_is_not_overturned_by_a_ga_edge():
    """SolidWorks counted one per unit. The GA prints three because three hang on the wall."""
    rows = [{"part_number": SUB, "quantity": 3, "source_pdf": GA, "bom_parent": GA}]
    nodes = _nodes([_part(SUB, 1, "solidworks_api")], rows)
    assert nodes[SUB]["qty_per_unit"] == 1.0
    assert nodes[SUB]["qty_own"] == 1.0
    assert "solidworks" in nodes[SUB]["qty_own_source"].lower()
    # AND IT SAYS WHAT IT BEAT. A number that changed without saying why is not auditable.
    assert "3" in nodes[SUB]["qty_note"]


def test_a_cell_reader_never_replaces_an_edge_even_though_it_outranks_the_tree():
    """THE DEFECT INVERTED, AND IT NEARLY SHIPPED. `bom_table` is rank 70 against the tree's 60,
    so a rule written as "anything that outranks the tree may replace the edge" lets an
    UNCORRECTED general-arrangement cell of 3 replace a sub-assembly edge of 1 — putting the ×3
    back by the same door it was shown out of.

    An edge is a per-parent count, and only a reader that counts instances states one. A cell
    reader gets the note and changes nothing.
    """
    rows = [{"part_number": SUB, "quantity": 1, "source_pdf": GA, "bom_parent": GA},
            {"part_number": LEAF, "quantity": 1, "source_pdf": SUB, "bom_parent": SUB}]
    nodes = _nodes([_part(SUB, 1, "solidworks_api"), _part(LEAF, 3, "bom_table")], rows)
    assert nodes[LEAF]["qty_per_unit"] == 1.0, "the edge stands; a GA cell is not a count"
    assert nodes[LEAF]["qty_own"] == 3.0
    assert "reads a cell rather than counting instances" in nodes[LEAF]["qty_note"]


def test_the_tree_still_wins_where_nothing_stronger_has_spoken():
    """The tree is not demoted. Where it is the only reader it is writing a field nobody
    stronger owns, and that is exactly what it is for — so the cascade stands, and the
    disagreement is reported rather than resolved by a rule that cannot see the drawing."""
    rows = [{"part_number": SUB, "quantity": 3, "source_pdf": GA, "bom_parent": GA}]
    nodes = _nodes([_part(SUB, 1, "bom_tree")], rows)
    assert nodes[SUB]["qty_per_unit"] == 3.0
    assert nodes[SUB]["qty_own"] == 1.0
    assert "confirm which is right" in nodes[SUB]["qty_note"]


def test_a_correction_at_the_parent_reaches_a_child_two_edges_down():
    """THE RISK THE FIRST VERSION OF THIS FIX ACTUALLY HAD, and 12349-02 is exactly its shape.

    The Lid does not hang off the general arrangement. It hangs under -69-100, which hangs under
    the GA — two edges down. A reconciliation that compares a part's own cell against a finished
    product can only work one edge below a root, and correcting -69-100 from 3 to 1 afterwards
    leaves the Lid still carrying the 3 its parent no longer has.

    Settling the EDGE while the cascade runs is what makes the correction propagate: one GA takes
    one -69-100, and one -69-100 takes one Lid, so the Lid is one per unit.
    """
    rows = [{"part_number": SUB, "quantity": 3, "source_pdf": GA, "bom_parent": GA},
            {"part_number": LEAF, "quantity": 1, "source_pdf": SUB, "bom_parent": SUB}]
    nodes = _nodes([_part(SUB, 1, "solidworks_api"), _part(LEAF, 1, "solidworks_api")], rows)
    assert nodes[SUB]["qty_per_unit"] == 1.0
    assert nodes[LEAF]["qty_per_unit"] == 1.0, "the Lid at 3 is the defect this exists for"


def test_a_part_under_two_parents_is_not_resolved_by_picking_one():
    """Its record holds one number; the two parents take different counts of it. The edges stand
    and the ambiguity is reported, because substituting one figure for both would be a guess."""
    OTHER = "12349-02-69-101"
    rows = [{"part_number": SUB, "quantity": 1, "source_pdf": GA, "bom_parent": GA},
            {"part_number": OTHER, "quantity": 1, "source_pdf": GA, "bom_parent": GA},
            {"part_number": LEAF, "quantity": 2, "source_pdf": SUB, "bom_parent": SUB},
            {"part_number": LEAF, "quantity": 3, "source_pdf": OTHER, "bom_parent": OTHER}]
    nodes = _nodes([_part(SUB, 1, "solidworks_api"), _part(OTHER, 1, "solidworks_api"),
                    _part(LEAF, 2, "solidworks_api")], rows)
    assert nodes[LEAF]["qty_per_unit"] == 5.0, "two from one parent and three from the other"
    assert "more than one parent" in nodes[LEAF]["qty_note"]


def test_genuine_nesting_is_left_alone():
    """Two leaves inside a sub-assembly the unit needs three of is six per unit. The leaf's own
    cell says 2 and that is not a disagreement: it is per-parent, and the cascade is the product.
    Nothing is reconciled here, and both figures are recorded."""
    rows = [{"part_number": SUB, "quantity": 3, "source_pdf": GA, "bom_parent": GA},
            {"part_number": LEAF, "quantity": 2, "source_pdf": SUB, "bom_parent": SUB}]
    nodes = _nodes([_part(SUB, 3, "solidworks_api"), _part(LEAF, 2, "solidworks_api")], rows)
    assert nodes[LEAF]["qty_per_unit"] == 6.0
    assert nodes[LEAF]["qty_own"] == 2.0
    assert not nodes[LEAF]["qty_note"]


def test_agreement_writes_no_note():
    """The normal row. Nothing to say, and a flag on every line is a flag nobody reads."""
    rows = [{"part_number": SUB, "quantity": 2, "source_pdf": GA, "bom_parent": GA}]
    nodes = _nodes([_part(SUB, 2, "solidworks_api")], rows)
    assert nodes[SUB]["qty_per_unit"] == 2.0
    assert not nodes[SUB]["qty_note"]


def test_the_workbook_carries_the_reconciled_figure_and_what_it_replaced():
    """wb_populate's canonical pass is where the sheet's quantity is actually set. It takes the
    graph node's figure — now the reconciled store rather than an independent cascade — and
    carries the part's own line alongside it instead of dropping it."""
    from wb_populate import canonicalise_part_estimates_for_workbook
    summary = {"canonical_route_shadow": {"nodes": [
        {"part_number": SUB, "kind": "assembly", "qty_per_unit": 1.0, "qty_own": 1.0,
         "qty_own_source": "solidworks_api",
         "qty_note": "costing 1 per unit from the SolidWorks model; the assembly tree "
                     "cascaded 3 from its parent edge and does not outrank that reader"},
    ]}}
    out = canonicalise_part_estimates_for_workbook(
        summary, [{"part_number": SUB, "quantity": 3, "description": "module"}])
    row = next(r for r in out if r["part_number"] == SUB)
    assert row["quantity"] == 1.0
    assert row["quantity_own"] == 1.0
    assert row["quantity_own_source"] == "solidworks_api"
    assert "does not outrank" in row["quantity_note"]


def test_the_extract_prints_both_columns_and_flags_the_difference():
    """Requirement: qty_own and qty_effective side by side, flagged when they differ."""
    from bom_and_route_extract import bom_sheet
    summary = {
        "document_analysis": {"bom_rows": [
            {"part_number": SUB, "description": "Gravity feeder module", "quantity": 1,
             "quantity_as_printed": 3,
             "quantity_note": "the general arrangement prints 3; it shows 3 arrangements, so "
                              "one arrangement takes 1",
             "source_pdf": GA},
        ]},
        "canonical_route_shadow": {"nodes": [
            {"part_number": SUB, "qty_per_unit": 3.0, "qty_own": 1.0,
             "qty_own_source": "bom_table", "qty_note": ""},
        ]},
    }
    row = bom_sheet(summary)[0]
    assert row["qty_own"] == 1
    assert row["qty_effective"] == 3.0
    assert "this line states 1" in row["qty_own_and_effective_differ"]
    assert "3 arrangements" in row["why_the_quantity_is_what_it_is"]
    assert row["quantity_as_printed_on_the_drawing"] == 3


def test_a_difference_with_no_reason_recorded_still_says_so():
    """The worst outcome is a silent difference. Where nothing explains it, the row says that."""
    from bom_and_route_extract import bom_sheet
    summary = {
        "document_analysis": {"bom_rows": [
            {"part_number": SUB, "quantity": 1, "source_pdf": GA}]},
        "canonical_route_shadow": {"nodes": [
            {"part_number": SUB, "qty_per_unit": 4.0}]},
    }
    row = bom_sheet(summary)[0]
    assert "no reason recorded" in row["why_the_quantity_is_what_it_is"]


def test_a_nameless_row_is_not_a_quantity_any_nameless_record_can_pick_up():
    """`None qty 4 KEPT (GA tree said 1)` — a log line that has appeared on several jobs.

    A parts-list row with no part number normalises to "", and the tree filed an effective
    quantity under that empty key. Any later record whose own part number was also missing looked
    up "" and took it. Neither half stands now: the tree files nothing under no name, and the
    record that has no name asks for nothing.
    """
    from bom_tree import resolve_effective_quantities
    out = resolve_effective_quantities([
        {"part_number": SUB, "quantity": 1, "source_pdf": GA},
        {"part_number": "", "quantity": 4, "source_pdf": GA},
        {"part_number": None, "quantity": 9, "source_pdf": SUB},
        {"part_number": LEAF, "quantity": 1, "source_pdf": SUB},
    ], main_ga=GA)
    effective = out.get("effective") or {}
    assert "" not in effective, "a quantity under no name is one anything nameless can take"
    assert None not in effective
    assert effective.get(LEAF) == 1
    assert any(f.get("severity") == "warning" and "no part number" in str(f.get("detail"))
               for f in (out.get("flags") or [])), "it is reported, not silently dropped"
