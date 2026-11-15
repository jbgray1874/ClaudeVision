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


# ── THE SUM OF SEVERAL TABLES' PRINTED COUNTS (15 Nov 2026) ────────────────────────────────
def _insert(rows):
    return {"part_number": "FIXING-INSERT", "quantity": sum(q for _p, q in rows),
            "bom_parents": [{"parent": p, "qty": q} for p, q in rows]}


def test_a_count_that_is_the_sum_of_its_parts_lists_rows_is_kept():
    part = _insert([("T-101", 14), ("T-102", 29), ("T-103", 14)])
    assert e._sanitise_part_quantity(part) == 57
    assert "quantity_unresolved" not in part
    flag = part["review_flags"][-1]
    assert flag["flag"] == "quantity_over_cap_kept" and "14 under T-101" in flag["detail"]


def test_a_count_that_is_not_the_sum_of_its_rows_is_still_capped():
    part = _insert([("T-101", 14), ("T-102", 29)])
    part["quantity"] = 57
    assert e._sanitise_part_quantity(part) == 1 and part["quantity_unresolved"]["computed"] == 57


def test_one_row_alone_is_not_this_rule():
    part = _insert([("T-101", 57)])
    assert e._sanitise_part_quantity(part) == 1
