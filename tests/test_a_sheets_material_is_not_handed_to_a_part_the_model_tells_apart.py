"""A SHEET'S ONE MATERIAL IS NOT HANDED TO A PART THE MODEL TELLS APART (15 Nov 2026).

One job's shared sheet states MDF for a shelf panel and also draws the panel's edging and a
lock plate, which have no sheets of their own. The model gives the panel MDF, the edging
Foamed PVC and the plate Plain Carbon Steel. The hand-down rule (D-426) gave the sheet's MDF to
all three and the record said the model's material was "the model's library appearance, not a
spec"; the plate and the edging were priced as 9 mm board.

D-426 was written for a model that gives every part of a sheet the same default (acrylic
layers all "steel"), and that still stands. A model that gives one sheet's parts different
families is not handing out a default: the sheet-mate keeps the model's material, as a
question.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import file_scan as fs  # noqa: E402
import source_precedence as sp  # noqa: E402


def _page(material, number=2, sheet="T-TWO"):
    return {"page_number": number,
            "page_analysis": {"title_block": {"drawing_numbers": [sheet], "materials": [material]}}}


def _part(code, desc, material, src="solidworks_applied_material", pages=(2,)):
    return {"part_number": code, "description": desc, "quantity": 1, "pages": list(pages),
            "page_roles": ["detail"], "normalized_material": material,
            "material_source": src, "review_flags": []}


def _by(parts):
    return {p["part_number"]: p for p in parts}


def test_edging_and_a_steel_plate_keep_the_models_material_on_a_board_sheet():
    parts = [_part("T-101", "SHELF PANEL", "MDF"), _part("T-102", "SHELF EDGING", "PVC"),
             _part("T-103", "SHELF LOCK SWIVEL PLATE", "MILD_STEEL")]
    fs._inherit_sheet_material_to_parts(parts, [_page("MDF")])
    got = _by(parts)
    assert got["T-102"]["normalized_material"] == "PVC"
    assert got["T-103"]["normalized_material"] == "MILD_STEEL"
    assert got["T-101"]["normalized_material"] == "MDF"
    for code in ("T-102", "T-103"):
        p = got[code]
        assert "material_inherited_from" not in p
        assert any("NOT handed to this part" in f for f in p["review_flags"])
        q = p["manufacturing_questions"][0]
        assert "the model says" in q["issue"] and "MDF" in q["issue"]


def test_parts_the_model_gives_one_default_still_take_the_sheets_material():
    """D-426's own case: the layers are all steel in the model and the sheet says acrylic."""
    parts = [_part("W-014", "WAVE LAYER", "MILD_STEEL"), _part("W-015", "WAVE LAYER", "MILD_STEEL")]
    fs._inherit_sheet_material_to_parts(parts, [_page("ACRYLIC")])
    for p in parts:
        assert p["normalized_material"] == "ACRYLIC", p["review_flags"]
        assert p["material_inherited_from"]


def test_a_material_that_is_not_the_models_is_still_overruled_by_the_sheet():
    parts = [_part("T-101", "SHELF PANEL", "MDF"),
             _part("T-103", "PLATE", "MILD_STEEL", src="inference")]
    fs._inherit_sheet_material_to_parts(parts, [_page("MDF")])
    assert _by(parts)["T-103"]["normalized_material"] == "MDF"


def test_a_part_on_another_sheet_does_not_make_the_model_tell_these_apart():
    parts = [_part("T-103", "PLATE", "MILD_STEEL"),
             _part("T-900", "PANEL", "MDF", pages=(7,))]
    fs._inherit_sheet_material_to_parts(parts, [_page("MDF"), _page("MDF", 7, "T-900")])
    assert _by(parts)["T-103"]["normalized_material"] == "MDF"


def test_the_predicate_itself():
    fam = fs._material_family
    panel, plate = _part("A", "", "MDF"), _part("B", "", "MILD_STEEL")
    assert sp.model_tells_sheet_mates_apart(plate, [panel, plate], fam)
    assert not sp.model_tells_sheet_mates_apart(plate, [plate], fam)
    assert not sp.model_tells_sheet_mates_apart(plate, [_part("C", "", "ZINTEC"), plate], fam)
    assert not sp.model_tells_sheet_mates_apart(_part("B", "", "MILD_STEEL", src="inference"),
                                                [panel], fam)


# ── THE READ'S OVERRIDE OF A "METAL DEFAULT" (llm_full_job) ───────────────────────────────
def test_the_reads_board_does_not_replace_a_model_metal_among_parts_the_model_tells_apart():
    from source_connectors import llm_full_job as lj
    panel, plate = _part("T-101", "PANEL", "MDF"), _part("T-103", "PLATE", "MILD_STEEL")
    assert lj._model_tells_apart(plate, [panel, plate])
    assert not lj._model_tells_apart(plate, [plate, _part("T-104", "BRACKET", "MILD_STEEL")])
