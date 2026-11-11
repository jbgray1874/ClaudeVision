"""A joint is asked in the words of what it joins, with the money its glue carries (D-708).

12693-03 small table, 16:16 book: the decision "How 12693-03-04J is joined" read "one bonding
event each (Glue, with the flame-polish that goes with it)" and asked "solvent cement,
adhesive, or a push/tab fit". 04J is an MDF insert. The question was written for acrylic and
was asked word for word of joinery once joinery took glue rows. It also left out what was at
stake: £13.53 of glue beside £19.73 of bench work on the same insert, which the review asked
to be told apart.

Synthetic records and made-up part numbers.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf  # noqa: E402

INS = "J-04J"


def _job(material, bench=True):
    kids = [f"{INS}-01", f"{INS}-02"]
    parts = [{"part_number": INS, "description": "TOP INSERT", "assembly_children": kids,
              "normalized_material": ""}]
    parts += [{"part_number": k, "description": "INSERT PIECE", "normalized_material": material,
               "parent_assemblies": [INS]} for k in kids]
    accepted = [{"workbook_row": 184, "engine_operations": ["glue"], "part_numbers": [INS]}]
    calculated = [{"workbook_row": 184, "operation": "Glue", "total_value_gbp": 13.53}]
    if bench:
        accepted.append({"workbook_row": 159, "engine_operations": ["bench_work", "assembly"],
                         "part_numbers": [INS]})
        calculated.append({"workbook_row": 159, "operation": "Bench Work Joinery",
                           "total_value_gbp": 19.73})
    return {"estimate_summary": {
        "part_estimates": parts,
        "canonical_route_shadow": {"decisions": [
            {"operation": "glue", "status": "required", "target_id": INS,
             "source": "inference"}]},
        "workbook_labour": {"rows": accepted},
        "final_estimate": {"labour_rows": calculated}}}


def _joint(source):
    return next(d for d in cf.costed_job(source).get("decisions_required") or []
                if str(d.get("issue") or "") == f"How {INS} is joined")


def test_a_board_assembly_is_asked_about_wood_glue_not_flame_polish():
    d = _joint(_job("MR MDF"))
    words = (d["assumption"] + " " + d["action"]).lower()
    assert "flame" not in words and "solvent" not in words and "push/tab" not in words
    assert "wood glue" in words and "dowels" in words
    assert "£13.53 a unit, Estimate row 184" in d["assumption"]
    assert d["gbp_at_stake"] == 13.53


def test_a_board_assembly_with_bench_work_is_asked_whether_the_bench_covers_the_gluing():
    d = _joint(_job("MR MDF"))
    assert f"bench work on {INS} already includes the gluing" in d["action"]
    assert "bench" not in _joint(_job("MR MDF", bench=False))["action"]


def test_an_acrylic_assembly_keeps_its_own_words():
    d = _joint(_job("CLEAR ACRYLIC 5MM"))
    assert "flame-polish" in d["assumption"] and "solvent cement" in d["action"]
    assert "bench" not in d["action"], "the bench-work clause is for board assemblies"


def test_a_material_nobody_named_is_asked_plainly():
    d = _joint(_job(""))
    words = (d["assumption"] + " " + d["action"]).lower()
    assert "flame" not in words and "wood glue" not in words
    assert "adhesive, or a mechanical fixing" in words
