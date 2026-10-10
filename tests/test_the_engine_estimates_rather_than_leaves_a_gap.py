"""Two policy gaps the 13:23 review named, and one report contradiction (D-453).

"013 should not simply retain a suspect low price with a question" and "an unmatched
historical allowance should not prevent shipment-based estimating merely because it exists in
SDI Live". And the report still said the GA was "nested and cut at 3 mm".
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import commercial_lines as cl                                         # noqa: E402
import costed_facts as cf                                             # noqa: E402
import estimator as e                                                 # noqa: E402


def _acr(pn, L, W, area, kg, t=3.0):
    return {"part_number": pn, "description": "WAVE", "normalized_material": "ACRYLIC",
            "normalized_thickness_mm": t, "quantity": 1, "stated_weight_kg": kg,
            "normalized_geometry": {"blank_length_mm": L, "blank_width_mm": W, "blank_area_mm2": area}}


_SIBS = [_acr("014", 2257.4, 199.99, 285684, 6.728), _acr("015", 2354.72, 99.99, 106666, 2.512),
         _acr("008", 1143, 98, 111517, 2.626)]


# ── the pack's model material ──────────────────────────────────────────────────────────

def test_measured_parts_that_weigh_as_steel_establish_the_packs_model_material():
    pm = e.pack_model_material(_SIBS)
    assert pm == {"material": "MILD STEEL", "parts": ["014", "015", "008"]}


def test_one_part_is_not_a_pack_reading_and_a_part_that_weighs_as_itself_votes_for_nothing():
    assert e.pack_model_material(_SIBS[:1]) is None
    honest = _acr("H", 1000, 500, 500000, 500000 * 3 * 1190e-9)      # weighs as acrylic
    assert e.pack_model_material([honest, _SIBS[0]]) is None


# ── 013's provisional blank ────────────────────────────────────────────────────────────

def _w013(**over):
    p = {"part_number": "013", "description": "WAVE LAYER 3", "normalized_material": "ACRYLIC",
         "normalized_thickness_mm": 3.0, "quantity": 1, "stated_weight_kg": 11.731,
         "normalized_geometry": {"blank_length_mm": 2190.34, "blank_width_mm": 17.0},
         "_pack_model_material": e.pack_model_material(_SIBS)}
    p.update(over)
    return p


def test_an_unmeasured_blank_is_priced_on_the_weight_implied_width_said_as_provisional():
    part = _w013()
    pe = e.estimate_part(part, 1)
    me = pe["material_estimate"]
    assert me["blank_length_mm"] == 2190.34 and abs(me["blank_width_mm"] - 227.4) < 0.5
    assert part["_blank_provisional"]["recorded_mm"] == [2190.34, 17.0]
    flag = " ".join(str(f) for f in part["review_flags"])
    assert "PROVISIONAL BLANK" in flag and "is INFERRED" in flag and "the 2190.34 mm side is the recorded figure" in flag
    assert "014, 015, 008" in flag and "working figure, not a measurement" in flag
    assert any(q["issue"].startswith("Blank of 013") for q in part["manufacturing_questions"])
    priced_on_17 = e.estimate_part(_w013(_pack_model_material=None), 1)["material_estimate"]
    assert me["unit_material_cost_gbp"] > priced_on_17["unit_material_cost_gbp"] * 5


def test_no_pack_reading_a_measured_outline_or_an_assembly_leaves_the_blank_alone():
    for part in (_w013(_pack_model_material=None),
                 _w013(normalized_geometry={"blank_length_mm": 2190.34, "blank_width_mm": 17.0,
                                            "blank_area_mm2": 30000.0}),
                 _w013(part_number="X_GA")):
        assert e._apply_mass_implied_blank(part) is None
        assert "_blank_provisional" not in part


def test_a_recorded_blank_that_already_carries_the_weight_is_not_widened():
    assert e._apply_mass_implied_blank(_w013(stated_weight_kg=0.8)) is None


# ── the commercial basis ───────────────────────────────────────────────────────────────

_WEAK = {"order_gbp": 10.0, "order_gbp_at_breaks": {1: 10.0, 50: 500.0}, "source_class": "sdi_history",
         "source_name": "SDI Live history: 12 quote line(s), same customer",
         "comparability": "same customer, quantity not held on the history header",
         "working": "median GBP 10.00 a unit of 12 packaging line(s)"}
_CS = {"order_gbp": 120.0, "order_gbp_at_breaks": {1: 120.0, 50: 960.0},
       "source_name": "researched per-pallet rate (x) x the counted shipment",
       "working": "GBP 120.00 per pallet x 1 pallet"}


def test_weak_history_does_not_override_a_counted_shipment_it_is_shown_beside_it(monkeypatch):
    monkeypatch.setattr(cl, "_sdi_live_rate", lambda code, order: dict(_WEAK))
    monkeypatch.setattr(cl, "_counted_shipment_price", lambda code, order: dict(_CS))
    ch = cl._choose_commercial_basis("PACKAGING", {"order_quantity": 1})
    assert ch["order_gbp"] == 120.0 and ch["basis"] == "the counted shipment at a researched unit rate"
    assert "not comparable" in ch["cross_check"] and "median GBP 10.00" in ch["cross_check"]


def test_comparable_history_is_used_and_the_business_rate_beats_both(monkeypatch):
    good = dict(_WEAK, comparability="same customer, quantity within half to double of 1")
    monkeypatch.setattr(cl, "_sdi_live_rate", lambda code, order: good)
    monkeypatch.setattr(cl, "_counted_shipment_price", lambda code, order: dict(_CS))
    assert cl._choose_commercial_basis("PACKAGING", {})["order_gbp"] == 10.0
    rate = {"order_gbp": 53.0, "source_class": "sdi_commercial_rate", "source_name": "CommercialRate x shipment"}
    monkeypatch.setattr(cl, "_sdi_live_rate", lambda code, order: rate)
    assert cl._choose_commercial_basis("PACKAGING", {})["basis"] == "SDI Live rate x the counted shipment"


def test_weak_history_alone_is_used_and_said_as_weak(monkeypatch):
    monkeypatch.setattr(cl, "_sdi_live_rate", lambda code, order: dict(_WEAK))
    monkeypatch.setattr(cl, "_counted_shipment_price", lambda code, order: None)
    ch = cl._choose_commercial_basis("PACKAGING", {})
    assert ch["order_gbp"] == 10.0 and "weak comparability" in ch["basis"]


# ── the report ─────────────────────────────────────────────────────────────────────────

def test_an_assembly_is_not_told_it_is_nested_and_cut():
    ga = {"part_number": "8188-08_GA", "normalized_thickness_mm": 3.0,
          "_displaced": {"normalized_thickness_mm": [{"value": 10.0, "source": "drawing_deterministic"}]}}
    assert cf.thickness_conflict(ga) is None
