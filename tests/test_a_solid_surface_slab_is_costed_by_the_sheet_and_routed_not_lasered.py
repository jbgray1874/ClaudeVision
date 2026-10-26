"""A solid-surface slab is costed by the sheet, and routed rather than lasered twice (D-598n).

9287-10-GA, 24 Oct 2026: D-598l named the base's material SOLID SURFACE, and the engine's one
cost-stream test still read it as sheet metal. The base would have been nested by mass on the
Sheet Steel block, and its flat's laser cut booked on the metal laser beside the read's CNC
routing. Solid surface is a slab sold by the sheet; and no shop rule names its cutter, so the
router is a proposal that is asked, never a rule the engine made up.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config                                                         # noqa: E402
import costed_facts                                                   # noqa: E402
import estimator                                                      # noqa: E402
import wb_populate                                                    # noqa: E402


def _base(material="SOLID SURFACE", ops=("laser_cutting", "cnc_routing")):
    return {"part_number": "7777-10-005", "description": "BASE", "normalized_material": material,
            "normalized_thickness_mm": 12.0, "thickness_mm": 12.0, "quantity": 1,
            "textual_operations": list(ops), "geometry_source": "dxf", "dxf_augmented": True,
            "normalized_geometry": {"length_mm": 303, "width_mm": 303}}


def test_solid_surface_is_costed_on_the_other_sheet_block_not_by_mass():
    for m in ("SOLID SURFACE", "SOLID_SURFACE", "12mm SOLID SURFACE"):
        assert costed_facts.is_other_sheet_material(m), m
    assert not costed_facts.is_other_sheet_material("MILD STEEL")
    nest = estimator.select_sheet_size("SOLID SURFACE", 303, 303)
    assert nest["nesting_rule"] == "workbook_other_sheet_J51"
    assert nest["candidate_sheet_size_mm"] == [3680, 760], "the slab config holds"


def test_its_cuts_are_not_booked_on_the_metal_laser():
    board = wb_populate._is_board("SOLID SURFACE")
    assert wb_populate._map_operation("laser_cutting", board, "", "SOLID SURFACE") != "Laser (Metal)"
    assert wb_populate._map_operation("cnc_routing", board, "", "SOLID SURFACE") == "CNC Joinery"


def test_a_laser_beside_a_router_comes_off_as_a_proposal_and_is_asked():
    part = _base()
    times = estimator.estimate_process_times(part, 1)
    assert part["removed_operations"] == ["laser_cutting"]
    assert part["textual_operations"] == ["cnc_routing"]
    assert "laser_cutting" not in times["times_min"] and times["times_min"]["cnc_routing"] > 0
    q = [x for x in part["manufacturing_questions"] if x["subject"] == "cut_method_proposed"]
    assert q and "not a shop rule" in q[0]["assumption"]
    assert any("PROPOSED" in str(f) for f in part["review_flags"])


def test_a_shop_rule_outranks_the_proposal(monkeypatch):
    monkeypatch.setattr(config, "CUT_METHOD_BY_MATERIAL", list(config.CUT_METHOD_BY_MATERIAL) + [
        {"material": "SOLID SURFACE", "method": "laser", "source": "test shop rule"}])
    part = _base()
    estimator.estimate_process_times(part, 1)
    assert part["removed_operations"] == ["cnc_routing"], "the shop's word, not the proposal's"
    assert not any(x.get("subject") == "cut_method_proposed"
                   for x in part.get("manufacturing_questions") or [])


def test_a_material_neither_table_names_keeps_both_cuts_and_flags():
    part = _base(material="PETG")
    estimator.estimate_process_times(part, 1)
    assert not part.get("removed_operations")
    assert any("CUT TWICE?" in str(f) for f in part["review_flags"])


def test_the_proposal_never_claims_to_be_the_shops():
    for row in config.CUT_METHOD_PROPOSED_BY_MATERIAL:
        assert "not an SDI shop rule" in row["source"], row
        assert not any(r["material"] == row["material"] for r in config.CUT_METHOD_BY_MATERIAL)
