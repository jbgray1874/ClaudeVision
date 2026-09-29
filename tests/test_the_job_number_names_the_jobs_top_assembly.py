"""The job number on its own is the job, and the job ships its top assembly.

James Gray, 29 Sep 2026, on 12173 Card Spinner: "it is 02 but we need to be able to run
against the top level 12173." The portal refused "12173": "12173 does not name any drawing
added here. Assemblies in the pack: 12173-02-GA Card Spinner; 12173-03-GA Spinner; ...
12173-07-GA Windmill WSF45. Type the one that is the product."

No sheet is numbered 12173 alone. But only one of the job's GAs is on top — 12173-02-GA,
whose parts list takes 03, 04, 05, 06 and 07-GA — and that one is the product. The rule is
the parts lists', not a name: two tops are still a choice, and a choice is still refused.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import product_identity as pi                                          # noqa: E402
import route_compiler as rc                                            # noqa: E402

_FILES = [
    "12173-02-GA Card Spinner_REVA.pdf",
    "12173-03-GA Spinner_REVA.pdf",
    "12173-03-201.pdf",
    "12173-04-GA Windmill WSF45_REVA.pdf",
    "12173-05-GA Rail_REVA.pdf",
    "12173-06-GA Single Bar Hook - 100mm_REVA.pdf",
    "12173-07-GA Windmill WSF45_REVA.pdf",
    "12173-07-1-GA Wrapping Paper Top Rack_REVA.pdf",
    "12173-07-2-GA Wrapping Paper Trough_REVA.pdf",
]


def _pack():
    """12173 as its parts lists read: 02 on top, 07 over its two racks."""
    gas = ["12173-02-GA", "12173-03-GA", "12173-04-GA", "12173-05-GA", "12173-06-GA",
           "12173-07-GA", "12173-07-1-GA", "12173-07-2-GA"]
    parts = [{"part_number": g, "description": g, "quantity": 1,
              "is_assembly_parent": True, "page_roles": ["assembly"]} for g in gas]
    parts += [{"part_number": p, "description": p, "quantity": 1, "page_roles": ["detail"]}
              for p in ("12173-03-201", "12173-04-201", "12173-05-101", "12173-06-201",
                        "12173-07-1-01M", "12173-07-2-02M")]
    extract = {"assemblies": [
        {"part_number": "12173-02-GA", "children": [
            {"part_number": "12173-03-GA", "qty": 1},
            {"part_number": "12173-04-GA", "qty": 2},
            {"part_number": "12173-05-GA", "qty": 1},
            {"part_number": "12173-06-GA", "qty": 8},
            {"part_number": "12173-07-GA", "qty": 1}]},
        {"part_number": "12173-03-GA", "children": [{"part_number": "12173-03-201", "qty": 2}]},
        {"part_number": "12173-04-GA", "children": [{"part_number": "12173-04-201", "qty": 1}]},
        {"part_number": "12173-05-GA", "children": [{"part_number": "12173-05-101", "qty": 1}]},
        {"part_number": "12173-06-GA", "children": [{"part_number": "12173-06-201", "qty": 1}]},
        {"part_number": "12173-07-GA", "children": [
            {"part_number": "12173-07-1-GA", "qty": 1},
            {"part_number": "12173-07-2-GA", "qty": 1}]},
        {"part_number": "12173-07-1-GA", "children": [
            {"part_number": "12173-07-1-01M", "qty": 1}]},
        {"part_number": "12173-07-2-GA", "children": [
            {"part_number": "12173-07-2-02M", "qty": 2}]},
    ]}
    return parts, extract


def test_the_portal_lets_the_job_number_run():
    """Not "none" — "none" holds Run. Said, and the assemblies named, but not blocked."""
    r = pi.resolve_product("12173", _FILES)
    assert r["status"] == "job", r
    assert "job number" in r["message"] and "12173-02-GA" in r["message"]
    assert "Type the one that is the product" not in r["message"]


def test_a_number_that_is_not_this_job_is_still_refused():
    r = pi.resolve_product("12174", _FILES)
    assert r["status"] == "none", r


def test_the_job_number_is_the_jobs_own_numbering_only():
    assert pi.is_of_the_job("12173", "12173-02-GA")
    assert pi.is_of_the_job("12173", "12173 - Card Spinner")
    assert not pi.is_of_the_job("12173", "121730-02-GA")
    assert not pi.is_of_the_job("12173-02", "12173-02-GA")     # not a job number alone


def test_the_run_prices_the_top_assembly():
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract, declared_product="12173")
    assert g["product_root"] == "12173-02-GA" and g["top_assemblies"] == ["12173-02-GA"]
    codes = {i.get("code") for i in g["issues"]}
    assert "declared_product_not_resolved" not in codes, g["issues"]
    assert "product_is_the_jobs_top_assembly" in codes
    q = g["quantities"]
    assert q["12173-06-GA"] == 8 and q["12173-06-201"] == 8
    assert q["12173-07-2-02M"] == 2


def test_the_same_run_typed_by_its_ga_is_the_same_product():
    parts, extract = _pack()
    by_job = rc.build_part_graph(parts, extract, declared_product="12173")
    parts, extract = _pack()
    by_ga = rc.build_part_graph(parts, extract, declared_product="12173-02")
    assert by_job["product_root"] == by_ga["product_root"]
    assert by_job["quantities"] == by_ga["quantities"]


def test_two_tops_of_the_job_are_a_choice_and_refused():
    """07 not linked under 02: two GAs on top. Nothing is chosen for the estimator."""
    parts, extract = _pack()
    extract["assemblies"][0]["children"] = [
        c for c in extract["assemblies"][0]["children"] if c["part_number"] != "12173-07-GA"]
    g = rc.build_part_graph(parts, extract, declared_product="12173")
    assert g["product_root"] == ""
    issue = next(i for i in g["issues"] if i.get("code") == "declared_product_not_resolved")
    assert issue["rolled_up"] is False
    assert sorted(issue["candidates"]) == ["12173-02-GA", "12173-07-GA"]
