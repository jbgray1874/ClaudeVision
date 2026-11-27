"""Harrods 9439-01-04-001 A4 BASE, 5 Oct 2026 (D-396): a 219 x 60 base cut from 5 mm plate
as a rim about 5 mm wide, 105 g on its sheet. The DXF is eight lines: the outer rectangle
and the inner one.

Two readers got it wrong before the pack was run. The net-area routine took the biggest
polygonized face for the blank — that face is the HOLE — and subtracted the rim from it:
7,760 mm2 for a part that is 2,690. And its 30% fill floor would then have thrown the
honest 20% away for the solid envelope. The D-392 weight check weighed the envelope,
516 g at 5 mm against the stated 105 g, and would have asked for a 1 mm gauge on a plate
the DXF name says is 5 mm.

The blank is the face whose outline encloses the others, with its holes already out; a
thin rim whose outline closes round the whole extent is a blank, not garbage; and where a
flat was measured the weight check weighs the cut outline, not the envelope.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

pytest.importorskip("shapely")
ezdxf = pytest.importorskip("ezdxf")

import estimator                                                      # noqa: E402
from dxf_reader import extract_flat_pattern_data                      # noqa: E402

RIM = 2690.0          # (219 x 60) - (209 x 50)


def _dxf(lines):
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for a, b in lines:
        msp.add_line(a, b, dxfattribs={"layer": "0"})
    p = Path(tempfile.mktemp(suffix=".dxf"))
    doc.saveas(str(p))
    try:
        return extract_flat_pattern_data(p) or {}
    finally:
        os.unlink(p)


def _rect(x0, y0, x1, y1):
    return [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]


def test_the_base_rim_is_its_rim():
    out = _dxf(_rect(-109.5, -30, 109.5, 30) + _rect(-104.5, -25, 104.5, 25))
    assert abs(out["blank_area_mm2"] - RIM) < 1.0, out.get("blank_area_mm2")
    assert abs(out["bbox_fill_pct"] - 20.5) < 0.5
    assert (out["blank_length_mm"], out["blank_width_mm"]) == (219.0, 60.0)


def test_a_solid_plate_and_a_plate_with_a_window_still_read():
    assert abs(_dxf(_rect(0, 0, 200, 100))["blank_area_mm2"] - 20000.0) < 1.0
    windowed = _dxf(_rect(0, 0, 200, 100) + _rect(50, 25, 150, 75))
    assert abs(windowed["blank_area_mm2"] - 15000.0) < 1.0          # 20,000 - 5,000


def test_a_fragment_that_does_not_close_round_the_extent_still_falls_back():
    """A small closed shape beside loose lines is not the blank: the envelope stands."""
    out = _dxf(_rect(0, 0, 20, 20) + [((0, 0), (300, 0)), ((300, 0), (300, 150))])
    assert out["blank_area_mm2"] == pytest.approx(300 * 150, rel=0.01)


def test_the_weight_check_weighs_the_cut_outline_where_one_was_measured():
    base = {"part_number": "X-001", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 5.0, "stated_weight_kg": 0.105,
            "normalized_geometry": {"blank_length_mm": 219.0, "blank_width_mm": 60.0,
                                    "blank_area_mm2": RIM}}
    assert estimator._blank_weight_check(base) is None
    # the same envelope with no measured outline is the 12696 case, and is still asked
    env = dict(base, normalized_geometry={"blank_length_mm": 219.0, "blank_width_mm": 60.0})
    msg = estimator._blank_weight_check(env)
    assert msg and "219 x 60 blank" in msg and "0.516 kg" in msg
    # a measured outline that still does not fit names the outline, not the envelope
    thin = dict(base, normalized_thickness_mm=12.0)
    msg = estimator._blank_weight_check(thin)
    assert msg and "cut outline" in msg and "2,690" in msg
