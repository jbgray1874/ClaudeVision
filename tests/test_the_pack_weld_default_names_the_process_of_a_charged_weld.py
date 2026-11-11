"""The pack's weld specification names the process of every charged weld (SCRUM-181).

12678-01-GA's border prints "WELD SPECIFICATION: ALL WELDS TO BE TIG UNLESS STATED", and
the two bracket assemblies were charged as Weld (CO2) on an inference whose question said
"the inference quotes no weld note from the drawing". Both halves of that were wrong in
opposite directions: the note exists and names the process, and the note still proves
nothing about whether THIS joint is welded.

THE LINE HELD HERE: process, never existence. The specification legend puts no weld on
any part — strip_specification_legend and its tests stand untouched — but a part that
already carries an arc-weld operation takes the pack default as its stated process, so
the sheet row says which process the rate must suit, the TIG rate gap is asked once, and
the inferred-weld question quotes the note instead of denying it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import costed_facts as cf  # noqa: E402
import weld_symbols as ws  # noqa: E402

PAGES = [{"page_number": 1, "pypdf_text":
          "WELD SPECIFICATION: ALL WELDS TO BE TIG UNLESS STATED "
          "RESISTANCE WELDING WIRE TO WIRE THE SET DOWN SHOULD BE 20%"}]


def test_the_pack_statement_is_read_as_a_default():
    read = ws.pack_weld_process(PAGES)
    assert read is not None
    assert read["process"] == "TIG"
    assert read["default"] is True


def test_a_joint_note_is_not_a_pack_default():
    assert ws.pack_weld_process([{"pypdf_text": "WELD TO BE TIG ON THIS JOINT"}]) is None


def test_a_charged_weld_takes_the_pack_process_and_asks_the_rate_gap():
    part = {"part_number": "12678-01-101SA", "inferred_operations": ["welding"]}
    touched = ws.apply_pack_weld_default([part], PAGES)
    assert touched == ["12678-01-101SA"]
    stated = part["weld_process_stated"]
    assert stated["process"] == "TIG"
    assert stated["source"] == "pack_specification"
    assert any("pack's weld specification" in f for f in part["review_flags"])
    # The TIG rate gap is asked, because the card's one arc-weld row is a CO2/MIG rate.
    assert any("rate card has no TIG rate" in str(q.get("issue"))
               for q in part["manufacturing_questions"])


def test_the_specification_still_puts_no_weld_on_a_part():
    """Existence is untouched: a part with no weld operation takes nothing from the
    note, however loudly the border states it."""
    part = {"part_number": "12678-01-03J", "operations": ["cnc_routing"]}
    assert ws.apply_pack_weld_default([part], PAGES) == []
    assert "weld_process_stated" not in part
    assert not part.get("manufacturing_questions")


def test_a_spot_weld_is_resistance_work_and_takes_no_arc_default():
    part = {"part_number": "P-SPOT", "operations": ["spot_welding"]}
    assert ws.apply_pack_weld_default([part], PAGES) == []


def test_a_parts_own_statement_is_kept():
    part = {"part_number": "P-OWN", "operations": ["welding"],
            "weld_process_stated": {"process": "MIG", "source": "drawing_deterministic"}}
    assert ws.apply_pack_weld_default([part], PAGES) == []
    assert part["weld_process_stated"]["process"] == "MIG"


# ── the inferred-weld question quotes the note ───────────────────────────────────────

def _guess(rec):
    return {"estimate_summary": {
        "part_estimates": [{"part_number": "X-101"}],
        "canonical_route_shadow": {"decisions": [{
            "operation": "welding", "status": "required", "source": "inference",
            "target_id": "X-101", "evidence": ""}]}},
        "manufacturing_writeup": {"parts": [rec]}}


def test_the_inferred_weld_question_quotes_the_packs_specification():
    rec = {"part_number": "X-101",
           "weld_process_stated": {"process": "TIG", "word": "TIG", "default": True,
                                   "source": "pack_specification"}}
    dd = [x for x in cf.costed_job(_guess(rec))["decisions_required"]
          if "inferred, not drawn" in x["issue"]][0]
    assert "quotes no weld note" in dd["assumption"]
    assert "pack's weld specification states TIG" in dd["assumption"]
    assert "names the process, not the joint" in dd["assumption"]


def test_without_a_pack_statement_the_question_reads_as_before():
    dd = [x for x in cf.costed_job(_guess({"part_number": "X-101"}))["decisions_required"]
          if "inferred, not drawn" in x["issue"]][0]
    assert "quotes no weld note from the drawing" in dd["assumption"]
    assert "pack's weld specification" not in dd["assumption"]


def test_the_scan_applies_the_pack_default_before_costing():
    scan = open(os.path.join(os.path.dirname(__file__), "..", "src", "file_scan.py"),
                encoding="utf-8").read()
    seg = scan[scan.index("def pre_costing_passes"):scan.index("def _finalize_scan_summary")]
    assert "apply_pack_weld_default" in seg
