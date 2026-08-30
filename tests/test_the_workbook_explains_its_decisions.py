"""The costed workbook must explain its own decisions, in the same file.

Estimators open one file. Everything that explains the number belongs inside it, not in a
side document -- so the Decision Report carries two things the run previously only said in
a console log nobody keeps:

  * WHO OWNS POWDER. Powder has twice this month put a figure on a sheet that no reader
    could trace to a decision: once as phantom mass from a plastic classified as steel, and
    once from a geometry sum that had never consulted the route. A cell naming the deciding
    authority makes both visible the moment they recur.
  * WHICH DECISIONS THE ENGINE HAD TO SETTLE. Every other line on the tab describes a
    decision that made itself -- one strongest source, nothing at that rank contradicting
    it. The contested ones are where estimator feedback is worth most, so they get their
    own block rather than a column halfway down a hundred rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from job_decision_report import (decisions_that_required_resolution,   # noqa: E402
                                 powder_authority)


def _s(decisions=None, present=True):
    payload = {"decisions": list(decisions)} if decisions is not None else {}
    return {"estimate_summary": {"canonical_route_shadow": payload} if present else {}}


def _d(op="powder_coating", status="required", **kw):
    base = {"operation": op, "status": status, "target_id": "11650-02-01A",
            "source": "dxf", "source_rank": 80, "decided_by": "the DXF",
            "contested": False, "losing_statuses": [], "settled_by_key": ""}
    base.update(kw)
    return base


# ── powder authority ────────────────────────────────────────────────────────────────
def test_a_coated_job_names_the_compiler_and_its_strongest_source():
    txt = powder_authority(_s([_d(source="solidworks_api", source_rank=90,
                                  decided_by="the SolidWorks model")]))
    assert "route compiler" in txt and "the SolidWorks model" in txt and "90" in txt


def test_a_job_the_route_ruled_out_says_a_powder_figure_would_contradict_it():
    """The 11650 side-panels failure stated as a sentence on the sheet."""
    txt = powder_authority(_s([_d(status="ruled_out")]))
    assert "NOTHING COATED" in txt and "contradict the route" in txt


def test_a_route_that_never_considered_powder_says_the_mass_is_unverified():
    txt = powder_authority(_s([_d(op="welding")]))
    assert "NO DECISION" in txt and "geometry" in txt and "unverified" in txt


def test_a_job_with_no_compiled_route_names_the_legacy_gate():
    """Never a silent zero and never an unnamed authority."""
    for empty in (_s([]), _s(None), _s(None, present=False), {}):
        txt = powder_authority(empty)
        assert "LEGACY FINISH GATE" in txt and "not traceable" in txt


@pytest.mark.parametrize("summary", [
    None, {}, {"estimate_summary": {"canonical_route_shadow": {"decisions": "broken"}}}])
def test_powder_authority_never_returns_an_empty_string(summary):
    """A blank cell reads as 'no powder', which is a statement this must never make by
    accident."""
    assert powder_authority(summary or {}).strip()


# ── decisions that required resolution ──────────────────────────────────────────────
def test_only_contested_decisions_are_listed():
    out = decisions_that_required_resolution(_s([
        _d(target_id="A", contested=False),
        _d(target_id="B", contested=True, losing_statuses=["ruled_out"])]))
    assert [d["target_id"] for d in out] == ["B"]


def test_the_weakest_resolution_is_listed_first():
    """A contest settled by the claim-id backstop had no distinguishing evidence at all --
    a coin flip made reproducible. It deserves a person before one settled by the drawing's
    own words does."""
    out = decisions_that_required_resolution(_s([
        _d(target_id="STRONG", contested=True, settled_by_key="quotes the drawing"),
        _d(target_id="WEAK", contested=True,
           settled_by_key="claim id (reproducibility backstop)")]))
    assert [d["target_id"] for d in out] == ["WEAK", "STRONG"]


def test_a_job_with_no_contest_returns_nothing_to_list():
    assert decisions_that_required_resolution(_s([_d()])) == []
    assert decisions_that_required_resolution({}) == []


# ── built is not wired ──────────────────────────────────────────────────────────────
_SRC = (ROOT / "src" / "job_decision_report.py").read_text(encoding="utf-8")


def test_both_blocks_are_actually_written_to_the_sheet():
    """The recurring defect in this codebase: correct evidence with no reader. A helper
    that returns the right answer and is never called explains nothing."""
    body = _SRC[_SRC.index("def add_decision_report_sheet"):]
    assert "powder_authority(summary)" in body, "the powder authority is never written"
    assert "decisions_that_required_resolution(summary)" in body, \
        "the contested block is computed nowhere"
    assert "DECISIONS THAT REQUIRED RESOLUTION" in body, "the block has no heading row"


def test_the_banner_sits_above_the_table_not_below_it():
    """Row 4, immediately under the title and above the header row at 5. A trust statement
    an estimator has to scroll to is one they will not read."""
    body = _SRC[_SRC.index("def add_decision_report_sheet"):]
    assert "_c(ws, 4, 1, _banner" in body
    assert "_c(ws, 5, ci, hdr" in body, "the header row has moved; re-check the banner row"


def test_the_banner_is_coloured_by_whether_anything_was_contested():
    body = _SRC[_SRC.index("def add_decision_report_sheet"):]
    assert "C_LOW if _contested" in body, \
        "a contested job's banner looks identical to a clean one's"


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── it renders on a real workbook, not merely in the abstract ───────────────────────
# THE TEST THAT FOUND THE BUG THE OTHERS COULD NOT. Every guard above reads the source or
# calls a helper; none of them opened openpyxl. The first end-to-end render raised
# "'MergedCell' object attribute 'value' is read-only" -- the block landed inside the
# template's merged footer. wb_populate had already paid for that lesson on 11350, where the
# same failure killed an entire estimator-input block after its heading.
def test_the_decision_report_renders_end_to_end():
    openpyxl = pytest.importorskip("openpyxl")
    from job_decision_report import add_decision_report_sheet

    wb = openpyxl.Workbook()
    summary = {
        "manufacturing_writeup": {"parts": [
            {"part_number": "11650-04-01A", "description": "SIDE PANEL LH",
             "normalized_material": "PETG", "normalized_thickness_mm": 3.0,
             "quantity": 2, "material_source": "llm_full_extract",
             "thickness_source": "dxf_flat_pattern"}]},
        "estimate_summary": {
            "part_estimates": [{"part_number": "11650-04-01A", "unit_cost_gbp": 1.2}],
            "canonical_route_shadow": {"decisions": [_d(
                target_id="11650-04-01A",          # the SAME part the BOM row describes
                status="ruled_out", contested=True, losing_statuses=["required"],
                settled_by_key="claim id (reproducibility backstop)")]}},
    }
    add_decision_report_sheet(wb, summary, {})
    ws = wb["Decision Report"]

    assert "NOTHING COATED" in str(ws.cell(row=4, column=1).value or ""), \
        "the powder authority is not on the sheet an estimator opens"
    hits = [r for r in range(1, ws.max_row + 1)
            if "DECISIONS THAT REQUIRED RESOLUTION" in str(ws.cell(row=r, column=1).value or "")]
    assert hits, "the contested block did not render"
    detail = [ws.cell(row=hits[0] + 2, column=c).value for c in range(1, 8)]
    assert detail[0] == "11650-04-01A"
    assert detail[6] == "claim id (reproducibility backstop)", \
        "the sheet does not say which key settled the contest"


def test_a_merged_cell_does_not_kill_the_report():
    """Explicitly, because the template merges ranges wherever the estimators find it
    tidy, and a report that raises produces no document at all."""
    openpyxl = pytest.importorskip("openpyxl")
    from job_decision_report import _writable

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.merge_cells(start_row=10, start_column=1, end_row=10, end_column=5)
    anchor = _writable(ws, 10, 3)
    assert anchor is not None, "a merged continuation resolved to nothing"
    anchor.value = "written"
    assert ws.cell(row=10, column=1).value == "written", \
        "the write did not land on the range's anchor"
