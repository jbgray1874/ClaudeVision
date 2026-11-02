"""A researched figure buys what its own answer says it buys (SCRUM-182, SCRUM-100).

TWO WAYS 12678-01-GA WAS UNDERPRICED BY ANSWERS READ AS SOMETHING ELSE:

THE BUYING UNIT (SCRUM-182). The lookup asked for a full sheet and the answer priced a
blank-sized piece at £7.50; the figure was stamped gbp_per_sheet, the workbook wrote it
into the Cost per sheet column, and the template divided a per-PIECE price by 24 parts a
sheet — six laminated shelves for £1.95. cut_piece_pricing already holds this discipline
for length-bought stock (D-441/D-442): the answer's own unit and words say what was
priced. The same now holds for sheet goods, and the charged cell is cross-checked so a
"sheet" price that does not hand back the engine's per-part money under the row's nest
is replaced by the per-part money times the nest, loudly.

THE MATERIAL (SCRUM-100). The spine's researched allowance described softwood PAR stock
and the top's an 18 mm birch plywood sheet, against questions asking for MDF — and both
were charged with MDF written beside them. The charged item, not just its label, has to
match the specification: an answer naming a different family is refused and the line
stays an honest gap with the clash on it.

AND THE STATED WEIGHT BELONGS TO THE SELECTED PRODUCT (SCRUM-178 tightening): the
heaviest figure anywhere in a pack can be another variant's, so pages naming the
declared product answer first, and an unmatched figure says so.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator  # noqa: E402
import indicative_price  # noqa: E402
import size_reading  # noqa: E402
import web_ai_price_lookup as wap  # noqa: E402


# ── the sheet rate respects the answer's own unit ────────────────────────────────────

def _stub_lookup(monkeypatch, **result):
    base = {"found": True, "price_gbp": 7.50, "unit": "each", "price_basis": "",
            "item_priced": "", "confidence": 0.5, "source_type": "llm"}
    base.update(result)
    monkeypatch.setattr(wap, "lookup_web_ai_price", lambda spec, **kw: dict(base))


def test_an_answer_that_priced_a_piece_is_refused_as_a_sheet(monkeypatch):
    _stub_lookup(monkeypatch, item_priced="350 x 250 mm MDF blank, one piece")
    assert wap.market_sheet_rate_indication("MDF", 18, 2440, 1220) is None


def test_a_per_kg_or_per_metre_answer_is_refused_as_a_sheet(monkeypatch):
    _stub_lookup(monkeypatch, unit="per_kg")
    assert wap.market_sheet_rate_indication("MDF", 18, 2440, 1220) is None
    _stub_lookup(monkeypatch, unit="per_metre")
    assert wap.market_sheet_rate_indication("MDF", 18, 2440, 1220) is None


def test_a_per_m2_answer_is_converted_to_the_sheet_it_was_asked_about(monkeypatch):
    _stub_lookup(monkeypatch, unit="per_m2", price_gbp=10.0)
    got = wap.market_sheet_rate_indication("MDF", 18, 2000, 1000)
    assert got is not None
    assert got["gbp_per_sheet"] == pytest.approx(20.0)     # 2 m2 x £10/m2
    assert got["gbp_per_m2"] == pytest.approx(10.0)


def test_a_sheet_answer_is_taken_as_the_sheet(monkeypatch):
    _stub_lookup(monkeypatch, price_gbp=54.0,
                 item_priced="full 2440 x 1220 sheet of 18mm MDF, trade")
    got = wap.market_sheet_rate_indication("MDF", 18, 2440, 1220)
    assert got is not None and got["gbp_per_sheet"] == 54.0
    assert got["unit_said"] == "EACH"


# ── the answer must describe the material it was asked for ──────────────────────────

def test_the_family_clash_is_read_from_the_answers_own_words():
    clash = estimator._material_answer_clash
    assert clash("MDF", "softwood PAR stock, 2.4 m") == "TIMBER"
    assert clash("MDF", "18mm birch plywood sheet") in ("PLYWOOD", "PLYWOOD / TIMBER")
    assert clash("MDF", "moisture resistant MDF board") == ""
    assert clash("TIMBER", "pine PAR 45x45") == ""
    assert clash("MDF", "a sheet of board, trade price") == ""
    assert clash("", "softwood PAR") == ""


def _spine():
    return {"part_number": "12678-01-02J", "description": "SPINE", "quantity": 1,
            "normalized_material": "MDF"}


def test_an_allowance_answered_about_another_material_is_refused(monkeypatch):
    monkeypatch.setattr(indicative_price, "resolve_indicative",
                        lambda *a, **kw: {"price_gbp": 11.98, "status": "provisional",
                                          "item_priced": "softwood PAR stock, 2.4 m length"})
    pe = _spine()
    assert estimator._made_part_material_allowance(pe) is None
    assert any("describes TIMBER" in f for f in pe["review_flags"])
    assert any("answered about TIMBER" in str(q.get("issue"))
               for q in pe["manufacturing_questions"])


def test_an_allowance_for_the_asked_material_is_charged(monkeypatch):
    monkeypatch.setattr(indicative_price, "resolve_indicative",
                        lambda *a, **kw: {"price_gbp": 20.0, "status": "provisional",
                                          "item_priced": "18mm MDF sheet stock",
                                          "evidence": {"source": "x"}})
    pe = _spine()
    assert estimator._made_part_material_allowance(pe) == 20.0
    assert pe["_last_resort_result"]["selected"]["price"] == 20.0


# ── the charged cell is cross-checked, and a conflict prices nothing ────────────────

def test_the_conflict_detector_is_a_suspicion_not_a_rebuild():
    import wb_populate as wb
    # £7.50 claiming to be a sheet of 24 parts the engine costs at £2.50 each: conflict.
    assert wb._buying_unit_conflict(7.50, 2.50, 24) is True
    # £54 a sheet of the same parts divides back to £2.25 — consistent, no conflict.
    assert wb._buying_unit_conflict(54.0, 2.50, 24) is False
    # A nest of one is a per-part allowance travelling correctly: never a conflict.
    assert wb._buying_unit_conflict(7.50, 7.50, 1) is False
    assert wb._buying_unit_conflict(None, 2.50, 24) is False


def test_a_conflicting_sheet_price_is_left_off_the_sheet_not_synthesised():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    seg = src[src.index("def _write_board_row"):]
    seg = seg[:seg.index("\n    row = ")]
    assert "CONFLICTING BUYING BASES" in seg
    assert "_buying_unit_conflict(_sheet_price, _cpp_chk, _pps_chk)" in seg
    assert "_sheet_price = None" in seg
    # And no synthetic sheet rate is manufactured to reproduce the engine's number.
    assert "SUSPECTED BUYING-UNIT ERROR" not in seg


def test_the_verified_reconstruction_survives_the_templates_scrap_arithmetic():
    """The pre-existing reconstruction (engine per-part money -> sheet cell) divides by
    (1 + scrap) BECAUSE the template multiplies by it: M = (L / J) x (1 + K) x D. A
    £2.50 part in a nest of 24 at 4% scrap writes £57.69, and the template's own
    arithmetic hands back £2.50 a part — not £2.60."""
    cpp, pps, scrap = 2.50, 24, 0.04
    sheet_cell = round(cpp * pps / (1.0 + scrap), 2)
    assert sheet_cell == pytest.approx(57.69, abs=0.01)
    charged_per_part = sheet_cell / pps * (1.0 + scrap)
    assert charged_per_part == pytest.approx(cpp, abs=0.005)
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    seg = src[src.index("def _write_board_row"):]
    assert "/ (1.0 + float(_scrap_frac))" in seg


# ── missing wording is never a presumed match ────────────────────────────────────────

def test_an_answer_that_names_nothing_is_unverified_and_said_so(monkeypatch):
    monkeypatch.setattr(indicative_price, "resolve_indicative",
                        lambda *a, **kw: {"price_gbp": 20.0, "status": "provisional",
                                          "item_priced": "stock sheet, trade price",
                                          "evidence": {"source": "x"}})
    pe = _spine()
    assert estimator._made_part_material_allowance(pe) == 20.0
    assert any("COMPATIBILITY UNVERIFIED" in f for f in pe["review_flags"])


def test_a_raw_core_answer_is_incompatible_with_the_faced_board():
    state, why = estimator._material_answer_state("MFMDF", 18, "18mm MDF sheet, trade")
    assert state == "incompatible"
    assert "raw core" in why


def test_a_different_gauge_is_a_contradiction_and_the_same_gauge_is_not():
    assert estimator._material_answer_state("MDF", 18, "25mm MDF sheet")[0] == "incompatible"
    assert estimator._material_answer_state("MDF", 18, "18mm MDF sheet")[0] == "compatible"
    assert estimator._material_answer_state("MDF", 18, "MDF sheet stock")[0] == "compatible"
    assert estimator._material_answer_state("MDF", 18, "")[0] == "unverified"


# ── the stated weight belongs to the selected product ───────────────────────────────

def test_the_weight_belongs_to_the_declared_product():
    summary = {"declared_product": "12678-01-GA", "pages": [
        {"page_number": 1,
         "pypdf_text": "12678-01-GA EDITIONS FOOTWEAR PODIUM WEIGHT: 33.07kg"},
        {"page_number": 2, "pypdf_text": "12699-09-GA ANOTHER VARIANT WEIGHT: 90kg"},
    ]}
    sw = size_reading.stated_product_weight_kg(summary)
    assert sw["kg"] == pytest.approx(33.07)
    assert sw["where"] == "page 1"
    assert sw["verified"] is True


def test_an_unmatched_weight_is_unverified_not_authoritative():
    summary = {"declared_product": "12678-01-GA", "pages": [
        {"page_number": 3, "pypdf_text": "REFERENCE FIXTURE WEIGHT: 90kg"}]}
    sw = size_reading.stated_product_weight_kg(summary)
    assert sw["kg"] == pytest.approx(90.0)
    assert sw["verified"] is False
    assert "not matched to the declared product 12678-01-GA" in sw["where"]


def test_an_unverified_weight_never_drives_the_shipment():
    """A warning string is not authority: the measured figure stands, and the unused
    stated figure rides as an open question the covering note prints."""
    import commercial_lines as cl
    parts = [{"blank_length_mm": 520.0, "blank_width_mm": 370.0,
              "normalized_thickness_mm": 2.5, "normalized_material": "MDF",
              "quantity": 1, "part_number": "P1"},
             {"part_number": "P2", "description": "SPINE"}]
    o = cl.describe_order(parts, 1, stated_weight={"kg": 33.07, "where": "page 3",
                                                   "verified": False})
    assert o["stated_unit_weight_kg"] is None
    assert o["weight_basis"] is None
    assert o["unit_weight_kg"] != pytest.approx(33.07)
    assert "does NOT drive the shipment" in o["stated_weight_unverified"]


def test_without_a_declared_product_the_heaviest_still_answers():
    summary = {"pages": [{"page_number": 1, "pypdf_text": "WEIGHT: 33.07kg"},
                         {"page_number": 2, "pypdf_text": "WEIGHT: 2068g"}]}
    sw = size_reading.stated_product_weight_kg(summary)
    assert sw["kg"] == pytest.approx(33.07) and sw["where"] == "page 1"
    assert sw["verified"] is True
