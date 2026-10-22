"""A board with no density is priced by area from the researched rung, not held at £0 (D-341).

12173's two MFC backs (18 mm Unilin Minnesota Oak, 1470 x 288) had a measured blank and were
held at £0: "MFC: no density recorded, so its material cannot be massed and is NOT costed".
Plain MFC is neither in the faced-board branch nor massable, so it fell past the researched
rung both of those have. Board is bought by the sheet and priced by area; the rung asks for
a sourced, dated £/m² — and where research cannot produce one, the line stays unpriced as
before.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as E  # noqa: E402


def _mfc():
    return {"part_number": "12173-03-03J", "description": "BACK PANEL",
            "normalized_material": "MFC", "normalized_thickness_mm": 18.0,
            "quantity": 2, "blank_length_mm": 1470.0, "blank_width_mm": 288.0,
            "normalized_geometry": {"blank_length_mm": 1470.0, "blank_width_mm": 288.0}}


def test_the_researched_rate_prices_it_and_says_so(monkeypatch):
    seen = {}

    def fake(material, thickness, part, noun="board"):
        seen["material"] = material
        return {"price_gbp": 10.0, "status": "INDICATIVE",
                "evidence": {"source": "a supplier page", "as_of": "2026-09-29",
                             "quantity_basis": "per m2"},
                "calculation": {"working": "0.4234 m2 x £23.62/m2"}}
    monkeypatch.setattr(E, "_researched_board_rate_m2", fake)
    p = _mfc()
    me = E.estimate_material(p)
    assert seen.get("material"), "the researched rung was never asked"
    assert me.get("cost_method") == "board_rate_researched", me.get("cost_method")
    assert me["cost_per_part_gbp"] and me["cost_per_part_gbp"] > 0
    assert any("RESEARCHED indicative" in f for f in p.get("review_flags") or [])


def test_no_evidence_leaves_it_visibly_unpriced(monkeypatch):
    monkeypatch.setattr(E, "_researched_board_rate_m2", lambda *a, **k: None)
    p = _mfc()
    me = E.estimate_material(p)
    assert not me.get("cost_per_part_gbp")
    assert any("no density recorded" in f for f in p.get("review_flags") or [])
