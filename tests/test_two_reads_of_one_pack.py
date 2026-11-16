"""Comparing two reads of one pack: the half of "reading quality" that needs no opinion.

Quality needs somebody to say what the right answer is. CONSISTENCY does not — if one pack read
twice gives two answers, at least one is wrong, and that is visible without knowing which.

THE DISTINCTION THE WHOLE TOOL RESTS ON. Two runs of one pack differ for two completely different
reasons, and confusing them wastes a day:

    a FIX        the engine changed between the runs and the second read is deliberately different
    INSTABILITY  the same build read the same bytes twice and answered differently

estimate_summary.engine_build carries the commit that wrote each record, so this is answerable
rather than assumed. A run whose build cannot be identified must be reported as UNKNOWN and never
quietly treated as "same build" — that turns every fix into a false instability report, and a tool
that cries wolf is one people stop reading.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import compare_two_reads as ctr                                          # noqa: E402


def _record(*, commit="aaaaaaa", dirty=False, qty=2, thickness=2.5,
            ops=("folding", "tubebend"), extra_part=False, vision_rows=1,
            bend_status="required") -> dict:
    parts = [
        {"part_number": "7332-01-002", "description": "LEG - CHS TUBE", "quantity": 2,
         "normalized_material": "MILD STEEL", "stock_form": "tube",
         "textual_operations": list(ops)},
        {"part_number": "7332-01-003", "description": "STRAP", "quantity": qty,
         "normalized_material": "MILD STEEL", "stock_form": "sheet",
         "thickness_mm": thickness, "blank_length_mm": 310.0, "blank_width_mm": 48.0,
         "bend_count": 2, "flat_pattern_detected": True,
         "textual_operations": ["laser_cutting", "folding"]},
    ]
    if extra_part:
        parts.append({"part_number": "7332-01-009", "description": "SPACER", "quantity": 4,
                      "normalized_material": "NYLON", "stock_form": "bar"})
    rows = [{"part_number": "7332-01-002", "source": "bom_table", "source_page": 3},
            {"part_number": "7332-01-003", "source": "bom_table", "source_page": 3}]
    rows += [{"part_number": "7332-01-003", "source": "vision", "source_page": 7}] * vision_rows
    build = {} if commit is None else {"commit": commit, "dirty": dirty, "subject": "subject"}
    return {"job_number": "7332-01", "processed_at": "2026-09-11T10:28:30",
            "manufacturing_writeup": {"parts": parts},
            "document_analysis": {"bom_rows": rows},
            "estimate_summary": {
                "engine_build": build,
                "canonical_route_shadow": {"decisions": [
                    {"target_id": "7332-01-002", "operation": "tubebend",
                     "status": bend_status},
                    {"target_id": "7332-01-003", "operation": "folding",
                     "status": "required"}]}}}


# ── the verdict that makes a difference actionable ────────────────────────────────────


def test_same_build_means_a_difference_is_instability():
    v = ctr.build_verdict(_record(), _record())
    assert v["state"] == "same_build"
    assert "instability in the reading, not a fix" in v["says"]


def test_different_builds_means_a_difference_may_be_a_fix():
    v = ctr.build_verdict(_record(commit="aaaaaaa"), _record(commit="bbbbbbb"))
    assert v["state"] == "different_builds"
    assert "may be a deliberate" in v["says"]
    assert "aaaaaaa" in v["says"] and "bbbbbbb" in v["says"], "name both, or it is not checkable"


def test_an_unknown_build_is_never_treated_as_the_same_build():
    """The failure this prevents: every deliberate fix reported as an instability, by a tool
    people then stop reading."""
    v = ctr.build_verdict(_record(), _record(commit=None))
    assert v["state"] == "unknown"
    assert "CANNOT be attributed" in v["says"]


def test_a_dirty_tree_qualifies_the_same_build_verdict():
    """Same commit is not the same code when somebody had edits in the working tree."""
    v = ctr.build_verdict(_record(dirty=True), _record())
    assert v["state"] == "same_build"
    assert "does not mean" in v["says"] and "same code" in v["says"]


# ── what counts as the reading ────────────────────────────────────────────────────────


def test_a_changed_quantity_is_reported_with_what_it_costs():
    out = ctr.compare_parts(_record(qty=2), _record(qty=4))
    hit = [c for c in out["changed"] if c["field"] == "quantity"][0]
    assert (hit["a"], hit["b"]) == (2, 4)
    assert "material" in hit["why"], "a bare field name leaves the reader to judge severity"


def test_a_changed_gauge_is_reported():
    out = ctr.compare_parts(_record(thickness=2.5), _record(thickness=3.0))
    assert any(c["field"] == "thickness_mm" for c in out["changed"])


def test_a_part_that_appears_or_vanishes_is_reported_in_the_right_direction():
    out = ctr.compare_parts(_record(), _record(extra_part=True))
    assert out["only_in_b"] == ["7332-01-009"]
    assert out["only_in_a"] == []


def test_money_is_not_part_of_the_reading():
    """Prices move for a dozen legitimate reasons — a rate card change, a catalogue update —
    and comparing them would bury the signal this tool exists for."""
    for money in ("unit_gbp", "material_gbp", "labour_gbp", "labour_estimate"):
        assert money not in ctr.READ_FACTS
    assert ctr.IGNORED, "and what was excluded is named, not silently dropped"


def test_reordered_operations_are_not_a_difference():
    """The compiler works from the set. Reporting an append order as a change would drown the
    real findings."""
    out = ctr.compare_parts(_record(ops=("folding", "tubebend")),
                            _record(ops=("tubebend", "folding")))
    assert out["changed"] == []


def test_a_float_that_differs_in_the_twelfth_decimal_is_the_same_measurement():
    a, b = _record(), _record()
    b["manufacturing_writeup"]["parts"][1]["blank_length_mm"] = 310.0000000001
    assert ctr.compare_parts(a, b)["changed"] == []


# ── the readers, counted separately ───────────────────────────────────────────────────


def test_a_reader_that_stopped_producing_rows_is_named():
    """THE FAILURE THIS CATCHES. A row count that drops from 3 to 2 says something went wrong;
    naming WHICH reader stopped says where to look. Rows are keyed by reader and page because
    one part read by two readers is two rows by design, and collapsing them would hide exactly
    this."""
    out = ctr.compare_bom(_record(vision_rows=1), _record(vision_rows=0))
    assert out["by_reader_a"]["vision"] == 1
    assert out["by_reader_b"].get("vision", 0) == 0
    assert out["by_reader_a"]["bom_table"] == out["by_reader_b"]["bom_table"], \
        "the reader that kept working is not implicated"
    assert ("7332-01-003", "vision", "7") in out["only_in_a"]


# ── the route ─────────────────────────────────────────────────────────────────────────


def test_an_operation_that_changed_status_is_reported():
    out = ctr.compare_route(_record(bend_status="required"),
                            _record(bend_status="not_applicable"))
    hit = [c for c in out["changed"] if c["operation"] == "tubebend"][0]
    assert (hit["a"], hit["b"]) == ("required", "not_applicable")


def test_the_same_route_read_twice_reports_nothing():
    assert ctr.compare_route(_record(), _record())["changed"] == []


def test_duplicate_decisions_for_one_operation_do_not_read_as_a_change():
    """The compiler emits one decision per piece of evidence, so one bend can arrive twice. What
    matters for consistency is whether the job still says the work happens — required wins."""
    a = _record()
    b = _record()
    b["estimate_summary"]["canonical_route_shadow"]["decisions"].append(
        {"target_id": "7332-01-002", "operation": "tubebend", "status": "unverified"})
    assert ctr.compare_route(a, b)["changed"] == []


# ── end to end, including the exit codes a script would branch on ─────────────────────


def _write(tmp_path: Path, name: str, record: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_two_identical_reads_exit_zero_and_say_so(tmp_path, capsys):
    a = _write(tmp_path, "a.json", _record())
    b = _write(tmp_path, "b.json", _record())
    assert ctr.report(a, b) == 0
    assert "IDENTICAL READING" in capsys.readouterr().out


def test_differences_exit_one(tmp_path):
    a = _write(tmp_path, "a.json", _record(qty=2))
    b = _write(tmp_path, "b.json", _record(qty=4))
    assert ctr.report(a, b) == 1


def test_an_unreadable_input_exits_two_rather_than_raising(tmp_path):
    a = _write(tmp_path, "a.json", _record())
    bad = tmp_path / "not-json.json"
    bad.write_text("{{{", encoding="utf-8")
    assert ctr.report(a, bad) == 2


def test_the_command_line_carries_no_shell_metacharacter(tmp_path):
    """PowerShell treats < as a reserved redirect operator, so a usage line containing a
    placeholder in angle brackets fails to parse before Python ever sees it. That has been
    pasted into a live console twice."""
    text = (ROOT / "tools" / "compare_two_reads.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if "compare_two_reads.py" in line:
            assert "<" not in line, f"reserved in PowerShell: {line.strip()}"
