"""12645: the body's parts list prints 120 M8 bolts; the over-50 quantity guard reset them to
1, so the book charged one bolt (D-315). The guard is for a number of unknown origin."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as e  # noqa: E402
import source_precedence as sp  # noqa: E402


def test_a_count_read_from_a_parts_list_is_kept():
    part = {"part_number": "M8 HEX HEAD BOLT"}
    sp.apply_field(part, "quantity", 120, "bom_tree")
    assert e._sanitise_part_quantity(part) == 120
    assert any(isinstance(f, dict) and f.get("flag") == "quantity_over_cap_kept"
               for f in part["review_flags"])


def test_a_count_of_unknown_origin_is_still_capped():
    assert e._sanitise_part_quantity({"part_number": "X", "quantity": 120}) == 1


def test_a_drawing_number_read_as_a_count_is_still_reset():
    part = {"part_number": "8172-01_WELDMENT"}
    sp.apply_field(part, "quantity", 8172, "bom_tree")
    assert e._sanitise_part_quantity(part) == 1
