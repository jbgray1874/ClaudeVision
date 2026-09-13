"""Two minutes of welding where the welding department says thirty.

7332-01's frame weldment booked 2 minutes of welding and 1 of dressing; SDI's welding
department states 0.5 hours and 20 minutes. The cause is not a rate. Weld run-time was

    max(1.0, (pierces * 90 + cut_length_mm * 0.01) / 60)

— hole count and cut length, which are properties of a FLAT BLANK. A weld assembly is what
blanks become; it has no flat of its own, so both drivers read zero on the only kind of part
welding ever runs on, and every weldment on every job took the 1-minute floor. A timer with
no valid input is not a low estimate, it is no estimate.

THE PUBLISHED METHOD is arc time (weld length ÷ travel speed) ÷ operating factor (MIG ~35%),
plus handling per joint and set-up — Miller Electric on arc-on time, the Australian Steel
Institute's fillet hour-rates per metre. It is implemented and live, and it computes the
moment a pack states a weld length or a joint count.

NOTHING STATES EITHER TODAY. No drawing field, no model property, and on 7332-01 the
weldment's members are siblings rather than children so they cannot even be counted. So
where there is nothing to measure the line carries the SHOP'S OWN stated allowance — 30
minutes, Howard Thurley, 9 Sep — flagged on the record as an allowance and not a
measurement, with its source named. One observation on one weldment, which is why it says so
rather than pretending to be geometry.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                           # noqa: E402
from estimator import estimate_process_times                            # noqa: E402


def _weldment(**over):
    part = {
        "part_number": "7332-01-101",
        "description": "FRAME WELDMENT",
        "normalized_material": "MILD_STEEL",
        "is_assembly_parent": True,
        "textual_operations": ["welding", "dress_welds"],
    }
    part.update(over)
    return part


# ── the allowance, where the pack measures nothing ───────────────────────────────────────

def test_a_weldment_no_longer_books_one_minute():
    out = estimate_process_times(_weldment())
    assert out["run_times_min_per_unit"]["welding"] == 30.0


def test_the_dressing_follows_it():
    """30 minutes of welding beside 1 of dressing is not one part described twice."""
    out = estimate_process_times(_weldment())
    assert out["run_times_min_per_unit"]["dress_welds"] == 20.0


def test_the_record_says_it_is_an_allowance_and_whose():
    part = _weldment()
    estimate_process_times(part)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "ALLOWANCE, not a measurement" in flags
    assert "welding department" in flags and "7332-01" in flags
    assert part.get("weld_time_is_an_allowance") is True


def test_it_says_what_would_replace_it():
    part = _weldment()
    estimate_process_times(part)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "weld length or a joint count" in flags


# ── the model, the moment a pack gives it something to measure ───────────────────────────

def test_a_stated_weld_length_is_computed_not_allowed():
    """600 mm at 300 mm/min is 2 minutes of arc; at a 35% operating factor, 5.71 minutes."""
    out = estimate_process_times(_weldment(weld_length_mm=600))
    assert out["run_times_min_per_unit"]["welding"] == 5.71


def test_joints_add_their_handling():
    out = estimate_process_times(_weldment(weld_length_mm=600, weld_joint_count=4))
    assert out["run_times_min_per_unit"]["welding"] == round(5.714 + 8.0, 2)


def test_a_joint_count_alone_is_enough_to_leave_the_allowance():
    out = estimate_process_times(_weldment(weld_joint_count=6))
    assert out["run_times_min_per_unit"]["welding"] == 12.0


def test_geometry_is_not_reported_as_an_allowance():
    part = _weldment(weld_length_mm=600)
    estimate_process_times(part)
    assert not part.get("weld_time_is_an_allowance")
    assert any("timed from geometry" in str(f) for f in part.get("review_flags") or [])
    assert estimate_process_times(part)["run_times_min_per_unit"]["dress_welds"] == 0.5


def test_the_features_block_is_read_too():
    out = estimate_process_times(_weldment(
        manufacturing_features={"weld_length_mm": 600}))
    assert out["run_times_min_per_unit"]["welding"] == 5.71


# ── a leaf part is untouched ─────────────────────────────────────────────────────────────

def test_a_welded_leaf_keeps_the_old_geometry_timer():
    """The rule is about assemblies, whose drivers were invalid. A blank still has both."""
    leaf = {"part_number": "X-01M", "normalized_material": "MILD_STEEL",
            "textual_operations": ["welding"], "normalized_thickness_mm": 1.5,
            "overall_length_mm": 300, "overall_width_mm": 200,
            "geometry_rollup": {"estimated_cut_length_mm": 900.0}}
    out = estimate_process_times(leaf)
    assert out["run_times_min_per_unit"]["welding"] < 5.0
    assert not leaf.get("weld_time_is_an_allowance")


# ── the constants are config, with their provenance ──────────────────────────────────────

def test_the_model_names_its_sources():
    m = config.WELD_TIME_MODEL
    assert "operating factor" in m["method_source"].lower()
    assert "welding department" in m["allowance_source"]
    assert m["operating_factor"] == 0.35
