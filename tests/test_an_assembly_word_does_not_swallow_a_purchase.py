"""12645 DRS External Shelter, 19:17 book (8fe2bc5): the top sheet's parts list prints
"Roller Shutter / Roller Shutter Door x2". BOMs & Routes carried it at 2 and the Assemble/pack
row named it, but the Estimate had no line for it: no price, no NOT PRICED flag, and the
banner said "5 to settle" without it — the biggest-money item on the job, absent in silence.

The existing minter (document_builder.bought_in_rows_without_records) did mint it as a
purchase. The table-row safety net then threw the mint away: 12645-03GA's one-word
description, DOOR, sits inside "Roller Shutter Door", so the subset article match filed the
shutter row as an occurrence of the door ASSEMBLY (D-318). One article inside another is now
the same article only between purchases.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import file_scan as fs  # noqa: E402

SHUTTER_ROW = {"part_number": "Roller Shutter", "description": "Roller Shutter Door",
               "quantity": 2, "bom_parent": "12645 - DRS EXTERNAL SHELTER V2"}


def _recon(held, rows):
    s = {"estimate_summary": {"part_estimates": [dict(h) for h in held]}}
    fs._reconcile_dualpath_into_part_estimates(s, {"rows": [dict(r) for r in rows]})
    return s["estimate_summary"]["part_estimates"]


def test_an_assembly_description_does_not_swallow_a_purchased_row():
    """The 12645 log: '[recon-row] ADD piano hinge' and nothing for the shutter."""
    parts = _recon([{"part_number": "12645-03GA", "description": "DOOR", "quantity": 1,
                     "page_roles": ["detail"]}], [SHUTTER_ROW])
    got = {str(p.get("part_number") or "").upper(): p for p in parts}
    assert "ROLLER SHUTTER" in got, sorted(got)
    assert got["ROLLER SHUTTER"]["quantity"] == 2
    assert got["12645-03GA"]["quantity"] == 1


def test_two_purchases_one_inside_the_other_are_still_one_article():
    """The rule the subset match was written for stands: "JST Y SPLITTER" holds
    "JST Y SPLITTER 3 WAY" (12567, D-290)."""
    parts = _recon([{"part_number": "BI-JSTYSPLITTER", "description": "JST Y SPLITTER",
                     "quantity": 1, "page_roles": ["bought_in"]}],
                   [{"part_number": "P/P", "description": "JST Y SPLITTER 3 WAY",
                     "quantity": 2, "bom_parent": "12567-02-GA"}])
    assert len(parts) == 1


def test_the_minted_shutter_reaches_the_graph_as_a_purchase_and_the_tally():
    """The whole chain on the fixed recon: the node is bought_in, the sheet has a row at 2
    with no price, and outstanding_summary names it as a missing price."""
    import costed_facts as cf
    import route_compiler as rc
    import wb_populate as wp
    top = "12645 - DRS EXTERNAL SHELTER V2"
    parts = _recon([{"part_number": "12645-03GA", "description": "DOOR", "quantity": 1,
                     "page_roles": ["detail"]}], [SHUTTER_ROW])
    shutter = next(p for p in parts if str(p.get("part_number") or "").upper() == "ROLLER SHUTTER")
    rows = [dict(SHUTTER_ROW),
            {"part_number": "12645-03GA", "description": "DOOR", "quantity": 1, "bom_parent": top}]
    graph = rc.build_part_graph(parts, {"assemblies": []}, bom_rows=rows)
    kinds = {str(n.part_number).upper(): n.kind for n in graph["nodes"]}
    assert kinds.get("ROLLER SHUTTER") == "bought_in", kinds
    assert shutter.get("quantity") == 2
    summary = cf.outstanding_summary(cf.costed_job(
        {"estimate_summary": {"part_estimates": [dict(shutter)]}}))
    assert summary["prices_missing"] == 1
    assert "Roller Shutter" in summary["named_phrase"]
