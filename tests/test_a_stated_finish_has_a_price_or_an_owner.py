"""A finish the drawing states is either priced or explicitly somebody's to price.

POWDER WAS THE ONLY FINISH THIS ENGINE COULD COST. Right for steel, wrong for everything else,
and invisible because both halves looked correct on their own: the non-metal rule correctly
refuses to powder-coat a plastic, and the route correctly contains no powder operation — so
nothing was flagged and the finish was silently free.

11650-04's side panels state `1/2 INCH REEDED VINYL + UV OR CLEAR VINYL`. The engine read it,
printed it as an observation, and costed laser, manual labour and assembly. No vinyl operation,
no rate, no line. The vinyl was free — on a panel where it is most of what the customer is
buying.

THE ANSWER IS NOT AN INVENTED RATE. It is a line that names the work, the area and the owner.
A finish costed at zero and a finish nobody has priced read identically on a sheet, and only
one of them is an under-charge anybody can catch — which is the whole difference between a
flag Tim can act on and a research project.

AND IT CLOSES IN ONE PLACE. A £/m² in config, keyed on the finish code, prices that finish on
every job that ever states it. No enquiry should need code for this.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import applied_finish as af  # noqa: E402
import config  # noqa: E402

BOOTS = "1/2 INCH REEDED VINYL + UV OR CLEAR VINYL"


@pytest.fixture()
def no_rates(monkeypatch):
    monkeypatch.setattr(config, "APPLIED_FINISH_RATES_GBP_PER_M2", {}, raising=False)


@pytest.fixture()
def with_vinyl_rate(monkeypatch):
    monkeypatch.setattr(config, "APPLIED_FINISH_RATES_GBP_PER_M2",
                        {"VINYL_REEDED": 14.50}, raising=False)


def _panel(finish=BOOTS, **kw):
    p = {"normalized_finish": finish}
    p.update(kw)
    return af.applied_finish_estimate(p, 1250.0, 525.0, 4)


# ── the vocabulary ───────────────────────────────────────────────────────────────────

def test_the_finish_this_job_states_is_recognised():
    assert af.finish_codes(BOOTS) == ["VINYL_REEDED"]


@pytest.mark.parametrize("text,expect", [
    ("VINYL WRAP TO FRONT FACE", ["VINYL"]),
    ("SCREEN PRINTED 2 COLOUR", ["PRINT"]),
    ("GLOSS LAMINATE", ["LAMINATE"]),
    ("SPRAY PAINT RAL 9010", ["PAINT"]),
    ("UV HARDCOAT", ["UV_COAT"]),
    ("OAK VENEER", ["VENEER"]),
])
def test_the_finishes_a_shopfitter_actually_applies_are_recognised(text, expect):
    assert af.finish_codes(text) == expect


def test_a_reeded_vinyl_is_not_also_charged_as_a_plain_vinyl():
    """It is one film. Naming both codes would put the same work on the sheet twice."""
    assert "VINYL" not in af.finish_codes(BOOTS)


def test_a_drawing_naming_two_finishes_gets_two_lines():
    """Costing only the first would charge for half the work the sheet asks for."""
    assert af.finish_codes("VINYL WRAP THEN UV VARNISH") == ["VINYL", "UV_COAT"]


def test_a_part_with_no_stated_finish_gets_no_line_at_all():
    """The ordinary case. This must add nothing to a job that does not ask for it."""
    assert af.applied_finish_estimate({}, 1250.0, 525.0, 4) is None
    assert af.applied_finish_estimate({"normalized_finish": "   "}, 1250.0, 525.0, 4) is None


def test_powder_is_not_re_costed_here():
    """It has its own workbook formula — by mass, both faces, oven. Two answers to one
    question is the defect family this codebase keeps finding."""
    assert af.finish_codes("POWDER COAT RAL 7016") == []


# ── no rate: an owned gap, never a zero ──────────────────────────────────────────────

def test_an_unpriced_finish_is_not_costed_at_nothing(no_rates):
    """THE DEFECT, STATED AS THE TEST. Zero and unpriced look identical on a sheet."""
    line = _panel()["finishes"][0]
    assert line["unit_finish_cost_gbp"] is None
    assert line["extended_finish_cost_gbp"] is None
    assert line["estimator_input_required"] is True


def test_the_gap_names_its_reason_so_it_can_be_sorted_not_read(no_rates):
    """Tim needs "you must decide this", not the thirteenth line of a warning list."""
    assert _panel()["finishes"][0]["reason"] == "no_rate_for_finish"
    assert _panel()["unpriced_finishes"] == ["VINYL_REEDED"]


def test_the_gap_carries_the_area_the_estimator_has_to_price(no_rates):
    """A finish code with no quantity beside it is a question, not a task."""
    line = _panel()["finishes"][0]
    assert line["area_m2_per_part"] == pytest.approx(1.250 * 0.525, abs=1e-6)
    assert "0.656" in line["note"] and "4 off" in line["note"]


def test_the_gap_says_where_to_close_it_and_that_it_closes_once(no_rates):
    """The difference between a system that gets quieter and one that needs an engineer per
    enquiry is whether the fix is a config line or a code change."""
    note = _panel()["finishes"][0]["note"]
    assert "APPLIED_FINISH_RATES_GBP_PER_M2" in note
    assert "every job stating this finish" in note


def test_the_drawings_own_words_are_kept_for_the_estimator(no_rates):
    """`+ UV OR CLEAR VINYL` is ambiguous — one film or two, and only a person can say. The
    engine records what was written rather than resolving it by pattern."""
    assert _panel()["finishes"][0]["stated_as"] == BOOTS


def test_an_unpriced_finish_adds_nothing_to_a_total(no_rates):
    """It must be visible without being money. A gap that quietly inflated the job would be
    worse than the silence it replaces."""
    assert _panel()["extended_finish_cost_gbp"] == 0.0


# ── a rate we hold: firm, reproducible, in the total ─────────────────────────────────

def test_a_rate_in_config_prices_the_finish(with_vinyl_rate):
    line = _panel()["finishes"][0]
    assert line["unit_finish_cost_gbp"] == pytest.approx(1.250 * 0.525 * 14.50, abs=0.01)
    assert line["estimator_input_required"] is False


def test_a_priced_finish_extends_by_quantity(with_vinyl_rate):
    est = _panel()
    assert est["extended_finish_cost_gbp"] == pytest.approx(
        1.250 * 0.525 * 14.50 * 4, abs=0.02)
    assert est["unpriced_finishes"] == []


def test_a_held_rate_is_attributed_and_reproducible(with_vinyl_rate):
    """It is a rate the business entered, so it is repeatable and must say so — that is what
    keeps `price_not_reproducible` off a job priced from it."""
    ps = _panel()["finishes"][0]["price_source"]
    assert ps["source_class"] == "catalogue" and ps["reproducible"] is True


def test_one_face_unless_the_drawing_says_otherwise(with_vinyl_rate):
    """A decorative film goes on the face the customer sees. Assuming two would double the
    money on every panel in the shop on nothing but an assumption."""
    assert _panel()["finishes"][0]["faces"] == 1


def test_a_finish_with_no_blank_is_still_owned_not_priced(with_vinyl_rate):
    """No area means no honest number, and a rate does not change that. The line still exists
    and still has an owner."""
    est = af.applied_finish_estimate({"normalized_finish": BOOTS}, None, None, 1)
    line = est["finishes"][0]
    assert line["estimator_input_required"] is True
    assert line["extended_finish_cost_gbp"] is None
    assert "No blank size" in line["note"]


# ── wired, not merely built ──────────────────────────────────────────────────────────

def test_the_costing_pass_writes_the_finish_onto_the_part(no_rates):
    """BUILT IS NOT WIRED. A finish module nothing calls leaves the vinyl exactly as free as
    it was."""
    import estimator
    part = {"part_number": "11650-04-01A", "normalized_material": "PETG",
            "normalized_thickness_mm": 2.0, "quantity": 4, "normalized_finish": BOOTS,
            "blank_length_mm": 1250.0, "blank_width_mm": 525.0,
            "material_estimate": {}, "manufacturing_interpretation": {}}
    estimator.estimate_part(part)
    est = part.get("applied_finish_estimate")
    assert est, "the costing pass did not record the stated finish"
    assert est["unpriced_finishes"] == ["VINYL_REEDED"]


def test_the_config_seam_exists_and_starts_empty():
    """Empty is an answer, not an oversight — and the guard is that it is a dict keyed on
    finish codes, so the first rate entered is a line rather than a change of shape."""
    rates = getattr(config, "APPLIED_FINISH_RATES_GBP_PER_M2", None)
    assert isinstance(rates, dict)
