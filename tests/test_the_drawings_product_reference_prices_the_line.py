"""12173-02 Card Spinner (D-386): the MFC back 12173-03-03J went out at £0 on four books while
its own title block named the product — UNILIN MINNESOTA OAK WARM NATURAL 0H440 (Z5L). The
price ladder asked SDI Live for "MFC" and the market for "18mm MFC board", and a per-sheet
answer was refused for being per sheet.

Generic rule: every line's product reference (colour, finish, printed material cell) is read
once; SDI Live is probed by its codes and decor words before the material word; the research
brief carries it; a per-sheet answer for a board is converted with the engine's own stock sheet.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as e                                                 # noqa: E402
import indicative_price as ip                                         # noqa: E402
import product_reference as pr                                        # noqa: E402

DECOR = "UNILIN MINNESOTA OAK WARM NATURAL 0H440 MINNESOTA OAK (Z5L)"


# ── reading the reference ────────────────────────────────────────────────────────────────

def test_codes_and_decor_words_are_read_and_qualifiers_are_not():
    ref = pr.product_reference({"colours": [DECOR], "surface_finishes": ["N/A"]})
    assert ref["codes"] == ["0H440", "Z5L"]
    assert ref["words"][:3] == ["MINNESOTA", "UNILIN", "OAK"]
    assert "NATURAL" not in ref["words"] and "WARM" not in ref["words"]
    assert "N/A" not in ref["text"]


def test_a_colour_standard_and_a_size_are_not_product_codes():
    ref = pr.product_reference({"colours": ["RAL9005 - JET BLACK", "RAL 7016"],
                                "surface_finishes": ["POWDER COATED - MATT"],
                                "description": "UPC STICKER; 15x10mm"})
    assert ref["codes"] == []
    assert ref["words"] == []


def test_a_part_with_nothing_printed_has_no_reference():
    assert pr.product_reference({"part_number": "X-01M"}) == {"text": "", "codes": [], "words": []}
    assert pr.reference_probes({"colours": [DECOR]}) == ["0H440", "Z5L", "MINNESOTA", "UNILIN", "OAK"]


# ── the brief carries it ─────────────────────────────────────────────────────────────────

def test_the_research_brief_carries_the_product():
    b = ip.research_brief({"description": "18mm MFC board", "quantity": 0.42,
                           "unit_of_measure": "m2", "colour": DECOR, "finish": None,
                           "product_reference": DECOR, "sheet_mm": [3080, 1220],
                           "material": "MFC"})
    assert b["colour"] == DECOR and b["sheet_mm"] == [3080, 1220] and b["material"] == "MFC"
    assert "finish" not in b


# ── a per-sheet answer becomes the £/m² the line is bought by ────────────────────────────

def _lookup(unit, price=60.0):
    def fake(spec, **kw):
        fake.spec = spec
        return {"found": True, "price_gbp": price, "unit": unit, "source_url": "https://x.test/l",
                "price_date": "2026-10-02", "price_basis": "1 sheet",
                "price_is_reproducible": True, "source_type": "web_search"}
    return fake


def test_a_sheet_price_is_divided_by_the_stock_sheet(monkeypatch):
    import web_ai_price_lookup as w
    monkeypatch.setattr(w, "lookup_web_ai_price", _lookup("each"))
    got = e._rung4_researcher({"description": "18mm MFC board", "wanted_unit": "square metre",
                               "sheet_mm": [3080, 1220], "colour": DECOR, "code": "0H440",
                               "material": "MFC"})
    assert abs(got["price_gbp"] - 60.0 / (3.08 * 1.22)) < 0.01
    assert got["unit"] == "per_m2" and "3080 x 1220" in got["quantity_basis"]
    assert w.lookup_web_ai_price.spec["colour"] == DECOR
    assert w.lookup_web_ai_price.spec["part_code"] == "0H440"


def test_a_per_m2_answer_or_no_sheet_is_left_alone(monkeypatch):
    import web_ai_price_lookup as w
    monkeypatch.setattr(w, "lookup_web_ai_price", _lookup("per_m2", 16.0))
    got = e._rung4_researcher({"description": "x", "wanted_unit": "square metre",
                               "sheet_mm": [3080, 1220]})
    assert got["price_gbp"] == 16.0
    monkeypatch.setattr(w, "lookup_web_ai_price", _lookup("each", 60.0))
    got = e._rung4_researcher({"description": "x", "wanted_unit": "square metre"})
    assert got["price_gbp"] == 60.0 and got["unit"] == "each"   # the producer will refuse it


# ── SDI Live is asked by the reference first ─────────────────────────────────────────────

class _Cur:
    def __init__(self, rows_by_token):
        self.rows_by_token = rows_by_token
        self.rows = []

    def execute(self, sql, params):
        tok = str(params[0]).strip("%")
        self.rows = self.rows_by_token.get(tok, [])

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, rows_by_token):
        self._c = _Cur(rows_by_token)

    def cursor(self):
        return self._c

    def close(self):
        pass


def test_the_catalogue_row_carrying_the_drawings_code_wins(monkeypatch):
    import config
    rows = {"0H440": [("UNI0H440", "UNILIN MFC 0H440 MINNESOTA OAK 2800 x 2070 x 18mm", 66.0)],
            "MFC": [("MFCW18", "MFC WHITE 2800 x 2070 x 18mm", 40.0)]}
    monkeypatch.setattr(config, "get_connection", lambda timeout=20: _Conn(rows), raising=False)
    e._SHEET_RATE_CACHE.clear()
    part = {"colours": [DECOR]}
    got = e._resolve_board_sheet_rate_gbp_per_m2("MFC", 18, part)
    assert got and got["product_reference_match"] is True
    assert got["material_token"] == "0H440"
    assert abs(got["rate_gbp_per_m2"] - 66.0 / (2.8 * 2.07)) < 0.05
    plain = e._resolve_board_sheet_rate_gbp_per_m2("MFC", 18, {"colours": []})
    assert plain and plain["product_reference_match"] is False
    assert abs(plain["rate_gbp_per_m2"] - 40.0 / (2.8 * 2.07)) < 0.05


# ── end to end: the board is priced, and per product ─────────────────────────────────────

def _board(code, colour):
    return {"part_number": code, "description": "BACK PANEL", "normalized_material": "MFC",
            "normalized_thickness_mm": 18, "quantity": 2, "blank_length_mm": 1470,
            "blank_width_mm": 288, "colours": [colour], "dxf_augmented": True,
            "normalized_geometry": {"blank_length_mm": 1470, "blank_width_mm": 288,
                                    "geometry_source": "dxf_flat_pattern"},
            "textual_operations": ["cnc_routing"]}


def test_the_mfc_back_is_priced_from_research_with_its_product_named(monkeypatch):
    import web_ai_price_lookup as w
    monkeypatch.setattr(w, "lookup_web_ai_price", _lookup("each"))
    e._RESEARCHED_BOARD_RATE_CACHE.clear()
    e._SHEET_RATE_CACHE.clear()
    r = e.estimate_part(_board("X-03J", DECOR), job_quantity=1)
    me = r["material_estimate"]
    assert me["cost_method"] == "board_rate_researched"
    assert me["unit_material_cost_gbp"] and me["unit_material_cost_gbp"] > 0
    assert "0H440" in w.lookup_web_ai_price.spec["description"]
    assert "3080 x 1220 mm sheet" in w.lookup_web_ai_price.spec["description"]
    assert any("RESEARCHED indicative price" in f for f in r["review_flags"])


def test_two_decors_of_one_board_are_two_rates(monkeypatch):
    import web_ai_price_lookup as w
    calls = []

    def fake(spec, **kw):
        calls.append(spec["description"])
        return {"found": True, "price_gbp": 60.0, "unit": "each", "source_url": "https://x.test",
                "price_date": "2026-10-02", "price_basis": "1 sheet",
                "price_is_reproducible": True, "source_type": "web_search"}
    monkeypatch.setattr(w, "lookup_web_ai_price", fake)
    e._RESEARCHED_BOARD_RATE_CACHE.clear()
    e._SHEET_RATE_CACHE.clear()
    e.estimate_part(_board("X-03J", DECOR), job_quantity=1)
    e.estimate_part(_board("X-04J", "EGGER W1000 PREMIUM WHITE"), job_quantity=1)
    e.estimate_part(_board("X-05J", DECOR), job_quantity=1)
    assert len(calls) == 2, calls                      # the oak once, the white once
