"""A BOM line costed in the Wire block is not a line that carries no price.

11762-17's wires 03M/04M are costed in the Wire block (£0.26/£0.59, in the £21.01 unit). Their
own BOM line reads "£0.00 — costed in Wire below" — a deliberate cross-reference so the material
is not doubled. The report/explanation's unpriced detector tested only for "costed in sheet
steel", so a WIRE (or Tube, or Other Sheet) cross-reference fell through and was reported as a
line carrying no price — and the report, the AI Explanation, the covering email and the sheet
banner all told the estimator the correct £21.01 was "understated by the wires".

The detector now recognises a cross-reference to ANY fabricated block. This pins the predicate
every one of those surfaces routes through.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimate_explained as ee  # noqa: E402


def test_a_wire_cross_reference_is_recognised_as_costed_elsewhere():
    assert ee._is_costed_in_a_block("11762-17-03M U WIRE — costed in Wire below") is True


def test_every_fabricated_block_counts_not_just_sheet_steel():
    for txt in (
        "BACK PLATE — costed in Sheet Steel below",
        "PANEL — costed in Other Sheet Material below",
        "RAIL — costed in Tube below",
        "U WIRE — costed in Wire below",
    ):
        assert ee._is_costed_in_a_block(txt) is True, txt


def test_a_real_bought_in_is_not_a_cross_reference():
    assert ee._is_costed_in_a_block("PERFO PLASTIC LOCKING CLIP - BOTTLTD.CO.UK") is False
    assert ee._is_costed_in_a_block("") is False
    assert ee._is_costed_in_a_block(None) is False


def test_a_wire_cross_reference_is_excluded_from_the_unpriced_list():
    """The list the report/email/banner all derive from: a wire cross-reference at £0 must not
    be counted as a line carrying no price, while a genuinely blank bought-in still is."""
    bom = [
        {"code": "11762-17-03M", "price": None, "qty": 1,
         "text": "11762-17-03M U WIRE — costed in Wire below"},
        {"code": "11762-17-02M", "price": None, "qty": 1,
         "text": "11762-17-02M BACK PLATE — costed in Sheet Steel below"},
        {"code": "FIXING", "price": None, "qty": 4, "text": "FIXING M6 SCREW"},
    ]
    unpriced = [r for r in bom
                if r.get("price") in (None, "") and not ee._is_costed_in_a_block(r.get("text"))]
    codes = {r["code"] for r in unpriced}
    assert codes == {"FIXING"}, codes            # only the genuinely blank line


def test_the_cross_reference_suffix_is_trimmed_from_the_description_for_every_block():
    assert ee._description(
        {"code": "11762-17-03M", "text": "11762-17-03M  U WIRE — costed in Wire below"}) == "U WIRE"
    assert ee._description(
        {"code": "11762-17-02M",
         "text": "11762-17-02M  BACK PLATE — costed in Sheet Steel below"}) == "BACK PLATE"
    # a real bought-in keeps its whole name (the hyphen in a URL is not a cross-reference)
    assert ee._description(
        {"code": "STD PART", "text": "STD PART  PERFO PLASTIC LOCKING CLIP - BOTTLTD.CO.UK"}
    ) == "PERFO PLASTIC LOCKING CLIP - BOTTLTD.CO.UK"
