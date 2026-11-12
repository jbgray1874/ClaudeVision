"""A material the drawing office typed outranks a model's appearance default (D-598l).

9287-10-GA's base, 24 Oct 2026, live run: its flat is named "12mm SOLID SURFACE", which the
filename reader could not say, so the material entered only as an inference; the SolidWorks
model's library appearance ("Steel") then took the base for 12 mm mild steel plate, nested it
on the Sheet Steel block and lasered it on the metal laser. Solid surface is now read from the
name, at the filename's rank; no rate is implied, so it stays unpriced and asked.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                         # noqa: E402
import drawing_job_merge as d                                         # noqa: E402
import source_precedence as sp                                        # noqa: E402


def test_solid_surface_is_read_from_a_flats_name_by_word_or_maker():
    for name in ("9287-10-005_12mm SOLID SURFACE_REV[A].DXF", "X-01_12MM HANEX.DXF",
                 "X-02 CORIAN 6mm.dxf", "X-03_HI-MACS_12.dxf"):
        assert d.material_from_dxf_filename(Path(name)) == "SOLID SURFACE", name
    assert d.material_from_dxf_filename(Path("X SIDE_5mm ACR.DXF")) == "ACRYLIC"


def test_the_models_appearance_default_does_not_replace_it():
    part = {"part_number": "X-005"}
    assert sp.apply_field(part, "normalized_material", "SOLID SURFACE", "dxf_filename")
    assert not sp.apply_field(part, "normalized_material", "MILD_STEEL",
                              "solidworks_applied_material")
    assert part["normalized_material"] == "SOLID SURFACE"


def test_it_is_routed_and_stocked_but_never_given_a_price():
    assert "SOLID SURFACE" in d._ROUTED_STOCK
    assert config.STANDARD_SHEET_SIZES_MM["SOLID_SURFACE"][0] == (3680, 760)
    assert config.MATERIAL_DENSITY_KG_PER_M3["SOLID_SURFACE"] == 1700
    assert "SOLID_SURFACE" not in (getattr(config, "BOARD_SHEET_PRICE_GBP", {}) or {})
    assert "SOLID_SURFACE" not in (getattr(config, "MATERIAL_PRICE_GBP_PER_KG", {}) or {})


def test_a_flat_of_it_with_no_cut_is_proposed_a_router_and_asked():
    part = {"part_number": "X-005", "normalized_material": "SOLID SURFACE",
            "geometry_source": "dxf_flat_pattern", "dxf_geometry_reliability": 1.0,
            "dxf_raw_geometry": {"blank_area_mm2": 91809.0, "bbox_mm": [303, 303]},
            "flat_blank_mm": [303, 303]}
    done = d.propose_missing_cuts([part])
    assert done == [{"part_number": "X-005", "result": "cnc_routing"}]
    assert "cnc_routing" in part["inferred_operations"]
    assert part["route_gap"]["issue"].endswith("(SOLID SURFACE sheet)"), "proposed, and asked"


# ── AN ASSEMBLY IS NOT CUT BY THE WHOLE-PACK READ (D-598l) ──────────────────────────────

def test_the_pack_reads_cut_does_not_land_on_an_assembly_of_cut_pieces():
    import source_connectors.llm_full_job as lj
    box = {"part_number": "X-002", "description": "BOX", "is_assembly_parent": True,
           "assembly_children": ["X-002-SIDE-01", "X-002-TOP-01"], "textual_operations": []}
    base = {"part_number": "X-005", "description": "BASE", "textual_operations": []}
    job = {"routes": [{"operation": "cnc_routing", "part_numbers": ["X-002", "X-005"],
                       "inferred": True, "confidence": "medium"},
                      {"operation": "glue", "part_numbers": ["X-002"], "inferred": True}]}
    lj.apply_routes_to_parts([box, base], job)
    assert "cnc_routing" not in box["textual_operations"]
    assert any("it is an assembly" in f for f in box["review_flags"])
    assert "glue" in box["textual_operations"], "joining is the assembly's own work"
    assert "cnc_routing" in base["textual_operations"]
