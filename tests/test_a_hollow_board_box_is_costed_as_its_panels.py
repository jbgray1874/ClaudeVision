"""A hollow board box is costed as the panels it is made of (SCRUM-180).

12678-01-01J BASE: the drawing's Section B-B shows a mitred plinth box (a top and four
walls, open beneath, with internal rails), while the model is one part 552 x 125 x 370.
The plate test rightly refused that box as a board, so nothing gauged it and nothing sized
it, and the line went out unpriced at a category default of 350 x 250.

THE RULE: a board leaf whose model fails the plate test, but whose volume fills under half
its envelope, is a box made of boards. Its gauge comes from the model's volume and surface
area (V = A t, S = 2A + P t, edge-corrected). Its panels are the envelope faces the
measured board area accounts for, and any area left over becomes internal rails of the
box's height. Each panel is a made record at that gauge and carries its own cut. The part
then stands as their assembly. Everything is provisional and asked; the drawing decides.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from source_connectors.solidworks import (hollow_board_takeoff,  # noqa: E402
                                          mint_hollow_board_panels,
                                          normalize_native_extract)

L, W, H = 552.0, 370.0, 125.0
SHELL5 = [(L, W), (L, H), (L, H), (W, H), (W, H)]


def _vs(faces, t):
    A = sum(a * b for a, b in faces)
    P = sum(2 * (a + b) for a, b in faces)
    return A * t, 2 * A + P * t


def _job(faces=SHELL5, t=18.0, material="MDF", bbox=(552.0, 125.0, 370.0), **extra):
    V, S = _vs(faces, t)
    rs = {"material": material, "is_sheet_metal": False, "bend_count": 0,
          "bbox_mm": list(bbox), "volume_mm3": V, "surface_area_mm2": S}
    rs.update(extra)
    return normalize_native_extract([{"title": "12678-01-01J", "doctype": 1,
                                      "route_signals": rs}])


def _parts():
    return [{"part_number": "12678-01-GA", "quantity": 1, "is_assembly_parent": True,
             "assembly_children": ["12678-01-01J"]},
            {"part_number": "12678-01-01J", "description": "BASE", "quantity": 1,
             "normalized_material": "MDF",
             "textual_operations": ["cnc_routing", "edge_banding"]}]


def test_the_takeoff_recovers_the_gauge_and_the_open_box():
    tk = hollow_board_takeoff([L, H, W], *_vs(SHELL5, 18.0))
    assert tk["gauge_mm"] == 18.0
    assert tk["fill"] < 0.5
    assert [(p["name"], p["length_mm"], p["width_mm"], p["count"]) for p in tk["panels"]] == [
        ("top", 552.0, 370.0, 1), ("long wall", 552.0, 125.0, 2),
        ("short wall", 370.0, 125.0, 2)]


def test_internal_rails_are_the_area_left_over():
    tk = hollow_board_takeoff([L, H, W], *_vs(SHELL5 + [(330.0, H), (330.0, H)], 18.0))
    assert tk["gauge_mm"] == 18.0
    rails = [p for p in tk["panels"] if p["name"] == "internal rail"]
    assert rails == [{"name": "internal rail", "length_mm": 330.0, "width_mm": 125.0,
                      "count": 2}]


def test_a_closed_box_takes_its_second_face():
    tk = hollow_board_takeoff([L, H, W], *_vs(SHELL5 + [(L, W)], 15.0))
    assert tk["gauge_mm"] == 15.0
    assert [p["name"] for p in tk["panels"]] == ["top", "long wall", "short wall",
                                                   "second face"]


def test_a_solid_block_or_missing_measures_are_refused():
    assert hollow_board_takeoff([L, H, W], L * W * H, 2 * (L * W + L * H + W * H)) is None
    assert hollow_board_takeoff([L, H, W], None, None) is None
    assert hollow_board_takeoff([L, H], 1000.0, 1000.0) is None


def test_the_base_stands_for_its_panels_at_the_measured_gauge():
    parts = _parts()
    assert mint_hollow_board_panels(parts, _job()) == ["12678-01-01J"]
    base = parts[1]
    assert base["is_assembly_parent"] is True
    assert base["hollow_board_takeoff"]["gauge_mm"] == 18.0
    assert any("is costed as a 18 mm board box" in str(q.get("issue"))
               for q in base["manufacturing_questions"])
    panels = {p["part_number"]: p for p in parts[2:]}
    assert sorted(panels) == ["12678-01-01J-P1", "12678-01-01J-P2", "12678-01-01J-P3"]
    assert base["assembly_children"] == sorted(panels)
    p2 = panels["12678-01-01J-P2"]
    assert (p2["blank_length_mm"], p2["blank_width_mm"], p2["quantity"]) == (552.0, 125.0, 2)
    for p in panels.values():
        assert p["normalized_thickness_mm"] == 18.0
        assert p["normalized_material"] == "MDF"
        assert "cnc_routing" in p["inferred_operations"]
        assert p["hollow_board_panel_of"] == "12678-01-01J"


def test_the_panels_are_routed_once_and_the_base_is_not():
    """Once the base is an assembly its own routing is not applicable, so the cut must
    travel with the panels or the cutting labour silently vanishes."""
    import route_compiler as rc
    parts = _parts()
    mint_hollow_board_panels(parts, _job())
    out = rc.compile_job_route(parts)
    req = {}
    for d in out["decisions"]:
        d = d if isinstance(d, dict) else d.__dict__
        for pid in (d.get("participants") or []):
            req[(d.get("operation"), pid)] = (d.get("status"), d.get("qty_per_unit"))
    assert req[("cnc_routing", "12678-01-01J")][0] == "not_applicable"
    assert req[("cnc_routing", "12678-01-01J-P1")] == ("required", 1.0)
    assert req[("cnc_routing", "12678-01-01J-P2")] == ("required", 2.0)
    assert req[("cnc_routing", "12678-01-01J-P3")] == ("required", 2.0)
    assert req[("edge_banding", "12678-01-01J")][0] == "required"


def test_the_panels_carry_the_blank_and_gauge_into_the_material_estimate():
    import estimator as est
    parts = _parts()
    mint_hollow_board_panels(parts, _job())
    base = est.estimate_part(dict(parts[1]), job_quantity=1)
    assert not (base.get("material_estimate") or {}).get("blank_area_m2")
    top = est.estimate_part(dict(parts[2]), job_quantity=1)
    me = top["material_estimate"]
    assert me["thickness_mm"] == 18.0
    assert abs(me["blank_area_m2"] - 0.552 * 0.370) < 1e-3


def test_never_a_metal_a_flat_a_bought_in_or_a_split_part():
    p = _parts()
    p[1]["normalized_material"] = "MILD_STEEL"
    assert mint_hollow_board_panels(p, _job(material="Plain Carbon Steel")) == []
    p = _parts()
    p[1]["is_bought_in"] = True
    assert mint_hollow_board_panels(p, _job()) == []
    p = _parts()
    mint_hollow_board_panels(p, _job())
    n = len(p)
    assert mint_hollow_board_panels(p, _job()) == [] and len(p) == n


def test_the_scan_splits_the_box_after_the_model_children():
    scan = open(os.path.join(os.path.dirname(__file__), "..", "src", "file_scan.py"),
                encoding="utf-8").read()
    assert scan.index("mint_model_children(summary") < scan.index(
        "mint_hollow_board_panels(summary")


def test_the_analyser_reads_the_density_free_measures():
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "solidworks",
                            "sw_native_analyse.py"), encoding="utf-8").read()
    assert "def get_volume_and_area_mm" in src
    assert '"SurfaceArea"' in src and '"Volume"' in src
    assert "EXTRACT_SCHEMA_VERSION = 4" in src
