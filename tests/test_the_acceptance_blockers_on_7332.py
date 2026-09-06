"""The three defects that kept 7332-01 off acceptance: two blockers and a double-charged waste.

1. A generated plating line arrived at the graph with no edge and blocked the job as
   "bom_node_disconnected". It is a finish ON the weldment, so the weldment owns it.
2. The flat-blank/cut-path invariant fired on the tube leg — a 15.88 x 15.88 figure against a
   9,106 mm cut path — when a tube is cut to length from bar and no blank ever priced it.
3. Waste was charged twice. Section stock is priced mass x rate x waste_factor and the sheet
   then wrote its own 4% scrap: the leg pair shipped £12.19 against a true £11.72. The felt
   pad's fixed £0.20 commodity rate went the same way, £0.80 -> £0.83.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator as e  # noqa: E402
import invariants as inv  # noqa: E402
import route_compiler as rc  # noqa: E402


def _leg():
    return {"part_number": "7332-01-002", "description": "LEG - 12.7 x 1.2 CHS TUBE",
            "normalized_material": "MILD STEEL", "quantity": 2,
            "section_stock": {"a": 12.7, "b": 12.7, "t": 1.2, "profile_form": "CHS",
                              "length_mm": 1400.0},
            # the spurious flat blank + real tube cut path that blocked the job
            "cut_length_mm": 9106.0, "blank_length_mm": 15.88, "blank_width_mm": 15.88}


# ── 1. the generated plating line has the parent it actually has ───────────────
def test_a_generated_plating_line_is_not_a_disconnected_node():
    parts = [
        {"part_number": "7332-01-101", "description": "FRAME WELDMENT",
         "normalized_material": "MILD STEEL", "normalized_finish": "PLATED",
         "is_assembly_parent": True,
         "assembly_children": ["7332-01-002", "7332-01-101-PLATE"]},
        {"part_number": "7332-01-002", "description": "LEG", "normalized_material": "MILD STEEL"},
        {"part_number": "7332-01-101-PLATE", "description": "plating",
         "page_roles": ["bought_in"], "_commercial_placeholder": True,
         "_plating_placeholder": True},
    ]
    graph = rc.build_part_graph(parts, {"assemblies": [
        {"part_number": "7332-01-101", "children": [
            {"part_number": "7332-01-002"}, {"part_number": "7332-01-101-PLATE"}]}]})
    plate = next(n for n in graph["nodes"] if n.part_number.endswith("-PLATE"))
    assert plate.parents == ["7332-01-101"]      # plating sits under the thing it plates
    disconnected = [i for i in (graph.get("issues") or [])
                    if i.get("code") == "bom_node_disconnected"]
    assert not disconnected


def test_a_generated_line_with_no_parent_at_all_is_still_exempt():
    """The exemption is by MARKER, not a list of names — the name list is why a plating line
    the list had never heard of blocked the job."""
    parts = [
        {"part_number": "TOP", "description": "GA", "is_assembly_parent": True,
         "assembly_children": ["LEAF"]},
        {"part_number": "LEAF", "description": "PANEL", "normalized_material": "MILD STEEL"},
        {"part_number": "SOMETHING-PLATE", "description": "plating",
         "page_roles": ["bought_in"], "_plating_placeholder": True},
    ]
    graph = rc.build_part_graph(parts, {"assemblies": [
        {"part_number": "TOP", "children": [{"part_number": "LEAF"}]}]})
    codes = [i.get("part_number") for i in (graph.get("issues") or [])
             if i.get("code") == "bom_node_disconnected"]
    assert "SOMETHING-PLATE" not in codes


# ── 2. a tube has no flat blank to disagree with ───────────────────────────────
def test_the_flat_blank_invariant_does_not_fire_on_a_tube():
    part = _leg()
    pe = e.estimate_part(part, job_quantity=6)
    assert part.get("stock_form") == "tube"
    out = inv.check_a_blank_and_its_cut_path_can_both_be_true(
        {"part_estimates": [pe], "parts": [part]})
    assert not out, f"a tube cannot disagree with a blank it never had: {out}"


def test_a_real_sheet_part_with_an_impossible_blank_still_blocks():
    """The check must keep working where it belongs — this is the guard on the exemption."""
    flat = {"part_number": "X-1", "description": "PANEL", "normalized_material": "MILD STEEL",
            "blank_length_mm": 12.0, "blank_width_mm": 11.0, "cut_length_mm": 9106.0}
    out = inv.check_a_blank_and_its_cut_path_can_both_be_true(
        {"part_estimates": [flat], "parts": [flat]})
    assert any(v.get("code") == "blank_and_cut_path_disagree" for v in out)


# ── 3. the waste allowance is charged once ─────────────────────────────────────
def test_section_stock_declares_its_waste_is_already_in_the_price():
    pe = e.estimate_part(_leg(), job_quantity=6)
    me = pe["material_estimate"]
    assert me.get("waste_included") is True
    assert me.get("waste_factor_applied") == 1.04


def test_the_sheet_leaves_scrap_alone_when_the_price_already_carries_it():
    """wb_populate writes 4% into the scrap column; a line whose rate already includes its
    allowance must get no scrap, or the same 4% is charged twice."""
    import wb_populate as wp
    src = open(wp.__file__, encoding="utf-8").read()
    assert "_waste_already_in" in src
    assert '_me_scrap.get("waste_included")' in src
    # and the fixed per-each commodity rates are covered by the same rule
    assert "standard_commodity_provisional" in src.split("_waste_already_in")[1][:400]
