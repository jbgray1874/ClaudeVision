"""One line, one price — under every spelling that line answers to.

10975-02's 12:16 book said two contradictory things about the same tape. Section 8:
"No line rests on an AI market indication." Section 3, four paragraphs later: "2 priced
line(s) that reached the total were costed by an AI market estimate rather than a
catalogue: 10975EPDMCLOSEDCELL" — BLOCKING.

Both were reading the same line. The tape is priced by the roll-goods length arithmetic
off SDI Live — 600 mm of a 10,000 mm roll at £4.50, the £0.28 on the sheet — and the
earlier market answer that arithmetic displaced was duly marked withheld on the part
record. But the compiler had merged this line from a second spelling, and the same
displaced price is stamped again under THAT name, where it went on reading as money in
the total.

So the job was blocked for a figure that never reached it, and an estimator reading the
report had to decide which of two sentences about one tape to believe.

WITHHOLDING IS A PROPERTY OF THE LINE, NOT OF THE OBJECT SOMEBODY HAPPENED TO HOLD. The
same lesson the missing-drawing check learned when a folded alias read as an absence, and
the same lesson wb_populate learned when marking one copy left its twin reading as money.

What must NOT change: a market price that genuinely reached the total is still caught,
under whichever of its names it is stamped with. This check is the only thing standing
between an estimate and three different totals on identical inputs.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import invariants                                                     # noqa: E402
import price_provenance as pp                                         # noqa: E402


def _stamp(**over):
    block = {"schema": pp.PRICE_SOURCE_SCHEMA, "source_class": "ai_estimate",
             "source_name": "llm_market", "applied": True}
    block.update(over)
    return block


def _tape_priced_by_the_roll():
    """The tape as the run leaves it: merged from a second spelling, its market answer
    displaced by the roll arithmetic."""
    tape = {"part_number": "10975",
            "description": "EPDM TAPE 25X1MM",
            "evidence": {"raw_aliases": ["10975EPDMCLOSEDCELL"]},
            "material_estimate": {"price_source": _stamp()}}
    pp.mark_withheld(tape, reason="superseded — this line is priced by the roll-goods "
                                  "length arithmetic")
    return tape


def _job(tape, stamped_under):
    """The same displaced price, stamped again under another of the line's names."""
    return {"parts": [tape], "estimate_summary": {"part_estimates": [
        {"matched_part_code": stamped_under,
         "cost_breakdown": {"system_cost": {"applied_to_total": True,
                                            "source": _stamp()}}}]}}


def test_the_displaced_price_names_every_spelling_it_answers_to():
    tape = _tape_priced_by_the_roll()
    names = [n.upper() for n in tape["price_superseded_identities"]]
    assert "10975" in names
    assert "10975EPDMCLOSEDCELL" in names, "the merged spelling is the same line"


def test_the_job_is_not_blocked_for_money_that_never_reached_the_total():
    """THE DEFECT."""
    out = invariants.check_prices_are_reproducible(
        _job(_tape_priced_by_the_roll(), "10975EPDMCLOSEDCELL"))
    assert [v.get("code") for v in out] == [], out


def test_the_line_is_clear_under_its_own_name_too():
    out = invariants.check_prices_are_reproducible(
        _job(_tape_priced_by_the_roll(), "10975"))
    assert [v.get("code") for v in out] == [], out


def test_a_market_price_that_did_reach_the_total_is_still_blocked():
    """THE GUARD THIS PROTECTS. 11350's AI estimate of £86.04 entered the material total
    and moved it every run — that is what this check exists for, and nothing above may
    quieten it."""
    job = {"parts": [{"part_number": "BI-SCREENCABLE"}],
           "estimate_summary": {"part_estimates": [
               {"part_number": "BI-SCREENCABLE",
                "cost_breakdown": {"system_cost": {"applied_to_total": True,
                                                   "source": _stamp()}}}]}}
    out = invariants.check_prices_are_reproducible(job)
    assert [v.get("code") for v in out] == ["price_not_reproducible"], out
    assert out[0]["detail"]["parts"] == ["BI-SCREENCABLE"], out[0]["detail"]


def test_one_lines_displacement_does_not_excuse_another_line():
    """The suppression is per-line and named. A different part's applied market price is
    untouched by the tape having been displaced."""
    job = _job(_tape_priced_by_the_roll(), "10975EPDMCLOSEDCELL")
    job["estimate_summary"]["part_estimates"].append(
        {"part_number": "BI-KNOB",
         "cost_breakdown": {"system_cost": {"applied_to_total": True,
                                            "source": _stamp()}}})
    out = invariants.check_prices_are_reproducible(job)
    assert [v.get("code") for v in out] == ["price_not_reproducible"], out
    assert out[0]["detail"]["parts"] == ["BI-KNOB"], out[0]["detail"]


def test_the_same_code_on_a_second_line_is_still_caught():
    """THE REVIEW'S P1: suppressing by part code alone would hide a live AI price the
    moment any line sharing that code had been displaced. One code can appear on two
    separately costed lines — a length off a roll and a whole unit bought in — and only
    ONE of them was displaced. The other is exactly what this check exists for."""
    tape = _tape_priced_by_the_roll()
    job = _job(tape, "10975EPDMCLOSEDCELL")
    job["estimate_summary"]["part_estimates"].append(
        {"part_number": "10975",          # the SAME code, a different line and price
         "cost_breakdown": {"system_cost": {"applied_to_total": True,
                                            "source": _stamp(unit_price_gbp=13.63)}}})
    out = invariants.check_prices_are_reproducible(job)
    assert [v.get("code") for v in out] == ["price_not_reproducible"], out
    assert out[0]["detail"]["count"] == 1, "the displaced copy stays suppressed"


def test_a_fingerprint_needs_the_source_and_the_figure_to_agree():
    """First argument is the DISPLACED price, second the stamp being judged."""
    from price_provenance import fingerprints_match as _m
    assert _m(["llm_market|ai_estimate", 13.63], ["llm_market|ai_estimate", 13.63])
    assert not _m(["llm_market|ai_estimate", 13.63], ["llm_market|ai_estimate", 4.50])
    assert not _m(["llm_market|ai_estimate", 13.63], ["udef|catalogue", 13.63])
    # Neither states a figure: an LLM stamp genuinely records none, so this is the ordinary
    # case and the source plus the line's name are all the evidence there is.
    assert _m(["llm_market|ai_estimate", None], ["llm_market|ai_estimate", None])
    # The judged stamp states one the displaced price does not. A figure we cannot check
    # off is a figure we report — this is what stops a second line being hidden.
    assert not _m(["llm_market|ai_estimate", None], ["llm_market|ai_estimate", 13.63])
    assert not _m(["", None], ["", None]), "a sourceless stamp matches nothing"


def test_the_fingerprint_reads_the_fields_an_llm_stamp_actually_writes():
    """llm_scan_price writes `source` and `source_type`; the resolver writes `source_name`
    and `source_class`. Reading only one pair gives an empty fingerprint on exactly the
    stamps this was built for, and an empty fingerprint matches nothing."""
    from price_provenance import stamp_fingerprint as _fp
    assert _fp({"source": "llm_drawing_scan", "source_type": "ai_estimate"}) == \
        ["llm_drawing_scan|ai_estimate", None]
    assert _fp({"source_name": "llm_market", "source_class": "ai_estimate",
                "selected": {"price": 4.5}}) == ["llm_market|ai_estimate", 4.5]


def test_an_older_record_without_fingerprints_still_works():
    """Records written before the fingerprint existed carry names only. They keep the
    name-based behaviour rather than losing their suppression altogether."""
    tape = _tape_priced_by_the_roll()
    tape.pop("price_superseded_prints")
    out = invariants.check_prices_are_reproducible(_job(tape, "10975EPDMCLOSEDCELL"))
    assert [v.get("code") for v in out] == [], out


def test_nothing_is_recorded_when_nothing_was_displaced():
    """A part whose stamps were already withheld gains no new claim — the list says what
    this call actually displaced, not what it looked at."""
    part = {"part_number": "X", "material_estimate": {
        "price_source": _stamp(affects_total=False)}}
    assert pp.mark_withheld(part) == 0
    assert "price_superseded_identities" not in part


# ── the alias arrives AFTER the price is displaced ───────────────────────────────────────
#
# THE REASON THIS TOOK THREE BUILDS. mark_withheld records the spellings the record carried
# WHEN ITS PRICE WAS DISPLACED — and on 10975-02 that moment is too early. The roll-goods
# pricer displaces the tape's market answer while the record still knows itself only as
# "10975"; the compiler attaches the merged spelling "10975EPDMCLOSEDCELL" afterwards. So
# every build that "fixed" this went on blocking under a name the withholding never saw.

def _tape_whose_alias_arrives_later():
    tape = {"part_number": "10975",
            "material_estimate": {"price_source": _stamp()}}
    pp.mark_withheld(tape, reason="superseded — priced by the roll-goods arithmetic")
    assert [n.upper() for n in tape["price_superseded_identities"]] == ["10975"], \
        "at withholding time the merged spelling does not exist yet"
    tape["evidence"] = {"raw_aliases": ["10975EPDMCLOSEDCELL"]}     # attached later
    return tape


def test_a_name_attached_after_the_withholding_is_still_honoured():
    """THE DEFECT, in its real shape."""
    out = invariants.check_prices_are_reproducible(
        _job(_tape_whose_alias_arrives_later(), "10975EPDMCLOSEDCELL"))
    assert [v.get("code") for v in out] == [], out


def test_the_closure_does_not_become_a_general_amnesty():
    """Closing over the job's identity graph must not quieten a market price that genuinely
    reached the total, on a line that shares no name with anything displaced."""
    job = _job(_tape_whose_alias_arrives_later(), "10975EPDMCLOSEDCELL")
    job["estimate_summary"]["part_estimates"].append(
        {"part_number": "BI-SCREENCABLE",
         "cost_breakdown": {"system_cost": {"applied_to_total": True,
                                            "source": _stamp()}}})
    out = invariants.check_prices_are_reproducible(job)
    assert [v.get("code") for v in out] == ["price_not_reproducible"], out
    assert out[0]["detail"]["parts"] == ["BI-SCREENCABLE"], out[0]["detail"]


def test_the_fingerprint_still_gates_the_closed_names():
    """The closure widens WHICH NAMES may be skipped; it does not widen which PRICES. A
    second line under a closed-in name, stating its own figure, still blocks."""
    job = _job(_tape_whose_alias_arrives_later(), "10975EPDMCLOSEDCELL")
    job["estimate_summary"]["part_estimates"].append(
        {"part_number": "10975",
         "cost_breakdown": {"system_cost": {"applied_to_total": True,
                                            "source": _stamp(unit_price_gbp=13.63)}}})
    out = invariants.check_prices_are_reproducible(job)
    assert [v.get("code") for v in out] == ["price_not_reproducible"], out
    assert out[0]["detail"]["count"] == 1


# ── what actually priced the line ────────────────────────────────────────────────────────
#
# THE FIX THAT SHOULD HAVE BEEN FIRST. The tape blocked through FOUR builds. Each attempt
# chased where a withheld FLAG lived — set it on the record, record the names it answers to,
# close those names over the job — and each failed the same way, because a flag written in
# one place has to survive to another and on this job it does not.
#
# The flag was never the evidence. The evidence is on the sheet: the line is priced by the
# roll-goods length arithmetic off SDI Live, £0.28, reproducible between runs. A line whose
# applied price came from a reproducible source cannot ALSO be a line costed by an AI market
# estimate — the money that reached the total came from the catalogue, and the market figure
# beside it is a rival that lost.

def _live(**over):
    block = {"schema": pp.PRICE_SOURCE_SCHEMA, "source_name": "udef_sqlserver",
             "source_class": "catalogue", "applied": True, "reproducible": True}
    block.update(over)
    return block


def test_a_line_the_catalogue_priced_is_not_blocked_by_a_rival_market_stamp():
    """THE LIVE SHAPE, with NO withheld flag anywhere — which is the state every previous
    fix assumed could not happen."""
    tape = {"part_number": "10975",
            "evidence": {"raw_aliases": ["10975EPDMCLOSEDCELL"]},
            "material_estimate": {"price_source": _live(unit_price_gbp=0.09)}}
    job = {"parts": [tape], "estimate_summary": {"part_estimates": [
        {"matched_part_code": "10975EPDMCLOSEDCELL",
         "cost_breakdown": {"system_cost": {"applied_to_total": True,
                                            "source": _stamp()}}}]}}
    assert "price_superseded_identities" not in tape, "no flag is set in this shape"
    out = invariants.check_prices_are_reproducible(job)
    assert [v.get("code") for v in out] == [], out


def test_the_clearance_travels_through_the_jobs_own_aliases():
    """The catalogue price is stamped under "10975" and the market one under the merged
    spelling. They are one line, and the job's own records say so."""
    tape = {"part_number": "10975",
            "folded_duplicate_identities": ["10975-02-00"],
            "material_estimate": {"price_source": _live()}}
    job = {"parts": [tape], "estimate_summary": {"part_estimates": [
        {"matched_part_code": "10975-02-00",
         "cost_breakdown": {"system_cost": {"applied_to_total": True,
                                            "source": _stamp()}}}]}}
    assert [v.get("code") for v in invariants.check_prices_are_reproducible(job)] == []


def test_an_ai_price_with_no_catalogue_behind_it_still_blocks():
    """THE GUARD. Only a REPRODUCIBLE APPLIED price on the same line clears it; 11350's
    £86.04 entered a total with nothing behind it and is exactly what this is for."""
    job = {"parts": [{"part_number": "BI-SCREENCABLE"}],
           "estimate_summary": {"part_estimates": [
               {"part_number": "BI-SCREENCABLE",
                "cost_breakdown": {"system_cost": {"applied_to_total": True,
                                                   "source": _stamp()}}}]}}
    out = invariants.check_prices_are_reproducible(job)
    assert [v.get("code") for v in out] == ["price_not_reproducible"], out


def test_a_catalogue_price_on_a_DIFFERENT_line_clears_nothing():
    """The clearance is per line, through that line's own names — not a job-wide amnesty
    because something somewhere was priced properly."""
    job = {"parts": [{"part_number": "10975",
                      "material_estimate": {"price_source": _live()}},
                     {"part_number": "BI-KNOB"}],
           "estimate_summary": {"part_estimates": [
               {"part_number": "BI-KNOB",
                "cost_breakdown": {"system_cost": {"applied_to_total": True,
                                                   "source": _stamp()}}}]}}
    out = invariants.check_prices_are_reproducible(job)
    assert [v.get("code") for v in out] == ["price_not_reproducible"], out
    assert out[0]["detail"]["parts"] == ["BI-KNOB"]
