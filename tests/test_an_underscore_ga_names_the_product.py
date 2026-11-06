"""An underscore before the sheet role is a separator, like a dash (D-426).

8188-08 M&S Hero Header, the live run of 9 Oct 14:50: the title block prints "8188-08_GA" and
the SolidWorks model is 8188-08_GA.SLDASM, so the graph's root kept the underscore. The
Drawing Number 8188-08 then named no assembly — "The pack has 2 top-level assemblies
(8188-12-GA, 8188-08_GA) and none can be chosen without guessing, so NOTHING is rolled up" —
and the magnetic swing stopper, removed from the GA at Rev G and on no parts list, was priced
beside the product: its plate lasered, its magnets, its powder, its assembly row.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc                                           # noqa: E402
from part_code_conventions import strip_assembly_role                 # noqa: E402
from product_identity import names_the_product, resolve_product       # noqa: E402


def test_an_underscore_role_strips_like_a_dash():
    assert strip_assembly_role("8188-08_GA") == "8188-08"
    assert strip_assembly_role("8188-08-GA") == "8188-08"
    assert strip_assembly_role("11908-21 GA") == "11908-21"


def test_only_a_role_strips_whatever_the_separator():
    """A hand is a product, and a numbered GA is a second drawing — underscore or not."""
    assert strip_assembly_role("ABC_LEFT") == "ABC_LEFT"
    assert strip_assembly_role("7332-01_GA2") == "7332-01_GA2"


def test_the_number_typed_names_the_underscore_ga_and_nothing_under_it():
    assert names_the_product("8188-08", "8188-08_GA")
    assert names_the_product("8188-08-GA", "8188-08_GA")
    assert not names_the_product("8188-08", "8188-08-SA05")
    assert not names_the_product("8188-08", "8188-12-GA")


def _pack():
    """8188-08 as the model gave it: the product's GA with the underscore, and the swing
    stopper's GA, which nothing in the product lists."""
    parts = [
        {"part_number": "8188-08_GA", "description": "THE FISHMONGER ASSY", "quantity": 1,
         "is_assembly_parent": True, "page_roles": ["assembly"]},
        {"part_number": "8188-08-SA05", "description": "FISHMONGER GRILL ASSY", "quantity": 1,
         "is_sub_assembly": True, "page_roles": ["assembly"]},
        {"part_number": "8188-08-007", "description": "TRAPPER BRACKET", "quantity": 2,
         "page_roles": ["detail"]},
        {"part_number": "8188-12-GA", "description": "MAGNETIC SWING STOPPER", "quantity": 1,
         "is_assembly_parent": True, "page_roles": ["assembly"]},
        {"part_number": "8188-12-001", "description": "STOPPER PLATE", "quantity": 1,
         "page_roles": ["detail"]},
    ]
    extract = {"assemblies": [
        {"part_number": "8188-08_GA", "children": [{"part_number": "8188-08-SA05", "qty": 1}]},
        {"part_number": "8188-08-SA05", "children": [{"part_number": "8188-08-007", "qty": 2}]},
        {"part_number": "8188-12-GA", "children": [{"part_number": "8188-12-001", "qty": 1}]},
    ]}
    return parts, extract


def test_the_declared_number_roots_the_underscore_ga_and_sets_the_stopper_aside():
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract, declared_product="8188-08")
    q = g["quantities"]
    assert g["product_root"] == "8188-08_GA", g.get("product_issues")
    assert q["8188-08-007"] == 2, q
    for gone in ("8188-12-GA", "8188-12-001"):
        assert gone not in q, f"{gone} is the stopper the GA dropped, and was still costed"
    codes = {i.get("code") for i in g.get("product_issues") or []}
    assert "declared_product_not_resolved" not in codes, g.get("product_issues")


def test_the_portal_check_finds_the_underscore_ga_before_run():
    r = resolve_product("8188-08", [
        "0348503_8188-08_GA_Hero_Header_Chilled_Fishmonger_REV_H.PDF",
        "8188-12-GA_MAGNETIC_SWING_STOPPER_REVB.PDF",
        "8188-29-SA01_Common_Frame_REVA.PDF",
    ])
    assert r["status"] == "ok", r["message"]
