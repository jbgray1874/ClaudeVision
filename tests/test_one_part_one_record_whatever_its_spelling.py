"""One part, one record, however its number is spelt; a drawing number is not an article; and a
line that says its money is elsewhere carries none (D-748).

0358141, 7 Nov 2026 22:17. The parts list reads "UPC0358141 M4" and the part's own sheet, whose
PDF text has its spaces stripped ("MILDSTEELBALLAST", "CUTOUTTHRUALL"), reads "UPC0358141M4".
Keyed by the literal string, every detail sheet minted a second record that held its geometry
and was never priced; the listed records bound to the parts list ("no page in this pack details
it") and the upright and three end caps were each priced as 1,400 mm of 30 x 15 x 2 tube:
GBP 136.60, 88% of the material. The report bound parts to pages 2 and 3 of a ten-page pack.

The same parts were then written up as "SAME ARTICLE AS UPC0358141 M2" because the drawing
number at the front of each part number was read as a manufacturer reference, and still
carried their GBP 13.66, because a fabricated leaf is priced from its material estimate.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import part_index as pi  # noqa: E402
import supplier_reference as sref  # noqa: E402


def _row(pn, desc, qty):
    return {"part_number": pn, "description": desc, "quantity": qty, "source": "BOTH",
            "bom_sheet": "pack.pdf#1"}


def _table_page(number, text):
    return {"page_number": number, "page_role": {"primary_role": "assembly"},
            "pattern_summary": {"part_numbers": []}, "geometry_summary": {},
            "normalized_text": text,
            "page_analysis": {"title_block": {"drawing_numbers": ["UPC0358141 M1"]}}}


def _detail_page(number, drawing_number, material="STAINLESS STEEL", thickness="3"):
    return {"page_number": number, "page_role": {"primary_role": "detail"},
            "pattern_summary": {"part_numbers": []}, "geometry_summary": {},
            "normalized_text": f"{drawing_number}ENDCAP{material.replace(' ', '')}{thickness}MM",
            "page_analysis": {"title_block": {
                "drawing_numbers": [drawing_number], "materials": [material],
                "thicknesses_mm": [thickness],
                "normalized": {"primary_material": material.replace(" ", "_"),
                               "primary_thickness_mm": float(thickness)}}}}


def _index(pages, rows):
    from document_builder import build_part_index
    return build_part_index({"pages": pages, "document_analysis": {"bom_rows": rows}})


# ── one part, one record ────────────────────────────────────────────────────────────────

def test_a_detail_sheet_binds_to_its_listed_part_however_the_number_is_spelt():
    rows = [_row("UPC0358141 M5", "ENDCAP", 2)]
    parts = _index([_table_page(3, "UPC0358141 M5 ENDCAP 2"), _detail_page(7, "UPC0358141M5")], rows)
    named = [p["part_number"] for p in parts]
    assert "UPC0358141M5" not in named                          # no second record
    m5 = next(p for p in parts if p["part_number"] == "UPC0358141 M5")
    assert 7 in m5["pages"] and m5.get("quantity") == 2
    assert "STAINLESS" in str(m5.get("materials")).upper()      # its own sheet's material
    assert not any("is bound to page" in str(f) for f in m5.get("review_flags") or [])


def test_two_listed_parts_that_spell_alike_are_never_made_one():
    parts = {"A 1": {}, "A1": {}}
    assert pi._the_listed_spelling("A1", parts) == "A1"         # exact wins
    assert pi._the_listed_spelling("A  1", {"A 1": {}, "A-1 ": {}}) == "A 1"
    assert pi._the_listed_spelling("ZZ9", {"A 1": {}}) == "ZZ9"  # nothing answers: unchanged


def test_a_page_names_a_code_with_or_without_its_spaces_but_m1_is_not_m10():
    assert pi._page_mentions("UPC0358141 M1", "UPC0358141 M1 RAIL")
    assert pi._page_mentions("UPC0358141 M1", "TITLEUPC0358141M1RAIL")
    assert not pi._page_mentions("UPC0358141 M1", "TITLE UPC0358141M10 RAIL")
    assert not pi._page_mentions("UPC0358141 M1", "")


# ── a drawing number is not an article ──────────────────────────────────────────────────

def test_the_drawing_number_at_the_front_of_a_part_number_is_not_its_identity():
    assert sref.identity_keys({"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP"}) == set()
    assert sref.identity_keys({"part_number": "HAFELE 651.09.302", "description": "Leveller"}) == {"651.09.302"}
    rows = [{"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP", "unit_cost_gbp": 3.5},
            {"part_number": "UPC0358141 M3", "description": "SHORT RUB STRIP"},
            {"part_number": "UPC0358141 M4", "description": "UPRIGHT"},
            {"part_number": "UPC0358141 M5", "description": "ENDCAP"}]
    assert sref.same_article_groups(rows) == []


def test_a_real_second_name_for_one_article_is_still_found():
    rows = [{"part_number": "ESSENTRA FOOT-466122", "description": "Levelling foot"},
            {"part_number": "FIXING1081", "description": "Essentra 466122 levelling foot",
             "supplier_references": [{"reference": "466122"}]}]
    assert sref.same_article_groups(rows) == [[0, 1]]


# ── a line that says its money is elsewhere carries none ────────────────────────────────

def test_a_line_marked_the_same_article_carries_no_money_however_it_was_priced():
    import wb_populate as wp
    leaf = {"part_number": "UPC0358141 M4", "_canonical_kind": "leaf",
            "material_estimate": {"unit_material_cost_gbp": 13.66}}
    assert wp._bom_line_price(leaf) == 13.66
    price, trace = wp._bom_line_price_traced({**leaf, "_duplicate_of": "UPC0358141 M2"})
    assert price == 0.0 and "costed on that line" in trace[-1]
