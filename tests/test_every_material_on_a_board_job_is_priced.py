"""Every material on a board job is priced, and the job's questions are only real ones (D-733).

12677-01-GA, 6 Nov 2026, 11:33 book, and the review of it:

  "Price 0.932 m of 20 mm VHB tape and the 9 mm black MFMDF locator from a suitable catalogue
   source or an explicitly justified provisional allowance. Removing wrong prices is necessary,
   but it does not fulfil 'price everything.'"
  "Both edging labour rows remain, but there is still no identifiable edging-material charge.
   The workbook also incorrectly says no edging callout exists, despite the drawing's edging
   instructions."
  "The email says one line has no price, yet both tape and locator material are zero. It also
   says the joint is unstated, although the drawing specifies VHB tape."

Synthetic records, a stand-in researcher and stand-in SDI Live rows; no job's files.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("SDI_OFFLINE", "1")

import edge_banding as eb                                                # noqa: E402
import estimator                                                         # noqa: E402
from owned_route_evidence import bonding_member, stated_bond             # noqa: E402


def _gel_tape():
    return {"part_number": "GEL TAPE", "description": "VHB GEL TAPE  233 × 20",
            "quantity": 4, "page_roles": ["bought_in"], "is_bought_in": True,
            "normalized_material": "BOUGHT_IN"}


def _always(**found):
    return lambda brief: dict(found)


ROLL_NO_LENGTH = {"price_gbp": 9.50, "unit": "roll", "source": "Example listing",
                  "as_of": "2026-11-06", "quantity_basis": "1 roll"}
ROLL_33M = {"price_gbp": 68.12, "unit": "roll", "source": "Example listing",
            "as_of": "2026-11-06", "quantity_basis": "1 roll of 33 m"}


# ── the tape: 0.932 m of 20 mm VHB ───────────────────────────────────────────────────

def test_sdi_lives_own_roll_row_comes_before_the_market(monkeypatch):
    monkeypatch.setattr(estimator, "_roll_by_its_length", lambda p: {
        "gbp_per_m": 1.90, "rows": [], "gap": "",
        "row": {"part_code": "TAPE-VHB19", "description": "3M VHB TAPE 19MM X 33M",
                "row_gbp": 62.70, "uom": "EA", "roll_m": 33.0, "width_mm": 19.0}})
    monkeypatch.setattr(estimator, "_rung4_researcher",
                        lambda b: pytest.fail("SDI's own roll answered; no research"))
    part = _gel_tape()
    r = estimator._resolve_part_system_cost(part)
    assert r["applied_unit_cost"] == pytest.approx(0.233 * 1.90, abs=1e-4)
    assert r["matched_part_code"] == "TAPE-VHB19"
    assert part["roll_goods_by_length"]["rate_from"] == "sdi_live"
    assert any("SDI Live TAPE-VHB19" in f for f in part["review_flags"])


def test_a_roll_price_that_states_its_length_is_divided_by_it(monkeypatch):
    monkeypatch.setattr(estimator, "_rung4_researcher", _always(**ROLL_33M))
    monkeypatch.setattr(estimator.config, "ROLL_GOODS_RESEARCHED_METRE_RATES", ())
    part = _gel_tape()
    r = estimator._resolve_part_system_cost(part)
    assert r["applied_unit_cost"] == pytest.approx(0.233 * 68.12 / 33.0, abs=1e-3)
    assert part["roll_goods_by_length"]["rate_from"] == "research_roll_length"
    assert any("a 33 m roll" in f for f in part["review_flags"])


def test_with_no_length_anywhere_the_dated_market_rate_prices_it(monkeypatch):
    monkeypatch.setattr(estimator, "_rung4_researcher", _always(**ROLL_NO_LENGTH))
    part = _gel_tape()
    r = estimator._resolve_part_system_cost(part)
    assert r["applied_unit_cost"] == pytest.approx(0.233 * 2.06, abs=1e-4)
    assert part["roll_goods_by_length"]["rate_from"] == "dated_market_rate"
    assert part["roll_goods_by_length"]["metres_per_unit"] == pytest.approx(0.932)
    ev = r["result"]["selected"]["metadata"]["evidence"]
    assert ev["source"] and ev["as_of"] and ev["unit_basis"] and ev["quantity_basis"], (
        "a researched figure carries its source, date, unit and quantity basis")
    assert "roll_goods_per_metre_unpriced" not in (part.get("risk_flags") or [])


def test_the_dated_rate_names_its_listings_and_is_in_date():
    import config
    (rate,) = [r for r in config.ROLL_GOODS_RESEARCHED_METRE_RATES if "VHB" in r["all_words"]]
    assert rate["gbp_per_m"] == pytest.approx(68.12 / 33.0, abs=0.01)
    assert rate["source"].count("£") == 5 and "33 m" in rate["source"]
    assert estimator._researched_metre_rate(_gel_tape()) is rate


def test_a_stale_market_rate_is_not_used(monkeypatch):
    import config
    old = dict(config.ROLL_GOODS_RESEARCHED_METRE_RATES[0], as_of="2025-01-01")
    monkeypatch.setattr(config, "ROLL_GOODS_RESEARCHED_METRE_RATES", (old,))
    monkeypatch.setattr(estimator, "_rung4_researcher", _always(**ROLL_NO_LENGTH))
    part = _gel_tape()
    assert estimator._resolve_part_system_cost(part)["applied_unit_cost"] is None
    assert "roll_goods_per_metre_unpriced" in part["risk_flags"]


def test_a_wider_tape_is_not_priced_on_the_narrow_rate():
    wide = dict(_gel_tape(), description="VHB TAPE 233 x 50")
    assert estimator._researched_metre_rate(wide) is None


# ── the 9 mm black MFMDF locator ─────────────────────────────────────────────────────

ROWS = {("MFMDF", 6.0): (9.49, "2440 X 1220 X 6MM MFMDF WHITE MATT"),
        ("MDF", 6.0): (3.00, "2440 X 1220 X 6MM MDF"),
        ("MDF", 9.0): (4.20, "2440 X 1220 X 9MM MDF")}


@pytest.fixture()
def sdi_boards(monkeypatch):
    def fake(material, t, part=None):
        k = (str(material).upper(), float(t or 0))
        if k not in ROWS:
            return None
        gbp, desc = ROWS[k]
        return {"rate_gbp_per_m2": gbp, "sample_count": 1, "product_reference_match": False,
                "rows": [{"part_code": f"{k[0]}{t:g}", "description": desc, "gbp_per_m2": gbp}]}
    monkeypatch.setattr(estimator, "_resolve_board_sheet_rate_gbp_per_m2", fake)


def test_a_faced_board_is_stepped_from_sdis_own_rows(sdi_boards):
    got = estimator._faced_board_by_core_step("MFMDF", 9.0)
    assert got["rate_gbp_per_m2"] == pytest.approx(9.49 + 4.20 - 3.00)
    step = got["core_step"]
    assert step["from_mm"] == 6.0 and step["core_word"] == "MDF"
    assert "£9.49 + (£4.20 - £3.00) = £10.69/m²" in step["working"]


def test_without_the_core_at_both_thicknesses_there_is_no_step(sdi_boards):
    assert estimator._faced_board_by_core_step("MFMDF", 12.0) is None


def test_the_locator_panel_is_priced_and_asked(sdi_boards):
    part = {"part_number": "T-03J", "description": "LOCATOR PANEL",
            "normalized_material": "MFMDF", "normalized_thickness_mm": 9.0,
            "blank_length_mm": 271.0, "blank_width_mm": 271.0, "quantity": 1}
    pe = estimator.estimate_part(part)
    area = 0.271 * 0.271
    assert pe["material_estimate"]["unit_material_cost_gbp"] == pytest.approx(
        area * 10.69 * 1.04, abs=0.01)
    assert any(f.startswith("FACED BOARD STEPPED FROM SDI'S OWN ROWS")
               for f in pe["review_flags"])
    assert any("10.69" in q["issue"] for q in part["manufacturing_questions"])


# ── the edging: the drawing's "N EDGED" dimension ────────────────────────────────────

def _panel(pn, size, words, colour):
    return {"part_number": pn, "normalized_material": "MFMDF", "_laminate_in_board": True,
            "normalized_thickness_mm": 9.0, "blank_length_mm": size, "blank_width_mm": size,
            "normalized_colour": colour, "quantity": 1, "edging_route_words": words}


def test_an_edged_dimension_over_a_square_blank_bands_all_four_edges():
    got = eb.banded_length_mm(_panel(
        "P-02J", 298.0, ["Part view also prints 300 EDGED and mirrored DEGDE."], "WHITE"))
    assert got["mm"] == 1192.0 and got["basis"] == "edged_dimension"
    assert got["edge_thickness_mm"] == 1.0
    assert "300 EDGED" in got["evidence"]


def test_an_edged_dimension_on_one_axis_bands_the_two_edges_across_it():
    part = {"blank_length_mm": 400.0, "blank_width_mm": 200.0,
            "edging_route_words": ["402 EDGED"]}
    got = eb.banded_length_mm(part)
    assert got["mm"] == 400.0, "the two 200 mm ends"


def test_a_dimension_that_is_not_the_blank_plus_edging_says_nothing():
    part = {"blank_length_mm": 400.0, "blank_width_mm": 200.0,
            "edging_route_words": ["EDGED", "450 EDGED"]}
    assert eb.banded_length_mm(part)["mm"] is None


def test_only_a_read_edging_route_puts_its_words_on_the_part():
    summary = {"llm_full_extract": {"routes": [
        {"operation": "edge_banding", "part_numbers": ["P-02J"],
         "notes": "Part view also prints 300 EDGED"},
        {"operation": "edge_banding", "part_numbers": ["P-04J"], "inferred": True,
         "notes": "probably EDGED"}]}}
    parts = [{"part_number": "P-02J"}, {"part_number": "P-04J"}]
    assert eb.stamp_edging_route_words(parts, summary) == 1
    assert parts[0]["edging_route_words"] == ["Part view also prints 300 EDGED"]
    assert "edging_route_words" not in parts[1]


def test_two_decors_make_two_edging_lines():
    parts = [_panel("P-02J", 298.0, ["300 EDGED"], "WHITE"),
             _panel("P-03J", 271.0, ["273 EDGED"], "BLACK")]
    summary = {"declared_product": "P-GA", "drawing_number": "P-GA",
               "manufacturing_writeup": {"parts": parts},
               "document_analysis": {"bom_rows": []}, "llm_full_extract": {}, "pages": []}
    estimator.estimate_document(parts, summary=summary)
    lines = {p["part_number"]: p for p in parts if p.get("_edging_line")}
    assert set(lines) == {"EDGE-ABS-WHITE", "EDGE-ABS-BLACK"}
    assert lines["EDGE-ABS-BLACK"]["_edging_for"] == ["P-03J"]
    assert lines["EDGE-ABS-BLACK"]["quantity"] == pytest.approx(1.084)
    assert lines["EDGE-ABS-WHITE"]["quantity"] == pytest.approx(1.192)
    assert "1 mm ABS edging to match BLACK" in lines["EDGE-ABS-BLACK"]["description"]
    assert "EDGED dimensions" in lines["EDGE-ABS-BLACK"]["description"]


# ── the joint: VHB tape on the assembly's own bill ───────────────────────────────────

def _assembly():
    return {"manufacturing_writeup": {"parts": [
        {"part_number": "T-101SA", "assembly_children": ["T-02J", "T-03J", "GEL TAPE"]},
        {"part_number": "GEL TAPE", "description": "VHB GEL TAPE"},
        {"part_number": "T-02J", "description": "TOP FINISHED PANEL"}]}}


def test_a_bonding_tape_on_the_bill_states_the_joint():
    assert bonding_member(_assembly(), "T-101SA") == "GEL TAPE (VHB GEL TAPE)"
    assert "its bill carries GEL TAPE" in stated_bond(_assembly(), "T-101SA")


def test_a_screw_on_the_bill_is_not_a_bond():
    s = {"manufacturing_writeup": {"parts": [
        {"part_number": "A", "assembly_children": ["B"]},
        {"part_number": "B", "description": "M6 x 12 SCREW"}]}}
    assert bonding_member(s, "A") == "" and stated_bond(s, "A") == ""


# ── the e-mail: every £0 line is counted ─────────────────────────────────────────────

def test_the_email_counts_the_sheet_rows_with_no_price(monkeypatch, tmp_path):
    import estimate_explained as ee
    sib = importlib.import_module("test_the_covering_note_says_what_the_estimate_costs")
    real = ee._gather

    def gather(workbook, scan_json):
        g = real(workbook, scan_json)
        rec = dict(g.get("record") or {})
        rec["decisions_required"] = list(rec.get("decisions_required") or []) + [
            {"kind": "missing_price", "part": "06A", "issue": "06A carries no price",
             "action": "supply a rate or a supplier quote"}]
        return dict(g, record=rec)
    monkeypatch.setattr(ee, "_gather", gather)
    note = ee.covering_email(sib._workbook(tmp_path / "j.xlsx"), sib._scan(tmp_path / "j.json"),
                             client="x")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", note["html"]))
    assert "2 lines carry no price" in text, "BI-SCREW on the bill and 06A on the sheet"
    assert "06A carries no price" in text
