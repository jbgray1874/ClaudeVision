"""12527-22-GA riser, third pass (D-372): two report lines that described a size or a gauge
the sheet does not use.

1. The BOM table printed the rail as 250 x 68.21 x 0.9 mm; the Sheet Steel row costs it at
   1 mm under the shop's 0.9-to-1.0 rule.
2. "UNRESOLVED; the size used is a fallback envelope" sat on the riser and the rail (both cut
   from their own DXFs), on the weldment (sized through its members) and on the customer's
   ticket (not cut by SDI at all). The detail-sheet pass wrote it before the DXFs landed and
   read only a top-level blank, where a measured flat lives under the geometry record.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from detail_page_geometry import (has_measured_flat, not_cut_from_a_blank,  # noqa: E402
                                  withdraw_stale_envelope_flags)
from job_report_html import _line_dimensions  # noqa: E402

ENV = ("12527-22-01M: page 3 is its detail sheet but its blank could not be taken from it — "
       "UNRESOLVED; the size used is a fallback envelope")


# ── the gauge column ─────────────────────────────────────────────────────────────────────

def _rail():
    return {"material_estimate": {"blank_length_mm": 250, "blank_width_mm": 68.21},
            "normalized_thickness_mm": 0.9, "geometry_source": "dxf_flat_pattern",
            "production_substitution": {"drawn_thickness_mm": 0.9, "costed_thickness_mm": 1.0}}


def test_the_column_shows_the_gauge_the_sheet_costs_and_names_the_drawn_one():
    cell = _line_dimensions({"thickness_mm": 0.9}, _rail())
    assert cell.startswith("250 × 68.21 × 1 mm")
    assert "drawn 0.9 mm, costed at 1 mm" in cell


def test_without_a_rule_the_column_is_unchanged():
    part = {"material_estimate": {"blank_length_mm": 100, "blank_width_mm": 50},
            "geometry_source": "dxf_flat_pattern"}
    cell = _line_dimensions({"thickness_mm": 2}, part)
    assert cell.startswith("100 × 50 × 2 mm") and "drawn" not in cell


# ── the envelope flag ────────────────────────────────────────────────────────────────────

def _dxf_part():
    return {"part_number": "12527-22-01M", "geometry_source": "dxf_flat_pattern",
            "dxf_augmented": True,
            "normalized_geometry": {"blank_length_mm": 250.0, "blank_width_mm": 68.208},
            "review_flags": [ENV, "something else"]}


def test_a_dxf_flat_under_the_geometry_record_is_measured():
    assert has_measured_flat(_dxf_part())


def test_the_flag_comes_off_a_measured_part_and_nothing_else_does():
    part = _dxf_part()
    assert withdraw_stale_envelope_flags([part]) == 1
    assert part["review_flags"] == ["something else"]


def test_an_assembly_or_a_supplied_line_uses_no_blank():
    assert not_cut_from_a_blank({"is_assembly_parent": True})
    assert not_cut_from_a_blank({"spot_weld_count": 4})
    assert not_cut_from_a_blank({"supplied_by_third_party": "OTHERS"})
    for rec in ({"part_number": "12527-22-101", "spot_weld_count": 4, "review_flags": [ENV]},
                {"part_number": "12527-22-03X", "supplied_by_third_party": "OTHERS",
                 "review_flags": [ENV]}):
        withdraw_stale_envelope_flags([rec])
        assert rec["review_flags"] == []


def test_a_leaf_nobody_measured_keeps_the_flag():
    leaf = {"part_number": "X-05M", "description": "SIDE PANEL", "geometry_source": "pdf",
            "normalized_material": "MILD STEEL", "textual_operations": ["laser_cutting"],
            "review_flags": [ENV]}
    assert not has_measured_flat(leaf)
    assert withdraw_stale_envelope_flags([leaf]) == 0
    assert leaf["review_flags"] == [ENV]


def test_the_detail_pass_skips_a_part_already_measured():
    src = (ROOT / "src" / "detail_page_geometry.py").read_text(encoding="utf-8")
    assert "if has_measured_flat(part):\n            continue" in src


def test_the_sweep_runs_once_every_reader_has():
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    block = src.split("EVERY READER HAS RUN, SO A FLAG ABOUT A SIZE NOBODY USES")[1][:500]
    assert "withdraw_stale_envelope_flags(part_estimates)" in block
    assert "withdraw_stale_envelope_flags(parts)" in block
    assert '"spot_weld_count": part.get("spot_weld_count")' in src
