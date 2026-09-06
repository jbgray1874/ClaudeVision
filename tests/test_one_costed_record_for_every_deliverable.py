"""One CostedJob after the Excel calculation. Every writer reads it. Nothing else.

The 7332-01 run of 6 September 17:17 shipped one estimate with several stories in it:

  - the e-mail banner said "2 lines priced from a market indication, £16.03"; its own §3
    footer said £16.63; the AI Explanation tab said "No line rests on an AI market
    indication". All three were looking at the same two lines — the plating (£15.83, a
    config £/kg) and the felt pad (£0.20 × 4, a config commodity) — and the two that called
    them a market lookup were reading the word INDICATIVE as if it meant AI.
  - the leg 7332-01-002 read "not named" for its price source on three tabs, "tube_bending,
    tubebend, folding, fold" for its operations on a fourth (the department inverted through
    every alias, including the fold the route had ruled out), and 9,106 mm — the page-summed
    cut path — as its cut length, against the 1,397 mm it was actually priced on.
  - the acrylic lens was £2.02 on the provenance tab and £2.82 on the sheet.
  - PACKAGING, DELIVERY and the plating line all read "MILD STEEL".
  - the breakdown carried a "Powder / scrap / other workbook material" row under a heading
    that said NOTHING COATED — the engine's net-part figures held against the sheet's nest.

The fix James approved is not another wording patch. It is one record — costed_facts.costed_job
— built after the read-back from the sheet's own calculated rows, that every deliverable reads
for its money, its firmness, its gaps, its operations and its lengths. This file proves the
record says the right things about a summary shaped like that run, and that each writer now
takes them from it. Nothing here re-costs anything: the money is the sheet's.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import costed_facts as cf  # noqa: E402


# ── the run, as the 171743 workbook recorded it ─────────────────────────────

def _part(pn, desc, qty, mat, thk, unit, ext, **extra):
    me = {"cost_per_part_gbp": unit, "unit_material_cost_gbp": unit,
          "extended_material_cost_gbp": ext}
    me.update(extra.pop("me", {}))
    p = {"part_number": pn, "description": desc, "quantity": qty,
         "normalized_material": mat, "normalized_thickness_mm": thk,
         "unit_cost_gbp": unit, "material_estimate": me}
    p.update(extra)
    return p


def seventy_three_thirty_two() -> dict:
    parts = [
        _part("7332-01-001", "BASE", 1, "MILD STEEL", 5.0, 4.42, 4.42,
              geometry_source="dxf_flat_pattern",
              geometry_rollup={"estimated_cut_length_mm": 1564},
              me={"blank_length_mm": 453, "blank_width_mm": 300},
              operations=["laser_cutting", "welding", "dress_welds", "handling"]),
        _part("7332-01-002", "LEG", 2, "MILD STEEL", 1.2, 5.86, 11.71,
              geometry_source="pdf",
              geometry_rollup={"estimated_cut_length_mm": 9106},
              section_stock={"a": 15.88, "b": 15.88, "t": 1.2, "length_mm": 1397.0,
                             "source": "llm_full_extract"},
              me={"cost_method": "section_stock_config_rate", "rate_gbp_per_kg": 2.05,
                  "stock_estimate": {"stock_form": "tube", "section_length_mm": 1397.0,
                                     "section_length_source": "section_stock",
                                     "section_length_reader": "llm_full_extract",
                                     "section_length_indicative": False}},
              operations=["tubebend", "welding", "handling"]),
        _part("7332-01-003", "STRAP", 2, "MILD STEEL", 2.5, 0.07, 0.14,
              geometry_source="dxf_flat_pattern",
              me={"blank_length_mm": 441, "blank_width_mm": 10},
              operations=["laser_cutting", "welding"]),
        _part("7332-01-004", "CAP", 2, "MILD STEEL", 2.5, 0.0, 0.01,
              geometry_source="dxf_flat_pattern",
              me={"blank_length_mm": 15.88, "blank_width_mm": 15.88},
              operations=["laser_cutting", "welding"]),
        _part("7332-01-005", "CHANNEL", 1, "MILD STEEL", 1.5, 0.10, 0.10,
              geometry_source="dxf_flat_pattern",
              me={"blank_length_mm": 441, "blank_width_mm": 24.7},
              operations=["laser_cutting", "folding", "welding"]),
        _part("7332-01-007", "LENS; 420x297mm", 2, "ACRYLIC", 2.0, 1.01, 2.02,
              geometry_source="dxf_flat_pattern", normalized_finish="POLISHED EDGES",
              me={"cost_method": "sheet_rate_live_udef",
                  "blank_length_mm": 420, "blank_width_mm": 297},
              operations=["laser_cutting", "diamond_polish", "manual_labour_acrylic",
                          "assembly"]),
        _part("7332-01-008", "BACK PANEL", 1, "MILD STEEL", 0.9, 0.73, 0.73,
              geometry_source="dxf_flat_pattern", normalized_finish="PLATED",
              me={"blank_length_mm": 420, "blank_width_mm": 297},
              operations=["laser_cutting", "powder_coating", "assembly"]),
        _part("7332-01-101", "FRAME WELDMENT", 1, "MILD STEEL", 1.2, 0.0, 0.0,
              normalized_finish="PLATED", canonical_kind="assembly",
              _canonical_kind="assembly",
              me={"cost_method": "weldment_parent_material_in_children"},
              operations=["welding", "dress_welds", "assembly"]),
        _part("PACKAGING", "Packaging (box / pallet — per-unit share, estimator to price)",
              1, "MILD STEEL", None, 0.0, 0.0, _commercial_placeholder=True,
              source="commercial_placeholder", cost_source="estimator_to_price",
              review_flags=["Commercial line — not derivable from drawings; estimator to "
                            "price (order-level)"]),
        _part("DELIVERY", "Delivery (per-unit share of order haulage — estimator to price)",
              1, "MILD STEEL", None, 0.0, 0.0, _commercial_placeholder=True,
              source="commercial_placeholder", cost_source="estimator_to_price",
              review_flags=["Commercial line — not derivable from drawings; estimator to "
                            "price (order-level)"]),
        _part("7332-01-101-PLATE",
              "7332-01-101 plating — INDICATIVE zinc/passivate, verify against plater — "
              "plated members: 7332-01-008 (excluded, own detail differs: 7332-01-001, "
              "7332-01-002, 7332-01-003, 7332-01-004, 7332-01-005)",
              1, "MILD STEEL", None, 15.83, 15.83, _plating_placeholder=True,
              _plating_members=["7332-01-001", "7332-01-002", "7332-01-003", "7332-01-004",
                                "7332-01-005", "7332-01-008"],
              _plating_members_costed=["7332-01-008"],
              _plating_members_deferred=["7332-01-001", "7332-01-002", "7332-01-003",
                                         "7332-01-004", "7332-01-005"],
              me={"cost_method": "subcontract_plating_indicative"},
              review_flags=["0.9 kg plated × £2.50/kg, plater vat minimum £95 spread over "
                            "6 off — INDICATIVE"]),
        _part("P/P", "BLACK FELT PAD, SELF-ADHESIVE, 25mm DIA", 4, "", None, 0.20, 0.80,
              page_roles=["bought_in"],
              me={"cost_method": "standard_commodity_provisional"},
              review_flags=["Provisional standard-commodity price — confirm against a "
                            "supplier quote"]),
    ]

    def node(pn, kind, qty, parents=()):
        return {"part_number": pn, "kind": kind, "qty_per_unit": qty,
                "parents": list(parents)}
    nodes = [
        node("7332-01-001", "leaf", 1, ["7332-01-101"]),
        node("7332-01-002", "leaf", 2, ["7332-01-101"]),
        node("7332-01-003", "leaf", 2, ["7332-01-101"]),
        node("7332-01-004", "leaf", 2, ["7332-01-101"]),
        node("7332-01-005", "leaf", 1, ["7332-01-101"]),
        node("7332-01-007", "leaf", 2, ["7332-01-GA"]),
        node("7332-01-008", "leaf", 1, ["7332-01-GA"]),
        node("7332-01-101", "assembly", 1, ["7332-01-GA"]),
        node("7332-01-101-PLATE", "bought_in", 1, ["7332-01-101"]),
        node("7332-01-GA", "assembly", 1),
        node("DELIVERY", "bought_in", 1),
        node("P/P", "bought_in", 4, ["7332-01-GA"]),
        node("PACKAGING", "bought_in", 1),
    ]

    def dec(did, op, status, target, scope, qty, participants, source, reason):
        return {"decision_id": did, "operation": op, "status": status, "target_id": target,
                "scope": scope, "qty_per_unit": qty, "participants": participants,
                "source": source, "reason": reason}
    _note = "textual_operations on existing part record"
    decisions = [
        dec("decision:8381d114d1b7", "laser_cutting", "required", "7332-01-001", "part", 1,
            ["7332-01-001"], "inference", _note),
        dec("decision:3ecf15719067", "laser_cutting", "required", "7332-01-003", "part", 2,
            ["7332-01-003"], "drawing_notes", _note),
        dec("decision:73799e4e493b", "laser_cutting", "required", "7332-01-004", "part", 2,
            ["7332-01-004"], "drawing_notes", _note),
        dec("decision:4f29793d3421", "laser_cutting", "required", "7332-01-005", "part", 1,
            ["7332-01-005"], "drawing_notes", _note),
        dec("decision:f99249261b29", "laser_cutting", "required", "7332-01-007", "part", 2,
            ["7332-01-007"], "drawing_notes", _note),
        dec("decision:9e7bb91bdc0f", "laser_cutting", "required", "7332-01-008", "part", 1,
            ["7332-01-008"], "drawing_notes", _note),
        dec("decision:1648f0570c0a", "welding", "required", "7332-01-101", "assembly", 1,
            ["7332-01-101"], "llm_full_extract", "FRAME WELDMENT"),
        dec("decision:3099a679f0de", "dress_welds", "required", "7332-01-101", "assembly", 1,
            ["7332-01-101"], "llm_full_extract", "FRAME WELDMENT"),
        dec("decision:5c548bd5dda1", "folding", "required", "7332-01-005", "part", 1,
            ["7332-01-005"], "drawing_notes", _note),
        dec("decision:874b5e7c83c1", "powder_coating", "not_applicable", "7332-01-008", "part",
            None, ["7332-01-008"], "drawing_deterministic",
            "the drawing states 'PLATED', which is plate, not powder coating"),
        dec("decision:6c0fb48090f7", "powder_coating", "not_applicable", "7332-01-101",
            "assembly", None, ["7332-01-101"], "drawing_deterministic",
            "the drawing states 'PLATED', which is plate, not powder coating"),
        dec("decision:41cff67679b3", "assembly", "required", "7332-01-GA", "assembly", 1,
            ["7332-01-007", "7332-01-008", "7332-01-101", "P/P"], "bom_tree",
            "the top assembly is packed whatever joined it"),
        dec("decision:4fc5c5b77efb", "diamond_polish", "required", "7332-01-007", "part", 2,
            ["7332-01-007"], "acrylic_route_rule", "inferred_operations"),
        dec("decision:df0bdab42586", "folding", "not_applicable", "7332-01-002", "part", None,
            ["7332-01-002"], "drawing_deterministic",
            "folding is not physically possible on stock form 'tube'"),
        dec("decision:9f4b11667dfe", "laser_cutting", "not_applicable", "7332-01-002", "part",
            None, ["7332-01-002"], "drawing_deterministic",
            "section stock is cut by the tube process, not sheet profiling"),
        dec("decision:bd368963bc63", "manual_labour_acrylic", "required", "7332-01-007",
            "part", 2, ["7332-01-007"], "acrylic_route_rule", "inferred_operations"),
        dec("decision:9e3d96e71416", "tubebend", "required", "7332-01-002", "part", 2,
            ["7332-01-002"], "drawing_deterministic",
            "the drawing states a bend and the stock form is tube — bent on the tube bender"),
    ]

    def lab(row, op, dept, parts_, qty, setup, hours, rate, value, basis, ops, dids):
        return ({"workbook_row": row, "operation": op, "department": dept,
                 "description": f"{op} ({', '.join(parts_)})", "qty_per_unit": qty,
                 "setup_minutes": setup, "batch_hours": hours,
                 "dept_rate_gbp_per_hour": rate, "total_value_gbp": value},
                {"workbook_row": row, "wb_operation": op, "engine_operations": ops,
                 "part_numbers": parts_, "decision_ids": dids, "rate_basis": basis,
                 "qty_per_unit": qty})
    labour = [
        lab(96, "Laser (Acrylic)", "LASA", ["7332-01-007"], 2, 10, 0.214286, 41.2119, 1.47,
            "historical", ["laser_cutting"], ["decision:f99249261b29"]),
        lab(97, "Laser (Metal)", "LASM", ["7332-01-001"], 1, 10, 0.266446, 68.1868, 3.03,
            "template_calculated", ["laser_cutting"], ["decision:8381d114d1b7"]),
        lab(98, "Laser (Metal)", "LASM", ["7332-01-003", "7332-01-004"], 4, 10, 0.221061,
            68.1868, 2.51, "template_calculated", ["laser_cutting"],
            ["decision:3ecf15719067", "decision:73799e4e493b"]),
        lab(99, "Laser (Metal)", "LASM", ["7332-01-005"], 1, 10, 0.188771, 68.1868, 2.15,
            "template_calculated", ["laser_cutting"], ["decision:4f29793d3421"]),
        lab(100, "Laser (Metal)", "LASM", ["7332-01-008"], 1, 10, 0.197203, 68.1868, 2.24,
            "template_calculated", ["laser_cutting"], ["decision:9e7bb91bdc0f"]),
        lab(101, "Weld (CO2)", "WELD", ["7332-01-101"], 1, 30, 0.706897, 41.7716, 4.92,
            "historical", ["welding"], ["decision:1648f0570c0a"]),
        lab(102, "Dress Welds", "DRES", ["7332-01-101"], 1, 30, 0.6, 28.6816, 2.87,
            "unmeasured_default", ["dress_welds"], ["decision:3099a679f0de"]),
        lab(103, "Tubebend", "TBEN", ["7332-01-002"], 2, 45, 1.15, 32.84, 6.29,
            "unmeasured_default", ["tubebend"], ["decision:9e3d96e71416"]),
        lab(104, "Fold", "FOLD", ["7332-01-005"], 1, 30, 0.56, 40.4678, 3.78,
            "engine_derived", ["folding"], ["decision:5c548bd5dda1"]),
        lab(105, "Manual labour (Acrylic)", "MANA", ["7332-01-007"], 2, 15, 0.31, 25.4257,
            1.31, "engine_derived", ["manual_labour_acrylic"], ["decision:bd368963bc63"]),
        lab(106, "Diamond Polish", "DPOL", ["7332-01-007"], 2, 10, 0.211109, 31.6024, 1.11,
            "engine_derived", ["diamond_polish"], ["decision:4fc5c5b77efb"]),
        lab(107, "Assemble/pack (Acrylic)", "PACP",
            ["7332-01-007", "7332-01-008", "7332-01-101", "P/P"], 1, 15, 0.45, 25.4257, 1.91,
            "size_banded", ["assembly"], ["decision:41cff67679b3"]),
    ]

    def bom(row, code, desc, unit, qty, total, pointer=False):
        return {"block": "bom", "workbook_row": row, "part_code": code,
                "description": desc + (" — costed in Sheet Steel below" if pointer else ""),
                "supplier": "", "unit_price_gbp": unit, "qty_per_unit": qty,
                "scrap": 0.04, "total_value_gbp": total}

    def steel(row, desc, qty, length, width, gauge, nest, total, block="steel"):
        return {"block": block, "workbook_row": row, "description": desc,
                "qty_per_unit": qty, "length_mm": length, "width_mm": width,
                "gauge": gauge, "sheet_length_mm": 2500, "sheet_width_mm": 1250,
                "qty_per_sheet": nest, "scrap": 0.04, "total_value_gbp": total}
    material_rows = [
        bom(10, "7332-01-001", "7332-01-001  BASE", None, 1, None, pointer=True),
        bom(11, "7332-01-003", "7332-01-003  STRAP", None, 2, None, pointer=True),
        bom(12, "7332-01-004", "7332-01-004  CAP", None, 2, None, pointer=True),
        bom(13, "7332-01-005", "7332-01-005  CHANNEL", None, 1, None, pointer=True),
        bom(14, "7332-01-008", "7332-01-008  BACK PANEL", None, 1, None, pointer=True),
        {"block": "bom", "workbook_row": 15, "part_code": "7332-01-007",
         "description": "7332-01-007  LENS; 420x297mm — costed in Other Sheet Material below",
         "supplier": "", "unit_price_gbp": None, "qty_per_unit": 2, "scrap": 0.04,
         "total_value_gbp": None},
        bom(16, "7332-01-002", "7332-01-002  LEG", 5.86, 2, 11.72),
        bom(17, "PACKAGING", "PACKAGING  Packaging (box / pallet — per-unit share, "
                             "estimator to price)", 0, 1, 0),
        bom(18, "DELIVERY", "DELIVERY  Delivery (per-unit share of order haulage — "
                            "estimator to price)", 0, 1, 0),
        bom(19, "7332-01-101-PLATE", "7332-01-101-PLATE  7332-01-101 plating — INDICATIVE "
                                     "zinc/passivate, verify against plater", 15.83, 1, 15.83),
        bom(20, "P/P", "P/P  BLACK FELT PAD, SELF-ADHESIVE, 25mm DIA", 0.2, 4, 0.80),
        steel(63, "7332-01-001  BASE", 1, 453, 300, 5, 15, 7.65),
        steel(64, "7332-01-003  STRAP", 2, 441, 10, 2.5, 290, 0.42),
        steel(65, "7332-01-004  CAP", 2, 15.88, 15.88, 2.5, 3105, 0.04),
        steel(66, "7332-01-005  CHANNEL", 1, 441, 24.7, 1.5, 165, 0.22),
        steel(67, "7332-01-008  BACK PANEL", 1, 420, 297, 0.9, 15, 1.38),
        steel(82, "7332-01-007  LENS; 420x297mm", 2, 420, 297, 2, 50, 2.82,
              block="other_sheet"),
    ]

    writeup = []
    for p in parts:
        w = {k: p[k] for k in ("part_number", "description", "normalized_material",
                               "normalized_thickness_mm") if k in p}
        for k in ("normalized_finish", "geometry_source", "geometry_rollup", "operations",
                  "section_stock", "canonical_kind"):
            if k in p:
                w[k] = p[k]
        writeup.append(w)

    return {
        "job_output_stem": "7332-01",
        "drawing_number": "7332-01",
        "estimate_summary": {
            "estimate_workbook_inputs": {"assumed_job_quantity": 6},
            "workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": 80.09},
            "part_estimates": [dict(p) for p in parts],
            "canonical_part_estimates": [dict(p) for p in parts],
            "canonical_route_shadow": {"nodes": nodes, "decisions": decisions},
            "workbook_labour": {"schema": "workbook_labour_rows.v3", "mode": "canonical",
                                "rows": [acc for _, acc in labour]},
        },
        "manufacturing_writeup": {"parts": writeup},
        "final_estimate": {
            "schema": "final_estimate.v2",
            "totals": {"material_gbp": 40.89, "labour_gbp": 33.59, "unit_gbp": 80.09},
            "labour_rows": [calc for calc, _ in labour],
            "material_rows": material_rows,
        },
        "invariants": {"may_quote_firm": False, "violations": []},
    }


def _line(job, pn):
    return next(l for l in job["lines"] if l["part_number"] == pn)


# ── the gaps, once ────────────────────────────────────────────────────────────

def test_the_two_commercial_lines_are_the_only_unpriced_ones():
    job = cf.costed_job(seventy_three_thirty_two())
    assert job["gaps"]["unpriced"] == ["PACKAGING", "DELIVERY"]
    assert job["gaps"]["unpriced_owners"] == {"PACKAGING": "estimator", "DELIVERY": "estimator"}


def test_the_plating_and_the_felt_pad_are_house_rates_not_market_indications():
    """The e-mail called these 'AI market indications'. They are SDI's own configured
    rates, stamped INDICATIVE because a person verifies them — a different action."""
    job = cf.costed_job(seventy_three_thirty_two())
    assert job["gaps"]["indicative_house"] == ["7332-01-101-PLATE", "P/P"]
    assert job["gaps"]["indicative_market"] == []
    assert job["gaps"]["indicative_market_gbp"] == 0.0


def test_the_indicative_money_is_one_number_and_it_is_the_extended_one():
    """£16.03 (unit prices summed) on the banner against £16.63 (price × qty) in §3."""
    job = cf.costed_job(seventy_three_thirty_two())
    assert job["gaps"]["indicative_house_gbp"] == 16.63


# ── the leg ───────────────────────────────────────────────────────────────────

def test_the_leg_names_its_rate_and_its_length_and_only_the_operation_it_was_bent_on():
    leg = _line(cf.costed_job(seventy_three_thirty_two()), "7332-01-002")
    # A house MATERIAL rate, like the sheet's own £/tonne: named, firm, not a hold to verify.
    assert leg["price_origin"]["firmness"] == cf.FIRM
    assert "section-stock trade rate" in leg["price_origin"]["label"]
    assert "£2.05/kg" in leg["price_origin"]["label"]
    assert leg["charged_unit_gbp"] == 5.86 and leg["charged_ext_gbp"] == 11.72
    assert leg["length"] == {"mm": 1397.0, "source": "section_stock",
                             "reader": "llm_full_extract", "indicative": False}
    assert leg["operations"] == ["tubebend"], (
        "the department inverted to every alias, including the fold the route ruled out")
    assert leg["section_profile"] == {"a": 15.88, "b": 15.88, "t": 1.2}


# ── the money is the sheet's ──────────────────────────────────────────────────

def test_the_acrylic_lens_is_charged_at_the_sheets_nest_figure():
    lens = _line(cf.costed_job(seventy_three_thirty_two()), "7332-01-007")
    assert lens["charged_ext_gbp"] == 2.82 and lens["charged_unit_gbp"] == 1.41
    assert lens["engine_ext_gbp"] == 2.02, "the engine's figure is kept, as 'not charged'"
    assert lens["block"] == "other_sheet" and lens["sheet_row"] == 82
    assert lens["price_origin"]["firmness"] == cf.FIRM
    assert "Other Sheet Material block — Estimate!82" in lens["price_origin"]["label"]


def test_a_nested_part_the_engine_rounds_to_nothing_is_not_a_zero_cost_review():
    cap = _line(cf.costed_job(seventy_three_thirty_two()), "7332-01-004")
    assert cap["charged_ext_gbp"] == 0.04 and cap["charged_unit_gbp"] == 0.02
    assert cap["price_origin"]["firmness"] == cf.FIRM
    assert cap["engine_unit_gbp"] == 0.0


def test_the_run_totals_are_the_sheets():
    job = cf.costed_job(seventy_three_thirty_two())
    assert job["run"] == {"order_qty": 6, "unit_gbp": 80.09, "material_gbp": 40.89,
                          "labour_gbp": 33.59, "totals_source": "excel_calculated",
                          "code_version": ""}


def test_the_charged_lines_add_back_to_the_sheet_with_no_powder_bucket():
    """The engine's net-part figures fell £5.13 short of the sheet's nest total and the
    shortfall was labelled 'Powder / scrap' under NOTHING COATED. Built from the charged
    figures the breakdown is the sheet's own money and the residual is a penny of rounding."""
    rows = dict(cf.charged_breakdown_by_material(seventy_three_thirty_two()))
    assert not any("powder" in k.lower() for k in rows), rows
    assert abs(sum(rows.values()) - 40.89) < 0.005
    assert rows["MILD STEEL"] == round(7.65 + 0.42 + 0.04 + 0.22 + 1.38 + 11.72, 2)
    assert rows["ACRYLIC"] == 2.82
    assert rows["Subcontract plating"] == 15.83
    assert rows["Bought-in"] == 0.80
    assert rows.get(cf.RESIDUAL_LABEL, 0.0) < 0.02


# ── what a line is made of ────────────────────────────────────────────────────

def test_a_commercial_line_and_a_service_are_not_made_of_mild_steel():
    job = cf.costed_job(seventy_three_thirty_two())
    assert _line(job, "PACKAGING")["material_label"] == "— (commercial line)"
    assert _line(job, "DELIVERY")["kind"] == "commercial"
    assert _line(job, "7332-01-101-PLATE")["material_label"] == "— (subcontract service)"
    assert _line(job, "P/P")["material_label"] == "— (bought-in)"
    assert _line(job, "7332-01-001")["material_label"] == "MILD STEEL"


def test_the_assembly_parent_is_nil_by_design_not_a_gap():
    frame = _line(cf.costed_job(seventy_three_thirty_two()), "7332-01-101")
    assert frame["kind"] == "assembly"
    assert frame["price_origin"]["firmness"] == cf.NIL
    assert frame["price_origin"]["owner"] == "nobody"
    assert frame["operations"] == ["welding", "dress_welds", "assembly"]


# ── plating as a field ────────────────────────────────────────────────────────

def test_plating_is_a_field_with_its_members_and_its_exclusions():
    job = cf.costed_job(seventy_three_thirty_two())
    assert job["plating"]["charged"] is True
    assert job["plating"]["line"] == "7332-01-101-PLATE"
    assert job["plating"]["parent"] == "7332-01-101"
    assert job["plating"]["members"] == ["7332-01-008"]
    assert job["plating"]["excluded"] == ["7332-01-001", "7332-01-002", "7332-01-003",
                                          "7332-01-004", "7332-01-005"]
    assert job["plating"]["ext_gbp"] == 15.83
    assert job["finishes_charged"] == "Diamond polished and plated"


def test_packaging_is_not_charged_on_this_run():
    assert cf.packaging_is_charged(seventy_three_thirty_two()) is False
    job = seventy_three_thirty_two()
    for r in job["final_estimate"]["material_rows"]:
        if r.get("part_code") == "PACKAGING":
            r["unit_price_gbp"] = r["total_value_gbp"] = 4.50
    assert cf.packaging_is_charged(job) is True


# ── release ───────────────────────────────────────────────────────────────────

def test_the_release_is_provisional_and_says_why():
    job = cf.costed_job(seventy_three_thirty_two())
    assert job["release"]["status"] == "provisional"
    reasons = " ".join(job["release"]["reasons"])
    assert "PACKAGING, DELIVERY" in reasons
    assert "market" not in reasons
    kinds = [d["kind"] for d in job["decisions_required"]]
    assert kinds.count("missing_price") == 2
    assert "manufacturing_decision" in kinds       # the plated member list, the leg's length
    assert kinds.count("indicative_rate") == 2
    assert "market_figure" not in kinds


def test_the_record_is_pure():
    a = cf.costed_job(seventy_three_thirty_two())
    b = cf.costed_job(seventy_three_thirty_two())
    assert a == b


def test_a_line_can_be_found_by_number():
    line = cf.costed_line(seventy_three_thirty_two(), "p/p")
    assert line and line["qty_per_unit"] == 4 and line["charged_ext_gbp"] == 0.80


# ── every writer reads it ─────────────────────────────────────────────────────

def test_the_provenance_tab_charges_the_sheets_money_and_names_the_leg():
    import estimation_report as er
    rows = {r["part_number"]: r for r in er.build_provenance(seventy_three_thirty_two())}
    lens = rows["7332-01-007"]
    assert lens["unit_cost"] == 1.41 and lens["extended_cost"] == 2.82
    assert "2.02" in lens["rate_basis"] and "not charged" in lens["rate_basis"]
    leg = rows["7332-01-002"]
    assert leg["operations"] == "tubebend"
    assert leg["cut_length_mm"] == 1397.0
    assert "1,397 mm" in leg["geometry_source"] and "llm_full_extract" in leg["geometry_source"]
    assert "section-stock trade rate" in leg["rate_basis"]
    cap = rows["7332-01-004"]
    assert not any("Zero cost" in f for f in cap["flags"]), cap["flags"]
    assert cap["unpriced_reason"] is None
    assert rows["PACKAGING"]["unpriced_reason"]["owner"] == "estimator"
    counts = er.reading_and_pricing_counts(list(rows.values()))
    assert counts["pending"] == 2


def test_the_breakdown_the_provenance_tab_prints_is_the_charged_one():
    import job_decision_report as jdr
    rows = dict(jdr.material_breakdown(seventy_three_thirty_two()))
    assert jdr.POWDER_SCRAP_LABEL not in rows, rows
    assert abs(sum(rows.values()) - 40.89) < 0.005


def test_the_finish_check_knows_plating_is_charged():
    import invariants as inv
    out = inv.check_a_stated_finish_is_costed(seventy_three_thirty_two())
    assert not [v for v in out if v["code"] == "stated_finish_not_costed"], out


def test_the_operation_check_reads_the_hierarchy():
    """Welding is charged on 7332-01-101, the weldment; its members carry the word too and
    were reported as 'named but not priced'. A row on an ancestor covers its members."""
    import invariants as inv
    out = inv.check_no_unpriced_operations_named(seventy_three_thirty_two())
    assert out == [], out


def test_the_quote_says_what_is_not_in_it_and_that_it_is_a_draft():
    import client_quote_html as q
    html = q.build_quote_html(seventy_three_thirty_two(), job_stem="7332-01")
    assert "Boxed for transport" not in html
    assert "Individual packing for transport" not in html
    assert "Packaging and delivery not included" in html
    assert "DRAFT" in html and "not for issue" in html
    assert "Valid for" not in html and "Valid 30 days" not in html
    assert "Diamond polished and plated" in html


def test_the_quote_keeps_its_packing_line_when_packaging_is_charged():
    import client_quote_html as q
    job = seventy_three_thirty_two()
    for r in job["final_estimate"]["material_rows"]:
        if r.get("part_code") in ("PACKAGING", "DELIVERY"):
            r["unit_price_gbp"] = r["total_value_gbp"] = 4.50
    for p in job["estimate_summary"]["canonical_part_estimates"]:
        if p["part_number"] in ("PACKAGING", "DELIVERY"):
            p["unit_cost_gbp"] = 4.50
            p["material_estimate"]["unit_material_cost_gbp"] = 4.50
    html = q.build_quote_html(job, job_stem="7332-01")
    assert "Boxed for transport" in html
    assert "Packaging and delivery not included" not in html


def test_the_ai_price_provenance_rows_name_the_leg_and_do_not_call_packaging_steel():
    import wb_populate as W
    rows = {r[0]: r for r in W._price_provenance_rows(seventy_three_thirty_two())}
    assert "section-stock trade rate" in rows["7332-01-002"][3]
    assert rows["7332-01-101-PLATE"][3].startswith("SDI subcontract plating rate")
    mats = {r[0]: r for r in W._material_detail_rows(seventy_three_thirty_two())}
    assert mats["PACKAGING"][2] == "— (commercial line)"
    assert mats["7332-01-101-PLATE"][2] == "— (subcontract service)"
    assert mats["7332-01-001"][2] == "MILD STEEL"
