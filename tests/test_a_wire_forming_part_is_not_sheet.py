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

import pytest

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


# ── material: no trusted length -> INDICATIVE wire price off a short assumed length ──
# Policy (James): never a blank. A wire with no schedule/CL length is NOT left at £0 and NOT
# priced as sheet off the PDF outline (5496/6364mm); it carries an INDICATIVE figure from a
# short assumed developed length x Ø x £1,600/t, flagged, that Tim overwrites when measured.
def test_a_u_wire_with_gauge_and_no_length_is_priced_indicative():
    """03M U-wire, Ø8, no length -> ~£0.26 (0.4m band), keyed on surviving mi.stock_form."""
    me = estimate_material({
        "part_number": "11762-17-03M",
        "description": "U WIRE",
        "normalized_material": "MILD STEEL",
        "quantity": 1,
        "manufacturing_interpretation": {"stock_form": "wire", "wire_gauge_mm": 8.0},
    })
    assert me["cost_method"] == "wire_tonne_rate_assumed_length"
    assert 0.20 <= me["unit_material_cost_gbp"] <= 0.32   # ~£0.26
    assert me["wire_gauge_mm"] == 8.0
    assert me["thickness_mm"] is None, "the diameter must never sit in the thickness field"
    assert me.get("stock_estimate", {}).get("length_assumed") is True


def test_a_wire_stand_with_gauge_and_no_length_is_priced_indicative():
    """04M WIRE STAND, Ø8, no length -> ~£0.59 (0.9m band)."""
    me = estimate_material({
        "part_number": "11762-17-04M",
        "description": "WIRE STAND",
        "normalized_material": "MILD STEEL",
        "quantity": 1,
        "manufacturing_interpretation": {"stock_form": "wire", "wire_gauge_mm": 8.0},
    })
    assert me["cost_method"] == "wire_tonne_rate_assumed_length"
    assert 0.45 <= me["unit_material_cost_gbp"] <= 0.75   # ~£0.59


def test_the_price_fires_on_surviving_stock_form_when_the_flag_is_lost():
    """THE LIVE MISS ON 11762-17: _bar_recognised did not survive to estimate_material, so the
    guard keys on manufacturing_interpretation.stock_form 'wire' (which did — it dropped the
    laser). A wire with no _bar_recognised is still priced here, not on the sheet/default card."""
    me = estimate_material({
        "part_number": "11762-17-03M", "description": "U WIRE",
        "normalized_material": "MILD STEEL", "quantity": 20,
        "manufacturing_interpretation": {"stock_form": "wire", "wire_gauge_mm": 8.0}})
    assert me["stock_form"] == "wire"
    assert me["cost_method"] == "wire_tonne_rate_assumed_length"
    assert me["unit_material_cost_gbp"] and me["unit_material_cost_gbp"] > 0
    assert "config_default_material_rates" not in str(me.get("price_source") or "")


def test_a_wire_named_part_that_trips_section_candidate_is_still_priced_here():
    """THE BUG THAT KEPT £45 ALIVE. _is_section_or_wire_candidate fires on the word WIRE, so the
    old `and not _is_section_or_wire_candidate` conjunct skipped 03M/04M into the default card.
    The guard now excludes only a REAL a×b×t tube; a wire with no such profile is priced here."""
    me = estimate_material({
        "part_number": "11762-17-04M", "description": "WIRE STAND",
        "normalized_material": "MILD STEEL", "quantity": 20,
        "manufacturing_interpretation": {"stock_form": "wire"}})
    assert me["cost_method"] == "wire_tonne_rate_assumed_length", "must not fall to the card"
    assert me["unit_material_cost_gbp"] and me["unit_material_cost_gbp"] > 0


def test_the_flag_says_the_length_was_assumed():
    part = {"part_number": "11762-17-03M", "description": "U WIRE",
            "normalized_material": "MILD STEEL", "quantity": 20, "_bar_recognised": True,
            "wire_gauge_mm": 8.0}
    estimate_material(part)
    flags = " ".join(part.get("review_flags") or [])
    assert "ASSUMED" in flags and "INDICATIVE" in flags
    assert "PDF outline is not a length" in flags


def test_the_pdf_outline_is_never_used_as_the_length():
    """The whole point: a 5496mm PDF cut path must not become 5.5m of priced wire (~£3.6).
    With no trusted wire_length_mm the price comes off the SHORT assumed band, not cut_length."""
    me = estimate_material({
        "part_number": "11762-17-03M", "description": "U WIRE",
        "normalized_material": "MILD STEEL", "quantity": 20, "_bar_recognised": True,
        "wire_gauge_mm": 8.0, "cut_length_mm": 5496.0,
        "normalized_geometry": {"developed_length_mm": None}})
    assert me["wire_length_mm"] <= 1500.0, "the inflated outline must never become the length"
    assert me["unit_material_cost_gbp"] < 1.0, "5.5m of Ø8 would be ~£3.6; the band keeps it low"


def test_an_a_by_b_by_t_tube_is_not_priced_as_assumed_wire():
    """A genuine hollow a×b×t profile is a TUBE — even with a 'wire' label poisoning it, the
    assumed-wire method must not swallow it; it keeps the linear-stock/tube path."""
    me = estimate_material({
        "part_number": "TUBE-01",
        "normalized_material": "MILD STEEL",
        "quantity": 1,
        "description": "40x40x3 SHS 500 LONG",
        "manufacturing_interpretation": {"stock_form": "wire"},  # poisoned label
        "section_stock": {"a": 40.0, "b": 40.0, "t": 3.0},
        "wire_length_mm": 500.0,
    })
    assert me.get("cost_method") != "wire_tonne_rate_assumed_length"


def test_a_wire_with_a_real_gauge_and_length_is_still_priced_on_the_bar_basis():
    """REGRESSION GUARD. A schedule-recognised stud with Ø and a TRUSTED length still prices on
    the bar formula (the branch above this one), not the assumed-length band."""
    me = estimate_material({
        "part_number": "1310-02", "normalized_material": "MILD STEEL", "quantity": 1,
        "_bar_recognised": True, "wire_gauge_mm": 8.0, "wire_length_mm": 65.0})
    assert me["cost_method"] == "workbook_bar_formula"
    assert me["stock_form"] == "wire"
    assert me["unit_material_cost_gbp"] and me["unit_material_cost_gbp"] > 0


def test_a_wire_stock_part_cannot_be_lasered():
    """The laser-drop half: the stock_form impossibility rules say a solid wire is never lasered
    (nor sheet-folded/punched); that is what strikes the laser row in route_compiler."""
    assert stock_form_rules.is_impossible_operation("laser_cutting", "wire", "MILD STEEL")
    assert stock_form_rules.is_impossible_operation("folding", "wire", "MILD STEEL")
    assert not stock_form_rules.is_impossible_operation("welding", "wire", "MILD STEEL")
    assert not stock_form_rules.is_impossible_operation("robomac", "wire", "MILD STEEL")
