"""D-592a: the reviewer's D-592 package, integrated where it found what D-592 missed.

A lone angle on a sheet is every angle it prints — a countersink, a mitre, a chamfer — and
D-592 made one into fold evidence: 0351292's strip kept a 25 mm flange (1293 x 37) that its
own 0.4 kg says it does not have. A measured blank is a measured size, not a measured hole
inventory. An outline is cut with a pierce. A punch nobody stated rides on nothing. A section's
wall is the section its own sheet names. Ownership that cannot be resolved is not permission.
The quote's example is a line whose machining is measured and of which nothing is asked.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import detail_page_geometry as g  # noqa: E402
import estimator as e  # noqa: E402
import fold_count as fc  # noqa: E402
import source_precedence as sp  # noqa: E402


# ── an angle is not a fold ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("angle", [90, 45, 120])
def test_a_bare_angle_counts_no_fold(angle):
    assert fc.press_brake_folds({"angles_deg": [angle], "process_notes": ["COUNTERSINK"]})["count"] == 0


def test_a_stated_count_callouts_and_a_measured_zero_still_decide():
    assert fc.press_brake_folds({"angles_deg": [90], "fold_count_textual": 2})["count"] == 2
    assert fc.press_brake_folds({"bend_count_dxf": 0, "fold_count_textual": 2})["count"] == 0
    assert fc.press_brake_folds({"drawing_bend_callouts": 2})["count"] == 2
    both = fc.press_brake_folds({"angles_deg": [90], "drawing_bend_callouts": 2,
                                 "solidworks_bend_features": 4})
    assert (both["count"], both["source"]) == (2, fc.CALLOUTS_AND_MODEL)


def test_the_fallback_bend_inference_does_not_count_an_angle_either():
    from feature_synthesis import synthesize_manufacturing_features
    part = {"part_number": "X-1", "normalized_material": "MILD_STEEL", "angles_deg": [90.0],
            "geometry_rollup": {}}
    assert synthesize_manufacturing_features(part)["bend_count"] == 0


def test_a_fold_instruction_is_words_or_a_measurement_not_a_label_or_an_angle():
    assert not g._fold_op_has_evidence({"operation_sources": {"folding": "inference"}})
    assert not g._fold_op_has_evidence({"operation_evidence": {"folding": "90 DEG COUNTERSINK"}})
    assert g._fold_op_has_evidence({"operation_evidence": {"folding": "RETURN FOLDED 90 DEG"}})
    assert g._fold_op_has_evidence({"operation_sources": {"folding": "solidworks_api"}})


def test_a_bare_angle_adds_no_flange_and_a_stated_fold_does():
    strip = {"part_number": "S-1", "normalized_material": "STAINLESS_STEEL",
             "normalized_thickness_mm": 3, "textual_operations": ["folding"], "angles_deg": [90]}
    with patch.object(g, "read_sheet_figures",
                      return_value={"figures": [(1293, "h"), (12, "v")], "text": "90 DEG CSK"}):
        blank = g.provisional_blank_from_sheets(strip, [{}])
        assert (blank["length"], blank["width"]) == (1293, 12)
        strip["fold_count_textual"] = 1
        assert g.provisional_blank_from_sheets(strip, [{}])["width"] == 37


def test_the_estimator_does_not_revive_an_angle_and_asks_instead():
    part = {"part_number": "A-1", "description": "BRACKET", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 2.0, "quantity": 1, "angles_deg": [90],
            "blank_length_mm": 200.0, "blank_width_mm": 100.0,
            "textual_operations": ["laser_cutting"],
            "geometry_rollup": {"estimated_cut_length_mm": 600.0}}
    out = e.estimate_process_times(part)
    assert out["bend_count"] == 0
    assert "folding" not in out["setup_times_min"]
    assert any(str(q.get("issue")).startswith("Folding of A-1")
               for q in part.get("manufacturing_questions") or [])


# ── a measured blank is a measured size, not a measured hole inventory ─────────────────────

def test_a_blank_from_the_model_does_not_make_page_holes_measured():
    part = {"part_number": "M-1", "blank_length_mm": 300.0, "blank_width_mm": 200.0,
            "blank_length_mm_source": "solidworks_api",
            "geometry_rollup": {"estimated_cut_length_mm": 1200.0, "estimated_hole_count": 6}}
    assert g.machining_is_measured(part) is False
    assert g.machining_evidence(part)["measured"] is False
    part["geometry_rollup"]["estimated_cut_length_mm_source"] = "solidworks_api"
    assert g.machining_is_measured(part) is True


# ── an outline is cut with a pierce, and its unread holes do not come back ─────────────────

def _bounded_tab():
    tab = {"part_number": "T-1", "description": "TOP BLANK", "normalized_material": "MILD_STEEL",
           "normalized_thickness_mm": 2.0, "quantity": 1, "textual_operations": ["laser_cutting"],
           "blank_length_mm": 30.0, "blank_width_mm": 7.4, "hole_sizes_mm": ["6", "8"],
           "geometry_rollup": {"estimated_cut_length_mm": 2823.0, "estimated_hole_count": 10,
                               "estimated_pierce_count": 12},
           "normalized_geometry": {"cut_length_mm": 2823.0, "hole_count": 10},
           "manufacturing_features": {"cut_length_mm": 2823.0, "hole_count": 10}}
    assert g.bound_cutting_to_blank(tab)
    return tab


def test_an_outline_is_cut_with_one_pierce_and_its_hole_sizes_do_not_revive_a_count():
    tab = _bounded_tab()
    out = e.estimate_process_times(tab)
    assert out["pierce_count"] == 1
    assert out["cut_length_mm"] == pytest.approx(74.8)


def test_the_workbook_reads_the_bounded_figures_not_the_page():
    from wb_populate import costed_geometry_value
    tab = _bounded_tab()
    assert costed_geometry_value(tab, "hole_count", "estimated_hole_count") is None
    assert costed_geometry_value(tab, "cut_length_mm", "estimated_cut_length_mm") == pytest.approx(74.8)


# ── a punch nobody stated ──────────────────────────────────────────────────────────────────

def _panel(**kw):
    p = {"part_number": "P-1", "description": "SIDE PANEL", "normalized_material": "MILD_STEEL",
         "normalized_thickness_mm": 1.5, "quantity": 1, "blank_length_mm": 600.0,
         "blank_width_mm": 400.0, "textual_operations": ["punch"],
         "operation_sources": {"punch": "inference"},
         "geometry_rollup": {"estimated_cut_length_mm": 4000.0, "estimated_hole_count": 40,
                             "estimated_pierce_count": 40}}
    p.update(kw)
    return p


def test_an_inferred_punch_on_unmeasured_holes_is_removed_and_the_laser_cuts():
    part = _panel()
    out = e.estimate_process_times(part)
    assert "punch" not in out["setup_times_min"] and "punch" not in part["textual_operations"]
    assert "laser_cutting" in out["setup_times_min"]
    assert any("PUNCH REMOVED" in f for f in part["review_flags"])


@pytest.mark.parametrize("kw", [{"operation_evidence": {"punch": "PUNCH ON STANDARD TOOLING"}},
                                {"description": "PERFORATED PANEL"},
                                {"dxf_augmented": True}])
def test_a_stated_named_or_measured_punch_is_kept(kw):
    part = _panel(**kw)
    assert "punch" in e.estimate_process_times(part)["setup_times_min"]


def test_a_page_path_is_asked_with_or_without_circles():
    part = _panel(textual_operations=["laser_cutting"], operation_sources={})
    part["geometry_rollup"].update(estimated_hole_count=0, estimated_pierce_count=0)
    e.estimate_process_times(part)
    assert any(str(q.get("issue")).startswith("Cutting of P-1:")
               and "read off the drawing's lines" in str(q.get("issue"))
               for q in part.get("manufacturing_questions") or [])


# ── a section's wall is the section its own sheet names ────────────────────────────────────

def _rail(text, **kw):
    part = {"part_number": "R-1", "pages": [12, 15], "normalized_material": "MILD_STEEL",
            "section_stock": {"a": 20, "b": 50, "t": 3, "profile_form": "RHS"}}
    part.update(kw)
    pages = [{"page_number": 15, "pdfplumber_text": text, "page_analysis": {
        "title_block": {"drawing_numbers": ["R-1"], "weights": ["1.4 kg"]}}}]
    return part, {"pages": pages}


def test_a_sections_wall_comes_from_the_section_its_own_sheet_names():
    part, summary = _rail("MILD STEEL RECT TUBE - RAW 50X20X2MM")
    sp.apply_field(part, "normalized_thickness_mm", 3.0, "drawing_deterministic")
    g.revalidate_from_own_sheets([part], summary)
    assert part["normalized_thickness_mm"] == 2.0
    assert sp.source_of(part, "normalized_thickness_mm") == "own_sheet_section"
    assert part["section_stock"]["t"] == 2.0


def test_two_sections_on_its_own_sheet_are_asked_not_picked():
    part, summary = _rail("RECT TUBE 50X20X2MM\nSQUARE TUBE 30X30X4MM")
    sp.apply_field(part, "normalized_thickness_mm", 3.0, "drawing_deterministic")
    g.revalidate_from_own_sheets([part], summary)
    assert part["normalized_thickness_mm"] == 3.0
    assert any(str(q.get("issue")).startswith("Section of R-1")
               for q in part.get("manufacturing_questions") or [])


def test_a_persons_wall_is_not_displaced_by_the_sheet():
    part, summary = _rail("RECT TUBE 50X20X2MM")
    sp.apply_field(part, "normalized_thickness_mm", 4.0, "estimator_confirmed")
    g.revalidate_from_own_sheets([part], summary)
    assert part["normalized_thickness_mm"] == 4.0


# ── ownership that cannot be resolved is not permission ────────────────────────────────────

def test_unresolved_page_ownership_gives_no_own_sheet():
    part = {"part_number": "ABC-1", "pages": [1]}
    summary = {"pages": [{"page_number": 1, "page_analysis": {
        "title_block": {"drawing_numbers": ["ABC-1"]}}}]}
    assert g.own_sheets(part, summary)
    with patch("part_index._bom_table_pages", side_effect=ValueError("bad structure")):
        assert g.own_sheets(part, summary) == []


# ── the quote's worked example ─────────────────────────────────────────────────────────────

def test_a_laser_line_cut_off_the_page_is_not_the_example(monkeypatch):
    import costed_facts as cf
    import quote_story as qs
    monkeypatch.setattr(cf, "record_lines", lambda s: {"A-1": {"price_origin": {"firmness": cf.FIRM}}})
    rec = {"part_number": "A-1", "_blank_provisional": {"weight_agrees": True},
           "textual_operations": ["laser_cutting"]}
    assert qs._line_is_supported({}, {"made": [rec]}, "A-1") is False
    rec["dxf_augmented"] = True
    assert qs._line_is_supported({}, {"made": [rec]}, "A-1") is True
    rec["manufacturing_questions"] = [{"issue": "Welding of A-1: timed as one joint"}]
    assert qs._line_is_supported({}, {"made": [rec]}, "A-1") is False


def test_an_unreadable_decisions_list_shows_no_example(monkeypatch):
    import costed_facts as cf
    import quote_story as qs
    monkeypatch.setattr(cf, "costed_job", lambda s: (_ for _ in ()).throw(ValueError("unreadable")))
    monkeypatch.setattr(qs, "_material_rows", lambda s: [
        {"block": "steel", "description": "A-1 TAB", "qty_per_unit": 1, "qty_per_sheet": 10,
         "total_value_gbp": 5.0}])
    assert qs.trace_part({}, {"made": [{"part_number": "A-1"}], "labour": [], "pages": []}) is None
