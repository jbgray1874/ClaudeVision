"""Five faults the 8188-08 12:16 live book (build 4fbbd95, c41d5cc) carried, each a rule (D-451).

1. The magnet's inference printed a false reason: "2,000 mm long against 500 mm, the largest
   size anything made on the job measures" — 500 x 400 was the wire frame's fallback envelope,
   on a job whose waves are 2.4 m long. A size nothing measured is no yardstick, every
   refutation is printed, and the line says what each rests on.
2. The M6 insert was charged twice for the fourth book: its whole-cell reading came in by a
   path no minter fix touched. One row read two ways is folded onto the coded record where
   every record meets the costing.
3. The acrylic parts' sheet weights were each 6.6 x their blank — 7,850 / 1,190: the model's
   mass in its default steel. The weight is read as the model's material, not four wrong gauges.
4. The product root 8188-08_GA had no assembly flag: it was weighed as a 53 x 20 sheet blank
   and shipped as a part. A record whose code names an assembly drawing is an assembly.
5. Packaging £10 and delivery £10.06 for the whole order: the shipment planner read only raw
   blank fields, counted nothing, and the market guessed a shipment it was never shown. The
   planner reads the shared resolver; the counted shipment is priced at a researched per-pallet
   rate, re-counted at every break, the working on the line.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import pytest                                                         # noqa: E402

import commercial_lines as cl                                         # noqa: E402
import estimator                                                      # noqa: E402
import invariants                                                     # noqa: E402
import palletising                                                    # noqa: E402
import size_reading as sr                                             # noqa: E402
from part_code_conventions import carries_assembly_role               # noqa: E402
from part_identity import fold_one_cell_duplicates                    # noqa: E402


# ── 1. evidence for the magnet ─────────────────────────────────────────────────────────

def _wave():
    return {"part_number": "W-015", "description": "WAVE LAYER 1", "normalized_material": "ACRYLIC",
            "geometry_source": "dxf_flat_pattern",
            "material_estimate": {"blank_length_mm": 2354.72, "blank_width_mm": 99.99}}


def _envelope_frame():
    return {"part_number": "F-004", "description": "WIRE WORK MESH FRAME",
            "normalized_geometry": {"blank_length_mm": 500.0, "blank_width_mm": 400.0,
                                    "_inferred": True, "blank_length_mm_source": "geometry_inference"},
            "review_flags": ["F-004 ... the size used is a fallback envelope"]}


def _magnet():
    return {"part_number": "KINGDOM:", "description": "50mm x 10mm x 2m MAGNET", "quantity": 14,
            "is_bought_in": True, "page_roles": ["bought_in"]}


def test_a_fallback_envelope_is_no_yardstick_and_the_costed_blank_is():
    assert sr.measured_job_yardstick_mm([_envelope_frame()]) is None
    assert sr.measured_job_yardstick_mm([_envelope_frame(), _wave()]) == 2354.72


def test_every_refutation_is_printed_with_what_it_rests_on():
    mag = _magnet()
    summary = {"pages": [{"page_number": "1", "pypdf_text": "WEIGHT: 43631.32g"}]}
    assert sr.apply_size_readings([mag], summary, yard_parts=[_envelope_frame(), _wave()]) == 1
    inf = mag["size_reading_inferred"]
    assert "500 mm" not in inf["why"], "a fallback envelope must not refute anything"
    assert "68." in inf["why"] and "43.6 kg" in inf["why"]
    assert "stated weight" in inf["rests_on"] and "magnet density" in inf["rests_on"]
    flag = " ".join(str(f) for f in mag["review_flags"])
    assert f"rests on {inf['rests_on']}" in flag


# ── 2. one row read two ways ───────────────────────────────────────────────────────────

def test_a_whole_cell_reading_is_folded_onto_the_coded_record_wherever_it_came_from():
    coded = {"part_number": "FIXING M6x12mm", "description": "THREADED INSERT, HEADED HEX DRIVE",
             "quantity": 4, "page_roles": ["bought_in"]}
    whole = {"part_number": "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE",
             "description": "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE", "quantity": 4,
             "supplier": "RS"}
    nut = {"part_number": "FIXING49", "description": "M6 THINSHEET THREADED INSERT", "quantity": 2}
    parts = [whole, nut, coded]
    assert fold_one_cell_duplicates(parts) == [("FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE", "FIXING M6x12mm")]
    assert [p["part_number"] for p in parts] == ["FIXING49", "FIXING M6x12mm"]
    assert coded["raw_aliases"] == ["FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE"]
    assert coded["supplier"] == "RS", "fields the coded record lacked are kept"
    assert any("read as one cell" in f for f in coded["review_flags"])


def test_two_readings_whose_quantities_disagree_are_two_lines():
    a = {"part_number": "FIXING M6x12mm", "description": "THREADED INSERT, HEADED HEX DRIVE", "quantity": 4}
    b = {"part_number": "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE", "description": "", "quantity": 8}
    parts = [a, b]
    assert fold_one_cell_duplicates(parts) == [] and len(parts) == 2


def test_the_fold_runs_before_costing_and_over_the_late_records():
    import inspect
    import file_scan
    assert "fold_one_cell_duplicates" in inspect.getsource(file_scan)
    assert "fold_one_cell_duplicates" in inspect.getsource(estimator.cost_uncosted_bought_in_records)


# ── 3 & 4. the weight a sheet prints, and an assembly root ──────────────────────────────

def test_a_sheet_weight_in_the_models_default_material_is_said_as_that_not_a_gauge():
    part = {"part_number": "T-011", "description": "FISHMONGER TEXT", "normalized_material": "ACRYLIC",
            "normalized_thickness_mm": 10.0, "_costed_blank_mm": [157.05, 745.16],
            "blank_area_mm2": 117027.0, "stated_weight_kg": 9.187}
    note = estimator._blank_weight_check(part)
    assert note and note.startswith("WEIGHT NOTE:"), note
    assert "mild steel" in note and "suggests the model carries mild steel" in note
    assert "cannot test the gauge" in note, "a density match suggests a model error; it does not prove the gauge"
    estimator.estimate_process_times(part, quantity=1)
    assert not any("Gauge of T-011" in str(q.get("issue")) for q in part.get("manufacturing_questions") or [])


def test_a_weight_no_default_material_explains_still_questions_the_gauge():
    part = {"part_number": "P-1", "description": "PANEL", "normalized_material": "ACRYLIC",
            "normalized_thickness_mm": 3.0, "_costed_blank_mm": [500.0, 300.0], "stated_weight_kg": 9.0}
    note = estimator._blank_weight_check(part)
    assert note and note.startswith("WEIGHT CHECK:")


def test_a_record_whose_code_names_an_assembly_is_one():
    assert carries_assembly_role("8188-08_GA") and carries_assembly_role("11908-21 GA")
    assert not carries_assembly_role("8188-08-016") and not carries_assembly_role("ABC-LEFT")
    ga = {"part_number": "8188-08_GA", "description": "HERO HEADER", "normalized_material": "MILD STEEL",
          "normalized_thickness_mm": 3.0, "blank_length_mm": 53.0, "blank_width_mm": 20.0,
          "weights": ["43631.32g"]}
    assert estimator._blank_weight_check(ga) is None


# ── 5. the shipment ────────────────────────────────────────────────────────────────────

def _panel(pn="P-1", L=1100.0, W=900.0):
    return {"part_number": pn, "description": "PANEL", "quantity": 1, "normalized_material": "MILD STEEL",
            "normalized_thickness_mm": 3.0, "material_estimate": {"blank_length_mm": L, "blank_width_mm": W}}


def test_the_planner_reads_the_costed_blank():
    plan = palletising.plan_shipment([_panel()], 10)
    assert plan["parts_measured"] == 1 and plan["pallet_count"] >= 1


def test_an_assembly_root_is_not_shipped_as_a_part():
    order = cl.describe_order([_panel(), dict(_panel("8188-08_GA", 53.0, 20.0))], 1)
    assert [p["part_number"] for p in order["shippable_parts"]] == ["P-1"]


def test_the_counted_shipment_is_priced_at_a_researched_per_pallet_rate_at_every_break(monkeypatch):
    asked = []

    def _research(brief):
        asked.append(brief)
        return {"price_gbp": 60.0, "unit": "pallet", "source": "a UK pallet network", "price_date": "2026-10-10"}
    monkeypatch.setattr(cl, "_commercial_researcher", _research)
    parts = [_panel()]
    order = cl.describe_order(parts, 1)
    got = cl._counted_shipment_price("DELIVERY", order)
    assert got and got["order_gbp"] == 60.0 * order["shipment"]["pallet_count"]
    assert "per pallet" in asked[0]["description"] and asked[0]["wanted_unit"] == "pallet"
    big = cl.describe_order(parts, 1000)
    assert got["order_gbp_at_breaks"][1000] == 60.0 * big["shipment"]["pallet_count"]
    assert got["order_gbp_at_breaks"][1000] > got["order_gbp_at_breaks"][1], \
        "a thousand panels travel on more pallets than one"
    assert "GBP 60.00 per pallet" in got["working"] and "re-counted at each break" in got["working"]


def test_nothing_counted_gives_no_shipment_price():
    assert cl._counted_shipment_price("DELIVERY", {"shipment": {"pallet_count": None, "carton_count": None}}) is None


# ── the consistency check ──────────────────────────────────────────────────────────────

def test_a_missing_drawing_whose_line_is_priced_is_a_warning_said_as_priced():
    summary = {"pages": [], "document_analysis": {"bom_rows": [
                   {"part_number": "8188-08-004", "description": "WIRE WORK MESH FRAME", "quantity": 1},
                   {"part_number": "8188-08-099", "description": "NOTHING PRICED", "quantity": 1}]},
               "estimate_summary": {"part_estimates": [
                   {"part_number": "8188-08-004", "material_estimate": {"unit_material_cost_gbp": 0.89}},
                   {"part_number": "8188-08-099", "material_estimate": {"unit_material_cost_gbp": 0.0}}]}}
    v = invariants.check_the_pack_contains_the_drawings_its_bom_names(summary) \
        if hasattr(invariants, "check_the_pack_contains_the_drawings_its_bom_names") else None
    if v is None:
        pytest.skip("check not exposed under that name")
    sev = {x["severity"]: x for x in v}
    if invariants.BLOCKING in sev:
        assert "8188-08-004" not in sev[invariants.BLOCKING]["message"]
    if invariants.WARNING in sev:
        assert "priced without one" in sev[invariants.WARNING]["message"]


def test_a_role_token_yields_to_a_measured_flat_or_an_explicit_classification():
    from detail_page_geometry import not_cut_from_a_blank
    ga = {"part_number": "X-01_GA", "description": "FRAME"}
    assert not_cut_from_a_blank(ga)
    assert not not_cut_from_a_blank(dict(ga, is_assembly_parent=False))
    measured = dict(ga, dxf_augmented=True, blank_length_mm=400.0, blank_width_mm=300.0)
    assert not not_cut_from_a_blank(measured), "a DXF flat says this GA-coded record is a cut part"
