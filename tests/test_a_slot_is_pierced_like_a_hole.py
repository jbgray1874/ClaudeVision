"""A slot is pierced like a hole, and the laser row counts it (D-684).

12693-01-03M, a 1.5 mm worktop skin, carries twenty 6.4 x 2.4 mm slots for its tabs. The DXF
contour walk measured 21 closed profiles: the outline and the twenty slots. The Sheet Steel
row's "No of holes" cell was left blank, because it asks only for the hole count and a slot is
not a circle, and the count that knew about the slots stayed on the raw record. The laser
calculator adds a second per pierce, so twenty starts were not in the row's time.

Only a complete contour walk is taken as a measurement. A walk that could not close its loops
is a floor, and the raw parser can count one profile twice; neither reaches the cell.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from wb_populate import measured_internal_cutouts  # noqa: E402


def _pe(count, source="dxf_contour_walk", **kw):
    g = {"estimated_pierce_count": count, "estimated_pierce_count_source": source}
    g.update(kw)
    return {"part_number": "12999-01-03M", "dxf_raw_geometry": g}


def test_twenty_slots_and_an_outline_are_twenty_internal_cut_outs():
    assert measured_internal_cutouts(_pe(21)) == 20


def test_an_outline_alone_has_no_internal_cut_out():
    assert measured_internal_cutouts(_pe(1)) is None


def test_an_incomplete_walk_is_not_put_on_the_sheet():
    assert measured_internal_cutouts(_pe(21, pierce_count_incomplete=True)) is None


def test_the_raw_parsers_figure_is_not_a_measurement():
    assert measured_internal_cutouts(_pe(21, source="dxf_raw_fallback")) is None
    assert measured_internal_cutouts(_pe(21, source="dxf_incomplete_walk_max")) is None


def test_no_flat_no_figure():
    assert measured_internal_cutouts({"part_number": "X"}) is None
    assert measured_internal_cutouts({"dxf_raw_geometry": None}) is None


def test_the_costed_record_carries_the_walk():
    """The count has to reach the record the workbook reads, or the cell cannot use it."""
    import estimator
    part = {"part_number": "12999-01-03M", "description": "TOP SKIN",
            "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 1.5,
            "geometry_source": "dxf", "flat_pattern_detected": True,
            "normalized_geometry": {"blank_length_mm": 1250.4, "blank_width_mm": 1250.4},
            "dxf_raw_geometry": {"estimated_pierce_count": 21,
                                 "estimated_pierce_count_source": "dxf_contour_walk",
                                 "pierce_count_incomplete": False,
                                 "closed_contour_count": 21, "estimated_hole_count": 0,
                                 "blank_area_mm2": 1552043.7},
            "textual_operations": ["laser_cutting"], "quantity": 1}
    pe = estimator.estimate_part(part, job_quantity=1)
    assert measured_internal_cutouts(pe) == 20
    assert "blank_area_mm2" not in pe["dxf_raw_geometry"], "only the pierce fields travel"
