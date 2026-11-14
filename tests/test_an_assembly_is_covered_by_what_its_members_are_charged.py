"""An assembly is covered by what its members are charged (14 Nov 2026).

Two warnings on the week's reviewed packs said work was missing while the workbook charged it.
The reviewer: "Reports sometimes claim parts or operations are missing when the workbook
charges them. Those warnings cannot yet be trusted without checking."

  * 11896-01-00-GA: three welded assemblies were each "no material row on the calculated
    sheet". A weldment's material is the tube, caps and spigots it is made of, and every one
    of those had a charged material row.
  * 12424-02-GA: "POLISHED EDGES" is stated on the insert and charged on its eight panels,
    each on its own outline (the route's one-level rule). The ledger said "the read names it
    and no calculated row charges it" beside eight charged polish rows.

The codes and figures here are this test's own.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import read_charge_contract as rcc  # noqa: E402

ASM, A, B = "T-01-101", "T-01-01M", "T-01-02M"


def _mat(row, code, value):
    return {"workbook_row": row, "charged_cell": f"Estimate!M{row}", "part_code": code,
            "description": f"{code} PIECE", "unit_price_gbp": value, "qty_per_unit": 1.0,
            "total_value_gbp": value}


def _lab(row, title, code, value=4.0):
    return {"workbook_row": row, "charged_cell": f"Estimate!M{row}", "operation": title,
            "part_numbers": code, "batch_hours": 0.2, "total_value_gbp": value}


def _summary(member_values=(9.0, 0.5), asm_method="weldment_parent_material_in_children",
             polish_rows=(), ledger_ops=()):
    items = [{"id": "D1", "kind": "part", "work": True, "label": "WELDED ASSEMBLY",
              "record": ASM, "link": "part_number", "page": 1,
              "as_read": {"name": "WELDED ASSEMBLY", "part_number": ASM}, "said_by": "drawing"}]
    for op in ledger_ops:
        items.append({"id": f"D1.op.{op}", "kind": "operation", "work": True, "item": op,
                      "label": f"WELDED ASSEMBLY: {op}", "record": ASM, "of": "D1", "page": 1,
                      "as_read": op, "said_by": "drawing_notes"})
    mats = [_mat(11 + i, code, v) for i, (code, v) in enumerate(zip((A, B), member_values))
            if v is not None]
    labs = [_lab(151 + i, "Diamond Polish", code) for i, code in enumerate(polish_rows)]
    return {
        "drawing_ledger": {"schema": "drawing_ledger.v1", "said_by": "drawing", "items": items,
                           "read_sources": [], "parts_read": 1},
        "manufacturing_writeup": {"parts": [
            {"part_number": ASM, "description": "WELDED ASSEMBLY", "assembly_children": [A, B]},
            {"part_number": A}, {"part_number": B}]},
        "estimate_summary": {"part_estimates": [
            {"part_number": ASM, "material_estimate": {"cost_method": asm_method}},
            {"part_number": A, "material_estimate": {}},
            {"part_number": B, "material_estimate": {}}]},
        "final_estimate": {"source": "excel_calculated", "material_rows": mats,
                           "labour_rows": labs, "adapter_problems": []},
        "workbook_labour": {"rows": [{"workbook_row": 151 + i, "part_numbers": [code],
                                      "engine_operations": ["diamond_polish"],
                                      "wb_operation": "Diamond Polish"}
                                     for i, code in enumerate(polish_rows)]},
    }


def _item(summary, ident="D1"):
    return next(i for i in rcc.record_drawing(summary)["items"] if i["id"] == ident)


# ── 1. A WELDMENT'S MATERIAL IS ITS MEMBERS' ───────────────────────────────────────────────
def test_a_weldment_whose_members_are_all_charged_is_covered_and_names_them():
    got = _item(_summary())
    assert got["state"] == rcc.COVERED, got
    assert A in got["how"] and B in got["how"] and "members" in got["how"]


def test_a_weldment_with_a_member_that_has_no_material_row_names_that_member():
    got = _item(_summary(member_values=(9.0, None)))
    assert got["state"] == rcc.UNRESOLVED and B in got["how"] and A not in got["how"], got


def test_a_member_on_the_sheet_at_no_price_does_not_cover_its_assembly():
    got = _item(_summary(member_values=(9.0, 0.0)))
    assert got["state"] == rcc.UNRESOLVED and B in got["how"], got


def test_a_part_that_is_not_costed_through_members_is_still_reported_missing():
    got = _item(_summary(asm_method="workbook_sheet_steel_formula"))
    assert got["state"] == rcc.UNRESOLVED and "no material row" in got["how"], got


# ── 2. AN EDGE FINISH ON AN ASSEMBLY IS CHARGED ON ITS MEMBERS ─────────────────────────────
def test_polish_stated_on_an_assembly_and_charged_on_its_members_is_covered():
    got = _item(_summary(polish_rows=(A, B), ledger_ops=("diamond_polish",)),
                "D1.op.diamond_polish")
    assert got["state"] == rcc.COVERED, got
    assert A in got["how"] and B in got["how"] and "its own edges" in got["how"]


def test_polish_charged_on_nothing_is_still_reported_missing():
    got = _item(_summary(ledger_ops=("diamond_polish",)), "D1.op.diamond_polish")
    assert got["state"] == rcc.UNRESOLVED, got


def test_an_operation_that_is_not_an_edge_finish_is_not_covered_by_members_this_way():
    s = _summary(ledger_ops=("folding",))
    s["final_estimate"]["labour_rows"] = [_lab(151, "Fold", A)]
    s["workbook_labour"]["rows"] = [{"workbook_row": 151, "part_numbers": [A],
                                     "engine_operations": ["folding"], "wb_operation": "Fold"}]
    got = _item(s, "D1.op.folding")
    assert got["state"] == rcc.UNRESOLVED, got
