"""Four fixes were written for two £0.00 lines and none of them was where the line travels.

    STD PART   3.5x19mm WOOD SCREW                       x6   £0.00
    FIXING     M4x10mm FLANGE BUTTON HEAD SCREW, BLACK   x4   £0.00

config holds 3p and 8p for both. `standard_commodity_price` returns them correctly when asked.
The table was right and the matcher was right the whole time — the line simply never asked.

THE FOUR THAT WERE TRIED, and why each missed:
  estimator.estimate_part's `sdi_bom_code_unpriced` branch — proven not taken: it appends the
    price chain's own account to review_flags, and estimator_inputs.material_input_note prints
    that in brackets after "MATERIAL UNPRICED". The sheet shows no bracket.
  estimator._resolve_part_system_cost's DB-free fallback — same branch, same miss.
  estimator._recognise_sdi_coded_bought_in — CANNOT reach them: its regex wants a prefix
    followed by 1-5 digits, and these carry no digits at all.
  estimator._bought_in_part_stub — reached for the PACKAGING placeholder on a live run (which
    is how it invented £12.00 there) and NOT for either screw.

AND THERE IS A FIFTH, which nobody had found: wb_populate.py already imports
standard_commodity_price. Its loop's first statement is

    if node.get("kind") != "bought_in" or identity in normalised: continue

so it prices a bought-in it is about to INVENT. These two already HAVE records — priceless
ones, filed into `normalised` moments earlier — so they take that `continue` in silence.

The fix sits over `normalised` itself: downstream of every reader, on the exact dictionary the
BOM rows are written from, so it sees the line whoever made it and under either spelling. Last
resort only — a line already carrying money, or one deliberately withheld, is left alone, and a
commercial allowance is never answered for by a table of component provisionals.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_populate import canonicalise_part_estimates_for_workbook as canonicalise  # noqa: E402

WOOD = "3.5x19mm WOOD SCREW"
M4 = "M4x10mm FLANGE BUTTON HEAD SCREW, BLACK"
PACK = "Packaging (box / pallet — per-unit share, estimator to price)"


def _summary(*nodes):
    return {"canonical_route_shadow": {
        "nodes": {pn: {"kind": kind, "description": d, "qty_per_unit": q}
                  for pn, d, q, kind in nodes}}}


def _rec(pn, desc, qty, **over):
    r = {"part_number": pn, "description": desc, "quantity": qty,
         "page_roles": ["bought_in"], "unit_cost_gbp": None,
         "extended_total_cost_gbp": None}
    r.update(over)
    return r


def _by_code(out):
    return {str(p.get("part_number")): p for p in out}


def _run(recs, nodes):
    return _by_code(canonicalise(_summary(*nodes), recs))


# ── the two lines that were £0 ───────────────────────────────────────────────────────────

def test_the_wood_screw_prices_on_the_sheet_side():
    out = _run([_rec("STD PART", WOOD, 6)], [("STD PART", WOOD, 6, "bought_in")])
    assert out["STD PART"]["unit_cost_gbp"] == 0.03
    assert out["STD PART"]["extended_total_cost_gbp"] == 0.18


def test_the_m4_does_too():
    out = _run([_rec("FIXING", M4, 4)], [("FIXING", M4, 4, "bought_in")])
    assert out["FIXING"]["unit_cost_gbp"] == 0.08
    assert out["FIXING"]["extended_total_cost_gbp"] == 0.32


def test_it_works_with_no_graph_node_at_all():
    """The record's own page_roles carry it — a line whose reader never reached the route
    graph must not fall back through the same hole."""
    out = _run([_rec("STD PART", WOOD, 6)], [])
    assert out["STD PART"]["unit_cost_gbp"] == 0.03


def test_the_basis_and_the_flag_say_what_it_is():
    out = _run([_rec("STD PART", WOOD, 6)], [("STD PART", WOOD, 6, "bought_in")])
    rec = out["STD PART"]
    assert rec["costing_basis"] == "standard_commodity_provisional"
    assert any("SDI trade rate" in str(f) for f in rec.get("review_flags") or [])


def test_the_material_estimate_carries_it_too():
    """_bom_line_price reads the material estimate; setting only unit_cost_gbp would leave
    the BOM row at £0.00 — which is the whole class of bug this sits in."""
    out = _run([_rec("STD PART", WOOD, 6)], [("STD PART", WOOD, 6, "bought_in")])
    me = out["STD PART"]["material_estimate"]
    assert me["unit_material_cost_gbp"] == 0.03
    assert me["extended_material_cost_gbp"] == 0.18


# ── last resort, never an overwrite ──────────────────────────────────────────────────────

def test_a_catalogue_price_is_left_exactly_as_it_stands():
    rec = _rec("STD PART", WOOD, 6, unit_cost_gbp=0.11,
               material_estimate={"unit_material_cost_gbp": 0.11,
                                  "cost_per_part_gbp": 0.11,
                                  "extended_material_cost_gbp": 0.66})
    out = _run([rec], [("STD PART", WOOD, 6, "bought_in")])
    assert out["STD PART"]["unit_cost_gbp"] == 0.11
    assert out["STD PART"].get("costing_basis") != "standard_commodity_provisional"


def test_a_deliberately_withheld_line_stays_withheld():
    """Roll goods and consumables are withheld ON PURPOSE and the row says so. A provisional
    must not quietly paper over a decision somebody made."""
    rec = _rec("VINYL76", "REEDED VINYL BASE", 4, _price_explicitly_withheld=True)
    out = _run([rec], [("VINYL76", "REEDED VINYL BASE", 4, "bought_in")])
    assert out["VINYL76"].get("unit_cost_gbp") in (None, 0, 0.0)


# ── and never for a commercial allowance ─────────────────────────────────────────────────

def test_packaging_is_not_priced_from_the_component_table():
    """18a19c2 all over again if this fails: the PALLET entry matches the word "pallet"
    inside the placeholder, and £12.00 lands on a line config holds empty by decision."""
    out = _run([_rec("PACKAGING", PACK, 1)], [("PACKAGING", PACK, 1, "bought_in")])
    assert out["PACKAGING"].get("unit_cost_gbp") in (None, 0, 0.0)


def test_delivery_is_not_either():
    d = "Delivery (per-unit share of order haulage — estimator to price)"
    out = _run([_rec("DELIVERY", d, 1)], [("DELIVERY", d, 1, "bought_in")])
    assert out["DELIVERY"].get("unit_cost_gbp") in (None, 0, 0.0)


def test_all_three_together_as_the_sheet_actually_has_them():
    """The real 12349-02 bill of materials: two fasteners and the packaging placeholder."""
    out = _run(
        [_rec("STD PART", WOOD, 6), _rec("FIXING", M4, 4), _rec("PACKAGING", PACK, 1)],
        [("STD PART", WOOD, 6, "bought_in"), ("FIXING", M4, 4, "bought_in"),
         ("PACKAGING", PACK, 1, "bought_in")])
    assert out["STD PART"]["unit_cost_gbp"] == 0.03
    assert out["FIXING"]["unit_cost_gbp"] == 0.08
    assert out["PACKAGING"].get("unit_cost_gbp") in (None, 0, 0.0)


# ── and never for something we make ──────────────────────────────────────────────────────

def test_a_part_we_fabricate_is_not_a_commodity():
    rec = _rec("12349-02-69-04M", "LID", 1, page_roles=["detail"])
    out = _run([rec], [("12349-02-69-04M", "LID", 1, "leaf")])
    assert out["12349-02-69-04M"].get("unit_cost_gbp") in (None, 0, 0.0)


def test_an_assembly_is_not_either():
    rec = _rec("12349-02-69-01A", "GRAVITY FEEDER FABRICATION", 1, page_roles=["assembly"])
    out = _run([rec], [("12349-02-69-01A", "GRAVITY FEEDER FABRICATION", 1, "assembly")])
    assert out["12349-02-69-01A"].get("unit_cost_gbp") in (None, 0, 0.0)


def test_a_bought_in_the_table_does_not_know_is_untouched():
    b = "10.1 DIA BUMPON TRANSPARENT; BUMPERSTOPS REF: PD.2120"
    out = _run([_rec("P/P", b, 6)], [("P/P", b, 6, "bought_in")])
    assert out["P/P"].get("unit_cost_gbp") in (None, 0, 0.0)
