"""Hotel Chocolat saved-pack coverage: every recovered part carries the material, gauge and
coat its own drawing states (27 Nov 2026). Private evidence, never committed; skipped
without it. The plinth case also needs the plinth DXFs (HC_PLINTH_DXF_DIR)."""
import json
import os
import re
from pathlib import Path

import pytest

from saved_scope_recovery import prepare


@pytest.fixture(scope="module")
def saved():
    p = Path(os.environ.get("HC_SAVED_SCOPE_FIXTURE", "private-fixtures/hc_saved_scope.json"))
    if not p.exists():
        pytest.skip("Private Hotel Chocolat saved evidence is not installed")
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("ref", ["A.33446", "A.34225"])
def test_every_part_whose_own_sheet_says_sheet_steel_is_costed_as_steel(saved, ref):
    prepared, audit = prepare(saved[ref])
    pages = {p.get("page_number"): p for p in prepared.get("pages") or []}
    checked = 0
    for part in prepared["parts"]:
        own = [pages[n] for n in part.get("pages") or [] if n in pages]
        if len(own) != 1:
            continue
        m = re.search(r"MATERIAL\s*:\s*([\d.]+)\s*mm[^;\n]*SHEET STEEL",
                      own[0].get("pdfplumber_text") or "", re.I)
        if not m:
            continue
        checked += 1
        assert part.get("normalized_material") == "MILD STEEL", part.get("part_number")
        assert float(part.get("normalized_thickness_mm") or 0) == float(m.group(1)), part.get("part_number")
    assert checked >= 20 and audit["title_block_materials_reread"]


def test_the_800_shelf_carries_each_parts_material_gauge_and_count(saved):
    prepared, _ = prepare(saved["B.34471"], scope="B.34473",
                          scope_basis="The folder is the shelving assembly; B.34473 lists its parts.")
    got = {p["part_number"]: (p.get("normalized_material"), p.get("normalized_thickness_mm"), p.get("quantity"))
           for p in prepared["parts"]}
    assert got == {"B-34471": ("MILD STEEL", 1.5, 1), "C-33383": ("MILD STEEL", 2.5, 2),
                   "D-34472": ("MILD STEEL", 1.5, 1)}


def test_the_plinth_panels_carry_material_and_size_and_the_tower_its_spray(saved):
    dxf_dir = os.environ.get("HC_PLINTH_DXF_DIR")
    if not dxf_dir or not Path(dxf_dir).is_dir():
        pytest.skip("The 1050mm plinth DXFs are not installed (HC_PLINTH_DXF_DIR)")
    import route_compiler as rc
    from sheet_view_sizes import apply_sheet_title_facts, apply_sheet_view_sizes
    prepared, _ = prepare(saved["B.34493"], identity_aliases={"10100892": "A.34494"},
                          scope_basis="Reviewed GA stock code: the tower assembly is A.34494.")
    dxfs = sorted(Path(dxf_dir).glob("nc1-*.DXF"))
    apply_sheet_view_sizes(prepared["parts"], {}, dxfs)
    apply_sheet_title_facts(prepared["parts"], {}, dxfs)
    panels = {p["part_number"]: p for p in prepared["parts"] if str(p["part_number"]).startswith("B34495-")}
    assert {(p["blank_length_mm"], p["blank_width_mm"], p["normalized_material"], p["normalized_thickness_mm"])
            for p in panels.values()} == {(300, 300, "MDF", 18), (1050, 300, "MDF", 18), (281, 281, "MDF", 18)}
    decisions = rc.compile_route_without_pricing(prepared)["decisions"]
    assert any(d["operation"] == "wet_spray" and d["status"] == "required" for d in decisions)
