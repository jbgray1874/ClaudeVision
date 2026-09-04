"""A wire/bar part's cost does not rest on a flat-pattern DXF, so it is not "doubted geometry".

11762-17's wires 03M/04M have no DXF and a long PDF outline, so _part_cost_credibility flagged
them no_part_dxf + pdf_geometry_inflation and dumped their whole extended cost (£33.22/£32.32,
mostly forming/weld LABOUR) into the "doubted" column — which dragged the report's credible-cost
ratio to "5%" and printed those figures as at-risk money on the wires. But since the wire fix a
wire is costed from the Wire block (gauge + tonne rate), not from that geometry, so the
flat-pattern doubts are the wrong doubts — exactly as they are for a bought-in that never has a
flat pattern.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator  # noqa: E402


def test_a_wire_costed_part_is_credible_despite_no_dxf():
    wire = {"part_number": "11762-17-03M", "description": "U WIRE",
            "extended_total_cost_gbp": 33.22,
            "material_estimate": {"stock_form": "wire",
                                  "cost_method": "wire_tonne_rate_assumed_length"}}
    ok, reasons = estimator._part_cost_credibility({}, wire)
    assert ok is True
    assert reasons == []


def test_a_bar_formula_part_is_credible_too():
    bar = {"part_number": "X-BAR", "description": "ROUND BAR",
           "extended_total_cost_gbp": 12.0,
           "material_estimate": {"cost_method": "workbook_bar_formula"}}
    assert estimator._part_cost_credibility({}, bar)[0] is True


def test_a_genuine_no_dxf_sheet_part_is_still_doubted():
    """The exemption is for wire/bar only — a flat part with no DXF and an inflated PDF outline
    must still be flagged, or the credibility check would stop meaning anything."""
    sheet = {"part_number": "X", "description": "PLATE", "extended_total_cost_gbp": 40.0,
             "material_estimate": {"stock_form": "sheet"}}
    mfg = {"geometry_rollup": {"estimated_cut_length_mm": 5000,
                               "confidence": {"geometry_reliability": 0.4}}}
    ok, reasons = estimator._part_cost_credibility(mfg, sheet)
    assert ok is False
    assert "no_part_dxf" in reasons
