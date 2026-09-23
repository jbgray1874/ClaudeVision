"""The portal's Drawing Number is the product; every other GA in the pack is detail.

James Gray, 23 Sep 2026, on the 11650-06 re-run: "Drawing Number on the portal is the
product. Every other GA in the folder is detail, counted only on a path from that product.
Do not treat 'two GAs in one enquiry' as two things that ship. That assumption is what
doubled SA02 / tabs / RSB / PEM."

The folder held the Coffret kit GA (11650-06-GA) and the cabinet-top GA (11650-02-GA). The
kit takes three of the top's RSB sub-assembly; the top's own BOM — its panels, its Ross
hardware, and one more SA02 — was costed as a second product beside the kit.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc                                           # noqa: E402


def _pack():
    """11650-06 as the folder arrived: the kit GA and the cabinet-top GA, both unowned."""
    parts = [
        {"part_number": "11650-06-GA", "description": "COFFRET HOSPITAL KIT", "quantity": 1,
         "is_assembly_parent": True, "page_roles": ["assembly"]},
        {"part_number": "11650-02-GA", "description": "CABINET TOP", "quantity": 1,
         "is_assembly_parent": True, "page_roles": ["assembly"]},
        {"part_number": "11650-02-SA02", "description": "RSB SUB ASSY", "quantity": 1,
         "is_sub_assembly": True, "page_roles": ["assembly"]},
        {"part_number": "11650-02-03M", "description": "RSB PLATE", "quantity": 1,
         "page_roles": ["detail"]},
        {"part_number": "11650-02-04M", "description": "LOCKING TAB", "quantity": 2,
         "page_roles": ["detail"]},
        {"part_number": "11650-02-01M", "description": "TOP PANEL", "quantity": 1,
         "page_roles": ["detail"]},
        {"part_number": "ROSS-HINGE", "description": "ROSS HINGE", "quantity": 2,
         "page_roles": ["detail"]},
    ]
    extract = {"assemblies": [
        {"part_number": "11650-06-GA", "children": [
            {"part_number": "11650-02-SA02", "qty": 3}]},
        {"part_number": "11650-02-GA", "children": [
            {"part_number": "11650-02-SA02", "qty": 1},
            {"part_number": "11650-02-01M", "qty": 1},
            {"part_number": "ROSS-HINGE", "qty": 2}]},
        {"part_number": "11650-02-SA02", "children": [
            {"part_number": "11650-02-03M", "qty": 1},
            {"part_number": "11650-02-04M", "qty": 2}]},
    ]}
    return parts, extract


def test_without_a_declared_product_the_second_ga_ships_too():
    """THE FAULT, AS IT WAS. Nothing named the product, so both GAs cascaded: SA02 4 not 3,
    and the top's panel and Ross hinges were costed into a kit that has none."""
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract)
    assert sorted(g["top_assemblies"]) == ["11650-02-GA", "11650-06-GA"]
    assert g["quantities"]["11650-02-SA02"] == 4
    assert "ROSS-HINGE" in g["quantities"]


def test_the_declared_product_is_the_only_root():
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract, declared_product="11650-06")
    q = g["quantities"]
    assert g["top_assemblies"] == ["11650-06-GA"] and g["product_root"] == "11650-06-GA"
    assert q["11650-02-SA02"] == 3, q
    assert q["11650-02-03M"] == 3, q
    assert q["11650-02-04M"] == 6, q
    for gone in ("11650-02-GA", "11650-02-01M", "ROSS-HINGE"):
        assert gone not in q, f"{gone} is only under the other GA and was still costed"
    # The shared sub-assembly keeps only the product's parent.
    sa02 = next(n for n in g["nodes"] if n.part_number == "11650-02-SA02")
    assert sa02.parents == ["11650-06-GA"], sa02.parents


def test_what_was_set_aside_is_said_and_named():
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract, declared_product="11650-06-GA Rev B")
    issue = next(i for i in g["issues"] if i.get("code") == "outside_the_product")
    assert issue["root"] == "11650-02-GA" and issue["product"] == "11650-06-GA"
    assert sorted(issue["identities"]) == ["11650-02-01M", "11650-02-GA", "ROSS-HINGE"]


def test_the_set_aside_records_leave_the_costed_population():
    """The graph forgetting a node does not stop its RECORD being priced — the workbook is
    written from the records. They leave, and the summary keeps what left and why."""
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract, declared_product="11650-06")
    summary: dict = {}
    removed = rc.set_aside_outside_product(parts, g["issues"], summary=summary)
    assert sorted(p["part_number"] for p in removed) == [
        "11650-02-01M", "11650-02-GA", "ROSS-HINGE"]
    assert all(p["part_number"] not in {"ROSS-HINGE", "11650-02-01M"} for p in parts)
    assert {e["root"] for e in summary["set_aside_outside_product"]} == {"11650-02-GA"}


def test_a_number_that_names_nothing_stops_the_roll_up_and_says_so():
    """Rule 4: no guess. Two roots and a Drawing Number that is neither — the Boots code, say
    — rolls nothing up: an un-multiplied kit is visibly unfinished, a doubled one is not."""
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract, declared_product="AC0706-03")
    assert g["top_assemblies"] == [] and g["product_root"] == ""
    issue = next(i for i in g["issues"] if i.get("code") == "declared_product_not_resolved")
    assert issue["rolled_up"] is False and "NOTHING is rolled up" in issue["detail"]
    assert g["quantities"]["11650-02-SA02"] == 1        # its own drawing count, un-multiplied


def test_one_root_and_a_mismatched_number_costs_the_root_and_flags_it():
    """With one root there is nothing to choose between, so it cascades — and the mismatch is
    still on the record for the estimator to correct."""
    parts, extract = _pack()
    parts = [p for p in parts if p["part_number"] not in {"11650-02-GA", "11650-02-01M",
                                                          "ROSS-HINGE"}]
    extract["assemblies"] = [a for a in extract["assemblies"]
                             if a["part_number"] != "11650-02-GA"]
    g = rc.build_part_graph(parts, extract, declared_product="11650-99")
    assert g["top_assemblies"] == ["11650-06-GA"]
    assert g["quantities"]["11650-02-SA02"] == 3
    issue = next(i for i in g["issues"] if i.get("code") == "declared_product_not_resolved")
    assert issue["rolled_up"] is True


def test_a_number_never_names_a_part_of_the_product():
    assert rc._names_the_product("11650-06", "11650-06-GA")
    assert rc._names_the_product("11650-06 GA_RevB", "11650-06-GA")
    assert not rc._names_the_product("11650-06", "11650-06-SA01")
    assert not rc._names_the_product("11650-06-GA", "11650-06-GA2")
    assert not rc._names_the_product("AC0706-03", "11650-06-GA")


def test_the_declared_product_reaches_every_compile(monkeypatch):
    """Read from the summary first, the environment (set by --product) second."""
    monkeypatch.setenv("SDI_PRODUCT", "11650-06")
    assert rc.declared_product_of({}) == "11650-06"
    assert rc.declared_product_of({"declared_product": "12392-04-GA"}) == "12392-04-GA"
    monkeypatch.delenv("SDI_PRODUCT")
    assert rc.declared_product_of({}) == ""


def test_the_runner_passes_the_portal_drawing_number():
    sys.path.insert(0, str(ROOT / "tools" / "runner"))
    import sdi_estimate_runner as runner
    cmd = runner.engine_command(ROOT, Path("python"), Path("job"), 2, "Boots",
                                product="11650-06")
    assert cmd[cmd.index("--product") + 1] == "11650-06"
    assert "--product" not in runner.engine_command(ROOT, Path("python"), Path("job"), 2,
                                                    "Boots")


def test_the_quote_is_titled_by_the_product_not_the_sheet_the_model_read():
    """Rule 5. The last run was titled AC0706-05 — the extender set's sheet."""
    from client_quote_html import _drawing_identity
    summary = {
        "llm_full_extract": {"drawing_info": {
            "drawing_number": "11650-06-SA01", "title": "AC0706-05 END PANEL GF CONVERSION",
            "revision": "A"}},
        "estimate_summary": {"canonical_route_shadow": {
            "product_root": "11650-06-GA", "top_assembly": "11650-06-GA",
            "top_assemblies": ["11650-06-GA"],
            "nodes": [{"part_number": "11650-06-GA",
                       "description": "COFFRET HOSPITAL KIT"}]}},
    }
    number, rev, product = _drawing_identity(summary, "11650-06-FragranceCoffret2025")
    assert number == "11650-06-GA", number
    assert "AC0706-05" not in f"{number} {rev} {product}"
    assert "COFFRET" in str(product).upper(), product
