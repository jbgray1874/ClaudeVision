"""A MEMBER COATED AS PART OF ITS WELDED ASSEMBLY IS COVERED BY THAT COATING (15 Nov 2026).

Three legs' own sheets state POWDER COATED. Each is welded into an upright that is coated as
one piece and carries the coating row. The ledger said of each leg "the read names it and no
calculated row charges it" beside the upright's charged coating, and the review list carried
it as three items reaching no charge. A warning the sheet contradicts teaches people to skip
warnings.

Where an assembly that lists the part carries a charged row for the same coat, the part is
covered by it. A member whose assembly carries no coating row is still unresolved.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import read_charge_contract as rcc  # noqa: E402

ASM, LEG, PLATE = "T-08-101", "T-08-01M", "T-08-04M"


def _summary(coat_on=(ASM,), title="Powder Coating", engine_op="powder_coating"):
    items = [{"id": "D1", "kind": "part", "work": True, "label": "UPRIGHT LEG", "record": LEG,
              "link": "part_number", "page": 2,
              "as_read": {"name": "UPRIGHT LEG", "part_number": LEG}, "said_by": "drawing"},
             {"id": "D1.op.powder_coating", "kind": "operation", "work": True,
              "item": "powder_coating", "label": "UPRIGHT LEG: powder_coating", "record": LEG,
              "of": "D1", "page": 2, "as_read": "powder_coating", "said_by": "drawing_notes"}]
    labs = [{"workbook_row": 170 + i, "charged_cell": f"Estimate!M{170 + i}", "operation": title,
             "part_numbers": code, "batch_hours": 0.3, "total_value_gbp": 12.0}
            for i, code in enumerate(coat_on)]
    return {
        "drawing_ledger": {"schema": "drawing_ledger.v1", "said_by": "drawing", "items": items,
                           "read_sources": [], "parts_read": 1},
        "manufacturing_writeup": {"parts": [
            {"part_number": ASM, "description": "UPRIGHT - WELDED ASSEMBLY",
             "assembly_children": [LEG, PLATE]},
            {"part_number": LEG}, {"part_number": PLATE}]},
        "estimate_summary": {"part_estimates": [
            {"part_number": ASM, "material_estimate": {}},
            {"part_number": LEG, "material_estimate": {}},
            {"part_number": PLATE, "material_estimate": {}}]},
        "final_estimate": {"source": "excel_calculated",
                           "material_rows": [{"workbook_row": 11, "charged_cell": "Estimate!M11",
                                              "part_code": LEG, "description": "LEG",
                                              "unit_price_gbp": 4.0, "qty_per_unit": 1.0,
                                              "total_value_gbp": 4.0}],
                           "labour_rows": labs, "adapter_problems": []},
        "workbook_labour": {"rows": [{"workbook_row": 170 + i, "part_numbers": [code],
                                      "engine_operations": [engine_op], "wb_operation": title}
                                     for i, code in enumerate(coat_on)]},
    }


def _op(summary):
    return next(i for i in rcc.record_drawing(summary)["items"] if i["id"] == "D1.op.powder_coating")


def test_a_leg_whose_upright_carries_the_coating_row_is_covered_and_names_it():
    got = _op(_summary())
    assert got["state"] == rcc.COVERED, got
    assert ASM in got["how"] and "coated as part of" in got["how"]


def test_a_leg_whose_upright_carries_no_coating_row_is_still_unresolved():
    got = _op(_summary(coat_on=()))
    assert got["state"] == rcc.UNRESOLVED, got


def test_a_leg_with_its_own_coating_row_is_charged_on_itself():
    got = _op(_summary(coat_on=(LEG,)))
    assert got["state"] == rcc.CHARGED, got


def test_a_coating_row_on_an_assembly_that_does_not_list_the_leg_does_not_cover_it():
    s = _summary()
    s["manufacturing_writeup"]["parts"][0]["assembly_children"] = [PLATE]
    assert _op(s)["state"] == rcc.UNRESOLVED
