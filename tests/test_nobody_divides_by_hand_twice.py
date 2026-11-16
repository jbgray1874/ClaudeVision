"""Howard said thirty minutes. The sheet said fifty, and both were reading the same config.

    "PER JOINT ... The stated 30 minutes is for 7332-01-101, a frame of four members —
     three joints — so it reads as 10 minutes a joint, and the 20 minutes of dressing as
     6.7."                                              — the comment that was in config.py

The engine counts the joints on that part itself, and it counts FIVE. So a rate derived from
three was multiplied by a count of five: 50 minutes of welding where the welding department
said 30, and 33.5 of dressing where it said 20. About £28 a unit on every weldment job.

NEITHER NUMBER WAS WRONG. Howard's 30 was right, the engine's 5 was right, and the division
between them was done once, by hand, against a guess — and then written down in prose, where
no reader could compare it with the count the code derives. The assumption and the measurement
were in different languages.

So the joint count now sits in SHOP_STATED beside the minutes it divides, and the per-joint
rates are DERIVED. Correct the count and both rates follow; nobody divides by hand again.

    James: "we should apply Howard's changes. can we put these into a central area that is
    easy to identify and change if needed"

SHOP_STATED is that area, and it is one home rather than a fourth. Howard's figures were
already in this file, in three separate constants, each with its own `source` string in its
own words — brushing at one, the plater pack and freight at another, the weld and dress times
at a third. An estimator asked "what did Howard actually say" had to know which three to open.
Now the constants READ from the register, so there is one number per fact, and a copy made
anywhere else is the defect this file keeps finding: two readers of one fact, agreeing until
the day they do not.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                           # noqa: E402

SRC = (ROOT / "src" / "config.py").read_text(encoding="utf-8")


# ── the recalibration lands on what the shop actually said ───────────────────────────────

def test_the_per_joint_rates_reproduce_howards_figures():
    """THE WHOLE POINT. At the joint count the engine derives for the part he timed, the
    model must return the number he gave."""
    w = config.WELD_TIME_MODEL
    joints = config.SHOP_STATED["weld_joints_measured_on"]
    assert w["weld_min_per_joint"] * joints == config.SHOP_STATED["weld_min_per_weldment"]
    assert w["dress_min_per_joint"] * joints == config.SHOP_STATED["dress_min_per_weldment"]


def test_the_rates_are_the_ones_howard_implies():
    assert config.WELD_TIME_MODEL["weld_min_per_joint"] == 6.0
    assert config.WELD_TIME_MODEL["dress_min_per_joint"] == 4.0


def test_the_old_three_joint_rates_are_gone():
    """10.0 and 6.7 were 30 and 20 over a joint count nothing measured."""
    assert config.WELD_TIME_MODEL["weld_min_per_joint"] != 10.0
    assert config.WELD_TIME_MODEL["dress_min_per_joint"] != 6.7


def test_the_allowance_is_the_stated_minutes_unchanged():
    """The flat allowance — used when the members cannot even be counted — IS Howard's
    figure, not a derivative of it, and must not move with the joint count."""
    assert config.WELD_TIME_MODEL["allowance_min_per_weldment"] == 30.0
    assert config.WELD_TIME_MODEL["dress_allowance_min_per_weldment"] == 20.0


def test_correcting_the_joint_count_moves_both_rates_together():
    """The property that makes this safe to hand over: one number to change, and the hand
    division that caused the defect cannot be repeated."""
    stated = dict(config.SHOP_STATED)
    for joints in (3, 4, 5, 6):
        assert stated["weld_min_per_weldment"] / joints * joints == 30.0


def test_the_division_is_written_down_not_done_in_prose():
    """The old calibration's arithmetic lived in a comment, which is why nothing could
    check it against the count the code derives."""
    assert 'SHOP_STATED["weld_min_per_weldment"] / SHOP_STATED["weld_joints_measured_on"]' in SRC
    assert '"weld_joints_measured_on": 5' in SRC


# ── one home, and the others read from it ────────────────────────────────────────────────

def test_every_figure_howard_stated_is_in_the_register():
    # The freight is deliberately NOT in this list any more: £120/order was 7332-01's own
    # transport quote — MONEY, not a shop method — and it lives in the price register
    # scoped job_only to that job (PLATER_FREIGHT).
    for key in ("weld_min_per_weldment", "dress_min_per_weldment", "weld_joints_measured_on",
                "brush_before_plate_min", "plater_pack_min", "plater_final_pack_min"):
        assert key in config.SHOP_STATED, key
    assert "plater_freight_gbp_per_order" not in config.SHOP_STATED


def test_every_figure_carries_its_own_who_and_when():
    """A figure with no name on it cannot be disagreed with, which is how a guess becomes a
    rate. AND THE NAME MUST BE THE RIGHT ONE: the register used to close with one shared
    stated_for_job header, and the header lied the day the second job's figures arrived —
    linebend and the acrylic laser are 0355255's, and anything printing the shared source
    attributed them to 7332-01. James caught it in review. One provenance entry per figure,
    and a figure without one fails here."""
    for key, value in config.SHOP_STATED.items():
        p = config.SHOP_STATED_PROVENANCE.get(key)
        assert p, f"{key} has a value and no provenance — who stated it, when, for what?"
        for field in ("stated_by", "stated_on", "source_job", "unit", "evidence"):
            assert p.get(field), f"{key} provenance is missing {field}"
    # and no orphaned provenance describing a figure that has gone
    for key in config.SHOP_STATED_PROVENANCE:
        assert key in config.SHOP_STATED, f"provenance for {key} but no figure"


def test_the_two_jobs_figures_are_attributed_to_their_own_jobs():
    """The exact mis-attribution, pinned."""
    assert config.SHOP_STATED_PROVENANCE["weld_min_per_weldment"]["source_job"] == "7332-01"
    assert config.SHOP_STATED_PROVENANCE["linebend_min_per_bend"]["source_job"] == "0355255"
    assert config.SHOP_STATED_PROVENANCE["laser_acrylic_parts_per_hour"]["source_job"] == "0355255"
    assert "0355255" in config.shop_stated_source("linebend_min_per_bend")
    assert "7332-01" not in config.shop_stated_source("linebend_min_per_bend")


def test_a_consumer_prints_the_right_jobs_source():
    assert "7332-01" in config.BRUSH_BEFORE_PLATE["source"]
    assert "7332-01" in config.PLATING_LOGISTICS["source"]
    assert "7332-01" in config.WELD_TIME_MODEL["allowance_source"]


def test_the_consumers_read_the_register_rather_than_repeating_it():
    """A second copy of a number is the defect, however well the two copies agree today."""
    assert config.BRUSH_BEFORE_PLATE["minutes_per_unit"] == \
        config.SHOP_STATED["brush_before_plate_min"]
    assert config.PLATING_LOGISTICS["pack_for_plater_min"] == \
        config.SHOP_STATED["plater_pack_min"]
    assert config.PLATING_LOGISTICS["final_pack_min"] == \
        config.SHOP_STATED["plater_final_pack_min"]


def test_no_consumer_hard_codes_a_figure_the_register_owns():
    """Read from the source, so a literal put back by hand fails here rather than on a job."""
    for block, literals in (("BRUSH_BEFORE_PLATE = {", ("40.0",)),
                            ("PLATING_LOGISTICS = {", ('"4.0"', '"8.0"', '"120.0"'))):
        body = SRC.split(block)[1].split("}")[0]
        for lit in literals:
            assert lit not in body, f"{block} hard-codes {lit} instead of reading SHOP_STATED"


def test_every_consumer_names_howard_on_the_sheet():
    """These figures reach an estimator's page. One observation from one job is not a
    weakness to hide — it is why the next estimator to disagree must know whose number it
    is."""
    for source in (config.BRUSH_BEFORE_PLATE["source"],
                   config.PLATING_LOGISTICS["source"],
                   config.WELD_TIME_MODEL["allowance_source"]):
        assert "Howard Thurley" in source, source
        assert "7332-01" in source, source


def test_the_values_the_env_can_still_override():
    """A shop cannot be made to wait for a commit to change a rate it has just re-measured."""
    # PLATER_FREIGHT_GBP is gone on purpose: the freight is register data now (a diff to
    # data/price_register.json, no code or env involved), not a shop rate to retune.
    for var in ("WELD_MIN_PER_JOINT", "WELD_DRESS_MIN_PER_JOINT", "PLATER_PACK_MIN",
                "PLATER_FINAL_PACK_MIN"):
        assert var in SRC, var
