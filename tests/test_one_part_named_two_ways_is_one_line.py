"""One part named two ways is one line on the sheet (D-334).

12645, 14:03 book of 29 Sep 2026: the shelter's parts list prints "HALF INCH WHITWORTH NUT /
M8 FULL NUT BZP GRADE 8" x120. The Estimate charged it twice — row 15 under the printed code at
a catalogue price, row 18 as "BI-NUT" at a market price — and AI Provenance said of each "also
appears as" the other. Two joins had pointed the pair at each other; the graph and the sheet
read one hop, so each name resolved to the other and both survived. Dave, 29 Sep: "confirm
whether they are duplicates and correct the sheet if so".
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc  # noqa: E402
import wb_populate as wp  # noqa: E402


def test_a_loop_settles_on_the_printed_code_not_the_invented_one():
    aliases = {"HALF INCH WHITWORTH NUT": "BI-NUT", "BI-NUT": "HALF INCH WHITWORTH NUT"}
    loops = rc._settle_alias_loops(aliases, {"HALF INCH WHITWORTH NUT": {}, "BI-NUT": {}})
    assert aliases == {"BI-NUT": "HALF INCH WHITWORTH NUT"}
    assert loops == [["BI-NUT", "HALF INCH WHITWORTH NUT"]]


def test_a_chain_is_followed_to_its_end():
    aliases = {"A-1 V2": "A-1", "A-1": "A-1-GA", "X": "Y"}
    rc._settle_alias_loops(aliases, {})
    assert aliases == {"A-1 V2": "A-1-GA", "A-1": "A-1-GA", "X": "Y"}


def test_the_choice_never_depends_on_order():
    one = {"BI-NUT": "NUT-7", "NUT-7": "BI-NUT"}
    two = {"NUT-7": "BI-NUT", "BI-NUT": "NUT-7"}
    rc._settle_alias_loops(one, {})
    rc._settle_alias_loops(two, {})
    assert one == two == {"BI-NUT": "NUT-7"}


def _node(pn, alias):
    return {"part_number": pn, "kind": "bought_in", "qty_per_unit": 120.0,
            "description": "M8 FULL NUT BZP GRADE 8", "children": [], "parents": ["12645-01GA"],
            "evidence": {"raw_aliases": [alias]}}


def _record(pn, price, source):
    return {"part_number": pn, "description": "M8 FULL NUT BZP GRADE 8", "quantity": 120,
            "page_roles": ["bought_in"], "unit_cost_gbp": price,
            "material_estimate": {"unit_material_cost_gbp": price, "cost_per_part_gbp": price,
                                  "price_source": {"source_class": source}}}


def test_the_12645_nut_pair_is_one_line_of_120():
    nodes = [_node("HALF INCH WHITWORTH NUT", "BI-NUT"),
             _node("BI-NUT", "HALF INCH WHITWORTH NUT")]
    summary = {"estimate_summary": {"canonical_route_shadow": {
        "schema": "priced_route.v1", "product_root": "12645", "top_assembly": "12645",
        "nodes": nodes}}}
    records = [_record("HALF INCH WHITWORTH NUT", 0.01, "udef_parts_table"),
               _record("BI-NUT", 0.01, "market_ai_indicative")]
    out = wp.canonicalise_part_estimates_for_workbook(summary, records)
    nuts = [r for r in out if "NUT" in str(r.get("part_number"))]
    assert len(nuts) == 1, [r.get("part_number") for r in out]
    assert nuts[0]["part_number"] == "HALF INCH WHITWORTH NUT"
    assert nuts[0]["quantity"] == 120.0                 # one 120, not two added together
