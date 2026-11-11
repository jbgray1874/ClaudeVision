"""A glued board assembly carries its adhesive and the wax its pack asks for (D-723).

11908-22-GA, 5 Nov 2026: five laminated MDF panels, mitred and rebated, glued into a tray, the
GA stating "FILL ANY OPEN GAPS ON CORNERS WITH MATCHING WAX". Neither the adhesive nor the wax
was on the bill. Each is now a line priced as its SHARE of a pack (a house allowance, stated),
never a whole pack per unit; a pack nobody can price leaves the line asked, not guessed.
Synthetic records and made-up part numbers.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator
from joinery_consumables import mint


def _tray(**asm_extra):
    asm = {"part_number": "T-GA", "is_assembly_parent": True,
           "assembly_children": ["T-01J", "T-02J", "T-03J"]}
    asm.update(asm_extra)
    return [asm,
            {"part_number": "T-01J", "normalized_material": "MDF", "quantity": 1},
            {"part_number": "T-02J", "normalized_material": "MDF", "quantity": 2},
            {"part_number": "T-03J", "normalized_material": "MDF", "quantity": 2}]


WAX_PACK = {"pages": [{"page_number": 1,
                       "pdfplumber_text": "FILL ANY OPEN GAPS ON CORNERS WITH MATCHING WAX"}]}


def test_a_glued_tray_gets_its_adhesive_and_the_wax_its_pack_names():
    parts = _tray()
    assert mint(parts, WAX_PACK) == ["T-GA-ADHESIVE", "T-GA-WAX"]
    glue, wax = parts[-2], parts[-1]
    assert glue["consumable_share"]["count"] == 0.05      # 5 pieces x 0.01 of a pack
    assert wax["consumable_share"]["count"] == 0.1
    assert glue["bom_parent"] == "T-GA" and glue["is_bought_in"]
    assert "MATCHING WAX" in wax["consumable_share"]["working"]
    assert all("HOUSE ALLOWANCE" in p["consumable_share"]["basis"] for p in (glue, wax))


def test_no_wax_line_without_a_wax_note():
    parts = _tray()
    assert mint(parts, {"pages": []}) == ["T-GA-ADHESIVE"]


def test_glue_already_on_the_route_is_not_added_twice():
    parts = _tray(textual_operations=["glue"])
    assert mint(parts, {"pages": []}) == []


def test_a_metal_assembly_gets_no_adhesive():
    parts = _tray()
    for p in parts[1:]:
        p["normalized_material"] = "MILD STEEL"
    assert mint(parts, WAX_PACK) == []


def test_minting_twice_adds_nothing_more():
    parts = _tray()
    mint(parts, WAX_PACK)
    assert mint(parts, WAX_PACK) == []


def test_the_line_is_its_share_of_the_pack(monkeypatch):
    monkeypatch.setattr(estimator, "_resolve_part_system_cost",
                        lambda p: {"applied_unit_cost": 8.0, "result": {"source": "udef"}})
    part = {"part_number": "T-GA-ADHESIVE", "description": "Wood adhesive",
            "consumable_share": {"reference_item": "PVA wood adhesive 1kg", "count": 0.05,
                                 "working": "w", "basis": "b"}}
    r = estimator._consumable_share_cost(part)
    assert r["applied_unit_cost"] == 0.4


def test_an_unpriced_pack_is_asked_never_guessed_whole(monkeypatch):
    monkeypatch.setattr(estimator, "_resolve_part_system_cost",
                        lambda p: {"applied_unit_cost": None})
    part = {"part_number": "T-GA-WAX", "description": "Matching wax filler",
            "consumable_share": {"reference_item": "hard wax filler stick", "count": 0.1,
                                 "working": "w", "basis": "b"}}
    r = estimator._consumable_share_cost(part)
    assert r["applied_unit_cost"] is None
    assert "consumable_share_unpriced" in part["risk_flags"]
    assert part["manufacturing_questions"]
    assert estimator._last_resort_price_is_needed(
        {"part_number": "T-GA-WAX", "risk_flags": part["risk_flags"]}) is False
