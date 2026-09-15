"""Three ways of describing a £250 brass plate, all of them wrong on the same book.

7332-01's 08:36 sheet charged Brass — Harrods 01 correctly and then said:

    finish headline        "Diamond polished"        — the plating paid for and unnamed
    plated members         "7332-01-008"             — one panel, not the welded frame
    PLATERFREIGHT bucket   "market figure to replace" — it is the transport department's

None of the three moves a number. All three are what an estimator checks the number
AGAINST, which is the only reason the number is worth having.

THE FINISH HEADLINE is the same defect twice. The docstring on costed_finish_label already
records it happening once — a stand with a polished lens AND plating described as "Diamond
polished" alone — and the fix then was to stop returning on the first match. It recurred
because the plating RECOGNISER knew one spelling: `"plating" in cost_method`, true of every
method that existed when it was written, false of the three the line has learned since
(named spec, estimator-stated, inherited). A line is a plating line because of what it IS.

And it names WHICH plate. "Plated" is equally true of £15.83 of trade zinc and a £250
decorative brass, and on a quote those are not the same sentence.

THE MEMBER LIST is right for the wrong question. Excluding a RAW-stated member exists
because the MASS decides the money on the £/kg card. £250 is per stand: the mass is not an
input, so the exclusion changes no figure and leaves the audit list claiming the plater is
quoted for one back panel when what goes in the tank is the frame.

THE FREIGHT BUCKET fell through a structural gap, not a textual one. The commercial-line
branch only recognises a commercial line with NO money, and this is the first one that
carries some — so it reached the AI/market catch, and the headline asked an estimator to
replace a market figure his own transport department had given him.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import costed_facts as cf                                               # noqa: E402
from estimator import apply_subcontract_plating                         # noqa: E402


def _summary(desc, money=250.0, **over):
    row = {"part_number": "7332-01-101-PLATE", "unit_cost_gbp": money,
           "_plating_placeholder": True, "description": desc}
    row.update(over)
    return {"estimate_summary": {"part_estimates": [row]}}


# ── the headline names the plate, and which plate ────────────────────────────────────────

def test_an_inherited_brass_spec_is_named_on_the_quote():
    s = _summary("7332-01-101 plating — Brass — Harrods 01, INHERITED from 7332-01",
                 cost_source="inherited_estimator_decision")
    assert cf._subcontract_plate_label(s) == "Brass — Harrods 01"
    assert cf.costed_finish_label(s) == "Brass — Harrods 01"


def test_an_estimator_stated_spec_is_named_too():
    s = _summary("7332-01-101 plating — Brass — Harrods 01, Howard Thurley's stated price",
                 cost_source="estimator_stated_price")
    assert cf._subcontract_plate_label(s) == "Brass — Harrods 01"


def test_the_specs_own_em_dash_does_not_truncate_it():
    """"Brass — Harrods 01" contains the very character that separates it from what follows,
    so a capture that stops at the first dash reports "Brass"."""
    s = _summary("7332-01-101 plating — Brass — Harrods 01, INHERITED from 7332-01")
    assert cf._subcontract_plate_label(s) == "Brass — Harrods 01"


def test_a_zinc_card_line_is_still_just_plated():
    """The card names no spec, so neither does the quote — "Plated" is all that is true."""
    s = _summary("7332-01-101 plating — INDICATIVE zinc/passivate, verify against plater quote",
                 money=15.83, cost_source="subcontract_plating_indicative")
    assert cf._subcontract_plate_label(s) == "Plated"


def test_a_blocked_line_names_no_finish_at_all():
    """£0 and unidentified. Promising a finish the sheet does not charge for is the rule
    this whole function exists to keep."""
    s = _summary("7332-01-101 plating — SPEC NOT IDENTIFIED: the drawing names a plate",
                 money=0.0)
    assert cf._subcontract_plate_label(s) == ""


def test_a_job_with_no_plating_is_untouched():
    s = {"estimate_summary": {"part_estimates": [
        {"part_number": "12349-02-69-04M", "unit_cost_gbp": 2.30, "description": "LID"}]}}
    assert cf._subcontract_plate_label(s) == ""


def test_the_line_is_recognised_by_what_it_is_not_by_a_word():
    """The three newer cost methods contain no "plating" anywhere."""
    for method in ("inherited_estimator_decision", "estimator_stated_price",
                   "subcontract_plating_named_spec"):
        row = {"part_number": "X-PLATE", "unit_cost_gbp": 250.0, "cost_source": method,
               "_plating_placeholder": True, "description": "X plating — Brass, stated"}
        assert cf._plating_row_is_costed(row), method


# ── the member list is the whole weldment when the price is per stand ────────────────────

def _plating_job(summary, finish="PLATED"):
    parts = [{"part_number": "7332-01-101", "description": "FRAME WELDMENT",
              "normalized_finish": finish, "is_assembly_parent": True, "quantity": 1,
              "material_estimate": {"unit_material_mass_kg": 0.9}},
             {"part_number": "7332-01-008", "normalized_finish": "PLATED", "quantity": 1,
              "material_estimate": {"unit_material_mass_kg": 0.4}},
             {"part_number": "7332-01-001", "normalized_finish": "RAW", "quantity": 1,
              "material_estimate": {"unit_material_mass_kg": 1.2}},
             {"part_number": "7332-01-101-PLATE", "_plating_placeholder": True,
              "_plating_weldment": "7332-01-101",
              "_plating_members": ["7332-01-008", "7332-01-001"], "quantity": 1,
              "description": "plating"}]
    apply_subcontract_plating(parts, summary, 6, parts)
    return parts[-1]


def test_a_quoted_price_lists_every_member():
    line = _plating_job({"customer": "Harrods"})
    assert line["unit_cost_gbp"] == 250.00
    assert "7332-01-001" in line["description"] and "7332-01-008" in line["description"]
    assert "no member is excluded" in line["description"]


def test_it_says_why_no_member_is_excluded():
    line = _plating_job({"customer": "Harrods"})
    assert "the mass is not an input" in line["description"]


def test_the_mass_card_still_excludes_what_it_must():
    """On £/kg the exclusion is load-bearing: a RAW member swept into the weight is money
    nobody agreed. That branch is untouched."""
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert "excluded, own detail differs" in src
    assert "WHEN THE PRICE IS PER STAND, THE MEMBER LIST IS THE WHOLE WELDMENT" in src


# ── and a transport figure is not a market lookup ────────────────────────────────────────

def test_the_plater_freight_is_an_indicative_house_rate_not_a_market_one():
    origin = cf._price_origin(
        {"part_number": "PLATERFREIGHT", "cost_source": "plater_freight_stated",
         "material_estimate": {"cost_method": "plater_freight_stated"}},
        kind="commercial", block=None, charged_unit=20.0, engine_unit=20.0,
        sheet_row=21, cross_ref=False, row_text="")
    assert origin["firmness"] == cf.INDICATIVE_HOUSE
    assert origin["class"] == "plater_freight"
    assert "transport department" in origin["label"].lower()


def test_it_is_advisory_rather_than_blocking():
    """"Replace this market figure" is an instruction nobody can carry out — there is no
    supplier to replace the transport department with. Verify or accept, like every other
    house rate."""
    assert cf.INDICATIVE_HOUSE != cf.INDICATIVE_MARKET


def test_a_real_market_line_is_still_a_market_line():
    origin = cf._price_origin(
        {"part_number": "P/P", "cost_source": "market_ai_indicative",
         "material_estimate": {"cost_method": "market_ai_indicative"}},
        kind="bought_in", block=None, charged_unit=0.35, engine_unit=0.35,
        sheet_row=22, cross_ref=False, row_text="")
    assert origin["firmness"] == cf.INDICATIVE_MARKET
