"""A weld the engine inferred on one piece stays charged and names its joint (D-718).

12676-01-GA2, 5 Nov 2026: the stand 12676-01-04M is one folded sheet. Its record carried
welding and weld dressing with no recorded source, and the route printed both as "an
unrecorded source" with nothing to say which joint, why, or what the time was for.

JG's ruling: explicitly specified work is priced; reasonably inferred work is priced with its
manufacturing reason and its assumption stated; an uncertain time is a provisional allowance,
never a blank; a question goes beside the charge for review and never replaces it. Being one
part does not rule welding out, and no printed weld symbol removes nothing.

So the charge stays REQUIRED in every case here, and what changes is what it says:
  * folds that turn the sheet through a full turn: the closing seam along the fold line;
  * a tray folded up on four sides: its four corner seams;
  * folds that locate no joint: one provisional joint, said so, with the review question.

Synthetic records and made-up part numbers.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator  # noqa: E402
import route_compiler as rc  # noqa: E402
from weld_reasoning import weld_has_its_own_reason, weld_joint_basis  # noqa: E402

GA, STAND = "J-GA2", "J-04M"


def _stand(**extra):
    part = {"part_number": STAND, "description": "STAND", "quantity": 1,
            "normalized_material": "MILD STEEL", "normalized_thickness_mm": 2.0,
            "blank_length_mm": 665.1, "blank_width_mm": 254.0,
            "parent_assemblies": [GA],
            "textual_operations": ["laser_cutting", "folding", "welding", "dress_welds"]}
    part.update(extra)
    return part


def _parts(**stand_extra):
    return [{"part_number": GA, "description": "SHOE RISER", "quantity": 1,
             "is_assembly_parent": True, "assembly_children": [STAND],
             "textual_operations": ["assembly"]}, _stand(**stand_extra)]


def _on(r, target):
    return {d["operation"]: d for d in r["decisions"] if d["target_id"] == target}


# ── the reasoning ─────────────────────────────────────────────────────────────

def test_folds_that_make_a_full_turn_close_on_one_seam():
    b = weld_joint_basis(_stand(angles_deg=[90, 90, 90, 90]))
    assert b["kind"] == "closing_seam" and b["joints"] == 1
    assert "closing seam" in b["joint"] and "254 mm" in b["joint"]
    assert "360" in b["why"]


def test_a_tray_folded_on_four_sides_has_four_corner_seams():
    b = weld_joint_basis(_stand(description="DRIP TRAY", bend_count=4,
                                product_envelope_mm={"length": 400, "width": 300,
                                                     "height": 40}))
    assert b["kind"] == "corner_seams" and b["joints"] == 4
    assert "four corner seams" in b["joint"] and "40 mm" in b["joint"]


def test_folds_that_locate_no_joint_are_one_provisional_joint():
    b = weld_joint_basis(_stand(angles_deg=[90, 90, 45, 45]))
    assert b["kind"] == "provisional" and b["joints"] == 1
    assert "not located" in b["joint"] and "provisional" in b["assumption"]


def test_a_weld_with_words_symbols_or_a_source_has_its_own_reason():
    assert not weld_has_its_own_reason(_stand())
    assert weld_has_its_own_reason(_stand(operation_evidence={"welding": "WELD CORNERS"}))
    assert weld_has_its_own_reason(_stand(weld_symbols={"fillet": 2}))
    assert weld_has_its_own_reason(_stand(operation_sources={"welding": "llm_full_extract"}))
    assert not weld_has_its_own_reason(_stand(operation_sources={"welding": "unrecorded"}))


# ── the route keeps the charge and says why ───────────────────────────────────

def test_a_closing_seam_is_the_routes_reason_and_the_weld_stays_charged():
    d = _on(rc.compile_job_route(_parts(angles_deg=[90, 90, 90, 90]), {}), STAND)
    for op in ("welding", "dress_welds"):
        assert d[op]["status"] == "required", op
        assert d[op]["source"] == "fold_geometry", op
        assert "closing seam" in d[op]["reason"], d[op]["reason"]
        assert "closing seam" in str(d[op].get("evidence") or ""), op


def test_an_unlocated_weld_stays_charged_as_a_provisional_allowance():
    """THE 12676 CASE AS THE RECORD STOOD: no angles read. Still charged, and the reason says
    it is one provisional joint, not 'no reader recorded a source' and nothing more."""
    d = _on(rc.compile_job_route(_parts(), {}), STAND)
    for op in ("welding", "dress_welds"):
        assert d[op]["status"] == "required", op
        assert "provisional" in d[op]["reason"], d[op]["reason"]
        assert "locate" in d[op]["reason"], d[op]["reason"]


def test_a_weld_with_its_own_words_is_untouched():
    d = _on(rc.compile_job_route(
        _parts(operation_evidence={"welding": "WELD CORNERS AND DRESS FLUSH"}), {}), STAND)
    assert d["welding"]["status"] == "required"
    assert "infers" not in d["welding"]["reason"]


# ── the estimator states the allowance beside the charge ──────────────────────

def test_the_estimate_states_joint_reason_and_minutes_and_asks_beside_the_charge():
    part = _stand(angles_deg=[90, 90, 90, 90])
    times = estimator.estimate_process_times(part, 1)
    run = times.get("run_times_min_per_unit") or {}
    assert (run.get("welding") or 0) > 0, "the weld is still timed and charged"
    flag = next(f for f in part.get("review_flags") or [] if f.startswith("WELD INFERRED"))
    assert "closing seam" in flag and "Allowance charged:" in flag and "min welding" in flag
    q = next(q for q in part.get("manufacturing_questions") or []
             if "(inferred)" in q.get("issue", ""))
    assert q["charged_operations"] == ["welding", "dress_welds"]
    assert q["subject"] == "welding"
    assert "strike" in q["action"], "the question is for review; the charge stands"
    assert part["weld_joint_basis"]["kind"] == "closing_seam"


def test_a_weldment_is_not_explained_as_one_piece():
    part = _stand(is_assembly_parent=True, assembly_children=["A", "B"])
    estimator.estimate_process_times(part, 1)
    assert not any(str(f).startswith("WELD INFERRED") for f in part.get("review_flags") or [])
