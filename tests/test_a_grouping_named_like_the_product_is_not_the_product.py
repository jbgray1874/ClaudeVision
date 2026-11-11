"""A model grouping named like the product is not the product (JG, 10 Nov 2026, 6364-01).

The run was asked for "6364-01". The model's "6364-01 Base Asm" names it by the number-and-
title rule, and the GA, 6364-01-000, does not; the base was costed as the product and the GA
with the bin, legs, rails, castors and every fixing was set aside as detail: £195 for a voting
unit. A candidate matched by its title, whose every part another root numbered under the
declared number already reaches, is a grouping of that root, and that root is the product."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc                                            # noqa: E402


def _p(pn, desc, **kw):
    return dict(part_number=pn, description=desc, quantity=kw.pop("q", 1), **kw)


def _pack(base_children=("9001-01-001",)):
    parts = [_p("9001-01-000", "VOTING UNIT"), _p("9001-01 Base Asm", "BASE ASM"),
             _p("9001-01-001", "BASE", normalized_material="MFC"),
             _p("9001-01-010", "BIN ASSEMBLY"), _p("9001-01-004", "BIN", normalized_material="MFC"),
             _p("9001-01-016", "LEG", normalized_material="MFC"),
             _p("ROSS: 50-360", "CASTOR", page_roles=["bought_in"])]
    extract = {"top_assembly": {"part_number": "9001-01-000"}, "assemblies": [
        {"part_number": "9001-01-000", "children": [
            {"part_number": "9001-01-001", "qty": 1}, {"part_number": "9001-01-010", "qty": 1},
            {"part_number": "9001-01-016", "qty": 2}, {"part_number": "ROSS: 50-360", "qty": 4}]},
        {"part_number": "9001-01-010", "children": [{"part_number": "9001-01-004", "qty": 1}]},
        {"part_number": "9001-01 Base Asm", "children": [
            {"part_number": c, "qty": 1} for c in base_children]},
    ]}
    return parts, extract


def _ids(g):
    return {n.part_number.upper() for n in g["nodes"]}


def test_the_root_that_holds_the_groupings_parts_is_the_product():
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract, declared_product="9001-01")
    issue = next(i for i in g["issues"]
                 if i.get("code") == "product_is_the_root_that_holds_its_parts")
    assert issue["product"].upper() == "9001-01-000"
    assert issue["set_aside_as_product"].upper() == "9001-01 BASE ASM"
    gone = {x.upper() for x in rc.outside_product_identities(g["issues"])}
    for pn in ("9001-01-001", "9001-01-010", "9001-01-004", "9001-01-016", "ROSS: 50-360"):
        assert pn not in gone, f"{pn} set aside"
    assert g["quantities"].get("9001-01-016") == 2.0


def test_a_grouping_holding_a_part_the_root_does_not_reach_stays_the_product():
    parts, extract = _pack(base_children=("9001-01-001", "9001-01-099"))
    parts.append(_p("9001-01-099", "BASE PANEL ONLY IN THE GROUPING", normalized_material="MFC"))
    g = rc.build_part_graph(parts, extract, declared_product="9001-01")
    assert not any(i.get("code") == "product_is_the_root_that_holds_its_parts"
                   for i in g["issues"]), "nothing guessed when the root does not hold it all"
