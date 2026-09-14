"""The second Harrods stand must not ask the same question the first one answered.

    "All changes we do should be worked to be inherited or it's a pointless one off hack
     that we will be found out on with the next drawing with the same characteristics"
                                                        — James Gray, SDI, 14 Sep 2026

He is right, and this file is where I was wrong. Brass Harrods 01 at £250 went into
7332-01's own answers file, which governs 7332-01 and nothing else. So the next Harrods
stand states the same bare "PLATED", blocks for the same reason, and somebody types the same
£250 — same characteristics, same manual work, every time. The blocking rule generalised; the
knowledge did not, and the knowledge is the part that cost a day to get.

THIS REVERSES A TEST WRITTEN ON PURPOSE. test_the_customer_name_alone_buys_nothing pinned
that a client called Harrods buys no plate spec, and that reasoning still holds: the ENGINE
must never infer a price from a customer's name. What changed is that this is not an
inference. An estimator stated it, for stated conditions, and recording that is the opposite
of guessing — "Harrods, so probably brass" against "Howard Thurley told us on 9 Sep that
Harrods stands calling up a bare PLATED are Brass Harrods 01 at £250".

WHAT MAKES INHERITANCE SAFE IS THAT IT ANNOUNCES ITSELF. Every inherited figure says whose
decision it was, which job it was made on, why, and what the line would have read without
it. An inherited price that arrives silently is indistinguishable from one the engine
invented, and that is the one thing this codebase does not do.

AND THE PACK STILL WINS. The register is consulted only where the drawings could not answer.
A pack that names its own spec is read; a job with a price already on it is untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                            # noqa: E402
from estimator import (apply_subcontract_plating, inherited_decision,    # noqa: E402
                       job_customer)


def _job(customer, finish="PLATED", drawing="9001-01"):
    """A DIFFERENT job from 7332-01 — that is the whole point of the test."""
    parts = [{"part_number": f"{drawing}-101", "description": "FRAME WELDMENT",
              "normalized_finish": finish, "is_assembly_parent": True, "quantity": 1,
              "material_estimate": {"unit_material_mass_kg": 0.9}},
             {"part_number": f"{drawing}-101-PLATE", "_plating_placeholder": True,
              "_plating_weldment": f"{drawing}-101",
              "_plating_members": [f"{drawing}-101"], "quantity": 1,
              "description": "plating"}]
    apply_subcontract_plating(parts, {"customer": customer}, 6, parts)
    return parts[1]


# ── the next drawing with the same characteristics ───────────────────────────────────────

def test_the_second_harrods_stand_is_priced_without_asking_again():
    line = _job("Harrods")
    assert line["unit_cost_gbp"] == 250.00
    assert line["cost_source"] == "inherited_estimator_decision"


def test_it_finds_the_customer_however_the_folder_spelled_it():
    """"Harrods Ltd" and "Harrods" are one customer. A rule that misses two spellings out of
    three is the one-off hack it was written to replace."""
    for name in ("Harrods", "HARRODS LTD", "Harrods Ltd", "Harrods Limited",
                 "harrods 9001-01"):
        assert _job(name)["unit_cost_gbp"] == 250.00, name


def test_another_customer_inherits_nothing():
    for name in ("Selfridges", "John Lewis", "", None):
        line = _job(name)
        assert line["unit_cost_gbp"] == 0.0, name
        assert line["cost_source"] == "subcontract_plating_spec_unidentified", name


# ── and the pack still outranks it ───────────────────────────────────────────────────────

def test_a_drawing_that_states_its_own_process_is_read_not_overruled():
    """A job whose finish says zinc is priced on the zinc card, Harrods or not. The register
    answers only where the drawings could not."""
    line = _job("Harrods", finish="zinc plated")
    assert line["cost_source"] == "subcontract_plating_indicative"
    assert line["unit_cost_gbp"] == 15.83


def test_a_drawing_naming_the_spec_itself_prices_from_the_spec_table():
    line = _job("Harrods", finish="PLATED Harrods01")
    assert line["cost_source"] == "subcontract_plating_named_spec"
    assert line["unit_cost_gbp"] == 250.00


# ── it says where it came from, every time ───────────────────────────────────────────────

def test_the_line_says_it_was_inherited_and_from_what():
    line = _job("Harrods")
    text = line["description"] + " " + " ".join(line["review_flags"])
    assert "INHERITED" in text
    assert "7332-01" in text                       # the job the decision was made on
    assert "Howard Thurley" in text                # whose decision
    assert "9 Sep 2026" in text                    # when
    assert "confirm it applies" in text.lower()


def test_it_says_what_the_line_would_have_read_without_it():
    """So an estimator can see the figure he is overriding, not just the one he is given."""
    flags = " ".join(_job("Harrods")["review_flags"])
    assert "Without it the line would read" in flags
    assert "SPEC NOT IDENTIFIED" in flags


def test_it_says_this_drawing_does_not_state_the_spec():
    """The most important sentence on the line: the figure is from an earlier job, not from
    the pack in front of the reader."""
    flags = " ".join(_job("Harrods")["review_flags"])
    assert "THIS DRAWING DOES NOT STATE THE SPEC" in flags


# ── the register itself ──────────────────────────────────────────────────────────────────

def test_every_entry_says_who_decided_it_and_when_and_why():
    """A decision of unknown origin cannot be confirmed or argued with, so it can only be
    deleted — the same rule the commodity price table already lives by."""
    for entry in config.INHERITED_ESTIMATOR_DECISIONS:
        for field in ("id", "when", "then", "decided_by", "decided_on", "decided_on_job",
                      "why"):
            assert str(entry.get(field) or "").strip() or entry.get(field), (field, entry)


def test_every_condition_must_match_not_just_one():
    """`when` is a conjunction. A customer match alone must not buy the price — that is
    exactly the inference this engine refuses to make."""
    assert inherited_decision("plating_gbp_per_unit", {"customer": "Harrods"}) is None
    assert inherited_decision("plating_gbp_per_unit", {
        "customer": "Harrods", "finish_family": "plate"}) is None
    assert inherited_decision("plating_gbp_per_unit", {
        "customer": "Harrods", "finish_family": "plate", "spec_identified": False})


def test_an_identified_spec_is_not_a_missing_one():
    """spec_identified True must not match the False condition — a boolean compares exactly,
    because "the spec could not be identified" is not nearly true."""
    assert inherited_decision("plating_gbp_per_unit", {
        "customer": "Harrods", "finish_family": "plate", "spec_identified": True}) is None


def test_an_entry_with_no_conditions_applies_to_nothing(monkeypatch):
    """A rule that matches every job is not a rule, it is a default, and a default that
    arrived by accident is how a price reaches a job nobody meant it to reach."""
    monkeypatch.setattr(config, "INHERITED_ESTIMATOR_DECISIONS",
                        [{"id": "oops", "when": {}, "then": {"plating_gbp_per_unit": 999.0},
                          "decided_by": "x", "decided_on": "y", "decided_on_job": "z",
                          "why": "w"}])
    assert inherited_decision("plating_gbp_per_unit", {"customer": "Anyone"}) is None
    assert _job("Selfridges")["unit_cost_gbp"] == 0.0


def test_a_decision_of_another_kind_is_not_returned():
    assert inherited_decision("weld_minutes", {
        "customer": "Harrods", "finish_family": "plate", "spec_identified": False}) is None


def test_the_customer_is_read_the_way_the_workbook_header_reads_it():
    """One answer to "who is this job for", so the register and the sheet cannot disagree."""
    assert job_customer({"customer": "Harrods"}) == "Harrods"
    assert job_customer({"client": "Harrods"}) == "Harrods"
    assert job_customer({}) == ""
    assert job_customer(None) == ""


# ── the rate correction that also had to inherit ─────────────────────────────────────────

def test_the_acrylic_laser_rate_is_the_departments_not_the_corpus():
    """"Line 96 – Laser Rate Acrylic Comparison AI 252 p/hour Manual Estimate 95 p/hour."
    252 was measured off THIRTEEN lines — the thinnest sample in the table. It was put in
    7332-01's answers file first, where every other acrylic job kept the figure he had
    already told us was wrong. A rate correction is how the department runs, not a decision
    about one stand."""
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    assert '"Laser (Acrylic)":           95,' in src
    assert "Howard Thurley (SDI estimating), 9 Sep 2026" in src
    assert "was 252 from 13 corpus lines" in src
