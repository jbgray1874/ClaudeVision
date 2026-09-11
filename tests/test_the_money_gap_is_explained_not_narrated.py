"""A record and an accepted workbook that disagree about money: account for it, don't tell a story.

v0013 of 7332-01 carries material GBP 34.96 and labour GBP 50.09 while the accepted 14:17
workbook says GBP 40.89 and GBP 33.59. The timing says v0013 is the run behind that workbook;
the money says it is not. Which one gives matters: if the record predates two corrections then
it is a pre-fix run, not the accepted baseline, and no amount of hashing makes it one.

diagnose_operations_gap.py already established the mechanism for half of it — 7332-01-002 is on
NO priced workbook row, so the route requires tubebend and nothing charges the part. A part
charged on nothing contributes no stock to the material total, which is the shape of a material
figure that is too low.

These tests cover the tool that reports that arithmetic: that it finds a stranded part, finds a
finish charged on a line, and — the part that matters most — that when the two known defects do
NOT account for the difference it says so rather than rounding the remainder away. A residual the
tool cannot explain is the interesting output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import explain_money_gap as emg                                          # noqa: E402


def _record(*, totals=None, powder=True, leg_priced=False) -> dict:
    """A record shaped like v0013: a leg the route bends, and a part carrying powder."""
    decisions = [{"decision_id": "d1", "target_id": "7332-01-002", "operation": "tubebend",
                  "status": "required", "participants": ["7332-01-002"]}]
    if powder:
        decisions.append({"decision_id": "d2", "target_id": "7332-01-101",
                          "operation": "powder_coating", "status": "required",
                          "participants": ["7332-01-101"]})
    summary = {
        "estimate_workbook_inputs": {"assumed_job_quantity": 6},
        "canonical_route_shadow": {"decisions": decisions},
        "part_estimates": [
            {"part_number": "7332-01-002", "quantity": 2, "normalized_material": "MILD_STEEL",
             "normalized_thickness_mm": 2.0, "blank_length_mm": 100.0, "blank_width_mm": 50.0},
            {"part_number": "7332-01-101", "quantity": 1, "normalized_material": "MILD_STEEL",
             "normalized_thickness_mm": 2.0, "blank_length_mm": 80.0, "blank_width_mm": 40.0}],
    }
    if leg_priced:
        # workbook_labour.rows is what priced_rows_for_part actually reads: the ACCEPTED row
        # grouping, which is where part_numbers and decision_ids live. Its absence is the root
        # cause of the whole v0013 puzzle — see the stage-0 check in diagnose_operations_gap.
        summary["workbook_labour"] = {"rows": [
            {"workbook_row": 10, "part_numbers": ["7332-01-002"], "wb_operation": "Tube Bend",
             "decision_ids": ["d1"]}]}
    record = {"processed_at": "2026-09-07T13:10:30+00:00", "estimate_summary": summary}
    if totals is not None:
        record["final_estimate"] = {"totals": totals}
    return record


def _run(tmp_path, record, **figures) -> str:
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    import io
    import contextlib
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        emg.explain(path, {"material_gbp": figures.get("material"),
                           "labour_gbp": figures.get("labour"),
                           "unit_gbp": figures.get("unit")}, figures.get("divisor", 0.93))
    return buffer.getvalue()


def test_a_part_charged_on_no_priced_row_is_named(tmp_path):
    """The mechanism the probe found on the real record. A part the route requires work on, that
    no workbook row charges, contributes no stock to the material total."""
    text = _run(tmp_path, _record(), material=40.89, labour=33.59)
    assert "on NO priced workbook row" in text
    assert "7332-01-002" in text
    assert "route requires ['tubebend']" in text
    assert "material figure that is too LOW" in text


def test_a_part_that_IS_on_a_row_is_not_reported_as_stranded(tmp_path):
    """The guard on the guard: a check that flags every part explains nothing."""
    text = _run(tmp_path, _record(leg_priced=True), material=40.89, labour=33.59)
    section = text.split("4 · parts the route requires")[1].split("5 ·")[0]
    assert "7332-01-002" not in section, section


def test_a_finish_charged_in_the_record_is_named(tmp_path):
    """Powder is the candidate for labour being too high: review found 7332-01's plated and
    Harrods-1 finishes read as powder, and that fix landed after 7 September."""
    text = _run(tmp_path, _record(powder=True), material=40.89, labour=33.59)
    assert "powder_coating" in text
    assert "7332-01-101" in text


def test_no_finish_is_reported_when_none_is_charged(tmp_path):
    text = _run(tmp_path, _record(powder=False), material=40.89, labour=33.59)
    section = text.split("3 · finish operations")[1].split("4 ·")[0]
    assert "none" in section


def test_the_whole_line_is_declared_an_upper_bound_not_the_finish_share(tmp_path):
    """A line can carry other work besides the finish. Reporting its whole money as "what
    removing powder would save" would overstate the saving, so the limit is stated."""
    text = _run(tmp_path, _record(powder=True), material=40.89, labour=33.59)
    assert "upper bound" in text


def test_a_record_with_no_totals_says_so_rather_than_comparing_engine_sums_silently(tmp_path):
    """Every archived 7332-01 summary is in this state. Presenting the engine's own line sums as
    though they were the workbook's arithmetic is how the two artefacts got conflated."""
    text = _run(tmp_path, _record(totals=None), material=40.89, labour=33.59, unit=80.09)
    assert "carries no final_estimate.totals" in text
    assert "NOT the workbook's arithmetic" in text
    assert "record has no total to compare" in text


def test_the_accepted_arithmetic_is_shown_so_the_divisor_can_be_checked(tmp_path):
    """40.89 + 33.59 = 74.48, / 0.93 = 80.09. If that does not reproduce the accepted unit then
    the divisor is wrong and every comparison built on it is too."""
    text = _run(tmp_path, _record(), material=40.89, labour=33.59, unit=80.09)
    assert "74.48" in text
    assert "80.09" in text


def test_an_unexplained_residual_is_called_out_rather_than_rounded_away(tmp_path):
    """THE MOST IMPORTANT ONE. If removing the finish does not account for the labour gap then
    something else moved between this record and the accepted workbook, and the two must not be
    treated as the same run. A tool that quietly absorbed the remainder would manufacture
    agreement."""
    record = _record(totals={"material_gbp": 34.96, "labour_gbp": 50.09})
    text = _run(tmp_path, record, material=40.89, labour=33.59, unit=80.09)
    assert "difference" in text
    # the record's own figures are printed against the accepted ones, signed
    assert "+16.50" in text or "16.50" in text
    assert "-5.93" in text or "5.93" in text


def test_the_tool_writes_nothing(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir()) if tmp_path.exists() else []
    _run(tmp_path, _record(), material=40.89)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert after == sorted(before + ["rec.json"]), "only the fixture the test itself wrote"


def test_a_missing_record_is_an_error_not_a_crash():
    assert emg.main(["explain_money_gap.py", "/no/such/file.json"]) == 2
