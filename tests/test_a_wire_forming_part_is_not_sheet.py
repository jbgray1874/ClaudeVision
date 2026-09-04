r"""
test_a_wire_forming_part_is_not_sheet.py

A PART WE FORM FROM WIRE OR BAR IS NOT A SHEET, HOWEVER ITS MATERIAL READS.

11762-17 (Milwaukee MX Fuel holder): 03M "U WIRE" (Ø8) and 04M "WIRE STAND" carried a
wire_forming op and welding, but their material read "MILD STEEL" — so the WIRE-in-materials
recogniser missed them and they fell to the SHEET path. Two lies followed: the Ø8 diameter
was read as an 8mm sheet THICKNESS and priced as a tiny plate (£0.11 / £0.13 of "steel"), and
a laser_cutting row was booked on a solid wire that is cut/formed on the Robomac, not lasered.

The fix, one rule every pack (not a 11762-17 by-part patch):
  * A part ROUTED as wire (a wire_forming op) — or NAMED wire/bar/rod WITH a diameter — is wire
    stock. It gets _bar_recognised + manufacturing_interpretation.stock_form "wire", the Ø moves
    off the thickness field, and the three stock_form readers then agree.
  * Material is priced on the Wire/Bar basis when a real developed LENGTH exists (a schedule /
    cut-list / CL dimension). A PDF-vector cut path is an inflated outline, NOT a length, so when
    no trusted length exists the line is an estimator input on WIRE stock — never a sheet penny.
  * laser (and sheet fold/punch) fall out via the stock_form "wire" impossibility gate — no
    fourth laser-writer patch.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from document_builder import _apply_post_build_fixes            # noqa: E402
from estimator import estimate_material                          # noqa: E402
import stock_form_rules                                          # noqa: E402


def _summary(pages=()):
    return {"pages": [
        {"page_number": n, "pdfplumber_text": t, "text_preview": t,
         "page_role": {"primary_role": r}} for n, t, r in pages]}


def _wire_part(pn, desc, ops, thickness=None):
    return {
        "part_number": pn, "description": desc,
        "materials": ["MILD STEEL"], "normalized_material": "MILD STEEL",
        "normalized_thickness_mm": thickness,
        "textual_operations": list(ops), "page_roles": ["detail"], "pages": [],
        "geometry_rollup": {"confidence": {"geometry_reliability": 0.0}},
    }


# ── recognition: a named wire becomes wire stock — on the NAME, before ops exist ─────
# THE LIVE-REPRO. This pass runs BEFORE textual_operations are inferred, so 11762-17-03M/04M
# reach it with NO wire_forming op yet and no explicit "DIA" callout. The first version of the
# fix keyed off the op / an explicit diameter and never fired. The NAME is what is available.
def test_03m_u_wire_becomes_wire_on_the_name_before_any_op_is_inferred():
    part = _wire_part("11762-17-03M", "U WIRE", ops=[], thickness=8.0)   # no op yet, no DIA text
    _apply_post_build_fixes([part], _summary())
    assert part.get("_bar_recognised") is True, "a WIRE name must recognise it with no op present"
    assert part.get("wire_gauge_mm") == 8.0, "the Ø8 misread into thickness must move to the gauge"
    assert part.get("normalized_thickness_mm") is None, "a diameter is not a sheet thickness"
    assert (part.get("manufacturing_interpretation") or {}).get("stock_form") == "wire"


def test_04m_wire_stand_with_no_diameter_is_still_wire_on_the_name():
    part = _wire_part("11762-17-04M", "WIRE STAND", ops=[], thickness=None)
    _apply_post_build_fixes([part], _summary())
    assert part.get("_bar_recognised") is True, "a WIRE name recognises it even with no Ø and no op"
    assert (part.get("manufacturing_interpretation") or {}).get("stock_form") == "wire"
    assert part.get("wire_gauge_mm") is None, "no diameter was given; it must not be invented"


def test_a_wire_forming_op_still_reinforces_it_if_already_present():
    part = _wire_part("X", "SPRING CLIP", ["wire_forming"], thickness=6.0)
    _apply_post_build_fixes([part], _summary())
    assert part.get("_bar_recognised") is True, "an explicit wire_forming op qualifies on its own"
    assert part.get("wire_gauge_mm") == 6.0


def test_a_named_bar_with_an_explicit_diameter_qualifies():
    part = _wire_part("X", "TIE BAR 8 DIA", [], thickness=None)
    _apply_post_build_fixes([part], _summary())
    assert part.get("_bar_recognised") is True
    assert part.get("wire_gauge_mm") == 8.0


# ── recognition guards: it must not sweep in sheet ──────────────────────────────────
def test_a_named_bar_with_no_op_and_no_diameter_is_not_wire():
    """A NAME alone is not enough — otherwise a sheet part called '...BAR...' becomes wire."""
    part = _wire_part("X", "CROSS BAR BRACKET", [], thickness=2.0)
    _apply_post_build_fixes([part], _summary())
    # No wire_forming op and no diameter callout -> the thickness is a real gauge; leave it.
    assert not part.get("_bar_recognised")
    assert part.get("normalized_thickness_mm") == 2.0


def test_a_part_with_a_flat_pattern_dxf_is_sheet_not_wire():
    """A measured flat pattern is proof of a sheet part; a stray 'bar' in the name must not
    reclassify it."""
    part = _wire_part("X", "BAR PANEL", ["wire_forming"], thickness=2.0)
    part["flat_pattern_detected"] = True
    _apply_post_build_fixes([part], _summary())
    assert not part.get("_bar_recognised")
    assert part.get("normalized_thickness_mm") == 2.0


def test_wire_mesh_is_left_to_the_section_path_not_reclassified_as_bar():
    part = _wire_part("X", "WIRE MESH PANEL", [], thickness=3.0)
    _apply_post_build_fixes([part], _summary())
    assert not part.get("_bar_recognised"), "WIRE MESH is a section, not a solid bar"


# ── material: no trusted length -> estimator input on WIRE, never a sheet penny ──────
def test_a_wire_with_a_gauge_but_no_length_is_an_estimator_input_not_sheet():
    """James's rule: a PDF cut path is not a length. With a Ø but no developed length the
    material is left for the estimator, on wire stock — not priced as a plate."""
    me = estimate_material({
        "part_number": "11762-17-03M", "normalized_material": "MILD STEEL",
        "quantity": 20, "_bar_recognised": True, "wire_gauge_mm": 8.0})
    assert me["stock_form"] == "wire"
    assert me["cost_method"] == "wire_stock_estimator_to_confirm"
    assert me["unit_material_cost_gbp"] is None, "a wire with no length must not carry a £ figure"
    assert me["thickness_mm"] is None, "the diameter must never sit in the thickness field"
    assert me.get("estimator_input_required") is True


def test_the_missing_datum_names_the_length():
    part = {"part_number": "11762-17-03M", "normalized_material": "MILD STEEL",
            "quantity": 20, "_bar_recognised": True, "wire_gauge_mm": 8.0}
    estimate_material(part)
    flags = " ".join(part.get("review_flags") or [])
    assert "developed length" in flags and "not measured" in flags
    assert "diameter" not in flags, "the diameter WAS given, so only the length is missing"


def test_a_wire_with_neither_gauge_nor_length_names_both():
    part = {"part_number": "11762-17-04M", "normalized_material": "MILD STEEL",
            "quantity": 20, "_bar_recognised": True}
    me = estimate_material(part)
    assert me["cost_method"] == "wire_stock_estimator_to_confirm"
    assert me["unit_material_cost_gbp"] is None
    flags = " ".join(part.get("review_flags") or [])
    assert "diameter" in flags and "developed length" in flags


def test_a_wire_with_a_real_gauge_and_length_is_still_priced_on_the_bar_basis():
    """REGRESSION GUARD. The estimator-input return must not intercept a bar that CAN be
    priced — a schedule-recognised stud with Ø and length still prices on the bar formula."""
    me = estimate_material({
        "part_number": "1310-02", "normalized_material": "MILD STEEL", "quantity": 1,
        "_bar_recognised": True, "wire_gauge_mm": 8.0, "wire_length_mm": 65.0})
    assert me["cost_method"] == "workbook_bar_formula"
    assert me["stock_form"] == "wire"
    assert me["unit_material_cost_gbp"] and me["unit_material_cost_gbp"] > 0


# ── the guard James asked for: fabricated + wire_forming + (sheet £ | laser) -> fail ─
def test_a_wire_stock_part_cannot_be_lasered():
    """The laser-drop half of the guard, at its source: the stock_form impossibility rules say
    a solid wire is never lasered (nor sheet-folded/punched). Recognition sets stock_form
    'wire'; this is what then strikes the laser row in route_compiler."""
    assert stock_form_rules.is_impossible_operation("laser_cutting", "wire", "MILD STEEL")
    assert stock_form_rules.is_impossible_operation("laser", "wire", "MILD STEEL")
    assert stock_form_rules.is_impossible_operation("folding", "wire", "MILD STEEL")
    # and the ops a wire legitimately keeps are NOT impossible
    assert not stock_form_rules.is_impossible_operation("welding", "wire", "MILD STEEL")
    assert not stock_form_rules.is_impossible_operation("robomac", "wire", "MILD STEEL")


def test_the_material_half_of_the_guard_no_sheet_pounds_on_a_wire():
    """A fabricated wire_forming part must not carry a Sheet-Steel-basis £: its material_estimate
    is wire stock, and unpriced (estimator input) rather than a sheet blank cost."""
    me = estimate_material({
        "part_number": "11762-17-04M", "normalized_material": "MILD STEEL", "quantity": 20,
        "_bar_recognised": True})
    assert me["stock_form"] == "wire"
    assert me["cost_method"] != "sheet_metal" and "sheet" not in me["cost_method"]
    assert me["unit_material_cost_gbp"] is None
