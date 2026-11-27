"""Stronger evidence retires the question it answers (D-598t; SCRUM-100, 104, 105, 76).

9439-07-04-GA, the riser, 25 Oct 2026 09:10. The checks found the frame's own sheet states
TIG, the GA prints a hot-melt note and the bar's own cut list reads 5 x 5 x 290, and the
Decisions table still asked whether the frame is welded at all, how the top is joined "no
drawing states the joint", and about a bar row "nothing is costed". The TIG ruling was netted
under the first question in its words; the covering e-mail listed no ruling; the advisory
listed the top's glue twice; "What must be replaced?" said no market price beside the record's
own market figure. A question stronger evidence answers is retired; a ruling that says what
stands and what to rule keeps its own row and reaches every surface.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf                                             # noqa: E402
import invariants                                                     # noqa: E402
from owned_route_evidence import bar_covers_row, corroborates, stated_bond  # noqa: E402


def _page(pn, text, number):
    return {"page_number": number, "source_pdf_path": "pack.pdf", "pdfplumber_text": text,
            "page_analysis": {"title_block": {"drawing_numbers": [pn]}}}


def _riser(weld_note="TIG", bond_note="TOP TO BE SECURED USING HOT MELT\nGLUE"):
    """A GA over a top and a welded frame of end frames and square bars."""
    nodes = [
        {"part_number": "GA", "kind": "assembly", "parents": [],
         "children": [{"part_number": "TOP", "qty": 1}, {"part_number": "FRAME", "qty": 1}]},
        {"part_number": "FRAME", "kind": "assembly", "parents": ["GA"],
         "children": [{"part_number": "BAR", "qty": 4}]},
        {"part_number": "TOP", "kind": "leaf", "parents": ["GA"], "children": []},
        {"part_number": "BAR", "kind": "leaf", "parents": ["FRAME"], "children": []}]
    decisions = [
        {"operation": "welding", "status": "required", "target_id": "FRAME",
         "source": "inference", "evidence": "", "reason": "frame of end frames and bars"},
        {"operation": "glue", "status": "required", "target_id": "TOP", "source": "inference"},
        {"operation": "glue", "status": "required", "target_id": "FRAME", "source": "inference"}]
    bar = {"part_number": "BAR", "pages": [4], "manufacturing_questions": [{
        "issue": "BAR's parts list carries a section row, '5 x 5mm BAR', that no cut-list "
                 "reading took (no length, or a section the part does not carry)",
        "assumption": "nothing is costed for this row",
        "action": "confirm the part's section and cut length",
        "source": "bom_pipeline.raise_unread_parts_list_rows"}]}
    return {
        "pages": [_page("GA", bond_note, 1), _page("FRAME", weld_note, 2),
                  _page("BAR", "ITEM QTY DESCRIPTION LENGTH\n1 1 5 x 5mm BAR 290", 4)],
        "manufacturing_writeup": {"parts": [{"part_number": "FRAME", "pages": [2]},
                                            {"part_number": "TOP", "pages": [3]}, bar]},
        "estimate_summary": {"canonical_route_shadow": {"nodes": nodes,
                                                        "decisions": decisions},
                             "part_estimates": [bar]}}


def _decisions(source):
    return cf.costed_job(source).get("decisions_required") or []


def _issues(source):
    return [str(d.get("issue") or "") for d in _decisions(source)]


def test_a_weld_its_own_sheet_states_is_not_asked_as_inferred():
    assert not any(i.endswith("is inferred, not drawn") for i in _issues(_riser()))
    assert any(i == "Welding on FRAME is inferred, not drawn"
               for i in _issues(_riser(weld_note="FRAME")))


def test_a_ruling_with_its_own_words_keeps_its_own_row():
    source = _riser(weld_note="FRAME")                  # the inferred question stands here
    source["invariants"] = {"verified": True, "violations": [{
        "code": "owned_route_scope_unresolved", "severity": "warning",
        "message": "FRAME: own-sheet TIG is charged on a non-TIG row.",
        "detail": {"assembly": "FRAME", "operation": "welding", "needs_ruling": True,
                   "assumption": "the weld is priced at the CO2 rate as a TIG allowance",
                   "action": "give the TIG rate, or confirm the CO2 rate stands"}}]}
    rows = [d for d in _decisions(source) if d.get("kind") == "ruling"]
    assert rows and "TIG allowance" in rows[0]["assumption"]
    assert not any(d.get("also_ruled_by_check") for d in _decisions(source))


def test_a_joint_the_drawing_states_is_not_asked_how_it_is_joined():
    assert not any(i.startswith("How ") and i.endswith("joined") for i in _issues(_riser()))
    assert any(i.startswith("How ") and i.endswith("joined")
               for i in _issues(_riser(bond_note="GENERAL ARRANGEMENT")))
    assert "HOT MELT" in stated_bond(_riser(), "TOP")


def test_a_bar_row_its_own_cut_list_read_is_not_asked_again():
    assert not any("section row" in i for i in _issues(_riser()))
    source = _riser()
    source["pages"][2]["pdfplumber_text"] = "ITEM QTY DESCRIPTION LENGTH\n1 1 6 x 6mm BAR 290"
    assert any("section row" in i for i in _issues(source)), "a different bar is still asked"
    part = source["manufacturing_writeup"]["parts"][2]
    assert not bar_covers_row(part, source["pages"], "5 x 5mm BAR")


def test_the_advisory_reads_each_rows_own_part_and_the_owned_evidence():
    source = _riser(bond_note="GENERAL ARRANGEMENT")
    shadow = source["estimate_summary"]["canonical_route_shadow"]
    for d in shadow["decisions"]:
        d["corroborated"] = False
    shadow["decisions"].append({"operation": "saw", "status": "required", "target_id": "BAR",
                                "source": "inference", "corroborated": False})
    source["final_estimate"] = {"labour_rows": [
        {"operation": "Glue", "part_numbers": "TOP", "total_value_gbp": 13.14},
        {"operation": "Glue", "part_numbers": "FRAME", "total_value_gbp": 13.14},
        {"operation": "Saw", "part_numbers": "BAR", "total_value_gbp": 6.53}]}
    v = invariants.check_uncorroborated_route_operations(source) \
        if hasattr(invariants, "check_uncorroborated_route_operations") else None
    if v is None:
        v = [x for x in invariants.check_job(source).get("violations") or []
             if x.get("code") == "route_operation_not_corroborated"]
    msg = " ".join(str(x.get("message")) for x in v)
    assert "Glue on TOP" in msg and "Glue on FRAME" in msg, msg
    assert "Saw on BAR" not in msg, "the bar's own cut list is why it is sawn"
    stated = _riser()
    assert corroborates(stated, "glue", "FRAME")


def test_the_email_lists_rulings_and_the_explanation_names_a_nested_market_line():
    import inspect
    import estimate_explained as ee
    src = inspect.getsource(ee.covering_email)
    assert '("manufacturing_decision", "ruling")' in src
    house, market = ee._split_by_firmness(
        [{"code": "PACKAGING", "text": "PACKAGING", "price": 55.63, "qty": 1}],
        {"PACKAGING": {"part_number": "PACKAGING"},
         "TOP": {"part_number": "TOP", "description": "TOP", "charged_unit_gbp": 8.24,
                 "qty_per_unit": 1, "block": "other_sheet"}},
        {"indicative_house": ["PACKAGING"], "indicative_market": ["TOP"]})
    assert [r["code"] for r in house] == ["PACKAGING"]
    assert [r["code"] for r in market] == ["TOP"], "a nested market line is a line"
