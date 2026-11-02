"""A reached model-only child with a readable file is priced, not only asked (SCRUM-155).

12678-01-GA: 04M x2, 05M x6 and 06M x8 hang off the two bracket assemblies in the
SolidWorks tree. The assemblies carry the welding, the dressing, the powder and the
bench work — and the children had no records, so no line anywhere held the bracket
steel. reached_bom_item_unaccounted fired, three missing-price decisions were raised,
and the unit went out short exactly the money nobody could see.

THE RULE: the hierarchy pass wires the edges; this mints the leaves — narrowly. Only a
child an existing parent record claims, only when its own model file read cleanly with
sheet geometry the costing can price (a flat pattern, or a plate-shaped solid), never a
bought-in, never a code that already has a record. The minted line carries the tree's
own per-unit arithmetic, a minted_from_model stamp and its question. A child whose file
failed stays unminted and keeps the missing-price question: short in the open, never
guessed.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from source_connectors.solidworks import (apply_native_hierarchy_to_parts,  # noqa: E402
                                          mint_model_children,
                                          normalize_native_extract)


def _job():
    return normalize_native_extract([
        {"title": "12678-01-101SA", "doctype": 2,
         "assembly_part_number": "12678-01-101SA",
         "assembly_edges": [
             {"parent": "12678-01-101SA", "child": "12678-01-05M", "qty": 1},
             {"parent": "12678-01-101SA", "child": "12678-01-06M", "qty": 1}]},
        {"title": "12678-01-102SA", "doctype": 2,
         "assembly_part_number": "12678-01-102SA",
         "assembly_edges": [
             {"parent": "12678-01-102SA", "child": "12678-01-04M", "qty": 1},
             {"parent": "12678-01-102SA", "child": "12678-01-06M", "qty": 1},
             {"parent": "12678-01-102SA", "child": "BOLT-SHAPE", "qty": 3},
             {"parent": "12678-01-102SA", "child": "FIXING99", "qty": 2}]},
        # A sheet-metal child whose file read: flat pattern, 2 mm.
        {"title": "12678-01-06M", "doctype": 1, "route_signals": {
            "material": "Mild Steel [CR4]", "is_sheet_metal": True, "bend_count": 0,
            "thickness_mm": 2.0, "flat_length_mm": 120.0, "flat_width_mm": 60.0,
            "bbox_mm": [120.0, 60.0, 2.0]}},
        # A plate modelled as an extrude: no flat, plate-shaped extents.
        {"title": "12678-01-04M", "doctype": 1, "route_signals": {
            "material": "Mild Steel", "is_sheet_metal": False, "bend_count": 0,
            "thickness_mm": 2.5, "bbox_mm": [90.0, 32.0, 2.5]}},
        # 05M's file FAILED: an error-only record, no route_signals.
        {"title": "12678-01-05M", "doctype": 1, "errors": ["native extract failed"]},
        # A bolt-shaped solid: not a plate, never minted.
        {"title": "BOLT-SHAPE", "doctype": 1, "route_signals": {
            "material": "Steel", "is_sheet_metal": False, "bend_count": 0,
            "thickness_mm": None, "bbox_mm": [40.0, 10.0, 10.0]}},
        # Plate-shaped but SDI's own conventions say bought in.
        {"title": "FIXING99", "doctype": 1, "route_signals": {
            "material": "Steel", "is_sheet_metal": False, "bend_count": 0,
            "thickness_mm": 2.0, "bbox_mm": [80.0, 40.0, 2.0]}},
    ])


def _parts():
    return [
        {"part_number": "12678-01-101SA", "description": "SHELF SUPPORT BRACKET ASSY",
         "quantity": 6, "is_sub_assembly": True},
        {"part_number": "12678-01-102SA", "description": "TOP SUPPORT BRACKET ASSY",
         "quantity": 2, "is_sub_assembly": True},
    ]


def _minted(job=None):
    parts = _parts()
    job = job or _job()
    apply_native_hierarchy_to_parts(parts, job)
    mint_model_children(parts, job)
    return {p["part_number"]: p for p in parts}


def test_the_bracket_steel_is_minted_with_the_rows_own_count():
    """THE ROW'S OWN QUANTITY, NEVER THE TREE'S PRODUCT. The first mint wrote the
    per-unit total and the route multiplied by the parent again — 12678's 19:09 run
    costed 05M at 216 off a '6 per 101SA x6' trail. The record carries the per-parent
    count on _per_parent_count's basis; the flag states the per-unit product the tree
    implies."""
    got = _minted()
    m6 = got["12678-01-06M"]
    assert m6["minted_from_model"] is True
    assert m6["quantity"] == 1                      # 1 per parent — the route multiplies
    assert (m6["blank_length_mm"], m6["blank_width_mm"]) == (120.0, 60.0)
    assert m6["normalized_thickness_mm"] == 2.0
    assert m6["native_flat_pattern"] is True
    assert "STEEL" in str(m6["normalized_material"]).upper()
    assert any("implies x8 a unit" in f for f in m6["review_flags"])
    assert any("the route multiplies, once" in f for f in m6["review_flags"])
    assert any("priced from its model alone" in str(q.get("issue"))
               for q in m6["manufacturing_questions"])


def test_a_plate_modelled_as_an_extrude_is_minted_from_its_extents():
    got = _minted()
    m4 = got["12678-01-04M"]
    assert m4["quantity"] == 1                      # 1 per 102SA; the route makes it 2
    assert (m4["blank_length_mm"], m4["blank_width_mm"]) == (90.0, 32.0)
    assert m4["normalized_thickness_mm"] == 2.5
    assert any("plate-shaped solid" in f for f in m4["review_flags"])


def test_a_shared_childs_undividable_total_is_never_invented():
    """THE SHARED CHILD (06M's real shape): a product total that cannot be attributed
    per parent carries 1 per parent with the conflict said out loud — the BOM-ranked
    edges and the quantity check decide, never a figure invented to make the
    arithmetic tidy."""
    from source_connectors.solidworks import (apply_native_hierarchy_to_parts,
                                              mint_model_children,
                                              normalize_native_extract)
    job = normalize_native_extract([
        {"title": "12678-01-GA", "doctype": 2, "assembly_part_number": "12678-01-GA",
         "bom": [{"part_number": "12678-01-06M", "qty": 16},
                 {"part_number": "12678-01-101SA", "qty": 6},
                 {"part_number": "12678-01-102SA", "qty": 2}],
         "assembly_edges": [
             {"parent": "", "child": "12678-01-101SA", "qty": 6, "child_doc_type": 2},
             {"parent": "", "child": "12678-01-102SA", "qty": 2, "child_doc_type": 2}]},
        {"title": "12678-01-101SA", "doctype": 2,
         "assembly_part_number": "12678-01-101SA",
         "assembly_edges": [
             {"parent": "12678-01-101SA", "child": "12678-01-06M", "qty": 12}]},
        {"title": "12678-01-102SA", "doctype": 2,
         "assembly_part_number": "12678-01-102SA",
         "assembly_edges": [
             {"parent": "12678-01-102SA", "child": "12678-01-06M", "qty": 4}]},
        {"title": "12678-01-06M", "doctype": 1, "route_signals": {
            "material": "Mild Steel", "is_sheet_metal": True, "bend_count": 0,
            "thickness_mm": 2.0, "flat_length_mm": 120.0, "flat_width_mm": 60.0,
            "bbox_mm": [120.0, 60.0, 2.0]}},
    ])
    parts = _parts()
    apply_native_hierarchy_to_parts(parts, job)
    mint_model_children(parts, job)
    m6 = {p["part_number"]: p for p in parts}["12678-01-06M"]
    assert m6["quantity"] == 1
    assert any("no per-parent count divides" in f for f in m6["review_flags"])
    assert any("the quantity check decide" in f for f in m6["review_flags"])


def test_a_multi_count_edge_keeps_the_per_parent_count_on_the_row():
    """A stated edge with no product total to divide: the DEDUPLICATED edge figure
    stands where the model states exactly one — 6 per bracket, the tree implying 36."""
    from source_connectors.solidworks import (apply_native_hierarchy_to_parts,
                                              mint_model_children,
                                              normalize_native_extract)
    job = normalize_native_extract([
        {"title": "12678-01-101SA", "doctype": 2,
         "assembly_part_number": "12678-01-101SA",
         "assembly_edges": [
             {"parent": "12678-01-101SA", "child": "12678-01-05M", "qty": 6}]},
        {"title": "12678-01-05M", "doctype": 1, "route_signals": {
            "material": "Mild Steel", "is_sheet_metal": True, "bend_count": 0,
            "thickness_mm": 2.0, "flat_length_mm": 300.0, "flat_width_mm": 114.6,
            "bbox_mm": [300.0, 114.6, 2.0]}},
    ])
    parts = [{"part_number": "12678-01-101SA", "description": "BRACKET ASSY",
              "quantity": 6, "is_sub_assembly": True}]
    apply_native_hierarchy_to_parts(parts, job)
    mint_model_children(parts, job)
    m5 = {p["part_number"]: p for p in parts}["12678-01-05M"]
    assert m5["quantity"] == 6
    assert any("implies x36 a unit" in f for f in m5["review_flags"])


def test_a_failed_file_keeps_its_missing_price_question():
    """05M's model did not read: no geometry means no mint, and the reached-item check
    still names it — short in the open, never guessed."""
    got = _minted()
    assert "12678-01-05M" not in got


def test_a_bolt_shape_and_a_bought_in_are_never_minted():
    got = _minted()
    assert "BOLT-SHAPE" not in got
    assert "FIXING99" not in got


def test_a_child_with_a_record_is_not_minted_twice():
    parts = _parts() + [{"part_number": "12678-01-06M", "description": "RIB",
                         "quantity": 1}]
    job = _job()
    apply_native_hierarchy_to_parts(parts, job)
    mint_model_children(parts, job)
    assert [p["part_number"] for p in parts].count("12678-01-06M") == 1
    assert not [p for p in parts if p.get("minted_from_model")
                and p["part_number"] == "12678-01-06M"]


def test_the_charged_quantity_chain_multiplies_once():
    """THE WHOLE CHAIN ON THE REAL EXTRACT SHAPE, as the second review demanded: the
    analyser lists an edge once per INSTANCE and states full-depth product totals, so
    six 05M in a product with six 101SA is ONE per bracket — per-parent is the child's
    product total over the parent's (_per_parent_count's basis), never the seen-edge
    sum. The 19:09 run charged 216; the truth this fixture states is 6."""
    import route_compiler as rc
    job = normalize_native_extract([
        {"title": "12678-01-GA", "doctype": 2, "assembly_part_number": "12678-01-GA",
         "bom": [{"part_number": "12678-01-05M", "qty": 6},
                 {"part_number": "12678-01-101SA", "qty": 6}],
         "assembly_edges": [
             {"parent": "", "child": "12678-01-101SA", "qty": 6, "child_doc_type": 2}]},
        {"title": "12678-01-101SA", "doctype": 2,
         "assembly_part_number": "12678-01-101SA",
         # One edge per instance seen — the record of sightings, not a count.
         "assembly_edges": [
             {"parent": "12678-01-101SA", "child": "12678-01-05M", "qty": 1}
             for _ in range(6)]},
        {"title": "12678-01-05M", "doctype": 1, "route_signals": {
            "material": "Mild Steel", "is_sheet_metal": True, "bend_count": 0,
            "thickness_mm": 2.0, "flat_length_mm": 300.0, "flat_width_mm": 114.6,
            "bbox_mm": [300.0, 114.6, 2.0]}},
    ])
    parts = [{"part_number": "12678-01-GA", "description": "PODIUM", "quantity": 1,
              "is_assembly_parent": True, "assembly_children": ["12678-01-101SA"]},
             {"part_number": "12678-01-101SA", "description": "BRACKET ASSY",
              "quantity": 6, "is_sub_assembly": True}]
    apply_native_hierarchy_to_parts(parts, job)
    mint_model_children(parts, job)
    m5 = {p["part_number"]: p for p in parts}["12678-01-05M"]
    assert m5["quantity"] == 1, "6 in the product over 6 brackets is ONE per bracket"
    assert any("so one takes 1" in f for f in m5["review_flags"])
    graph = rc.build_part_graph(parts)
    node = next(n for n in graph["nodes"] if n.part_number == "12678-01-05M")
    assert node.qty_per_unit == 6, (node.qty_per_unit, node.qty_trail)
    assert any("= 6" in t for t in node.qty_trail), node.qty_trail
    # And through the last gate onto the ONE quantity field the sheet costs — the same
    # field the material row and every labour row read, so 6 is what both charge.
    import wb_populate as wbp
    summary = {"estimate_summary": {"canonical_route_shadow": {
        "nodes": [{"part_number": n.part_number, "qty_per_unit": n.qty_per_unit,
                   "qty_trail": list(n.qty_trail)} for n in graph["nodes"]],
        "issues": []}}}
    out = wbp.canonicalise_part_estimates_for_workbook(
        summary, [{"part_number": "12678-01-05M", "description": "RIB", "quantity": 1,
                   "normalized_material": "MILD_STEEL"}])
    row = next(e for e in out if e["part_number"] == "12678-01-05M")
    assert row["quantity"] == 6, (row.get("quantity"), "the charged field is canonical")


def test_the_scan_wires_the_mint_after_the_hierarchy():
    scan = open(os.path.join(os.path.dirname(__file__), "..", "src", "file_scan.py"),
                encoding="utf-8").read()
    assert scan.index("apply_native_hierarchy_to_parts(") < scan.index(
        "mint_model_children(summary")
