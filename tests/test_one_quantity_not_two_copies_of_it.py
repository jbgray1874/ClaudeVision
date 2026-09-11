"""The workbook quantity and the quantity apply_field owns have to be the same number.

WHAT WENT WRONG. `apply_field` arbitrates a part's quantity and names the reader that won:

    [bom_tree] 12349-02-69-04M qty 1 KEPT (GA tree said 3) — stronger source

The part record held 1. The Estimate sheet printed 3. It printed 3 because `wb_populate` takes
the workbook quantity from the ROUTE GRAPH's node, and the graph runs its own cascade that has
never heard of the precedence layer — so the sheet was costed on a figure the arbitration had
already rejected, and the log even said so.

Correcting the general-arrangement ROW (the child edge both cascades read) fixed that job. This
is the rule underneath it: where a part hangs DIRECTLY off a root, the cascade and the record are
two statements about the same number, so they must agree, and when they do not, RANK decides.

WHAT THIS MUST NOT DO, and each case is a test below:

  * It must not promote the BOM tree over the model. The tree still loses to SolidWorks.
  * It must not touch genuine nesting. A 2-off inside a 3-off sub-assembly is six per unit, and
    the part's own cell saying 2 is not a contradiction — it is a different question.
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


def test_the_tree_still_wins_where_nothing_stronger_has_spoken():
    """The tree is not demoted. Where it is the only reader it is writing a field nobody
    stronger owns, and that is exactly what it is for — so the cascade stands, and the
    disagreement is reported rather than resolved by a rule that cannot see the drawing."""
    rows = [{"part_number": SUB, "quantity": 3, "source_pdf": GA, "bom_parent": GA}]
    nodes = _nodes([_part(SUB, 1, "bom_tree")], rows)
    assert nodes[SUB]["qty_per_unit"] == 3.0
    assert nodes[SUB]["qty_own"] == 1.0
    assert "confirm which is right" in nodes[SUB]["qty_note"]


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
