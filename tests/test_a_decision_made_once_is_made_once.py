"""A decision inherits. A QUOTED PRICE does not — and plating is a quoted price.

    "All changes we do should be worked to be inherited or it's a pointless one off hack
     that we will be found out on with the next drawing with the same characteristics"
                                                        — James Gray, SDI, 14 Sep 2026

That is right, and this file used to apply it to the wrong thing. Brass Harrods 01 at £250
went into a register keyed on the CUSTOMER, so the next Harrods stand whose drawing said
only "PLATED" would price at £250 without asking. We told Howard we had done it. He
corrected us on 16 Sep:

    "Plating would be as drawing specific, £250.00 is from supplier per unit and is
     independent of any other job. Plating jobs priced independently."

So the premise was wrong, not the implementation. A price a plater quoted for one job is
evidence about THAT job; the customer's name buys nothing at all. The entry is revoked, and
test_the_customer_name_alone_buys_nothing — which this file reversed on purpose, and which
was right the first time — stands again.

WHAT SURVIVES, AND WHY IT IS WORTH KEEPING. The machinery is sound and the fault was in what
we put through it: every condition must match, an entry with no conditions applies to
nothing, every entry names who decided it and when, and anything inherited announces itself
on the line. A genuine standing decision — a rule an estimator states AS a rule — still
belongs here. A quoted price wearing a rule's clothes does not, and the tests below now pin
that distinction rather than the £250.

AND READING THE SPEC OFF THE DRAWING IS UNAFFECTED. A pack that names "Harrods 01" is read;
what no longer travels is the figure beside it, which is marked priced-per-job and asks for
this job's plater quote.
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


# The shape a GENUINE standing decision takes — a rule an estimator states AS a rule, not a
# price he quoted for a job. Howard's own: "dressing varies between clients, M&S dress all
# seen welds, TTI no dressing." Used as a fixture so the machinery keeps its tests without
# the revoked price.
_A_REAL_STANDING_RULE = {
    "id": "ms-dress-seen-welds",
    "when": {"customer": "M&S", "finish_family": "weld", "seen_welds": True},
    "then": {"weld_dress_required": True},
    "decided_by": "Howard Thurley (SDI estimating)", "decided_on": "16 Sep 2026",
    "decided_on_job": "7332-01",
    "why": "M&S dress all seen welds; TTI none. His words, as a rule rather than a price",
}


def test_an_earlier_jobs_figure_reaches_no_new_estimate():
    """THE RULE IN ITS FINAL FORM. Three corrections landed on this one figure in a day:
    revoke the customer inheritance; stop it being a chargeable constant; scope it to its
    own job. Each was right and none was enough, because each still let the number reach a
    line. James Gray, 16 Sep 2026: "our estimating process is as independent as it can be…
    it must be impossible for an estimator run to read, display or charge it."
    """
    import price_register
    assert price_register.lookup("HARRODS01", ("7332-01",)) is None
    for job in (("7332-01",), ("9001-01",), ()):
        unit, note, method = plating_unit_price(2.4, 6, _POLICY, "Harrods 01", job)
        assert unit is None and method == "subcontract_plating_quote_needed", job
        assert "250" not in note, job


def test_what_survives_is_knowledge_and_not_a_number():
    spec = config.NAMED_PLATE_SPECS["HARRODS01"]
    assert spec["decorative"] is True, "so the per-kilo zinc card cannot price it"
    assert spec["requires_quote"] is True, "so a fresh job-specific quote is required"
    assert not any(isinstance(v, (int, float)) and v > 1 for v in spec.values()), \
        "no figure of any kind lives in the method entry"


def test_a_drawing_naming_the_spec_is_read_and_then_asks():
    """The pack still outranks everything for IDENTIFICATION — a drawing naming Harrods 01
    is read, not overruled — and the line then asks for this job's plater price."""
    parts = [{"part_number": "9001-01-101", "description": "FRAME WELDMENT",
              "normalized_finish": "HARRODS 01", "is_assembly_parent": True, "quantity": 1,
              "material_estimate": {"unit_material_mass_kg": 0.9}},
             {"part_number": "9001-01-101-PLATE", "_plating_placeholder": True,
              "_plating_weldment": "9001-01-101", "_plating_members": ["9001-01-101"],
              "quantity": 1, "description": "plating"}]
    apply_subcontract_plating(parts, {"customer": "Harrods",
                                      "job_output_stem": "9001-01"}, 6, parts)
    _desc = str(parts[1].get("description") or "")
    assert "Harrods 01" in _desc, "the spec the drawing names is read"
    assert "NOT PRICED" in _desc and "ASKED OF" in _desc
    assert "250" not in _desc


# ── the revoked entry ────────────────────────────────────────────────────────────────────

def test_no_customer_buys_a_plating_price():
    """THE REVOCATION. Howard: plating is drawing-specific and priced job by job."""
    assert config.INHERITED_ESTIMATOR_DECISIONS == [], \
        "a quoted price must not live in the standing-decision register"
    assert inherited_decision("plating_gbp_per_unit", {
        "customer": "Harrods", "finish_family": "plate", "spec_identified": False}) is None


def test_the_second_harrods_stand_asks_again_on_purpose():
    """It looks like a regression and it is the correction. Another stand is another
    plater quote, and the engine may not answer that question for him."""
    parts = [{"part_number": "9001-01-101", "description": "FRAME WELDMENT",
              "normalized_finish": "PLATED", "is_assembly_parent": True, "quantity": 1,
              "material_estimate": {"unit_material_mass_kg": 0.9}},
             {"part_number": "9001-01-101-PLATE", "_plating_placeholder": True,
              "_plating_weldment": "9001-01-101", "_plating_members": ["9001-01-101"],
              "quantity": 1, "description": "plating"}]
    apply_subcontract_plating(
        parts, {"job_folder": r"D:\Enquiries\Harrods\9001-01"}, 6, parts)
    assert parts[1]["unit_cost_gbp"] != 250.00



def test_another_customer_inherits_nothing():
    assert inherited_decision("plating_gbp_per_unit", {
        "customer": "Selfridges", "finish_family": "plate",
        "spec_identified": False}) is None


# ── and the pack still outranks it ───────────────────────────────────────────────────────

def test_a_drawing_that_states_its_own_process_is_read_not_overruled():
    """A job whose finish says zinc is priced on the zinc card, Harrods or not. The register
    answers only where the drawings could not."""
    line = _job("Harrods", finish="zinc plated")
    assert line["cost_source"] == "subcontract_plating_indicative"
    assert line["unit_cost_gbp"] == 15.83



# ── it says where it came from, every time ───────────────────────────────────────────────




# ── the register itself ──────────────────────────────────────────────────────────────────

def test_every_entry_says_who_decided_it_and_when_and_why():
    """A decision of unknown origin cannot be confirmed or argued with, so it can only be
    deleted — the same rule the commodity price table already lives by."""
    for entry in config.INHERITED_ESTIMATOR_DECISIONS:
        for field in ("id", "when", "then", "decided_by", "decided_on", "decided_on_job",
                      "why"):
            assert str(entry.get(field) or "").strip() or entry.get(field), (field, entry)


def test_every_condition_must_match_not_just_one(monkeypatch):
    """`when` is a conjunction. A customer match alone must not buy the price — that is
    exactly the inference this engine refuses to make."""
    monkeypatch.setattr(config, "INHERITED_ESTIMATOR_DECISIONS", [_A_REAL_STANDING_RULE])
    assert inherited_decision("weld_dress_required", {"customer": "M&S"}) is None
    assert inherited_decision("weld_dress_required", {
        "customer": "M&S", "finish_family": "weld"}) is None
    assert inherited_decision("weld_dress_required", {
        "customer": "M&S", "finish_family": "weld", "seen_welds": True})


def test_an_identified_spec_is_not_a_missing_one(monkeypatch):
    """spec_identified True must not match the False condition — a boolean compares exactly,
    because "the spec could not be identified" is not nearly true."""
    monkeypatch.setattr(config, "INHERITED_ESTIMATOR_DECISIONS", [_A_REAL_STANDING_RULE])
    assert inherited_decision("weld_dress_required", {
        "customer": "M&S", "finish_family": "weld", "seen_welds": False}) is None


def test_an_entry_with_no_conditions_applies_to_nothing(monkeypatch):
    """A rule that matches every job is not a rule, it is a default, and a default that
    arrived by accident is how a price reaches a job nobody meant it to reach."""
    monkeypatch.setattr(config, "INHERITED_ESTIMATOR_DECISIONS",
                        [{"id": "oops", "when": {}, "then": {"plating_gbp_per_unit": 999.0},
                          "decided_by": "x", "decided_on": "y", "decided_on_job": "z",
                          "why": "w"}])
    assert inherited_decision("plating_gbp_per_unit", {"customer": "Anyone"}) is None
    assert _job("Selfridges")["unit_cost_gbp"] == 0.0


def test_a_decision_of_another_kind_is_not_returned(monkeypatch):
    monkeypatch.setattr(config, "INHERITED_ESTIMATOR_DECISIONS", [_A_REAL_STANDING_RULE])
    assert inherited_decision("weld_minutes", {
        "customer": "M&S", "finish_family": "weld", "seen_welds": True}) is None


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


# ── and the customer is the one the SHEET says, not a narrower reading ───────────────────
#
# THE DEFECT THIS PINS WAS MINE, ONE HOUR AFTER WRITING THE REGISTER. The header prints the
# customer from four sources; the register read two. On 7332-01 the name comes from the
# fourth — the pack sits in a Harrods folder and nothing on any drawing says Harrods — so the
# sheet said Harrods, the register looked for Harrods and found "", and £250 did not reach a
# job that plainly qualified. A second reader that agrees with the first until the one case
# that matters is the defect class this whole session has been about.

def test_the_customer_is_found_in_the_job_folder_too():
    """client_from_job_folder exists for exactly this — it was written when the header cell
    was falling back to the job number."""
    assert job_customer({"job_folder": r"D:\Enquiries\Harrods\7332-01"}) == "Harrods"
    assert job_customer({"job_folder": r"C:\SDI\Production\Harrods\7332-01"}) == "Harrods"


def test_a_stated_customer_still_wins_over_the_folder():
    assert job_customer({"customer": "Selfridges",
                         "job_folder": r"D:\Enquiries\Harrods\7332-01"}) == "Selfridges"


def test_a_folder_that_names_no_customer_yields_nothing():
    """Conservative by design: a wrong customer name on a sheet is worse than a blank, and
    an inherited PRICE keyed on a wrong name is worse again."""
    assert job_customer({"job_folder": r"C:\jobs\7332-01"}) == ""
    assert job_customer({"job_folder": ""}) == ""



def test_it_delegates_rather_than_copying_the_rule():
    """If the header's rule changes this must change with it — a third copy is how the two
    disagreed in the first place."""
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert "from wb_populate import client_from_job_folder" in src


# ── and the label had to become enforcement ──────────────────────────────────────────────
#
# Revoking the customer-keyed entry was not enough. NAMED_PLATE_SPECS still held £250 and
# plating_unit_price still charged it whenever ANY job's finish said Harrods01: the new
# priced_per_job / quoted_for_job fields were labels, and the pricing function received no
# job identity to check them against. Howard's clarification was undone in the one place
# that charges.

from estimator import job_identity_codes, plating_unit_price      # noqa: E402

# The real card, because its `rate_covers` is what stops zinc pricing a brass — a
# stripped-down fixture silently disables the guard these tests are about.
_POLICY = config.PLATE_SUBCONTRACT_POLICY




def test_the_spec_must_still_be_named_by_the_drawing():
    """The comparator is reached by the PACK naming the spec. A drawing that says only
    "PLATED" names no spec and reaches none of this — it blocks, as it always did."""
    unit, _, method = plating_unit_price(2.4, 6, _POLICY, "PLATED", ("9001-01",))
    assert unit is None and method == "subcontract_plating_spec_unidentified"


def test_the_spec_is_named_on_the_line_wherever_it_lands():
    _, note, _ = plating_unit_price(2.4, 6, _POLICY, "Harrods 01", ("9001-01",))
    assert "Harrods 01" in note


def test_the_job_is_recognised_however_the_record_spells_it():
    """The drawing number carries the sheet role, the stem does not, and both are this job."""
    assert "7332-01" in job_identity_codes(
        {"document_analysis": {"drawing_number": "7332-01-GA"}})
    assert "7332-01" in job_identity_codes({"job_output_stem": "7332-01"})
    assert "7332-01" in job_identity_codes({"job_folder": r"K:\Estimating\Harrods\7332-01"})
