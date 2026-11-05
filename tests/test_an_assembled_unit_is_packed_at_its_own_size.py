"""A UNIT THAT SHIPS ASSEMBLED IS DESCRIBED AT ITS OWN SIZE, NOT ITS FLAT (D-717).

12676-01-GA2's stand is one folded 2 mm sheet. The packaging was worked from the assembled
unit, 304.2 x 254 x 240.5 mm, but the summary line said "largest panel 665 x 254mm": the
flat blank before folding. An estimator reading it took the carton for a box around a flat
sheet. The flat is named only when the order is packed by its parts.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import commercial_lines as cl


def test_an_assembled_unit_is_named_at_its_envelope():
    order = {"assembled_unit": {"envelope_mm": [304.2, 254, 240.5]},
             "largest_part_mm": [665.08, 254]}
    words = cl.packed_size_phrase(order)
    assert words == "packed as the assembled unit, 304.2 x 254 x 240.5mm"
    assert "665" not in words


def test_parts_packed_still_name_the_largest_panel():
    assert cl.packed_size_phrase({"largest_part_mm": [2026, 1144]}) == \
        "largest panel 2026 x 1144mm"


def test_nothing_measured_says_nothing():
    assert cl.packed_size_phrase({}) == ""
    assert cl.packed_size_phrase({"assembled_unit": {"envelope_mm": [300, 0, 200]}}) == ""


def test_the_packaging_line_uses_the_assembled_size(monkeypatch):
    order = {"order_quantity": 1, "order_weight_kg": 2.6,
             "assembled_unit": {"envelope_mm": [304.2, 254, 240.5]},
             "largest_part_mm": [665.08, 254]}
    monkeypatch.setattr(cl, "describe_order", lambda *a, **k: dict(order))
    seen = {}
    monkeypatch.setattr(cl, "_line", lambda code, o, d, h: seen.setdefault("d", d))
    cl.packaging_line([], 1)
    assert "packed as the assembled unit, 304.2 x 254 x 240.5mm" in seen["d"]
    assert "largest panel" not in seen["d"]
