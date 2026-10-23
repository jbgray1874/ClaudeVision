"""D-591: when a part's own sheet is known, everything that depends on WHICH sheet it was read
from is read again from that sheet — and cutting its blank cannot hold is not the part's.

The 0351292 13:23 book had the right blanks and the wrong dependants: the top blank's laser and
punch came from 12,637 mm of lines and the holes on the rail's assembly sheet, its weight check
compared 0.003 kg with the rail's 8.1 kg, the downstand's with the base's 8.6 kg, the strip's
unproven fold widened its blank, the downstand and the cross rail fell out of their assemblies'
coat because the assembly sheet's "POWDER COAT ASSEMBLY" was read as their own finish, and two
checks called assemblies with six and two members memberless and missing. Each rule is held with
the pack shape that broke it and a case where the old reading was right and must survive.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import detail_page_geometry as g  # noqa: E402
import estimator as e  # noqa: E402
import invariants  # noqa: E402


def _page(n, dn, *, weight=None, cut=0.0, holes=0, cues=None, text=""):
    return {"page_number": n, "text": text,
            "geometry_summary": {"estimated_cut_length_mm": cut, "estimated_hole_count": holes,
                                 "estimated_pierce_count": holes},
            "page_analysis": {"title_block": {"drawing_numbers": list(dn),
                                              "weights": [weight] if weight else []},
                              "feature_cues": dict(cues or {})}}


def _pack():
    """Page 9: the base assembly — its parts list names the downstand; page 11: the downstand."""
    return {
        "pages": [_page(9, ["ASM-9", "D-1", "P-1"], weight="8.6KG", cut=5811.0, holes=48,
                        cues={"hole_sizes_mm": [9.0] * 6, "radii_mm": ["225"]}),
                  _page(11, ["D-1"], weight="0.6KG", cut=5757.0, holes=20,
                        cues={"hole_sizes_mm": [], "radii_mm": ["225"]})],
        "document_analysis": {"bom_rows": [
            {"part_number": "D-1", "bom_sheet": "pack.pdf#8", "bom_parent": "ASM-9"},
            {"part_number": "P-1", "bom_sheet": "pack.pdf#8", "bom_parent": "ASM-9"}]},
    }


def _downstand(**kw):
    p = {"part_number": "D-1", "description": "DOWNSTAND", "normalized_material": "MILD_STEEL",
         "normalized_thickness_mm": 2.0, "pages": [9, 11], "weights": ["8.6KG", "0.6KG"],
         "hole_sizes_mm": [9.0] * 6, "radii_mm": ["225", "225"],
         "geometry_rollup": {"estimated_cut_length_mm": 11568.0, "estimated_hole_count": 68,
                             "estimated_pierce_count": 68},
         "normalized_geometry": {"cut_length_mm": 11568.0, "hole_count": 68}}
    p.update(kw)
    return p


# ── the own sheet: titled with the part, and not somebody else's parts list ────────────────

def test_a_parts_list_that_names_the_part_is_not_its_own_sheet():
    assert [s["page_number"] for s in g.own_sheets(_downstand(), _pack())] == [11]


def test_the_assemblys_own_parts_list_is_still_its_own_sheet():
    asm = {"part_number": "ASM-9", "pages": [9]}
    assert [s["page_number"] for s in g.own_sheets(asm, _pack())] == [9]


# ── weight, features and page geometry from the own sheet ─────────────────────────────────

def test_weight_features_and_cutting_are_read_again_from_the_own_sheet():
    part = _downstand()
    assert g.revalidate_from_own_sheets([part], _pack()) == ["D-1"]
    assert g._stated_weight_kg(part) == pytest.approx(0.6)
    assert e._stated_weight_reference(part)[0] == pytest.approx(0.6)
    assert part["hole_sizes_mm"] == [] and part["radii_mm"] == ["225"]
    assert part["geometry_rollup"]["estimated_cut_length_mm"] == 5757.0
    assert part["normalized_geometry"]["hole_count"] == 20
    assert part["_own_sheet_revalidation"]["foreign_pages"] == [9]


def test_a_part_with_only_its_own_sheet_is_left_as_it_was():
    part = _downstand(pages=[11], weights=["0.6KG"])
    before = dict(part["geometry_rollup"])
    assert g.revalidate_from_own_sheets([part], _pack()) == []
    assert part["geometry_rollup"] == before


def test_a_measured_flat_keeps_its_cutting():
    part = _downstand(dxf_augmented=True, geometry_source="dxf_flat_pattern",
                      blank_length_mm_source="dxf_flat_pattern")
    g.revalidate_from_own_sheets([part], _pack())
    assert part["geometry_rollup"]["estimated_cut_length_mm"] == 11568.0
    assert g._stated_weight_kg(part) == pytest.approx(0.6), "the weight is still its own"


# ── cutting the blank cannot hold ──────────────────────────────────────────────────────────

def _blank(part, L, W):
    g._write_blank(part, L, W, g.PROVISIONAL_SOURCE)
    part["_blank_provisional"] = {"basis": g.PROVISIONAL_SOURCE}
    return part


def test_a_tab_does_not_carry_its_pages_lines_or_circles():
    """The top blank's own page alone holds 2,823 mm of lines and 10 circles."""
    tab = _blank({"part_number": "T-1", "normalized_material": "MILD_STEEL",
                  "geometry_rollup": {"estimated_cut_length_mm": 2823.0,
                                      "estimated_hole_count": 10, "estimated_pierce_count": 12},
                  "normalized_geometry": {"cut_length_mm": 2823.0, "hole_count": 10}},
                 30.0, 7.4)
    assert g.bound_unmeasured_cut_path([tab]) == ["T-1"]
    assert tab["normalized_geometry"]["cut_length_mm"] == pytest.approx(74.8)
    assert tab["geometry_rollup"]["estimated_hole_count"] == 0
    assert any("CUTTING FROM THE BLANK" in f for f in tab["review_flags"])


def test_a_plate_whose_cutting_fits_its_blank_keeps_it():
    plate = _blank({"part_number": "P-9", "normalized_material": "MILD_STEEL",
                    "geometry_rollup": {"estimated_cut_length_mm": 5000.0,
                                        "estimated_hole_count": 20},
                    "normalized_geometry": {"cut_length_mm": 5000.0, "hole_count": 20}},
                   1154.0, 450.0)
    assert g.bound_unmeasured_cut_path([plate]) == []
    assert plate["normalized_geometry"]["cut_length_mm"] == 5000.0


def test_a_measured_flat_is_never_bounded():
    part = {"part_number": "M-1", "normalized_material": "MILD_STEEL", "dxf_augmented": True,
            "geometry_source": "dxf_flat_pattern",
            "normalized_geometry": {"cut_length_mm": 9000.0, "hole_count": 400,
                                    "blank_length_mm": 100.0, "blank_width_mm": 100.0,
                                    "blank_length_mm_source": "dxf_flat_pattern"}}
    assert g.bound_unmeasured_cut_path([part]) == []


# ── a flange only for a fold with evidence ─────────────────────────────────────────────────

def _strip_sheet(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    pg = doc.new_page(width=1191, height=842)
    pg.insert_text((500, 300), "1293", fontsize=9)
    pg.insert_text((420, 340), "12", fontsize=9, rotate=90)
    path = tmp_path / "strip.pdf"
    doc.save(str(path))
    doc.close()
    return {"page_number": 2, "source_page_number": 1, "source_pdf_path": str(path),
            "page_analysis": {"title_block": {"weights": []}}}


def test_an_unproven_fold_does_not_widen_the_blank(tmp_path):
    strip = {"part_number": "S-1", "normalized_material": "STAINLESS_STEEL",
             "normalized_thickness_mm": 3.0, "textual_operations": ["folding"]}
    blank = g.provisional_blank_from_sheets(strip, [_strip_sheet(tmp_path)])
    assert blank and (blank["length"], blank["width"]) == (1293.0, 12.0)


def test_a_fold_the_drawing_states_still_develops_it(tmp_path):
    strip = {"part_number": "S-1", "normalized_material": "STAINLESS_STEEL",
             "normalized_thickness_mm": 3.0, "textual_operations": ["folding"],
             "fold_count_textual": 1}
    blank = g.provisional_blank_from_sheets(strip, [_strip_sheet(tmp_path)])
    assert blank and blank["width"] == 37.0


def test_a_fold_with_the_drawings_words_takes_the_allowance(tmp_path):
    strip = {"part_number": "S-1", "normalized_material": "STAINLESS_STEEL",
             "normalized_thickness_mm": 3.0, "textual_operations": ["folding"],
             "operation_evidence": {"folding": "RETURN FOLDED 90 DEG"}}
    blank = g.provisional_blank_from_sheets(strip, [_strip_sheet(tmp_path)])
    assert blank and blank["width"] > 12.0


# ── a coat stated for the assembly is the assembly's ───────────────────────────────────────

def test_a_member_holding_the_assemblys_coat_is_in_the_assemblys_area(monkeypatch):
    asm = {"part_number": "ASM-9", "textual_operations": ["powder_coating"], "quantity": 1}
    downstand = {"part_number": "D-1", "normalized_material": "MILD_STEEL",
                 "normalized_thickness_mm": 2.0, "blank_length_mm": 1435.2,
                 "blank_width_mm": 25.0, "textual_operations": ["powder_coating"],
                 "normalized_finish": "POWDER COAT ASSEMBLY - GRAPHITE RAL7024 SATIN"}
    monkeypatch.setattr(e, "_compiled_parent_map", lambda parts, summary: {"D-1": {"ASM-9"}})
    e.stamp_members_coated_area([asm, downstand], {"pages": []})
    assert asm.get("_powder_members_coated_m2") == pytest.approx(1.4352 * 0.025 * 2, rel=1e-3)


def test_a_member_with_its_own_powder_finish_is_still_coated_on_its_own_line():
    own = {"part_number": "D-2", "textual_operations": ["powder_coating"],
           "normalized_finish": "POWDER COATED RAL9005"}
    assert e._member_carries_its_own_coat(own) is True


# ── the checks read the hierarchy the page prints ──────────────────────────────────────────

def _shadow(nodes):
    return {"estimate_summary": {"canonical_route_shadow": {"nodes": nodes}}}


def test_an_assembly_with_compiled_members_is_not_memberless():
    job = {"parts": [{"part_number": "ROOT", "is_assembly_parent": True},
                     {"part_number": "ASM-9", "is_assembly_parent": True,
                      "owning_assembly": "ROOT"},
                     {"part_number": "D-1", "owning_assembly": "ROOT",
                      "unit_material_cost_gbp": 2.79}]}
    assert invariants.check_a_memberless_assembly_carries_nothing(job)
    job.update(_shadow([{"part_number": "D-1", "parents": ["ASM-9"]},
                        {"part_number": "ASM-9", "parents": ["ROOT"]}]))
    assert invariants.check_a_memberless_assembly_carries_nothing(job) == []


def test_an_assembly_whose_members_the_pack_read_is_not_a_missing_drawing():
    summary = {"document_analysis": {"bom_rows": [
        {"part_number": "12345-01-09", "description": "BASE ASSEMBLY", "quantity": 1}]},
        "pages": [{"page_number": 11, "page_analysis": {"title_block": {
            "drawing_numbers": ["12345-01-11"]}}}],
        "manufacturing_writeup": {"parts": []}}
    out = invariants.check_the_pack_contains_the_drawings_its_bom_names(summary)
    assert any("12345-01-09" in str(v) for v in out), "with nothing read, it is missing"
    summary.update(_shadow([{"part_number": "12345-01-11", "parents": ["12345-01-09"]}]))
    out = invariants.check_the_pack_contains_the_drawings_its_bom_names(summary)
    assert not any("12345-01-09" in str(v) for v in out)


# ── a section's gauge is its wall; the worked example is a settled line ────────────────────

def test_a_sections_labour_row_names_its_wall():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert 'thickness = _safe(_ss_row.get("t"))' in src


def test_the_quote_walks_through_a_line_with_no_open_question():
    import quote_story as qs
    src = open(qs.__file__, encoding="utf-8").read()
    body = src[src.index("def trace_part("):src.index("def cost_model(")]
    assert "not in _open" in body and "decisions_required" in body
