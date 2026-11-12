"""
Mentioned in provenance is not the same as added to a number.

Job 12392's header graphic was answered by an AI market estimate of GBP 35.62. The engine
refused it — "KEPT OFF the price column", "line will be GBP 0" — and wrote nothing into the
money. price_not_reproducible blocked the job anyway, for a figure the sheet had deliberately
declined to use.

The check was not wrong and neither was stamp_affects_total, which already distinguishes a
price that was FOUND from one that reached the TOTAL. It can only read what somebody wrote,
and it falls back to `applied`, which is true of any price that was found. The branch that
withheld the price never recorded that it had.

THE GUARD THIS PROTECTS MUST SURVIVE. On 11350 an AI estimate of GBP 86.04 DID enter the
material total and moved it every run — 97% of the material on that job. That is what this
invariant exists to catch and it is untouched: a price that reached the total is never marked
withheld.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import price_provenance


def _ai_stamp(applied=True):
    return {"schema": price_provenance.PRICE_SOURCE_SCHEMA,
            "source_name": "llm_market_estimate", "source_class": "ai_estimate",
            "unit_price_gbp": 35.62, "applied": applied}


def _part(**extra):
    part = {"part_number": "12392-02-17G", "description": "HEADER GRAPHIC",
            "price_source": _ai_stamp()}
    part.update(extra)
    return part


def test_the_defect_reproduces_before_the_writer_speaks():
    """A found-but-refused price reads as money in the total, because `applied` is all the
    check has to fall back on."""
    assert price_provenance.stamp_affects_total(_part()["price_source"]) is True


def test_withholding_is_recorded_where_a_checker_can_read_it():
    part = _part()
    assert price_provenance.mark_withheld(part) == 1
    assert price_provenance.stamp_affects_total(part["price_source"]) is False
    assert part["price_source"]["withheld_reason"]


def test_an_applied_ai_price_is_never_marked_and_still_blocks():
    """THE 11350 CASE. GBP 86.04 entered the material total and moved it every run. Nothing
    here touches a price that reached the total — mark_withheld is called only by the branch
    that refuses to write one."""
    applied = {"parts": [_part()]}
    stamps = [b for _p, b in price_provenance.iter_price_stamps(applied)]
    assert stamps and all(price_provenance.stamp_affects_total(b) for b in stamps)
    assert all(price_provenance.stamp_is_ai_estimate(b) for b in stamps), \
        "it must still be recognised as generated — only its reach is in question"


def test_marking_is_idempotent_and_reports_what_it_changed():
    part = _part()
    assert price_provenance.mark_withheld(part) == 1
    assert price_provenance.mark_withheld(part) == 0, "already marked; nothing to change"


def test_a_record_with_no_price_is_not_an_error():
    assert price_provenance.mark_withheld({"part_number": "PACKAGING"}) == 0
    assert price_provenance.mark_withheld({}) == 0


def test_every_stamp_under_the_record_is_marked():
    """A part can carry more than one price block — a legacy copy and a canonical one — and
    the invariant walks all of them. Marking one and missing the other is how 12392 reported
    TWO lines for a single withheld graphic."""
    part = _part(canonical_price=_ai_stamp(), nested={"another_price": _ai_stamp()})
    assert price_provenance.mark_withheld(part) == 3
    assert not any(price_provenance.stamp_affects_total(b)
                   for _p, b in price_provenance.iter_price_stamps(part))


def test_the_withholding_branch_calls_it():
    """A helper nothing calls is the defect it was written to fix."""
    import inspect
    import wb_populate
    assert "_pp.mark_withheld(pe)" in inspect.getsource(wb_populate)


def test_a_line_withheld_is_honoured_wherever_its_stamps_live():
    """TWO OFFENDING LINES BECAME ONE, WHICH IS THE SAME DEFECT AT HALF THE VOLUME. A part's
    price stamp is written in more than one place — the costed record and the raw part record
    the geometry passes hold — and marking the object in hand left the twin still reading as
    money. Withholding is a property of the LINE."""
    import invariants
    summary = {
        "estimate_summary": {"part_estimates": [_part()]},   # marked copy
        "parts": [_part()],                                  # the twin nobody marked
        "final_estimate": {"totals": {"unit_gbp": 41.98}},
    }
    price_provenance.mark_withheld(summary["estimate_summary"]["part_estimates"][0])
    assert len(invariants.check_prices_are_reproducible(summary)) == 1, \
        "precondition: the unmarked twin still blocks"

    summary["withheld_price_lines"] = ["12392-02-17G"]
    assert invariants.check_prices_are_reproducible(summary) == []


def test_the_declaration_cannot_silence_a_price_that_reached_the_total():
    """Only the branch that writes GBP 0.00 onto the sheet adds a code, and it adds the code
    it refused. A DIFFERENT part's applied AI price is untouched — this is not a mute button."""
    import invariants
    other = _part()
    other["part_number"] = "11350-01-02 MIR"
    summary = {"estimate_summary": {"part_estimates": [other]},
               "withheld_price_lines": ["12392-02-17G"],
               "final_estimate": {"totals": {"unit_gbp": 86.04}}}
    found = invariants.check_prices_are_reproducible(summary)
    assert len(found) == 1 and found[0]["severity"] == invariants.BLOCKING


def test_the_withholding_branch_declares_the_line():
    import inspect
    import wb_populate
    assert 'summary.setdefault("withheld_price_lines", [])' in inspect.getsource(wb_populate)
