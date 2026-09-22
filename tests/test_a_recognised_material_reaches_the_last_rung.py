"""A material this engine recognises and cannot price still reaches the bottom of the ladder.

James Gray, 22 September 2026, briefing the 11650 Fragrance Coffret run: the PETG panels
are "2 mm PETG — laser acrylic path, do not nest as steel", and the hardware needs "real
rates, not £0".

The nesting was already right. The PRICE was not, and the reason is in config's own words
against `MATERIAL_PRICE_GBP_PER_KG`:

    PETG, HIPS, ABS, PVC, FOAMEX, PP and PS have a sheet size and a density above but
    DELIBERATELY NO RATE HERE. A price is a commercial fact and SDI owns it; inventing one
    would put a number on a quote that nobody has agreed to.

That refusal is right and stays. What was wrong is what happened next: nothing. The last
rung — a researched figure that names its source, its date, what it is per and the
arithmetic — was wired for FACED BOARD only, and `_researched_board_rate_m2` says in its own
docstring why that is arbitrary: "Rung 4 is not a property of being a bought-in; it is the
last rung, and every line is entitled to it."

So a board reached the bottom rung and a plastic fell off the ladder — on the packs where
the plastic IS the job. 11650's PETG side panels are the standing example, named in that
config comment AND in `estimator_inputs`' NO_VOCABULARY branch: a part with a measured
blank, a known density and a known sheet size, reported as UNDER-CHARGED, costing £0.

NOTHING HERE INVENTS A PRICE. The producer returns a figure only with its evidence, and
where it cannot, the line stays unpriced and visible exactly as it is today.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config                                                          # noqa: E402
import estimator                                                       # noqa: E402


def _petg_panel() -> dict:
    """11650-04-01A as the readers hand it over: measured, recognised, unpriceable."""
    return {
        "part_number": "11650-04-01A",
        "description": "SIDE PANEL",
        "normalized_material": "PETG",
        "normalized_thickness_mm": 2.2,
        "blank_length_mm": 1570.0,
        "blank_width_mm": 525.0,
        "quantity": 1,
        "review_flags": [],
    }


def test_the_gap_this_closes_is_real_and_deliberate():
    """The premise, pinned: PETG is recognised — it has a sheet size and a density — and
    carries no rate. If somebody adds one, this test should be deleted, not edited."""
    assert "PETG" in getattr(config, "PLASTIC_SHEET_SIZES_MM", {}) or any(
        "PETG" in str(getattr(config, n, "")) for n in dir(config) if "SHEET" in n.upper())
    assert config.MATERIAL_PRICE_GBP_PER_KG.get("PETG") is None, (
        "PETG now has a rate — the researched rung is no longer this job's answer")
    assert config.MATERIAL_DENSITY_KG_PER_M3.get("PETG"), "PETG has no density to mass it by"


def test_a_recognised_plastic_is_nested_as_plastic_not_as_steel():
    """The half that was already right, kept honest: a 2mm PETG panel nests on the plastic
    sheet, not on 2500 x 1250 steel."""
    sheet = estimator.select_sheet_size("PETG", 1570.0, 525.0)
    assert sheet["candidate_sheet_size_mm"] == [3050, 2050]
    assert "steel" not in str(sheet.get("nesting_rule") or "").lower()


def test_a_researched_rate_prices_the_panel_and_says_it_was_researched(monkeypatch):
    """The rate comes back PER SQUARE METRE and is converted here, because this path costs
    by mass. The conversion is arithmetic an estimator can check: £/kg = £/m² ÷ (gauge × ρ).
    """
    asked = {}

    def _fake(material, thickness, part, noun="board"):
        asked["material"], asked["thickness"], asked["noun"] = material, thickness, noun
        return {"unit_price_gbp": 12.50, "price_gbp": 12.50,
                "status": "INDICATIVE — not a quotation",
                "evidence": {"source": "a named UK trade listing", "as_of": "2026-09-22",
                             "quantity_basis": "1 sheet, 3050 x 2050"}}

    monkeypatch.setattr(estimator, "_researched_board_rate_m2", _fake)
    part = _petg_panel()
    out = estimator.estimate_material(part)

    # It asked about a SHEET, not a board — the noun decides what the market answers about.
    assert asked["noun"] == "sheet" and asked["material"] == "PETG"

    # £12.50/m² over (0.0022 m x 1270 kg/m3) = 2.794 kg/m² -> £4.4739/kg.
    _kg_per_m2 = 0.0022 * float(config.MATERIAL_DENSITY_KG_PER_M3["PETG"])
    assert out.get("unit_material_cost_gbp"), "the panel is still unpriced"
    _mass = float(out["unit_material_mass_kg"])
    assert out["unit_material_cost_gbp"] == pytest.approx(
        _mass * (12.50 / _kg_per_m2) * (1.0 + float(getattr(config, "SCRAP_PERCENTAGE", 0.04))),
        rel=0.02), "the money does not follow from the researched rate"

    # AND IT SAYS SO. The source name begins "llm_" so the firmness check recognises it
    # with no new rule, and the line carries the source, the date and the arithmetic.
    src = out.get("price_source") or {}
    assert "llm_" in str(src.get("source") or src.get("source_class") or "").lower() or \
        "llm_" in str(src).lower(), src
    flag = [f for f in part["review_flags"] if "RESEARCHED indicative price" in f]
    assert len(flag) == 1, part["review_flags"]
    assert "a named UK trade listing" in flag[0] and "2026-09-22" in flag[0]
    assert "/kg" in flag[0] and "confirm against a current supplier price" in flag[0]
    assert "config.MATERIAL_PRICE_GBP_PER_KG" in flag[0], (
        "the line does not say what would end the question permanently")


def test_no_evidence_means_no_figure(monkeypatch):
    """The refusal that makes the rest of it safe. Where the research cannot produce a
    source, a date and a basis, the producer returns nothing — and the line stays unpriced
    and visible, exactly as it was before this existed."""
    monkeypatch.setattr(estimator, "_researched_board_rate_m2",
                        lambda *a, **k: None)
    part = _petg_panel()
    out = estimator.estimate_material(part)
    assert not out.get("unit_material_cost_gbp")
    assert not any("RESEARCHED indicative price" in f for f in part["review_flags"])


def test_a_material_with_a_rate_never_asks(monkeypatch):
    """The control, and the one that matters for every other job in the building: a material
    this engine CAN price must not reach the market rung at all."""
    called = []
    monkeypatch.setattr(estimator, "_researched_board_rate_m2",
                        lambda *a, **k: called.append(a) or None)
    part = dict(_petg_panel(), normalized_material="POLYCARBONATE",
                part_number="11650-01-05A", description="DOOR")
    assert config.MATERIAL_PRICE_GBP_PER_KG.get("POLYCARBONATE"), "the control has no rate"
    estimator.estimate_material(part)
    assert not called, "a priced material was sent to the market anyway"
