"""Howard Thurley's answers had nowhere to go, so we kept asking him the same questions.

Brass Harrods 01 at £250. Tube bend not required. Acrylic laser at 95/hr, not 252. Three
answers from the person who runs the department, and not one of them had a home: each was a
config edit by us, or an overtype that died with that workbook. Re-run the job and the sheet
asks again.

    "It sounds like the file estimator_confirmed.py is well named and if it is one of a very
     few locations of config this is ok for now .. we should apply his change. Will they be
     inherited by other jobs?"                              — James Gray, SDI, 14 Sep 2026

THE ANSWER TO THAT QUESTION IS THE DESIGN. Two homes, and which one a figure goes in is the
whole of whether it inherits:

    config.py                 how SDI works          EVERY job, every run
    <drawing>_confirmed.json  what we decided here   THAT drawing, and no other

So the weld allowance, the plater freight and the brushing minutes are in config — they are
true of any job that welds, plates, or sends work out. The £250, the tube bend and the 95/hr
are in the job's own file — they are true of 7332-01. The next Harrods stand asks again
rather than inheriting a price nobody re-checked, which is the correct behaviour and not a
limitation.

AND A DECISION IS NOT A READING. `parts` in this file refuses prices, by name, and that rule
is untouched: a price entered there would read in the output exactly like one the engine
sourced. `estimator_decisions` sits BESIDE it and is the opposite — it exists to be visibly a
person's call, carries their name and date onto every line it touches, and says so on the
sheet.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator as e                                                    # noqa: E402
import estimator_confirmed as ec                                         # noqa: E402


def _file(tmp_path, decisions, **extra):
    doc = {"confirmed_by": "Howard Thurley", "confirmed_on": "2026-09-15",
           "parts": {}, "estimator_decisions": decisions}
    doc.update(extra)
    p = tmp_path / "7332-01_confirmed.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# ── the file reads what it is given, and says what it refuses ────────────────────────────

def test_the_three_answers_are_all_read(tmp_path):
    data, problems = ec.load_corrections(_file(tmp_path, {
        "plating_gbp_per_unit": 250.0, "plating_spec": "Brass — Harrods 01",
        "operations_off": {"7332-01-002": ["tube_bending"]},
        "throughput_per_hour": {"Laser (Acrylic)": 95}}))
    d = data["estimator_decisions"]
    assert d["plating_gbp_per_unit"] == 250.0
    assert d["plating_spec"] == "Brass — Harrods 01"
    assert d["operations_off"] == {"7332-01-002": ["tube_bending"]}
    assert d["throughput_per_hour"] == {"Laser (Acrylic)": 95.0}
    assert not problems


def test_a_decision_this_engine_does_not_apply_is_reported(tmp_path):
    """A key that silently does nothing is how a feature comes to be trusted while
    contributing nothing — the same rule the unmatched part codes already follow."""
    _, problems = ec.load_corrections(_file(tmp_path, {"weld_minutes": 30}))
    assert any("is not a decision this engine applies" in p for p in problems)


def test_a_malformed_decision_is_refused_loudly(tmp_path):
    _, problems = ec.load_corrections(_file(tmp_path, {
        "plating_gbp_per_unit": "two hundred and fifty",
        "operations_off": ["7332-01-002"],
        "throughput_per_hour": {"Laser (Acrylic)": -5}}))
    assert len(problems) >= 3
    assert any("not a positive number" in p for p in problems)


def test_a_file_with_no_decisions_block_is_exactly_as_before(tmp_path):
    p = tmp_path / "7332-01_confirmed.json"
    p.write_text(json.dumps({"confirmed_by": "H", "parts": {}}), encoding="utf-8")
    data, _ = ec.load_corrections(p)
    assert data["estimator_decisions"] == {}


def test_the_price_refusal_on_readings_is_untouched(tmp_path):
    """THE RULE THIS MUST NOT BREAK. A price in `parts` would inherit the engine's own
    provenance. It is still refused, with its reason, and the new block is the answer to
    where it should go instead."""
    p = tmp_path / "7332-01_confirmed.json"
    p.write_text(json.dumps({"confirmed_by": "H", "parts": {
        "7332-01-101": {"price_gbp": 250, "thickness_mm": 1.0}}}), encoding="utf-8")
    data, problems = ec.load_corrections(p)
    assert any("REFUSED" in x for x in problems)
    assert "price_gbp" not in data["parts"].get("7332-01-101", {})


# ── the plating price: his figure, named as his ──────────────────────────────────────────

def _plating_job():
    parts = [{"part_number": "7332-01-101", "description": "FRAME WELDMENT",
              "normalized_finish": "PLATED", "is_assembly_parent": True, "quantity": 1,
              "material_estimate": {"unit_material_mass_kg": 0.9}},
             {"part_number": "7332-01-101-PLATE", "_plating_placeholder": True,
              "_plating_weldment": "7332-01-101", "_plating_members": ["7332-01-101"],
              "quantity": 1,
              "description": "7332-01-101 plating — INDICATIVE zinc/passivate"}]
    return parts


DECIDED = {"estimator_decisions": {
    "plating_gbp_per_unit": 250.0, "plating_spec": "Brass — Harrods 01",
    "decided_by": "Howard Thurley", "decided_on": "2026-09-15",
    "decided_in": "7332-01_confirmed.json"}}


def test_the_plating_line_takes_his_price():
    parts = _plating_job()
    e.apply_subcontract_plating(parts, DECIDED, 6, parts)
    assert parts[1]["unit_cost_gbp"] == 250.00
    assert parts[1]["cost_source"] == "estimator_stated_price"


def test_the_line_says_it_is_his_and_not_the_engines():
    parts = _plating_job()
    e.apply_subcontract_plating(parts, DECIDED, 6, parts)
    text = parts[1]["description"] + " " + " ".join(parts[1]["review_flags"])
    assert "Howard Thurley" in text
    assert "Brass — Harrods 01" in text
    assert "NOT a rate this engine sourced" in text
    assert "zinc" not in parts[1]["description"].lower()


def test_it_does_not_move_with_the_mass_or_the_order():
    a = _plating_job()
    e.apply_subcontract_plating(a, DECIDED, 6, a)
    b = _plating_job()
    b[0]["material_estimate"]["unit_material_mass_kg"] = 40.0
    e.apply_subcontract_plating(b, DECIDED, 500, b)
    assert a[1]["unit_cost_gbp"] == b[1]["unit_cost_gbp"] == 250.00


def test_without_the_decision_the_line_still_blocks():
    """The engine has not learned anything about Harrods. Take the answers file away and it
    is back to "spec not identified", which is the honest state."""
    parts = _plating_job()
    e.apply_subcontract_plating(parts, {}, 6, parts)
    assert parts[1]["unit_cost_gbp"] == 0.0
    assert parts[1]["cost_source"] == "subcontract_plating_spec_unidentified"


def test_another_job_is_completely_unaffected():
    """THE INHERITANCE QUESTION, ANSWERED IN A TEST. The decision travels in a summary, and
    a job whose summary carries none gets none of it."""
    parts = _plating_job()
    e.apply_subcontract_plating(parts, {"estimator_decisions": {}}, 6, parts)
    assert parts[1]["unit_cost_gbp"] == 0.0


# ── an operation he has taken off stays off ──────────────────────────────────────────────

def test_a_removed_operation_does_not_come_back():
    part = {"part_number": "7332-01-002", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.2, "fold_count_textual": 2,
            "textual_operations": ["tube_bending", "handling"],
            "material_estimate": {"stock_form": "tube"},
            "_estimator_operations_off": ["tube_bending"]}
    out = e.estimate_process_times(part, 6)
    assert "tube_bending" not in out["run_times_min_per_unit"]
    assert "tube_bending" in (part.get("removed_operations") or [])


def test_a_part_with_no_decision_keeps_its_operation():
    part = {"part_number": "7332-01-002", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.2, "fold_count_textual": 2,
            "textual_operations": ["tube_bending", "handling"],
            "material_estimate": {"stock_form": "tube"}}
    e.estimate_process_times(part, 6)
    assert "tube_bending" in (part.get("textual_operations") or [])


def test_taking_one_operation_off_leaves_the_others():
    part = {"part_number": "X", "normalized_material": "MILD_STEEL",
            "textual_operations": ["laser_cutting", "folding", "handling"],
            "_estimator_operations_off": ["folding"]}
    ops = e._part_ops(part)
    assert "folding" not in ops
    assert "laser_cutting" in ops and "handling" in ops


# ── and the two homes stay separate ──────────────────────────────────────────────────────

def test_the_rules_that_should_inherit_are_in_config_not_in_the_job_file():
    """Weld allowance, plater freight and brushing are true of any job that welds, plates or
    sends work out. They are not decisions about one stand and must not live in one stand's
    file."""
    import config                                                        # noqa: PLC0415
    assert config.WELD_TIME_MODEL["allowance_min_per_weldment"] == 30.0
    assert config.PLATING_LOGISTICS["freight_gbp_per_order"] == 120.0
    assert config.BRUSH_BEFORE_PLATE["minutes_per_consignment"] == 40.0
    for block in (config.WELD_TIME_MODEL, config.PLATING_LOGISTICS,
                  config.BRUSH_BEFORE_PLATE):
        assert any("source" in k for k in block), block


def test_the_job_file_is_named_for_the_drawing_so_it_cannot_govern_another():
    """The naming convention IS the inheritance boundary, so it is pinned here rather than
    left as a comment."""
    assert any("{drawing}" in name for name in ec.FILE_NAMES)
