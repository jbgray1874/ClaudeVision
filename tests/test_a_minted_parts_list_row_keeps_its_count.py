"""12645: the body's parts list prints 120 M8 nuts under "Half Inch Whitworth Nut", a code with
no digit, so the table reconciler minted BI-NUT for the row and wrote its 120 with no source.
The over-50 guard exempts a count read off a parts list (D-315) and could not see that this one
was: the record went to costing as 1 nut, flagged "reset to 1" (offline replay of the pack).
The two match paths beside the mint already record "bom_tree"; the mint now does too."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as e  # noqa: E402
import file_scan as fs  # noqa: E402
import source_precedence as sp  # noqa: E402


def test_a_minted_row_over_the_cap_is_costed_at_its_printed_count():
    summary = {"estimate_summary": {"part_estimates": []}}
    fs._reconcile_dualpath_into_part_estimates(summary, {"rows": [
        {"part_code": "Half Inch Whitworth Nut", "description": "M8 FULL NUT BZP GRADE 8",
         "qty": 120, "bom_parent": "12645-01GA"}]})
    (rec,) = summary["estimate_summary"]["part_estimates"]
    assert rec["part_number"] == "BI-NUT"
    assert sp.source_of(rec, "quantity") == "bom_tree"
    assert e._sanitise_part_quantity(rec) == 120
