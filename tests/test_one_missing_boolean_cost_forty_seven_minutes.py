"""Howard Thurley's weld, dress and pack figures were in config the whole time.

    "Line 86 & 87 - Weld & Dress AI Estimate for 2 Minutes & 1 Minute respectively, Timings
     from Welding Dept. 0.5 Hours & 20 Minutes respectively."
    "Line 107 – 2 Minutes allowance for Assembly / Pack … Manual Estimate for 4 Minutes Pack
     for Platers / 8 Minutes Final Assembly & Pack."

Thirty minutes, twenty minutes, four plus eight. All three were written into
config.WELD_TIME_MODEL and config.PLATING_LOGISTICS days ago, with his name on them, and all
three books since have shipped 2, 1 and 2. The engine was not ignoring him. Two gates were
shut in front of the numbers, and a third opened and was overruled.

GATE ONE — TWO BOOLEANS. The weld allowance and the dress allowance both asked
`is_assembly_parent or is_sub_assembly`. 7332-01-101 is a FRAME WELDMENT: the Provenance tab
prints it as an assembly, the route graph gives it six children, the plating line lists its
members by name — and its record carries neither flag. So both allowances fell through to a
1-minute floor and a 0.5-minute minimal bead. One missing boolean, 47 minutes a unit, about
£28.57 on a £63 stand.

That is the same lesson the plating member list had already taught: it had to stop reading
the parent's own child list and re-derive from the compiled hierarchy. ASK WHAT THE JOB SAYS
THIS PART IS. Not whether one reader happened to set one flag.

GATE TWO — THE SAME TEST, WRITTEN TWICE. Dressing is timed ~90 lines before welding, so the
two branches each kept their own copy of the weldment test. Widening one and not the other
produces 20 minutes of dressing beside 1 minute of welding: the exact absurdity the existing
comment says the shared predicate exists to prevent, in the other direction.

GATE THREE — THE FLOOR GUARD. Even with the minutes right, the workbook has its own labour
model: a corpus of 1,982 historical jobs, and a guard that substitutes the median whenever a
derived throughput is more than 5x off it. A 12-minute pack derives 5/hr against a 58/hr
median, so the median won. The guard is sound — it stops a missing bend count billing five
hours to route a panel — but it cannot tell a garbage derivation from a time the shop gave
us. A corpus median is evidence about jobs in general; a stated time is evidence about this
one, and it wins.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                            # noqa: E402
from estimator import estimate_process_times, is_weldment_parent         # noqa: E402


def _101(**over):
    """7332-01-101 exactly as the pack hands it over: no assembly flag, no child list."""
    part = {"part_number": "7332-01-101", "description": "FRAME WELDMENT",
            "normalized_material": "MILD_STEEL", "normalized_finish": "PLATED",
            "textual_operations": ["welding", "dress_welds", "assembly"], "quantity": 1}
    part.update(over)
    return part


def _times(part):
    return estimate_process_times(part, 6)["run_times_min_per_unit"]


# ── the three figures he gave us ─────────────────────────────────────────────────────────

def test_the_welding_department_gets_its_thirty_minutes():
    assert _times(_101())["welding"] == 30.0


def test_and_its_twenty_minutes_of_dressing():
    assert _times(_101())["dress_welds"] == 20.0


def test_and_the_part_that_goes_to_a_plater_is_packed_twice():
    """As TWO operations since Howard's 15 Sep ruling ("Two separate Operations this
    job") — 4 out to the plater on its own row, 8 final. The total is the same 12."""
    t = _times(_101())
    assert t["plater_pack"] == 4.0 and t["handling"] == 8.0


def test_all_three_on_the_one_part_at_once():
    """Together, because they were reported together and because the failure was shared:
    2 / 1 / 2 against 30 / 20 / 12 (the 12 now split 4 + 8 per his ruling)."""
    t = _times(_101())
    assert (t["welding"], t["dress_welds"],
            t["plater_pack"] + t["handling"]) == (30.0, 20.0, 12.0)


# ── how the weldment is recognised, and how narrowly ─────────────────────────────────────

def test_the_flags_still_work_where_a_reader_did_set_them():
    for flag in ("is_assembly_parent", "is_sub_assembly"):
        assert is_weldment_parent({flag: True}), flag


def test_the_hierarchy_is_read_where_the_flags_are_absent():
    assert is_weldment_parent({"child_parts": ["a", "b"]})
    assert is_weldment_parent({"page_roles": ["assembly"]})
    assert is_weldment_parent({"kind": "weldment"})


def test_the_shops_own_naming_table_is_consulted():
    """config.WELDMENT_PARENT_DESC_TOKENS exists to answer exactly this question and nothing
    was asking it. "FRAME WELDMENT" is the description on the part that cost the money."""
    assert is_weldment_parent({"description": "FRAME WELDMENT"})
    assert is_weldment_parent({"description": "BASE WELD ASSEMBLY"})


def test_a_leaf_part_is_not_a_weldment():
    for part in ({"part_number": "7332-01-001", "description": "BASE"},
                 {"part_number": "12349-02-69-04M", "description": "LID"},
                 {"description": "BRACKET", "child_parts": ["only-one"]},
                 {}):
        assert not is_weldment_parent(part), part


def test_a_bracket_that_is_welded_keeps_its_own_small_time():
    """THE LINE THIS MUST NOT CROSS. 12349-02-69-03M is two laser-cut parts welded once. A
    Harrods frame's half hour must not land on it because both carry a weld."""
    bracket = {"part_number": "12349-02-69-03M", "description": "BRACKET",
               "normalized_material": "MILD_STEEL",
               "textual_operations": ["welding", "dress_welds"], "quantity": 1}
    t = _times(bracket)
    assert t["welding"] == 1.0 and t["dress_welds"] == 0.5


def test_an_unplated_weldment_is_packed_once():
    """The pack doubling is the plater's round trip, not a property of weldments."""
    assert _times(_101(normalized_finish="POWDER COATED RAL9005"))["handling"] == 0.8


# ── a measurement always beats the allowance ─────────────────────────────────────────────

def test_a_stated_weld_length_still_wins():
    """The allowance is what stands when the pack measures nothing. It must never displace a
    drawing that actually says how much weld there is."""
    t = _times(_101(weld_length_mm=800))
    assert t["welding"] != 30.0
    assert t["welding"] == 7.62


def test_a_counted_joint_still_wins_over_the_flat_allowance():
    """AND IT NOW AGREES WITH THE MAN WHO TIMED IT, which it did not before.

    This is 7332-01-101's real member list — six members, so five joints — and it asserted
    50 minutes and 33.5. That is precisely the pair James found on the sheet, against
    Howard's stated 30 and 20, and this test was holding it in place: the per-joint rate had
    been set by dividing his 30 by an ASSUMED three joints (config's own comment: "a frame
    of four members - three joints") while the engine multiplied it by the five it counts
    here. An assumption in prose and a measurement in code, never compared.

    Counting still beats the flat allowance — that rule is untouched, and it is what keeps a
    frame's time off a two-part holder. It just no longer arrives at a different answer from
    the shop for the very part the shop measured."""
    t = _times(_101(child_parts=["001", "002", "003", "004", "005", "008"]))
    assert t["welding"] == 30.0                       # 5 joints x 6 min = Howard's 30
    assert t["dress_welds"] == 20.0                   # 5 joints x 4 min = Howard's 20


def test_the_line_says_which_of_the_three_it_used():
    """An allowance that reads like a measurement is the thing this whole area exists to
    stop, so the row has to name itself."""
    part = _101()
    estimate_process_times(part, 6)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "WELD TIME IS AN ALLOWANCE, not a measurement" in flags
    assert "SDI welding department" in flags


# ── and the figures stay in config, with his name on them ────────────────────────────────

def test_the_numbers_are_config_and_say_whose_they_are():
    wm = config.WELD_TIME_MODEL
    assert wm["allowance_min_per_weldment"] == 30.0
    assert wm["dress_allowance_min_per_weldment"] == 20.0
    assert "welding department" in wm["allowance_source"]
    pl = config.PLATING_LOGISTICS
    assert pl["pack_for_plater_min"] == 4.0 and pl["final_pack_min"] == 8.0
    assert "Howard Thurley" in pl["source"]


def test_changing_the_config_figure_changes_the_sheet(monkeypatch):
    """The point of holding them in config: one edit, and it moves. If this ever fails a
    number has been hard-coded somewhere downstream again."""
    monkeypatch.setitem(config.WELD_TIME_MODEL, "allowance_min_per_weldment", 45.0)
    assert _times(_101())["welding"] == 45.0
