"""12674-01 (11 Nov 2026): a bought fitting is not timber, and a model's default material is not
a specification.

* "HAFELE: 637.30.941", six plinth feet on the parts list, took the GA's TIMBER and were costed
  as sawn, glued, sprayed and routed parts. A maker's name, a colon and the maker's code is a
  supplier's article: it inherits no material and is priced as the item bought.
* 12674-01-01J BASE: the model says "Steel", measured nothing, and every other part beside it is
  MDF under a GA that states TIMBER. It is not priced as steel: it is a visible gap with a
  question that says what each source states.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import file_scan as fs                                            # noqa: E402
import part_code_conventions as pcc                               # noqa: E402


def test_a_makers_name_and_colon_before_a_code_is_a_suppliers_article():
    for code in ("HAFELE: 637.30.941", "HAFELE:637.30.941", "ROSS: 50-360-R-BH10",
                 "McCue: GGT-10-401", "IRONMONGERY DIRECT: 324250"):
        assert pcc.is_supplier_article(code), code
    for code in ("DWG NO: 12345-01", "PART: 123", "12674-01-01J", "FIXING", "P/P", "MATERIAL: MDF"):
        assert not pcc.is_supplier_article(code), code


def _da(materials=("TIMBER",)):
    return {"primary_fields": {"normalized_material": "TIMBER"},
            "title_block": {"materials": list(materials), "normalized": {"primary_material": "TIMBER"}}}


def test_a_suppliers_article_does_not_inherit_the_drawings_material():
    parts = [{"part_number": "HAFELE: 637.30.941", "description": "PLINTH ADJUSTING FITTING"},
             {"part_number": "7001-01-02J", "description": "SIDE PANEL"}]
    fs._inherit_document_material_to_parts(parts, _da())
    assert not parts[0].get("normalized_material") and not parts[0].get("materials")
    assert parts[1].get("normalized_material") == "TIMBER", "a made part still inherits"


def test_a_saved_record_gives_back_an_inherited_material_on_a_bought_item_only():
    feet = {"part_number": "HAFELE: 637.30.941", "normalized_material": "TIMBER",
            "materials": ["TIMBER"], "material_inherited_from": "document_level"}
    glue = {"part_number": "7001-01-101SA-ADHESIVE", "normalized_material": "TIMBER",
            "materials": ["TIMBER"], "material_inherited_from": "document_level"}
    own = {"part_number": "ROSS: 50-360-R-BH10", "normalized_material": "MILD_STEEL",
           "materials": ["MILD STEEL"]}
    said = fs.release_inherited_material_from_bought_items([feet, glue, own])
    assert not feet.get("normalized_material") and feet["materials"] == []
    assert feet["material_released_from_document"] == "TIMBER" and len(said) == 1
    assert glue["normalized_material"] == "TIMBER", "the job's minted lines are costed their own way"
    assert own["normalized_material"] == "MILD_STEEL", "a material the item states stays"


def _board(pn, mat="MDF"):
    return {"part_number": pn, "normalized_material": mat,
            "material_source": "solidworks_applied_material"}


def _rows(*pns):
    return [{"part_number": pn, "bom_parent": "7001-01-101SA"} for pn in pns]


def test_a_lone_default_model_material_is_not_priced_and_is_asked():
    base = dict(_board("7001-01-01J", "MILD_STEEL"), description="BASE",
                native_material_without_geometry=True,
                review_flags=["material 'MILD_STEEL' from the SolidWorks model (applied material: Steel)"])
    parts = [base, _board("7001-01-02J"), _board("7001-01-03J"), _board("7001-01-04J")]
    da = dict(_da(), bom_rows=_rows("7001-01-01J", "7001-01-02J", "7001-01-03J", "7001-01-04J"))
    said = fs.doubt_a_lone_model_material(parts, da)
    assert len(said) == 1 and not base.get("normalized_material")
    assert base["material_model_said"] == "MILD_STEEL"
    q = next(f for f in base["review_flags"] if f.startswith("MATERIAL NOT STATED"))
    assert "MILD_STEEL" in q and "BOARD" in q and "NOT PRICED" not in q.upper()
    assert not any(f.startswith("material 'MILD_STEEL' from the SolidWorks") for f in base["review_flags"])


def test_a_model_material_stands_where_it_is_measured_or_not_alone():
    measured = dict(_board("7001-01-01J", "MILD_STEEL"))                     # geometry was read
    parts = [measured, _board("7001-01-02J"), _board("7001-01-03J")]
    assert fs.doubt_a_lone_model_material(parts, dict(_da(), bom_rows=_rows("7001-01-01J", "7001-01-02J", "7001-01-03J"))) == []
    assert measured["normalized_material"] == "MILD_STEEL"
    mixed = dict(_board("7001-01-01J", "MILD_STEEL"), native_material_without_geometry=True)
    parts = [mixed, _board("7001-01-02J"), _board("7001-01-03J", "MILD_STEEL")]
    assert fs.doubt_a_lone_model_material(parts, _da(("TIMBER", "MILD STEEL"))) == []
    assert mixed["normalized_material"] == "MILD_STEEL", "a mixed job keeps what the model says"
