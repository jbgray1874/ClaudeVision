"""Every BOM item the product reaches is charged, free-issued, or an open question.

12567-01's 13:14 book: the two EPDM tape lengths were reached from the product through the
end header's table, sat on BOMs & Routes at x2, and had no line on the Estimate, no place on
the missing-price list and no ruling anywhere. The identity seal asks whether every priced
row is in the graph; nothing asked whether every reached graph item was on the bill (D-300).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import invariants as inv  # noqa: E402


def _summary(nodes, part_estimates, root="12567-01-GA"):
    return {"estimate_summary": {
        "part_estimates": part_estimates,
        "canonical_route_shadow": {"schema": "priced_route.v1", "product_root": root,
                                   "top_assembly": root, "nodes": nodes},
    }}


def _node(pn, kind, children=(), aliases=()):
    return {"part_number": pn, "kind": kind, "qty_per_unit": 1.0,
            "children": [{"part_number": c, "qty": 1.0} for c in children],
            "evidence": {"raw_aliases": list(aliases)}}


def _charged(pn, gbp=5.0):
    return {"part_number": pn, "quantity": 1, "unit_total_cost_gbp": gbp,
            "extended_total_cost_gbp": gbp}


GA = _node("12567-01-GA", "assembly",
           children=("12567-02-GA",))
SUB = _node("12567-02-GA", "assembly",
            children=("P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM", "12567-02-01M"))
TAPE = _node("P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM", "bought_in")
PANEL = _node("12567-02-01M", "leaf")


def _codes(violations):
    return {v["code"] for v in violations}


def test_a_reached_item_with_no_record_is_blocking():
    """The 13:14 shape: the tape is reached and nothing anywhere stands for it."""
    s = _summary([GA, SUB, TAPE, PANEL], [_charged("12567-02-01M")])
    out = inv.check_every_reached_bom_item_is_accounted_for(s)
    assert _codes(out) == {"reached_bom_item_unaccounted"}
    assert out[0]["severity"] == inv.BLOCKING
    assert "P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM" in out[0]["message"]
    assert "part_estimates[" not in out[0]["message"], "codes, never array indices"


def test_a_record_with_an_open_question_is_accounted_for():
    tape_rec = {"part_number": "P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM",
                "quantity": 2, "review_flags": [
                    "NOT PRICED — no catalogue, price file or quote we can query holds this item"]}
    s = _summary([GA, SUB, TAPE, PANEL], [_charged("12567-02-01M"), tape_rec])
    assert inv.check_every_reached_bom_item_is_accounted_for(s) == []


def test_money_in_the_total_is_accounted_for():
    tape_rec = {"part_number": "P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM",
                "quantity": 2,
                "cost_breakdown": {"system_cost": {"unit_cost_gbp": 3.25,
                                                   "applied_to_total": True}}}
    s = _summary([GA, SUB, TAPE, PANEL], [_charged("12567-02-01M"), tape_rec])
    assert inv.check_every_reached_bom_item_is_accounted_for(s) == []


def test_a_withheld_or_declined_price_is_an_open_question_not_a_silence():
    withheld = {"part_number": "P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM",
                "quantity": 2, "_price_explicitly_withheld": True}
    s = _summary([GA, SUB, TAPE, PANEL], [_charged("12567-02-01M"), withheld])
    assert inv.check_every_reached_bom_item_is_accounted_for(s) == []
    declined = {"part_number": "P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM",
                "quantity": 2,
                "cost_breakdown": {"system_cost": {
                    "unit_cost_gbp": 3.25, "applied_to_total": False,
                    "source": {"schema": "price_source.v1", "applied": True}}}}
    s = _summary([GA, SUB, TAPE, PANEL], [_charged("12567-02-01M"), declined])
    assert inv.check_every_reached_bom_item_is_accounted_for(s) == []


def test_a_fabricated_leaf_costed_in_sheet_steel_is_charged():
    """£0 BOM cell, material money in the block — the ordinary fabricated shape."""
    panel_rec = {"part_number": "12567-02-01M", "quantity": 1,
                 "material_estimate": {"extended_material_cost_gbp": 17.22}}
    s = _summary([GA, SUB, PANEL], [panel_rec])
    assert inv.check_every_reached_bom_item_is_accounted_for(s) == []


def test_assemblies_virtuals_commercials_and_set_asides_do_not_fire():
    virtual = _node("VIRTUAL_ JST SPLITTER^12567-02-301", "leaf")
    powder = _node("POWDER", "bought_in")
    sub = dict(SUB)
    sub["children"] = SUB["children"] + [{"part_number": virtual["part_number"], "qty": 1.0},
                                         {"part_number": "POWDER", "qty": 1.0}]
    set_aside = _node("12567-06-GA", "assembly", children=("12567-06-01M",))
    stray = _node("12567-06-01M", "leaf")            # not reached from the root
    s = _summary([GA, sub, PANEL, virtual, powder, set_aside, stray],
                 [_charged("12567-02-01M")])
    # the tape node is absent from this graph; the only finding would be a false one
    assert inv.check_every_reached_bom_item_is_accounted_for(s) == []


def test_an_alias_reaches_the_record():
    tape_alias = _node("P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM", "bought_in",
                       aliases=("BI-EPDMTAPE",))
    rec = _charged("BI-EPDMTAPE", 3.25)
    s = _summary([GA, SUB, tape_alias, PANEL], [_charged("12567-02-01M"), rec])
    assert inv.check_every_reached_bom_item_is_accounted_for(s) == []


def test_a_job_with_no_money_anywhere_has_no_bill_to_reconcile():
    s = _summary([GA, SUB, TAPE, PANEL],
                 [{"part_number": "12567-02-01M", "quantity": 1}])
    assert inv.check_every_reached_bom_item_is_accounted_for(s) == []


def test_the_check_is_registered():
    """A check that exists and is not in CHECKS is indistinguishable from one that passes."""
    assert inv.check_every_reached_bom_item_is_accounted_for in inv.CHECKS
