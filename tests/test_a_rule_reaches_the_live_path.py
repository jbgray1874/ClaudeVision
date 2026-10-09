"""A rule that works on a part must also work where the live run actually meets the part (D-433).

8188-08's 17:37 book, run with D-426..D-428 in place: the report said wave layers 014 and 015
took ACRYLIC from the sheet that draws them, while the Estimate costed both as 3 mm mild steel —
the material was handed down AFTER estimate_document had priced them. And the magnet's
mixed-unit question (D-427) appeared nowhere: its line was added from the BOM table read after
costing and was costed on a copy, and the question died with the copy. Both unit tests passed,
because they called the rule directly.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf                                             # noqa: E402
import estimator                                                      # noqa: E402
import invariants                                                     # noqa: E402


def test_the_sheets_material_is_handed_down_before_the_part_is_costed():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    costing = src.index('summary["estimate_summary"] = estimate_document(')
    handed = src.find("_inherit_sheet_material_to_parts(summary[")
    assert 0 <= handed < costing, "the sheet's material must reach the part before it is priced"
    body = src[src.index("def _build_additive_summary_sections"):]
    assert "_inherit_sheet_material_to_parts(" not in body.split("\ndef ", 1)[0], \
        "a second, later hand-down would only write a note the price never saw"


def _late_magnet_summary():
    rec = {"part_number": "KINGDOM", "description": "50mm x 10mm x 2m MAGNET", "quantity": 14,
           "is_bought_in": True, "page_roles": ["bought_in"],
           "review_flags": ["Added from dual-path BOM table read (a row only the table reader saw)"]}
    return {"estimate_summary": {"part_estimates": [rec]},
            "manufacturing_writeup": {"parts": []}}


def test_a_line_added_after_costing_keeps_its_question_and_its_mark():
    summary = _late_magnet_summary()
    assert estimator.cost_uncosted_bought_in_records(summary) == 1
    pe = summary["estimate_summary"]["part_estimates"][0]
    assert pe["_price_unresolved"]["units"] == ["m", "mm"]
    issues = [q["issue"] for q in pe.get("manufacturing_questions") or []]
    assert any("mixes m and mm" in i for i in issues), issues


def test_the_report_and_the_quote_gate_see_it():
    summary = _late_magnet_summary()
    estimator.cost_uncosted_bought_in_records(summary)
    jp = cf.job_parts(summary)
    assert any("mixes m and mm" in q["issue"] for q in jp[0].get("manufacturing_questions") or [])
    codes = [v["code"] for v in invariants.check_an_unresolved_reading_blocks_the_quote(summary)]
    assert codes == ["unresolved_reading_priced"]


def test_the_reports_merge_keeps_both_records_questions():
    q_raw = {"issue": "raised on the drawing record after costing"}
    q_est = {"issue": "raised while costing"}
    summary = {"manufacturing_writeup": {"parts": [
                   {"part_number": "P1", "manufacturing_questions": [q_raw]}]},
               "estimate_summary": {"part_estimates": [
                   {"part_number": "P1", "manufacturing_questions": [q_est, dict(q_raw)]}]}}
    issues = [q["issue"] for q in cf.job_parts(summary)[0]["manufacturing_questions"]]
    assert issues == ["raised on the drawing record after costing", "raised while costing"]
