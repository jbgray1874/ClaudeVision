"""A steel weldment inside a joinery unit is charged, once, on the steel (D-605, SCRUM-104).

THE HPP 01:12 BOOK. The read marked the halo top rim, the four posts and the guard rail welded.
The unit is MDF, the material of most of its panels. The concept rule moved the members' joints
onto the unit, to charge them once (D-531, D-537); the board gate then took welding off an MDF
record ("welding removed: part is MDF, which is not welded"); and no weld row was charged
anywhere for a steel halo. The report said so correctly, item by item.

The rule now: where the unit is positively non-metal, its welded METAL members are their own
weldment. The longest of them hosts the Weld and Dress rows with at least N-1 joints for N
welded pieces, the others point to it, a stated process stays on the host, every member keeps
its own coat, and no timber, board or plastic record acquires welding.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402
import estimator  # noqa: E402
import read_charge_contract as rcc  # noqa: E402

BRIEF = "Steel frame TIG welded."


def _part(name, mat, ops, qty=1, L=600, W=300, T=18, form=None, section=None):
    p = {"name": name, "kind": "fabricated", "quantity": qty, "material_guess": mat,
         "assumed_blank_mm": {"length": L, "width": W, "thickness": T}, "operations": ops}
    if form:
        p["stock"] = {"form": form, "section_mm": section, "wall_mm": 3, "length_mm": L,
                      "aperture_mm": [], "wire_mm": 0}
    return p


def _hpp(unit_metal=False):
    board = "MILD STEEL" if unit_metal else "MDF"
    return {"product": {"name": "HPP"}, "unit_operations": ["assembly"], "parts": [
        _part("ROUND BASE", board, ["cnc_routing"], L=1200, W=1200),
        _part("SHELF A", board, ["cnc_routing"], qty=2),
        _part("SHELF B", board, ["cnc_routing"], qty=2),
        _part("COLUMN SKIN", board, ["cnc_routing"]),
        _part("HALO RING TOP RIM", "MILD STEEL", ["rolling", "welding", "powder_coating"],
              L=7540, W=50, T=3, form="flat_bar", section=[50, 3]),
        _part("SUSPENSION POST", "MILD STEEL", ["saw", "welding", "powder_coating"], qty=4,
              L=400, W=50, T=3, form="box_section", section=[50, 50]),
        _part("GUARD RAIL RING", "MILD STEEL", ["rolling", "welding", "powder_coating"],
              L=6660, W=50, T=3, form="box_section", section=[50, 50]),
        _part("ACRYLIC TRAY", "ACRYLIC", ["laser_cutting", "welding"], qty=6, L=300, W=200, T=5),
    ]}


def _records(answer=None, brief=BRIEF):
    answer = answer or _hpp()
    parts = cs.parts_from_concept(answer, "HPP", brief=brief)
    parts = parts if isinstance(parts, list) else parts.get("parts", parts)
    unit = cs.unit_assembly_part(parts, answer, "HPP")
    cs.carry_weld_process(unit, parts, answer, brief)
    named = {d.split("  ")[0]: p for d, p in
             ((str(p.get("description") or ""), p) for p in parts)}
    return answer, unit, parts, named


def _ops(rec):
    return set(rec.get("inferred_operations") or [])


def test_the_mdf_unit_is_not_welded_and_the_steel_is():
    _a, unit, parts, n = _records()
    assert not (_ops(unit) & {"welding", "spot_welding"}), "the MDF unit carries no weld"
    rim, post, rail = n["HALO RING TOP RIM"], n["SUSPENSION POST"], n["GUARD RAIL RING"]
    assert "welding" in _ops(rim), "the longest welded steel member hosts the joints"
    assert rim["weld_joint_count"] == 5, "1 rim + 4 posts + 1 rail = 6 pieces, at least 5 joints"
    for m in (post, rail):
        assert "welding" not in _ops(m) and m["weld_charged_on"] == rim["part_number"], (
            "charged once, on the host, never again against every member")


def test_no_board_or_plastic_record_acquires_a_weld_from_its_neighbours():
    _a, unit, parts, n = _records()
    for name in ("ROUND BASE", "SHELF A", "SHELF B", "COLUMN SKIN"):
        assert not (_ops(n[name]) & {"welding", "spot_welding"}), name
        assert not n[name].get("weld_charged_on"), name
    tray = n["ACRYLIC TRAY"]
    assert not tray.get("weld_charged_on"), "acrylic is not joined into the steel weldment"


def test_the_stated_process_stays_on_the_host():
    _a, unit, parts, n = _records()
    assert (n["HALO RING TOP RIM"].get("weld_process_stated") or {}).get("process") == "TIG"
    assert not unit.get("weld_process_stated"), "the unit is not a weld host"


def test_each_steel_member_keeps_its_own_coat():
    _a, unit, parts, n = _records()
    for name in ("HALO RING TOP RIM", "SUSPENSION POST", "GUARD RAIL RING"):
        assert "powder_coating" in _ops(n[name]), name
        assert not n[name].get("coat_charged_on"), name


def test_the_joints_rest_on_a_disclosed_allowance_and_are_asked():
    _a, unit, parts, n = _records()
    said = [f for f in unit["review_flags"] if "are their own weldment" in f]
    assert said and "at least 5 joint(s) at the shop's per-joint rate" in said[0]
    assert "Confirm the members are welded and the joint count" in said[0]


def test_the_host_is_charged_weld_minutes():
    _a, unit, parts, n = _records()
    pt = estimator.estimate_process_times(n["HALO RING TOP RIM"], 1)
    assert (pt.get("run_times_min_per_unit") or {}).get("welding", 0) > 0


def test_a_metal_unit_is_still_the_weldment():
    """D-531 and D-537 unchanged where the unit is metal."""
    _a, unit, parts, n = _records(_hpp(unit_metal=True))
    assert "welding" in _ops(unit)
    assert n["HALO RING TOP RIM"]["weld_charged_on"] == unit["part_number"]


# ── the read ledger agrees: charged on the host, covered on the members ──────────────────

def test_the_ledger_shows_the_host_charged_and_the_members_covered(monkeypatch):
    monkeypatch.setenv("SDI_QUANTITY_BREAKS", "1")
    answer, unit, parts, n = _records()
    rim, post = n["HALO RING TOP RIM"], n["SUSPENSION POST"]
    weld = ({"workbook_row": 160, "engine_operations": ["welding"],
             "part_numbers": [rim["part_number"]]},
            {"workbook_row": 160, "part_numbers": rim["part_number"], "batch_hours": .5,
             "total_value_gbp": 20.9, "charged_cell": "Estimate!M160", "operation": "Weld (CO2)",
             "qty_per_unit": 1, "dept_rate_gbp_per_hour": 41.77})
    ledger = rcc.capture(answer, records=[unit] + parts, raw_response=json.dumps(answer),
                         read_key="k", brief=BRIEF)
    s = {"read_ledger": ledger, "manufacturing_writeup": {"parts": [unit] + parts},
         "estimate_summary": {"canonical_part_estimates": [
             {"part_number": p["part_number"], "quantity": p.get("quantity") or 1}
             for p in [unit] + parts]},
         "workbook_labour": {"rows": [weld[0]]},
         "final_estimate": {"source": "excel_calculated", "material_rows": [],
                            "labour_rows": [weld[1]]},
         "requested_order_quantity": 1}
    r = rcc.audit(s)
    states = {e["id"]: e for e in r["items"] if e["id"].endswith(".op.welding")}
    rim_item = next(e for e in states.values() if e.get("record") == rim["part_number"])
    post_item = next(e for e in states.values() if e.get("record") == post["part_number"])
    assert rim_item["state"] == rcc.CHARGED, rim_item
    assert post_item["state"] == rcc.COVERED and rim["part_number"] in post_item["how"], post_item
