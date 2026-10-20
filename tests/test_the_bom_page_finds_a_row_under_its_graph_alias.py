"""12645, 19:17 book, BOMs & Routes: "12645-01GAV2 BODY FRAME" (row 12) and, on the offline
replay, "Half Inch Whitworth Nut" printed qty own and a BLANK qty effective although the graph
held both — as 12645-01GA V2 and BI-NUT, each carrying the printed spelling as an alias. The
page read the payload's "aliases" key, which no payload carries; the aliases live on the nodes,
where wb_populate already reads them."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bom_and_route_extract as bre  # noqa: E402


def _summary():
    return {
        "document_analysis": {"bom_rows": [
            {"part_number": "Half Inch Whitworth Nut", "description": "M8 FULL NUT BZP GRADE 8",
             "quantity": 120, "bom_parent": "12645-01GA"},
            {"part_number": "12645-01GAV2", "description": "BODY FRAME", "quantity": 1}]},
        "estimate_summary": {"canonical_route_shadow": {"nodes": [
            {"part_number": "BI-NUT", "qty_per_unit": 120.0, "qty_own": 120.0,
             "qty_trail": ["12645-01GA x1 -> BI-NUT x120 (BOM) = 120"],
             "evidence": {"raw_aliases": ["HALF INCH WHITWORTH NUT"]}},
            {"part_number": "12645-01GA", "qty_per_unit": 1.0,
             "evidence": {"raw_aliases": ["12645-01GA V2", "12645-01GAV2"]}}]}},
    }


def test_a_row_printed_under_an_aliased_spelling_gets_its_effective_quantity():
    rows = {r["part_number"]: r for r in bre.bom_sheet(_summary())}
    assert rows["Half Inch Whitworth Nut"]["qty_effective"] == 120.0
    assert "BI-NUT x120" in rows["Half Inch Whitworth Nut"]["how_the_quantity_multiplies"]
    assert rows["12645-01GAV2"]["qty_effective"] == 1.0
