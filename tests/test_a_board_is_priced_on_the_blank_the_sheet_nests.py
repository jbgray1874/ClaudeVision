"""A board is priced on the blank the sheet nests, and the joint adhesive on SDI's own tin.

D-724. 11908-22-GA, 5 Nov 2026, 21:49 book: three laminated MDF panels were priced on 340 x 400,
350 x 400 and 304 x 400. The top-level blank still held the two largest numbers in the page text
while the measured DXF flat (340 x 290, 350 x 28, 300 x 28) sat where the sheet read it, so the
sheet turned the engine's money back into a sheet price on the true area: a 350 x 28 strip at
GBP 966 a sheet, its neighbour at GBP 1,510.

D-725. The same run's adhesive allowance (50 g) reached the sheet unpriced: no catalogue row is
called "PVA wood adhesive 1kg" and the market lookup came back empty. SDI Live's adhesive rows
now price it by the kilo, the laminate bond the shop buys standing in, declared, where no wood
adhesive is held.

Synthetic records, made-up part numbers and a drawn rectangle; no job's files.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator                                                         # noqa: E402
from joinery_consumables import mint                                     # noqa: E402

GUESSED = "document_text_largest_numbers"


def _strip_dxf(tmp_path: Path, length: float = 350, width: float = 28) -> Path:
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    pts = [(0, 0), (length, 0), (length, width), (0, width), (0, 0)]
    for a, b in zip(pts, pts[1:]):
        msp.add_line(a, b)
    path = tmp_path / "T-02J_9mm_MDF_REVB.dxf"
    doc.saveas(path)
    return path


# ── D-724: the measured flat replaces a guessed blank ────────────────────────────────


def test_a_measured_flat_replaces_the_page_texts_guess(tmp_path):
    from drawing_job_merge import apply_dxf_geometry_to_part
    part = {"part_number": "T-02J", "normalized_material": "MDF",
            "blank_length_mm": 400.0, "blank_width_mm": 350.0,
            "blank_length_mm_source": GUESSED, "blank_width_mm_source": GUESSED}
    apply_dxf_geometry_to_part(part, _strip_dxf(tmp_path))
    assert (part["blank_length_mm"], part["blank_width_mm"]) == (350.0, 28.0)
    assert part["blank_length_mm_source"] == "dxf_flat_pattern"
    assert part["blank_width_mm_source"] == "dxf_flat_pattern"


def test_a_models_flat_is_not_displaced_by_the_dxf(tmp_path):
    from drawing_job_merge import apply_dxf_geometry_to_part
    part = {"part_number": "T-02J", "normalized_material": "MDF",
            "blank_length_mm": 351.0, "blank_width_mm": 29.0,
            "blank_length_mm_source": "solidworks_api",
            "blank_width_mm_source": "solidworks_api"}
    apply_dxf_geometry_to_part(part, _strip_dxf(tmp_path))
    assert (part["blank_length_mm"], part["blank_width_mm"]) == (351.0, 29.0)
    assert part["blank_length_mm_source"] == "solidworks_api"


def test_an_empty_blank_stays_as_it_was(tmp_path):
    """Only a held, weaker blank is replaced; the field is not newly invented here."""
    from drawing_job_merge import apply_dxf_geometry_to_part
    part = {"part_number": "T-02J", "normalized_material": "MDF"}
    apply_dxf_geometry_to_part(part, _strip_dxf(tmp_path))
    assert "blank_length_mm_source" not in part


def _priced_strip(rate_key, **part_extra):
    estimator._RESEARCHED_BOARD_RATE_CACHE[rate_key] = {
        "unit_price_gbp": 18.0, "price_gbp": 18.0, "status": "indicative"}
    part = {"part_number": "T-02J", "normalized_material": "MFMDF",
            "normalized_geometry": {"blank_length_mm": 350.0, "blank_width_mm": 28.0},
            "blank_length_mm": 400.0, "blank_width_mm": 350.0,
            "blank_length_mm_source": GUESSED, "blank_width_mm_source": GUESSED}
    part.update(part_extra)
    try:
        return estimator._researched_board_rate_m2("MFMDF", 9.0, part)
    finally:
        estimator._RESEARCHED_BOARD_RATE_CACHE.pop(rate_key, None)


def test_the_researched_board_rate_is_applied_to_the_measured_flat():
    out = _priced_strip(("MFMDF", 9.0, ""))
    assert out is not None
    # 350 x 28 = 0.0098 m2 at GBP 18 a m2, not 400 x 350 = 0.14 m2
    assert out["price_gbp"] == pytest.approx(0.1764, abs=1e-4)
    assert "0.0098 square metre" in out["calculation"]["working"]


def test_with_no_measured_flat_the_held_blank_still_prices():
    out = _priced_strip(("MFMDF", 9.0, ""), normalized_geometry={},
                        blank_length_mm_source="drawing_deterministic",
                        blank_width_mm_source="drawing_deterministic")
    assert out["price_gbp"] == pytest.approx(18.0 * 0.14, abs=1e-4)


# ── D-725: the joint adhesive is priced from SDI's own tins ──────────────────────────


def _adhesive_line():
    parts = [{"part_number": "T-GA", "assembly_children": ["T-01J", "T-02J"]},
             {"part_number": "T-01J", "normalized_material": "MDF", "quantity": 1},
             {"part_number": "T-02J", "normalized_material": "MDF", "quantity": 4}]
    mint(parts, {"pages": []})
    return next(p for p in parts if p["part_number"] == "T-GA-ADHESIVE")


def _tins(**by_word):
    """A stand-in for SDI Live: the first word of each spec picks the row, if any."""
    def fake(spec, unit):
        row = by_word.get(str((spec.get("all_words") or [""])[0]).upper())
        if not row:
            return {"gbp_per_unit": None, "unit": unit, "row": None, "rows": [], "gap": "none"}
        return {"gbp_per_unit": row["pack_gbp"] / row["pack_size"], "unit": unit,
                "row": row, "rows": [row], "gap": ""}
    return fake


PVA = {"part_code": "GLU-PVA5", "description": "PVA WOOD GLUE 5KG", "pack_gbp": 20.0,
       "pack_size": 5.0, "pack_unit": "kg"}
CONTACT = {"part_code": "GLU-CON5", "description": "CONTACT ADHESIVE 5KG TIN",
           "pack_gbp": 40.0, "pack_size": 5.0, "pack_unit": "kg"}


def test_the_minted_line_carries_its_mass_and_the_rows_to_price_it():
    glue = _adhesive_line()
    share = glue["consumable_share"]
    assert share["count"] == 0.05 and share["pack_kg"] == 1.0
    assert [s["all_words"][0] for s in share["catalogue_specs"]][0] == "PVA"
    assert share["catalogue_specs"][-1].get("stand_in") is True


def test_sdis_own_pva_prices_the_allowance_by_the_kilo(monkeypatch):
    monkeypatch.setattr(estimator, "_adhesive_by_its_pack", _tins(PVA=PVA, CONTACT=CONTACT))
    monkeypatch.setattr(estimator, "_resolve_part_system_cost",
                        lambda p: pytest.fail("the market chain must not be asked"))
    glue = _adhesive_line()
    r = estimator._consumable_share_cost(glue)
    assert r["applied_unit_cost"] == pytest.approx(0.05 * 4.0)      # 50 g at GBP 4 a kg
    assert r["matched_part_code"] == "GLU-PVA5"
    assert "STAND-IN" not in " ".join(glue["review_flags"])
    assert glue["consumable_share_priced_by"]["kg_used"] == 0.05


def test_with_no_wood_adhesive_the_laminate_bond_stands_in_and_says_so(monkeypatch):
    monkeypatch.setattr(estimator, "_adhesive_by_its_pack", _tins(CONTACT=CONTACT))
    glue = _adhesive_line()
    r = estimator._consumable_share_cost(glue)
    assert r["applied_unit_cost"] == pytest.approx(0.05 * 8.0)      # 50 g at GBP 8 a kg
    flag = " ".join(glue["review_flags"])
    assert "STAND-IN" in flag and "GLU-CON5" in flag
    assert glue["consumable_share_priced_by"]["stand_in"] is True
    assert "consumable_share_unpriced" not in (glue.get("risk_flags") or [])


def test_with_no_tin_at_all_the_ordinary_chain_is_asked(monkeypatch):
    monkeypatch.setattr(estimator, "_adhesive_by_its_pack", _tins())
    monkeypatch.setattr(estimator, "_resolve_part_system_cost",
                        lambda p: {"applied_unit_cost": 6.0, "result": {}})
    glue = _adhesive_line()
    assert estimator._consumable_share_cost(glue)["applied_unit_cost"] == pytest.approx(0.3)


def test_a_share_with_no_stated_mass_keeps_the_pack_path(monkeypatch):
    """The wax is priced per stick, not by the kilo: no tin lookup is made for it."""
    monkeypatch.setattr(estimator, "_adhesive_by_its_pack",
                        lambda s, u: pytest.fail("a stick is not priced by the kilo"))
    monkeypatch.setattr(estimator, "_resolve_part_system_cost",
                        lambda p: {"applied_unit_cost": 2.5, "result": {}})
    part = {"part_number": "T-GA-WAX", "description": "wax",
            "consumable_share": {"reference_item": "hard wax filler stick", "count": 0.1,
                                 "working": "w", "basis": "b", "pack_kg": None,
                                 "catalogue_specs": []}}
    assert estimator._consumable_share_cost(part)["applied_unit_cost"] == pytest.approx(0.25)
