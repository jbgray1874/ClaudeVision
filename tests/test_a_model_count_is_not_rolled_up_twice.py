"""A part's SolidWorks count is per parent when it goes into `quantity` — never per product.

James Gray, 22 September 2026, reviewing the 11650-06 Coffret hospital kit against his own
exploded list: sliders 24 against 12, locking tabs 12 against 6, RSB plates 18 against 3,
extenders 9 against 3. He had warned in advance — "treat 12 as the full-explode including
sub-assy; don't buy 6 + 12" — and the engine arrived at the same over-count by another road.

TWO FACTS UNDER ONE NAME. The model's native BOM is FULL-DEPTH: its figure for a part is how
many the whole PRODUCT contains, already multiplied through every assembly above it. That
figure was written into `quantity`. But `quantity` on a record means how many ONE PARENT
takes: route_compiler's `_per_parent` says so in terms and multiplies it down the tree. The
model outranks the drawing's BOM edge, so the product total was kept as a per-parent count
and then rolled up a second time — an extender the model counts 3 of, under a set the kit
takes 3 of, came out at 9. The report said so itself: "qty 1.0 -> 3 from the SolidWorks
assembly BOM (component count, all levels)".
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc                                           # noqa: E402
from source_connectors.solidworks import (                            # noqa: E402
    NativeBomRow, NativeJob, apply_native_to_pre_estimate)


def _kit_parts():
    """11650-06 as the drawing readers leave it: the kit GA, the extender set, and the
    extender with the per-set count its own sheet prints."""
    return [
        {"part_number": "11650-06-GA", "description": "COFFRET HOSPITAL KIT",
         "quantity": 1, "is_assembly_parent": True,
         "assembly_children": ["11650-06-SA01"], "page_roles": ["assembly"]},
        {"part_number": "11650-06-SA01", "description": "END PANEL GF CONVERSION SET",
         "quantity": 3, "is_sub_assembly": True, "is_assembly_parent": True,
         "assembly_children": ["11650-04-03A"], "page_roles": ["assembly"]},
        {"part_number": "11650-04-03A", "description": "EXTENDER PANEL", "quantity": 1,
         "normalized_material": "PETG", "page_roles": ["detail"], "review_flags": []},
    ]


def _model():
    """The model agrees with the drawing, and says so twice over: one extender per set on
    its own edge list, and three in the whole product on the full-depth BOM."""
    return NativeJob(
        found=True,
        bom=[NativeBomRow(part_number="11650-06-SA01", quantity=3, is_assembly=True),
             NativeBomRow(part_number="11650-04-03A", quantity=3)],
        assembly_pns=["11650-06-GA", "11650-06-SA01"],
        hierarchy={"11650-06-GA": [("11650-06-SA01", 3.0)],
                   "11650-06-SA01": [("11650-04-03A", 1.0)]})


def _costed_qty(parts, pn):
    graph = rc.build_part_graph(parts)
    return graph["quantities"].get(pn)


def test_three_sets_of_one_extender_are_three_extenders_not_nine():
    """THE FAULT, REPRODUCED AND FIXED. Before, the extender's record read 3 (the product
    total) at the model's rank, the compiler took it as "per SA01", and 3 sets x 3 = 9."""
    parts = _kit_parts()
    apply_native_to_pre_estimate(parts, _model())
    ext = next(p for p in parts if p["part_number"] == "11650-04-03A")

    assert ext["quantity"] == 1, (
        f"the extender's quantity is {ext['quantity']} — the product total was written where "
        f"a per-parent count belongs")
    assert ext["quantity_total_per_unit"] == 3, "the model's product total was thrown away"
    assert _costed_qty(parts, "11650-04-03A") == 3, "the kit is costed with the wrong count"


def test_the_total_is_kept_as_a_second_road_to_the_same_answer():
    """Where the roll-up and the model's own count disagree, the line says so — the model's
    top assembly is not always the job's, so a difference can be legitimate, and a person is
    the one who can tell. Silence is the one thing it must not be."""
    parts = _kit_parts()
    apply_native_to_pre_estimate(parts, _model())
    # Simulate the old double count arriving by some other road.
    next(p for p in parts if p["part_number"] == "11650-04-03A")["quantity_total_per_unit"] = 9
    graph = rc.build_part_graph(parts)
    note = str((graph.get("qty_notes") or {}).get("11650-04-03A") or "")
    node = next((n for n in (graph.get("nodes") or [])
                 if getattr(n, "part_number", None) == "11650-04-03A"), None)
    note = note or str(getattr(node, "qty_note", "") or "")
    assert "SolidWorks model counts 9" in note, (
        f"a roll-up that disagrees with the model's own count went unremarked: {note!r}")


def test_a_part_under_two_parents_is_decided_by_the_bom_not_the_total():
    """One part under two assemblies has no single per-parent count, and the product total
    would be multiplied again under each of them. The drawing's BOM edges carry a count per
    parent, so they decide, and the record says why the model's figure was not used."""
    parts = _kit_parts()
    model = _model()
    model.hierarchy["11650-06-GA"].append(("11650-04-03A", 2.0))
    model.bom[1] = NativeBomRow(part_number="11650-04-03A", quantity=5)
    apply_native_to_pre_estimate(parts, model)
    ext = next(p for p in parts if p["part_number"] == "11650-04-03A")
    assert ext["quantity"] == 1, "the product total was written for a multi-parent part"
    assert any("sits under 2 assemblies" in f for f in ext["review_flags"]), ext["review_flags"]


def test_a_model_with_no_tree_behaves_exactly_as_before():
    """THE CONTROL. With no edge list there is nothing to say which parent the count belongs
    to, and the full-depth figure is still the best reading there is — so that case writes
    it, as it always did. The fix changes only what a tree can prove."""
    parts = [{"part_number": "401912-02", "description": "METAL DIVIDER", "quantity": 1,
              "page_roles": ["detail"], "review_flags": []}]
    job = NativeJob(found=True, bom=[NativeBomRow(part_number="401912-02", quantity=2)],
                    assembly_pns=[], hierarchy={})
    apply_native_to_pre_estimate(parts, job)
    assert parts[0]["quantity"] == 2
    assert any("component count, all levels" in f for f in parts[0]["review_flags"])


def test_the_multiplication_trail_is_written_down():
    """Review of 11650-06: "The workbook proves that many own quantities and effective
    quantities differ, but it does not prove all effective quantities are wrong... The system
    needs to show the exact parent-to-child multiplication trail, then an estimator can
    approve or correct it."

    The product was the only thing the roll-up kept, so nobody could say WHICH edge made a
    count. Every path is now recorded, each step with the count one parent takes and who said
    so, and the paths add up to what is costed."""
    parts = _kit_parts()
    apply_native_to_pre_estimate(parts, _model())
    graph = rc.build_part_graph(parts)
    node = next(n for n in graph["nodes"] if n.part_number == "11650-04-03A")

    assert node.qty_trail, "the roll-up left no working behind it"
    trail = node.qty_trail[0]
    assert trail.startswith("11650-06-GA x1"), trail
    assert "11650-06-SA01 x3" in trail and "11650-04-03A x1" in trail, trail
    assert trail.endswith("= 3"), trail
    # Who said so, per step — the thing an estimator needs to overrule the right edge.
    assert "(BOM" in trail, trail

    # And it reaches the BOM page, where an estimator reads it.
    from bom_and_route_extract import graph_quantity_by_code
    summary = {"estimate_summary": {"canonical_route_shadow": {
        "nodes": [{"part_number": n.part_number, "qty_per_unit": n.qty_per_unit,
                   "qty_trail": n.qty_trail} for n in graph["nodes"]]}}}
    assert graph_quantity_by_code(summary)["11650-04-03A"]["qty_trail"] == node.qty_trail


def test_two_paths_are_two_lines_that_add_up():
    """A part reached twice is costed as the sum, and the trail shows both — which is exactly
    the case the reviewer raised about the slider sitting under more than one parent."""
    parts = [
        {"part_number": "TOP", "quantity": 1, "is_assembly_parent": True,
         "assembly_children": ["A", "B"], "page_roles": ["assembly"]},
        {"part_number": "A", "quantity": 2, "is_assembly_parent": True,
         "assembly_children": ["SLIDER"], "page_roles": ["assembly"]},
        {"part_number": "B", "quantity": 3, "is_assembly_parent": True,
         "assembly_children": ["SLIDER"], "page_roles": ["assembly"]},
        {"part_number": "SLIDER", "quantity": 1, "page_roles": ["detail"]},
    ]
    graph = rc.build_part_graph(parts)
    node = next(n for n in graph["nodes"] if n.part_number == "SLIDER")
    assert len(node.qty_trail) == 2, node.qty_trail
    totals = sorted(float(t.rsplit("= ", 1)[1]) for t in node.qty_trail)
    assert sum(totals) == node.qty_per_unit, (totals, node.qty_per_unit)


def test_a_repeated_edge_is_not_a_bigger_count():
    """THE 11650-06 RE-RUN, REPRODUCED. The model listed the set->extender edge more than
    once, the first cut SUMMED them, and one extender per set was costed as six — 18 in the
    kit, worse than the 9 it was written to fix. The per-parent figure is now the child's
    product total over the parent's: 3 extenders / 3 sets = 1."""
    parts = _kit_parts()
    # The drawing gets it wrong, so the model has to CORRECT it — which is the only way to
    # prove the figure came from the ratio rather than from the drawing standing unopposed.
    next(p for p in parts if p["part_number"] == "11650-04-03A")["quantity"] = 2
    model = _model()
    # The same edge, reported twice — per instance, per configuration or per SLDASM.
    model.hierarchy["11650-06-SA01"] = [("11650-04-03A", 1.0), ("11650-04-03A", 1.0),
                                        ("11650-04-03A", 1.0), ("11650-04-03A", 3.0)]
    apply_native_to_pre_estimate(parts, model)
    ext = next(p for p in parts if p["part_number"] == "11650-04-03A")
    assert ext["quantity"] == 1, f"repeated edges were added up: {ext['quantity']}"
    assert any("3/3 = 1" in f for f in ext["review_flags"]), ext["review_flags"]
    assert _costed_qty(parts, "11650-04-03A") == 3


def test_the_check_is_never_swallowed_by_an_earlier_note():
    """The cross-check exists to say "rolled up to 18, the model counts 3". On the re-run it
    was written only if the part had no note yet — and it had one — so the line that would
    have caught the regression never reached the page.

    A slider under two sets, each taking a different count by the drawing's BOM edges, with
    its own record reading neither: the multi-parent note is written first, by _per_parent.
    The model's product total then disagrees with the roll-up, and BOTH must be on the line."""
    parts = [
        {"part_number": "TOP", "quantity": 1, "is_assembly_parent": True,
         "page_roles": ["assembly"]},
        {"part_number": "SET-A", "quantity": 1, "is_assembly_parent": True,
         "page_roles": ["assembly"]},
        {"part_number": "SET-B", "quantity": 1, "is_assembly_parent": True,
         "page_roles": ["assembly"]},
        {"part_number": "SLIDER", "quantity": 1, "quantity_total_per_unit": 99,
         "page_roles": ["detail"]},
    ]
    extract = {"assemblies": [
        {"part_number": "TOP", "children": [{"part_number": "SET-A", "qty": 1},
                                            {"part_number": "SET-B", "qty": 1}]},
        {"part_number": "SET-A", "children": [{"part_number": "SLIDER", "qty": 2}]},
        {"part_number": "SET-B", "children": [{"part_number": "SLIDER", "qty": 3}]},
    ]}
    graph = rc.build_part_graph(parts, llm_extract=extract)
    note = str((graph.get("qty_notes") or {}).get("SLIDER") or "")
    node = next(n for n in graph["nodes"] if n.part_number == "SLIDER")
    note = note or str(getattr(node, "qty_note", "") or "")
    assert "more than one parent" in note, f"the earlier note this test needs is absent: {note!r}"
    assert "CHECK:" in note and "counts 99" in note, f"the check was swallowed: {note!r}"
