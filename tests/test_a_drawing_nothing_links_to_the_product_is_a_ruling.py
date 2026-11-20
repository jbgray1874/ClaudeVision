"""A DRAWING NOTHING LINKS TO THE PRODUCT IS A RULING, NOT ONLY A SENTENCE (20 Nov 2026).

12110-01-GA1, run d95c7b140e6a: 12110-07-06M is drawn on sheet 8 of the End Roofing Panel's
own PDF; neither the model nor any printed parts list holds it, so it is rightly not priced. It
was said only in the scope sentence at the top of the report, and none of the estimate's 74
decisions named it, so a reviewer read it as a part dropped. It is now a ruling the estimate
waits on. A line the graph reaches is not asked about. Invented numbers.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import costed_facts as cf  # noqa: E402


def _summary(issues):
    return {"declared_product": "50005-01-GA", "drawing_number": "50005-01-GA",
            "estimate_summary": {"part_estimates": [], "canonical_route_shadow": {
                "declared_product": "50005-01-GA", "product_root": "50005-01-GA",
                "issues": issues, "nodes": []}}}


def test_an_unlinked_drawing_is_a_ruling_on_the_decision_list():
    s = _summary([{"code": "not_linked_to_the_product", "product": "50005-01-GA",
                   "identities": ["50005-07-06M"], "detail": "not linked"}])
    rows = [d for d in cf.costed_job(s)["decisions_required"]
            if d.get("check_code") == "not_linked_to_the_product"]
    assert [(d["part"], d["kind"]) for d in rows] == [("50005-07-06M", "ruling")]
    assert "not priced" in rows[0]["assumption"]


def test_with_nothing_unlinked_no_such_row():
    rows = [d for d in cf.costed_job(_summary([]))["decisions_required"]
            if d.get("check_code") == "not_linked_to_the_product"]
    assert rows == []
