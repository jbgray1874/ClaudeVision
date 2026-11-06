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

# READ THE RATE, DO NOT REPEAT IT.
#
# These assertions used to carry 10.0 and 6.7 as literals, which is how a recalibration
# turns into eight red tests that each have to be re-derived by hand — the very arithmetic
# that caused the defect. They now assert the RULE (joints x the shop's rate) against the
# one place the rate lives, so correcting the rate corrects the expectation with it.
WELD = config.WELD_TIME_MODEL["weld_min_per_joint"]      # 6.0 = Howard's 30 over 5 joints
DRESS = config.WELD_TIME_MODEL["dress_min_per_joint"]    # 4.0 = his 20 over the same 5


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
    """A stated joint count with no length prices per JOINT, not as arc handling.

    The 2 min handling figure supplements arc time; it is not the cost of making a joint.
    Where the only fact is how many joints there are, the per-joint rate is what applies —
    the shop's 30 minutes over the FIVE joints of the frame it was measured on."""
    out = estimate_process_times(_weldment(weld_joint_count=6))
    assert out["run_times_min_per_unit"]["welding"] == round(6 * WELD, 2)


def test_geometry_is_not_reported_as_an_allowance():
    part = _weldment(weld_length_mm=600)
    estimate_process_times(part)
    assert not part.get("weld_time_is_an_allowance")
    assert any("timed from geometry" in str(f) for f in part.get("review_flags") or [])


def test_a_stated_length_dresses_in_proportion_to_its_weld():
    """THE 0.5-MINUTE HOLE, WHICH THIS FILE USED TO PIN OPEN.

    The allowance branch dresses 20 against 30, and the per-joint branch 6.7 against 10 —
    and the LENGTH branch dressed a metre of weld in thirty seconds, because Tim's minimal
    single-bead figure was the `else`. So the better the drawing, the more absurd the pair,
    which is the same defect Howard Thurley reported from the other end: "Weld & Dress AI
    Estimate for 2 Minutes & 1 Minute respectively."

    Dressing is the same fraction of welding in both of the shop's own statements — 20 over
    30 — so the length branch uses that fraction rather than a fourth number nobody gave us.
    Taken from the rates themselves, because a literal 0.67 here was a third copy of it."""
    part = _weldment(weld_length_mm=600)
    out = estimate_process_times(part)
    weld = out["run_times_min_per_unit"]["welding"]
    dress = out["run_times_min_per_unit"]["dress_welds"]
    assert dress == round(weld * (DRESS / WELD), 2), (weld, dress)
    assert any("dressing scaled to the weld" in str(f)
               for f in part.get("review_flags") or [])


def test_a_part_that_is_not_welded_gains_no_dressing():
    """The proportion applies to welding, so a part with no weld has nothing to be a
    proportion of — 12349-02 must not pick up a dress line from this."""
    part = _weldment(weld_length_mm=600, textual_operations=["laser_cutting"])
    out = estimate_process_times(part)
    assert not out["run_times_min_per_unit"].get("dress_welds")


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


# ── one number for every weldment is a blanket, not a rule ───────────────────────────────
# The shop's 30 minutes is for 7332-01-101, a frame of FOUR members — three joints. Applied
# flat it also landed on 12349-02-69-03M, which is two laser-cut parts welded once, on the
# very sheet about to go to a different customer. Scaled per joint it reproduces the shop's
# own figure on the part the shop measured, and stays proportionate on the part it did not.

def test_the_frame_howard_timed_comes_out_at_the_stated_thirty():
    """THE ANCHOR, AND IT MOVED — because it was anchored to the wrong part.

    This asserted that a FOUR-member frame returns Howard's 30, on the strength of a comment
    in config reading "a frame of four members - three joints". 7332-01-101 is not a
    four-member frame. is_weldment_parent's own docstring records what the job says it is:
    "the route graph gives it SIX children, the plating line lists its members by name" —
    six members, five joints. James's dry run confirms it from the other end, 50 minutes at
    the old 10 a joint.

    So the rate was Howard's 30 divided by three while the engine multiplied it by five, and
    this test held the error in place by checking the wrong frame. The stated thirty belongs
    to the frame he actually timed."""
    out = estimate_process_times(_weldment(children=["a", "b", "c", "d", "e", "f"]))
    assert out["run_times_min_per_unit"]["welding"] == 30.0
    assert out["run_times_min_per_unit"]["dress_welds"] == 20.0


def test_a_smaller_frame_is_charged_as_a_smaller_frame():
    """The consequence, and the point of pricing per joint at all: four members is three
    joints, which is three-fifths of the work of the frame the shop timed — not all of it."""
    out = estimate_process_times(_weldment(children=["a", "b", "c", "d"]))
    assert out["run_times_min_per_unit"]["welding"] == round(3 * WELD, 2)
    assert out["run_times_min_per_unit"]["dress_welds"] == round(3 * DRESS, 2)


def test_a_two_part_holder_is_not_charged_like_a_frame():
    """12349-02-69-03M: one joint, so a fifth of the frame's work, not all of it."""
    out = estimate_process_times(_weldment(
        part_number="12349-02-69-03M", children=["12349-02-69-03M-01",
                                                 "12349-02-69-03M-02"]))
    assert out["run_times_min_per_unit"]["welding"] == WELD
    assert out["run_times_min_per_unit"]["dress_welds"] == DRESS


def test_the_line_says_how_many_joints_and_where_the_rate_came_from():
    part = _weldment(children=["a", "b", "c"])
    estimate_process_times(part)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert f"2 joint(s) at {WELD:g} min" in flags and "3 members" in flags
    assert "welding department" in flags


def test_members_are_counted_from_any_spelling():
    for field in ("child_parts", "children", "assembly_children"):
        out = estimate_process_times(_weldment(**{field: ["a", "b", "c"]}))
        assert out["run_times_min_per_unit"]["welding"] == round(2 * WELD, 2), field


def test_a_weldment_whose_members_cannot_be_counted_keeps_the_flat_allowance():
    """7332-01-101's members are siblings, not children — nothing to count."""
    part = _weldment()
    out = estimate_process_times(part)
    assert out["run_times_min_per_unit"]["welding"] == 30.0
    assert part.get("weld_time_is_an_allowance") is True


def test_a_stated_joint_count_beats_the_member_count():
    out = estimate_process_times(_weldment(children=["a", "b"], weld_joint_count=5))
    assert out["run_times_min_per_unit"]["welding"] == round(5 * WELD, 2)


def test_a_stated_weld_length_still_wins_over_both():
    out = estimate_process_times(_weldment(children=["a", "b", "c"], weld_length_mm=600))
    assert out["run_times_min_per_unit"]["welding"] == round(5.714 + 2 * 2.0, 2)
