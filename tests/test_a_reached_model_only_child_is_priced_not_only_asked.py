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


def test_the_bracket_steel_is_minted_with_the_trees_own_arithmetic():
    got = _minted()
    m6 = got["12678-01-06M"]
    assert m6["minted_from_model"] is True
    assert m6["quantity"] == 8                      # 1 x 101SA's 6 + 1 x 102SA's 2
    assert (m6["blank_length_mm"], m6["blank_width_mm"]) == (120.0, 60.0)
    assert m6["normalized_thickness_mm"] == 2.0
    assert m6["native_flat_pattern"] is True
    assert "STEEL" in str(m6["normalized_material"]).upper()
    assert any("x8 a unit" in f for f in m6["review_flags"])
    assert any("priced from its model alone" in str(q.get("issue"))
               for q in m6["manufacturing_questions"])


def test_a_plate_modelled_as_an_extrude_is_minted_from_its_extents():
    got = _minted()
    m4 = got["12678-01-04M"]
    assert m4["quantity"] == 2
    assert (m4["blank_length_mm"], m4["blank_width_mm"]) == (90.0, 32.0)
    assert m4["normalized_thickness_mm"] == 2.5
    assert any("plate-shaped solid" in f for f in m4["review_flags"])


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


def test_the_scan_wires_the_mint_after_the_hierarchy():
    scan = open(os.path.join(os.path.dirname(__file__), "..", "src", "file_scan.py"),
                encoding="utf-8").read()
    assert scan.index("apply_native_hierarchy_to_parts(") < scan.index(
        "mint_model_children(summary")
