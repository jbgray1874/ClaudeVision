"""A bought-in size printed in two units is a question, not a silent price (D-426).

8188-08's GA lists 14 of "KINGDOM: 50mm x 10mm x 2m MAGNET". The market lookup priced fourteen
two-metre magnets at £48.50 each — £706.16 of a £1,814 unit — where the GA's note calls them neo
magnets taped to the underside, most likely 2 mm. The line stays priced as printed; the mix of
units is put to a person on the line's own decisions.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator                                                      # noqa: E402
from extractor_patterns import size_mixing_units                      # noqa: E402


def test_a_size_in_millimetres_and_metres_is_found():
    hit = size_mixing_units("50mm x 10mm x 2m MAGNET")
    assert hit and hit["text"] == "50mm x 10mm x 2m" and hit["units"] == ["m", "mm"]


def test_a_size_in_one_unit_or_none_is_not():
    for text in ("25.4 x 25.4 x 1.2 x 300mm", "1292 x 200", "2m x 1m", "M6 x 20 FLANGE BUTTON",
                 "M6X12MM THREADED INSERT", "6MM GLUE IN DOWEL"):
        assert size_mixing_units(text) is None, text


def test_the_bought_in_line_carries_the_question_and_keeps_its_price():
    part = {"part_number": "KINGDOM", "description": "50mm x 10mm x 2m MAGNET", "quantity": 14,
            "is_bought_in": True, "page_roles": ["bought_in"], "unit_cost_gbp": 48.5}
    estimator.estimate_process_times(part, 14)
    qs = [q for q in part.get("manufacturing_questions") or []
          if q.get("source") == "extractor_patterns.size_mixing_units"]
    assert len(qs) == 1 and "50mm x 10mm x 2m" in qs[0]["issue"], qs
    # D-430: the figure is held, not charged — the record keeps it, the sheet shows it
    assert qs[0]["assumption"].startswith("held out of the unit cost")
    assert part["_price_held"]["reason"].startswith("the printed size 50mm x 10mm x 2m")
    assert part["unit_cost_gbp"] == 48.5
