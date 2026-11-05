"""A weld on one piece that nothing evidences is asked, not charged (D-715).

12676-01-GA2, 5 Nov 2026, 19:59 book: the stand 12676-01-04M is one continuous folded sheet of
2 mm mild steel. Its record carried welding and dress_welds with no recorded source, no words
from the sheet and no weld symbol (the route printed both as "an unrecorded source"), the
SolidWorks model read no weld, and the book charged Weld (CO2) £43.64 and Dress Welds £24.62
at 1 off. The pack's "ALL WELDS TO BE TIG" says how a weld is made if there is one; it does
not say there is one.

A weld joins pieces, or closes a seam the drawing shows. On a part with no parts of its own and
nothing saying so, whether the work exists is a question; the charge waits for the answer.
Anything that does evidence it (a recorded source, the sheet's own words, a counted weld symbol)
or an assembly target keeps the charge exactly as before.

Synthetic records and made-up part numbers.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import invariants  # noqa: E402
import route_compiler as rc  # noqa: E402

GA, STAND = "J-GA2", "J-04M"


def _parts(**stand_extra):
    stand = dict({"part_number": STAND, "description": "STAND", "quantity": 1,
                  "normalized_material": "MILD STEEL", "normalized_thickness_mm": 2.0,
                  "parent_assemblies": [GA],
                  "textual_operations": ["laser_cutting", "folding", "welding", "dress_welds"]},
                 **stand_extra)
    return [{"part_number": GA, "description": "SHOE RISER", "quantity": 1,
             "is_assembly_parent": True, "assembly_children": [STAND],
             "textual_operations": ["assembly"]}, stand]


def _on(r, target):
    return {d["operation"]: d for d in r["decisions"] if d["target_id"] == target}


def test_an_unevidenced_weld_on_one_piece_is_held_not_charged():
    d = _on(rc.compile_job_route(_parts(), {}), STAND)
    for op in ("welding", "dress_welds"):
        assert d[op]["status"] == "unverified", op
        assert d[op]["reason"].startswith("UNSUPPORTED"), d[op]["reason"]
        assert STAND in d[op]["reason"] and "confirm whether" in d[op]["reason"]
    assert d["folding"]["status"] == "required", "only the weld is held to evidence here"


def test_the_check_says_unsupported_and_asks_whether_the_work_exists():
    r = rc.compile_job_route(_parts(), {})
    found = invariants.check_canonical_route_shadow({"canonical_route_shadow": r})
    held = [v for v in found if v.get("code") == "canonical_route_decision_unverified"
            and "welding" in v.get("message", "")]
    assert held and "is UNSUPPORTED" in held[0]["message"]
    assert "UNOWNED" not in held[0]["message"]


def test_a_weld_symbol_counted_on_its_sheet_keeps_the_charge():
    d = _on(rc.compile_job_route(_parts(weld_symbols={"fillet": 2}), {}), STAND)
    assert d["welding"]["status"] == "required"


def test_a_recorded_source_keeps_the_charge():
    d = _on(rc.compile_job_route(
        _parts(operation_sources={"welding": "llm_full_extract",
                                  "dress_welds": "llm_full_extract"}), {}), STAND)
    assert d["welding"]["status"] == d["dress_welds"]["status"] == "required"


def test_the_sheets_own_words_keep_the_charge():
    d = _on(rc.compile_job_route(
        _parts(operation_evidence={"welding": "WELD CORNERS AND DRESS FLUSH"}), {}), STAND)
    assert d["welding"]["status"] == "required"
