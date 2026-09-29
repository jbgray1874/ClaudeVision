"""The banner counts what the sheet leaves open, not only what it priced.

12645 DRS External Shelter, 19:17 book: Estimate!H6 read "PROVISIONAL — to settle: 4 market
figures to replace + 1 quantity check" on a £3,493.86 unit. Counted nowhere: the two roller
shutters (reached, no line at all), the 120 M8 nuts and 16 tek screws (stated on the body's
parts list, not carried), and the provisional steel lines. The tally built its list from
priced lines, and the reached-item check that does see a missing item runs after the banner
is written (D-324). The same walk now feeds both, and a blocking check whose items are
already rows is not counted twice.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf  # noqa: E402
import invariants as inv  # noqa: E402


def _node(pn, kind, children=(), aliases=(), qty=1.0):
    return {"part_number": pn, "kind": kind, "qty_per_unit": qty,
            "children": [{"part_number": c, "qty": 1.0} for c in children],
            "evidence": {"raw_aliases": list(aliases)}}


def _charged(pn, gbp=5.0):
    return {"part_number": pn, "quantity": 1, "unit_total_cost_gbp": gbp,
            "extended_total_cost_gbp": gbp,
            "material_estimate": {"cost_per_part_gbp": gbp, "unit_material_cost_gbp": gbp}}


def _summary(nodes, parts, bom_rows=(), root="P-TOP"):
    return {"document_analysis": {"bom_rows": list(bom_rows)},
            "estimate_summary": {
                "part_estimates": parts,
                "canonical_route_shadow": {"schema": "priced_route.v1", "product_root": root,
                                           "top_assembly": root, "nodes": nodes}}}


TOP = _node("P-TOP", "assembly", children=("P-BODY", "WIDGET SHUTTER"))
BODY = _node("P-BODY", "assembly", children=("P-01M",), aliases=("P-BODY V2",))
PANEL = _node("P-01M", "leaf")
SHUTTER = dict(_node("WIDGET SHUTTER", "leaf", qty=2.0),
               evidence={"raw_aliases": [], "bom_stated": True})   # a parts list printed it


def test_a_reached_item_with_no_line_is_a_missing_price():
    s = _summary([TOP, BODY, PANEL, SHUTTER], [_charged("P-01M")])
    summary = cf.outstanding_summary(s)
    assert summary["prices_missing"] == 1, summary
    assert summary["phrase"].startswith("1 price missing")
    d = next(d for d in cf.costed_job(s)["decisions_required"] if d["part"] == "WIDGET SHUTTER")
    assert d["kind"] == "missing_price" and d["qty"] == 2.0
    assert "no line on the sheet" in d["issue"]


def test_the_tally_does_not_wait_for_the_checks_and_does_not_count_twice():
    s = _summary([TOP, BODY, PANEL, SHUTTER], [_charged("P-01M")])
    before = cf.costed_job(s)["release"]["outstanding"]
    s["invariants"] = {"violations": inv.check_every_reached_bom_item_is_accounted_for(s)}
    assert s["invariants"]["violations"], "the check still fires"
    assert cf.costed_job(s)["release"]["outstanding"] == before == 1


def test_a_stated_row_the_product_does_not_carry_is_counted():
    rows = [{"part_number": "Half Inch Nut", "description": "M8 FULL NUT", "quantity": 120,
             "bom_parent": "P-BODY"},
            {"part_number": "P-01M", "description": "PANEL", "quantity": 1},         # carried
            {"part_number": "P-BODY V2", "description": "BODY", "quantity": 1}]      # an alias
    s = _summary([TOP, BODY, PANEL], [_charged("P-01M")], bom_rows=rows)
    summary = cf.outstanding_summary(s)
    assert summary["stated_not_carried"] == 1, summary
    assert "1 stated row not carried" in summary["phrase"]
    assert cf.costed_job(s)["release"]["draft"] is True


def test_a_stated_row_is_not_counted_when_the_product_did_not_resolve():
    """Offline 12645 stopped its roll-up; counting against either root flagged every row under
    the other. The stopped roll-up has its own issue."""
    rows = [{"part_number": "Half Inch Nut", "description": "M8 FULL NUT", "quantity": 120}]
    s = _summary([TOP, BODY, PANEL], [_charged("P-01M")], bom_rows=rows, root="")
    assert cf.stated_rows_not_carried(s) == []


def test_market_figures_carry_their_money_in_the_phrase():
    s = _summary([TOP, BODY, PANEL], [_charged("P-01M")])
    job = cf.costed_job(s)
    job["decisions_required"].append({"part": "PACKAGING", "kind": "market_figure",
                                      "gbp_at_stake": 135.0})
    assert "1 market figure to replace (£135.00)" in cf.outstanding_summary(job)["phrase"]


def test_a_clean_job_still_says_nothing_outstanding():
    top = dict(TOP, children=[{"part_number": "P-BODY", "qty": 1.0}])
    s = _summary([top, BODY, PANEL], [_charged("P-01M")])
    assert cf.outstanding_summary(s)["phrase"] == "nothing outstanding"


def test_a_line_the_sheet_carries_is_not_reported_as_missing():
    """12645 14:03 report: "FIXING x16 is on the bill the product reaches and has no line on
    the sheet" — beside Estimate row 19, FIXING x16 at £1.50. The workbook minted and priced
    that line for a bought-in node with no engine record, so it lived only in the list the
    sheet was written from, which the check did not read (D-328)."""
    fixing = _node("FIXING", "bought_in", qty=16.0)
    top = dict(TOP, children=[{"part_number": "P-BODY", "qty": 1.0},
                              {"part_number": "FIXING", "qty": 16.0}])
    s = _summary([top, BODY, PANEL, fixing], [_charged("P-01M")])
    assert "FIXING" in inv._reached_unaccounted_core(s)["unaccounted"], "the fault, as shipped"
    s["estimate_summary"]["canonical_part_estimates"] = [
        _charged("P-01M"),
        {"part_number": "FIXING", "description": "M8x20mm HEX HEAD BOLT", "quantity": 16,
         "unit_cost_gbp": 0.09, "_canonical_kind": "bought_in"}]
    assert inv._reached_unaccounted_core(s)["unaccounted"] == []
    assert not any("has no line on the sheet" in str(d.get("issue"))
                   for d in cf.costed_job(s)["decisions_required"])


def test_a_sheet_line_with_no_price_is_still_an_open_question():
    """The sheet's list is read for what it carries, not as a pass: a minted line with no price
    and no ask is still unaccounted."""
    fixing = _node("FIXING", "bought_in", qty=16.0)
    top = dict(TOP, children=[{"part_number": "P-BODY", "qty": 1.0},
                              {"part_number": "FIXING", "qty": 16.0}])
    s = _summary([top, BODY, PANEL, fixing], [_charged("P-01M")])
    s["estimate_summary"]["canonical_part_estimates"] = [
        {"part_number": "FIXING", "description": "M8 BOLT", "quantity": 16}]
    assert "FIXING" in inv._reached_unaccounted_core(s)["unaccounted"]
