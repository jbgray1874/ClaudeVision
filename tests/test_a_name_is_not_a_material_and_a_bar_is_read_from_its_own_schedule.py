"""12173-02 Card Spinner, 4 Oct 21:12 book on 7a07977 (D-391). Two lines went wrong once every
part was read on its OWN pages (D-390) instead of borrowing the pack's:

* 12173-04-201 CARD POCKET ASSEMBLY — seven fillets and POWDER COATED - MATT on its own sheet —
  was flipped to CARD from the word in its NAME, tagged bought-in, and lost its weld, its
  dressing and its coat (eight off); its parent's coat was then ruled out because its one member
  was "bought in". A description names the thing, often for what it holds; the MATERIAL field
  names the material. A non-metal word in the name overrules only a material the part did not
  state for itself, and never an assembly's.
* 12173-06-01M ARM, a Ø6 bar 119.93 long, prints "6.00mm DIA 119.93" on its own sheet and no
  blank; it was wire only while another part's "MILD STEEL WIRE" was read over the whole pack.
  On its own pages it fell to the sheet path: lasered, folded, priced from a 1 mm gauge it never
  stated. A diameter and a length with no blank, no flat and no stated sheet thickness is a bar.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import document_builder as db                                         # noqa: E402


# ── the bare schedule ─────────────────────────────────────────────────────────────────────

def test_a_diameter_and_a_length_on_the_parts_own_sheet_is_a_bar():
    text = "ITEM DESCRIPTION QTY 1 6.00mm DIA 119.93 1 MATERIAL: MILD STEEL FINISH: WELDED"
    assert db._parse_bar_schedule(text) == []                 # no item/qty-prefixed row
    rows = db._parse_bar_schedule(text, bare=True)
    assert rows == [{"gauge_mm": 6.0, "length_mm": 119.93, "qty": 1}]


def test_a_hole_callout_or_a_stated_sheet_thickness_is_not_a_bar():
    assert db._parse_bar_schedule("4 HOLES 6mm DIA 100 PCD", bare=True) == []
    assert db._parse_bar_schedule("6mm DIA 100 THRU", bare=True) == []
    assert db._parse_bar_schedule("1.5mm THK MILD STEEL  6.00mm DIA 119.93", bare=True) == []
    # the strong form is untouched by the flag
    assert db._parse_bar_schedule("1 1 6.00mm DIA 119.93", bare=True) == \
        db._parse_bar_schedule("1 1 6.00mm DIA 119.93")


def test_the_arm_is_bar_stock_on_its_own_pages_and_takes_the_robomac_not_the_laser():
    summary = {"pages": [
        {"page_number": 1, "text_preview": "SINGLE BAR HOOK  MATERIAL: MILD STEEL WIRE  "
                                           "ITEM QTY DESCRIPTION  1 1 4mm DIA 233.4"},
        {"page_number": 3, "text_preview": "ARM  ITEM DESCRIPTION QTY  1 6.00mm DIA 119.93 1  "
                                           "MATERIAL: MILD STEEL  FINISH: WELDED"},
    ]}
    arm = {"part_number": "X-06-01M", "description": "ARM", "materials": ["MILD STEEL"],
           "pages": [3], "page_roles": ["detail"],
           "textual_operations": ["laser_cutting", "folding"], "geometry_rollup": {}}
    db._apply_post_build_fixes([arm], summary)
    assert arm.get("_bar_recognised") is True
    assert arm.get("wire_gauge_mm") == 6.0 and arm.get("wire_length_mm") == 119.93
    assert arm.get("normalized_thickness_mm") is None
    ops = set(arm.get("textual_operations") or [])
    assert "robomac" in ops and "laser_cutting" not in ops and "folding" not in ops
    assert (arm.get("material_estimate") or {}).get("stock_form") == "wire"
    assert any("round stock per its own sheet" in str(f) for f in arm.get("review_flags") or [])


# ── a name is not a material ──────────────────────────────────────────────────────────────

def _summary_with(title: str) -> dict:
    return {"pages": [{"page_number": 2, "text_preview": title}]}


def test_a_steel_assembly_named_for_what_it_holds_keeps_its_steel_its_weld_and_its_coat():
    title = ("CARD POCKET ASSEMBLY  12173-04-201  MATERIAL  MILD STEEL  FINISH  "
             "POWDER COATED - MATT")
    pocket = {"part_number": "X-04-201", "description": "CARD POCKET ASSEMBLY",
              "materials": ["MILD STEEL"], "normalized_material": "MILD_STEEL", "pages": [2],
              "page_roles": ["detail"], "textual_operations": ["welding", "powder_coating"],
              "geometry_rollup": {}}
    db._apply_post_build_fixes([pocket], _summary_with(title))
    assert "bought_in" not in (pocket.get("page_roles") or [])
    assert "non_metal_material_corrected" not in (pocket.get("review_flags") or [])
    assert {"welding", "powder_coating"} <= set(pocket.get("textual_operations") or [])
    assert pocket.get("normalized_material") == "MILD_STEEL"
    assert any("what it holds or displays" in str(f) for f in pocket.get("review_flags") or [])


def test_a_leaf_with_its_own_steel_is_not_flipped_by_its_name_but_an_inherited_steel_is():
    title = "CARD HOLDER  MATERIAL  MILD STEEL  FINISH  RAW"
    holder = {"part_number": "X-04-07M", "description": "CARD HOLDER",
              "materials": ["MILD STEEL"], "normalized_material": "MILD_STEEL", "pages": [2],
              "page_roles": ["detail"], "textual_operations": ["laser_cutting", "folding"],
              "overall_length_mm": 120.0, "overall_width_mm": 40.0, "geometry_rollup": {}}
    diffuser = {"part_number": "X-04-08", "description": "LED DIFFUSER",
                "materials": ["MILD STEEL"], "material_inherited_from": "document_level",
                "pages": [3], "page_roles": ["detail"], "textual_operations": ["powder_coating"],
                "overall_length_mm": 1330.0, "overall_width_mm": 16.0, "geometry_rollup": {}}
    summary = _summary_with(title)
    summary["pages"].append({"page_number": 3, "text_preview": "LED DIFFUSER  1330 x 16"})
    db._apply_post_build_fixes([holder, diffuser], summary)
    assert "bought_in" not in (holder.get("page_roles") or [])
    assert "laser_cutting" in (holder.get("textual_operations") or [])
    # the inherited steel has no statement of its own to overrule: the name still speaks
    assert "bought_in" in (diffuser.get("page_roles") or [])
    assert "powder_coating" not in (diffuser.get("textual_operations") or [])


def test_an_assembly_named_for_what_it_holds_is_not_flipped_even_on_an_inherited_steel():
    title = "LED HOUSING ASSEMBLY  MATERIAL  FINISH  POWDER COATED"
    housing = {"part_number": "X-05-101", "description": "LED HOUSING ASSEMBLY",
               "materials": ["MILD STEEL"], "material_inherited_from": "document_level",
               "pages": [2], "page_roles": ["detail"], "is_sub_assembly": True,
               "textual_operations": ["welding", "powder_coating"], "geometry_rollup": {}}
    db._apply_post_build_fixes([housing], _summary_with(title))
    assert "bought_in" not in (housing.get("page_roles") or [])
    assert {"welding", "powder_coating"} <= set(housing.get("textual_operations") or [])
    assert any("an assembly's material is its members'" in str(f)
               for f in housing.get("review_flags") or [])
    # no statement of its own settles it, so a person is asked and no money moves
    qs = housing.get("manufacturing_questions") or []
    assert any("steel assembly of its members, or a purchased led item" in str(q.get("issue"))
               for q in qs)
