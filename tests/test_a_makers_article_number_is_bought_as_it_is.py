"""A supplier's article number, with the maker's name in front, is a purchase (SCRUM-194).

0358141's parts list carries "HAFELE 651.09.302 / M8 x 22 Base Leveller" with no sheet of its
own. Read without a model, it inherited the rail's MILD STEEL and the deterministic ledger held
it as a made part; the LLM read had flagged it bought-in, so the gap only showed once the model
was off. The rule is the shape of the code, never the name: a dotted article number names
something bought, and measured geometry of the part's own still outranks it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bought_in_policy as bp  # noqa: E402
import drawing_read_ledger as drl  # noqa: E402
import part_code_conventions as pcc  # noqa: E402


def test_a_dotted_article_with_or_without_the_makers_name_is_an_article_and_a_revision_is_not():
    assert pcc.is_supplier_article("HAFELE 651.09.302")
    assert pcc.is_supplier_article("651.09.302")
    assert pcc.is_supplier_article("Hafele651.02.909")
    assert not pcc.is_supplier_article("REV1.2"), "a revision mark is not an article"
    assert not pcc.is_supplier_article("UPC0358141 M4")
    assert not pcc.is_supplier_article("12349-02-69-100")
    assert pcc.drawing_family("HAFELE 651.09.302") == ""


def test_the_leveller_is_bought_in_by_its_code_unless_its_own_geometry_says_we_cut_it():
    lev = {"part_number": "HAFELE 651.09.302", "description": "M8 x 22 Base Leveller", "quantity": 4,
           "pages": [2], "bound_to_parts_list_page": 2, "page_roles": ["detail"], "materials": ["MILD STEEL"]}
    assert "supplier's article" in bp.bought_in_reason(lev)
    cut = dict(lev, flat_pattern={"length_mm": 120.0, "width_mm": 40.0, "area_mm2": 4800.0},
               blank_length_mm=120.0, blank_width_mm=40.0, normalized_thickness_mm=3.0)
    if bp.has_fabrication_evidence(cut):
        assert bp.bought_in_reason(cut) == "", "measured geometry of its own outranks the code's shape"
    led = drl.capture({}, parts=[lev])
    assert led["items"] == [] and led["parts_read"] == 0, "a purchase is not a made part's sheet"
