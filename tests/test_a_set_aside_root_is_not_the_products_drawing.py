"""12645, 19:17 book (build 8fe2bc5): the product reached the body as "12645-01GA V2" and set
aside "12645-01GA" — the same drawing under its title block's number — with the 120 nuts and 16
tek screws only that spelling owned. The reached-item check (D-315) walks the reached graph and
scoping had removed both, so the run completed and the report said "the 2 line(s) only it
reaches". A set-aside root that is a spelling of a drawing the product reaches now blocks, by
name."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import invariants as inv  # noqa: E402


def _summary(root, product_nodes):
    return {"estimate_summary": {"canonical_route_shadow": {
        "product_root": product_nodes[0],
        "nodes": [{"part_number": n, "evidence": {}} for n in product_nodes],
        "issues": [{"code": "outside_the_product", "root": root,
                    "identities": [root, "4.8MMHEXHEADTEKSCREW", "BI-NUT"]}]}}}


def test_the_products_own_drawing_under_another_spelling_blocks_by_name():
    out = inv.check_a_set_aside_root_is_not_the_products_drawing(
        _summary("12645-01GA", ["12645-DRS EXTERNAL SHELTER V2", "12645-01GA V2"]))
    assert [v["code"] for v in out] == ["set_aside_root_is_the_products_drawing"]
    assert out[0]["severity"] == inv.BLOCKING
    assert "BI-NUT" in out[0]["message"] and "4.8MMHEXHEADTEKSCREW" in out[0]["message"]


def test_another_general_arrangement_set_aside_is_not_blocked():
    """11650-06: the cabinet top's GA is a different drawing from the kit; setting it aside is
    the product rule working."""
    assert inv.check_a_set_aside_root_is_not_the_products_drawing(
        _summary("11650-02-GA", ["11650-06-GA", "11650-02-SA02"])) == []
