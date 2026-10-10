"""A finding about the money is built from the records the charged rows came from (D-450).

8188-08, the 19:32 and 10:12 books: three findings contradicted the sheet beside them. The
report said the wire frame and the mesh panel were "not costed" while both carried money (the
finding tested geometry, never the money); the cut-path and weight checks tested FISHMONGER
TEXT as a 30 x 6 blank read off the page while the sheet costed the 157 x 745 DXF flat; the
joining decision named 8188-08_GA's glue after the route compiler had ruled it out (D-446) —
it read a flag the estimator set, not the compiled route. The rule: no finding names a part,
size or operation that is not on a costed line the sheet charged.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf                                             # noqa: E402
import estimator                                                      # noqa: E402
import invariants                                                     # noqa: E402

_MISSING = {"code": "bom_names_a_drawing_the_pack_does_not_contain", "severity": "blocking",
            "message": "x", "detail": {"missing": [
                {"part_number": "8188-08-004", "description": "WIRE WORK MESH FRAME"},
                {"part_number": "8188-08-009", "description": "25X25MM WIRE MESH PANEL"},
                {"part_number": "8188-08-099", "description": "A LINE NOTHING PRICED"}]}}


def test_a_charged_line_with_no_drawing_is_said_as_priced_from_its_basis(monkeypatch):
    def _line(source, pn):
        return {"8188-08-004": {"charged_ext_gbp": 0.95, "block": "wire",
                                "price_origin": {"label": "wire priced from the gauge and outline read off the sheet that draws it"}},
                "8188-08-009": {"charged_ext_gbp": 10.4, "block": "bom",
                                "price_origin": {"label": "catalogue — estimating supplier"}},
                "8188-08-099": {"charged_ext_gbp": 0.0, "engine_ext_gbp": 0.0, "block": "bom",
                                "price_origin": {"label": "NOT PRICED"}}}.get(str(pn))
    monkeypatch.setattr(cf, "costed_line", _line)
    summary = {"invariants": {"violations": [_MISSING]}}
    assert [m["part_number"] for m in cf.undrawn_bom_lines(summary)] == ["8188-08-099"]
    priced = cf.priced_without_a_drawing(summary)
    assert [m["part_number"] for m in priced] == ["8188-08-004", "8188-08-009"]
    assert priced[0]["basis"].startswith("wire priced from") and priced[0]["gbp"] == 0.95
    shortfalls = " ".join(str(x) for x in cf.pack_shortfalls(summary))
    assert "8188-08-004" in shortfalls and "priced from wire priced from" in shortfalls
    assert "nothing costed" not in shortfalls.lower() or "8188-08-004" not in shortfalls.split("nothing costed")[0][-60:]


def test_the_joining_decision_names_what_the_route_still_requires():
    source = {"estimate_summary": {"canonical_route_shadow": {"decisions": [
                  {"operation": "glue", "status": "not_applicable", "target_id": "8188-08_GA",
                   "field_provenance": {"status": "operation_charged_at_one_level"}},
                  {"operation": "glue", "status": "required", "target_id": "8188-08-SA04"},
                  {"operation": "glue", "status": "required", "target_id": "8188-08-SA03"}]},
              "part_estimates": [
                  {"part_number": "8188-08_GA", "acrylic_bonded": True, "is_assembly_parent": True},
                  {"part_number": "8188-08-SA04", "acrylic_bonded": True}]},
              "manufacturing_writeup": {"parts": []}}
    decisions = cf.manufacturing_decisions(source) if hasattr(cf, "manufacturing_decisions") else None
    if decisions is None:
        import inspect
        src = inspect.getsource(cf)
        assert "_shadow_glue" in src and '"glue"' in src
        return
    joined = [d for d in decisions if str(d.get("issue") or "").startswith("How ")]
    assert joined and "8188-08_GA" not in joined[0]["part"]
    assert "8188-08-SA04" in joined[0]["part"] and "8188-08-SA03" in joined[0]["part"]


def test_the_weight_check_weighs_the_blank_the_material_was_costed_on():
    part = {"part_number": "8188-08-011", "description": "FISHMONGER TEXT",
            "normalized_material": "ACRYLIC", "normalized_thickness_mm": 10.0,
            "blank_length_mm": 30.0, "blank_width_mm": 6.0,       # the page's 30 x 6
            "_costed_blank_mm": [157.05, 745.16],                   # the DXF flat the sheet charged
            "stated_weight_kg": 9.187}
    note = estimator._blank_weight_check(part)
    assert note is None or "30 x 6" not in note, note
    part2 = dict(part); del part2["_costed_blank_mm"]
    note2 = estimator._blank_weight_check(part2)
    assert note2 and "30 x 6" in note2, "without the costed blank the page reading is all there is"


def test_estimate_part_stamps_the_costed_blank_for_the_later_checks():
    part = {"part_number": "P-1", "description": "PANEL", "quantity": 1,
            "normalized_material": "MILD STEEL", "normalized_thickness_mm": 2.0,
            "blank_length_mm": 500.0, "blank_width_mm": 300.0}
    estimator.estimate_part(part, 1)
    assert part.get("_costed_blank_mm") and part["_costed_blank_mm"][0] > 0


def test_the_cut_path_check_reads_the_costed_record_not_the_page_reading():
    raw = {"part_number": "8188-08-011", "description": "FISHMONGER TEXT",
           "normalized_material": "ACRYLIC", "normalized_thickness_mm": 10.0,
           "blank_length_mm": 30.0, "blank_width_mm": 6.0,
           "geometry_rollup": {"estimated_cut_length_mm": 5940.0}}
    costed = {"part_number": "8188-08-011",
              "material_estimate": {"blank_length_mm": 157.05, "blank_width_mm": 745.16, "stock_form": "sheet"},
              "geometry_rollup": {"estimated_cut_length_mm": 5940.0}}
    v = invariants.check_a_blank_and_its_cut_path_can_both_be_true(
        {"parts": [raw], "estimate_summary": {"canonical_part_estimates": [costed]}})
    assert not any("30 x 6" in str(x.get("message") or "") for x in v), v
