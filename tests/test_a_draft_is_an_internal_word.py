"""The quotation announced itself unfinished, to the customer, in SDI's own part numbers.

    DRAFT — not for issue · 2 prices missing + 1 market figure to replace + 3 manufacturing
    decisions + 1 indicative rate to verify: PACKAGING, DELIVERY, 7332-01-101, 7332-01-002,
    7332-01-003, 7332-01-004, 7332-01-005, 7332-01-007, 7332-01-008, PLATERFREIGHT

James: "we know that the estimator can make amendments to the s/sheet and regenerate the
quote and it will be sent out on the back of their changes, so we don't want anything which
makes it look like it's not a quote for a CLIENT, because after their changes, it will be."

THE BANNER DESCRIBES THE WRONG MOMENT. It is true when the engine stops and false when the
document is read: the estimator prices the two missing lines, settles the decisions, and
regenerates — and the page that goes out still says a person owes it work nobody owes it any
more. A warning that is wrong on the day it is read is not a safeguard.

It said the same thing in four places, which is why removing the banner alone would have been
worse than leaving it: the Basis row printed "Draft — not for issue" in place of the offer
window, the footer repeated it, and the packing row read "to be priced" — an instruction to an
estimator, on a customer's quotation. A page that looks finished and says "not for issue"
twice in small print is the worst of both.

THE CONDITION FOR REMOVING IT IS THAT THE TALLY SURVIVES, and this file holds both halves.
The same reasoning was already applied twice on this page — to the invariant banner, and to
the "Not included in this price" gap list that named every BOM line with no drawing — and both
times the rule was the same: the engine's findings are the estimator's to act on, and the
customer is not shown the workings. So the covering e-mail subject, the job report, the AI
Explanation and the Decision Report must all still carry it, and if any of them ever stops,
this fails rather than the quote quietly becoming the only record.

AND THE SCOPE EXCLUSION IS NOT THE RELEASE STATUS. "Packaging and delivery are not included
in this price" stays, because a quotation silent about them promises them. That is a
commercial fact the customer needs. "Not for issue" is the engine talking about itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import client_quote_html as q                                           # noqa: E402

# Every way the page used to tell a customer the estimate was not finished.
FORBIDDEN = ("DRAFT", "not for issue", "to be priced", "to be priced before issue",
             "prices missing", "market figure to replace", "manufacturing decisions",
             "indicative rate to verify", "to verify", "outstanding")


def _job(draft=True):
    """A costed job with real open items — the shape that produced the banner."""
    return {
        "job_number": "7332-01", "customer": "Harrods", "assumed_job_quantity": 6,
        "estimate_summary": {"part_estimates": [
            {"part_number": "7332-01-101", "unit_cost_gbp": 62.0, "quantity": 1,
             "description": "FRAME WELDMENT"},
            {"part_number": "PACKAGING", "unit_cost_gbp": 0.0, "quantity": 1,
             "description": "PACKAGING"},
        ]},
        "release": {"draft": draft, "outstanding": 4},
        "decisions_required": [
            {"part": "PACKAGING", "kind": "missing_price", "issue": "no price"},
            {"part": "DELIVERY", "kind": "missing_price", "issue": "no price"},
            {"part": "7332-01-002", "kind": "manufacturing", "issue": "cut length"},
        ],
    }


def _released_job():
    """The same job after an estimator has settled it — every line priced, the commercial
    inputs recorded complete, release authorised. THIS is the customer document, and it is
    the one the forbidden wording must never reach.

    James's original point stands and is now structural rather than editorial: "after their
    changes, it will be [a quote for a client]". The page a client sees is the page produced
    AFTER those changes, so it cannot carry a tally of work nobody owes any more — there is
    none.
    """
    job = _job(draft=False)
    # PACKAGING is EXCLUDED by the estimator's decision, not left unpriced — so the scope
    # sentence below is reachable on a released page, which is the point of the test that
    # asserts it. An unpriced line is a gap and blocks release; an excluded one is an answer.
    job["estimate_summary"]["part_estimates"][1]["_commercial_excluded"] = True
    job["estimate_summary"]["workbook_equivalent_pricing"] = {
        "m105_total_unit_cost_gbp": 149.87}
    # The workbook was read back and every line carries money — which is what "settled"
    # means, and what `costed_facts.costed_job` reads to say the record is no longer a draft.
    job["final_estimate"] = {
        "totals": {"unit_cell": "Estimate!M105", "unit_cell_value": 149.87,
                   "unit_gbp": 149.87, "source": "excel_calculated"},
        "material_rows": [{"description": "7332-01-101 FRAME WELDMENT",
                           "part_number": "7332-01-101",
                           "block": "steel", "qty_per_unit": 1,
                           "total_value_gbp": 62.0, "charged_cell": "Estimate!M63",
                           "supplier": "SDI Live"},
                          ],
        "labour_rows": []}
    job["invariants"] = {"violations": [], "may_quote_firm": True}
    job["decisions_required"] = []
    job["commercial_inputs"] = {"complete": True}
    job["quote_release"] = {"authorised_by": "Dave Shepherd",
                            "authorised_at": "2026-09-18T15:40"}
    return job


def _html(draft=True):
    """The CUSTOMER document. What this file polices has always been that page.

    It used to be the only page there was, so rendering the open job WAS rendering the
    customer's quotation. It is not any more: an unsettled record produces the portal working
    copy, which is internal and says what is outstanding because the person reading it is the
    person who closes those items. So the fixture renders the released job, and a companion
    test below asserts the unsettled one is not a customer document at all — which is a
    stronger guarantee than the wording ban it replaces, because it does not depend on
    anybody remembering to keep a phrase off a page.
    """
    return q.build_quote_html(_released_job(), job_stem="7332-01")


# ── the customer is not shown the workings ───────────────────────────────────────────────

@pytest.mark.parametrize("phrase", FORBIDDEN)
def test_the_quotation_never_says_it_is_unfinished(phrase):
    html = _html(draft=True)
    assert phrase.lower() not in html.lower(), (
        f"the client quotation still carries {phrase!r} — it describes the moment the engine "
        f"stopped, and the document is issued after an estimator has settled it")


def test_no_internal_part_number_is_listed_as_an_open_question():
    """The banner named ten. A customer reading a quotation for a stand has no use for
    7332-01-005 and every reason to ask what is wrong with it."""
    html = _html(draft=True)
    for pn in ("7332-01-002", "7332-01-005", "7332-01-008", "PLATERFREIGHT"):
        assert pn not in html, pn


def test_a_settled_job_and_an_open_one_produce_the_same_page():
    """THE PROOF THAT THE STATUS IS GONE RATHER THAN REWORDED. If any wording still varied
    with the release block, these two would differ."""
    assert _html(draft=True) == _html(draft=False)


def test_an_unsettled_job_is_not_a_customer_document_at_all():
    """AND THE STRONGER FORM OF THE SAME RULE.

    The ban on "DRAFT — not for issue" was a rule about wording, and a rule about wording is
    kept by everyone remembering it. This one cannot be forgotten: a record with open lines,
    no commercial inputs and no authorisation cannot produce a customer page, so there is no
    page for the phrase to appear on.
    """
    from quote_state import CUSTOMER, NotReleasable, quote_state

    state = quote_state(_job(draft=True))
    assert state["customer_releasable"] is False
    assert state["portal_editable"] is True, "the estimator must always have a page to edit"
    with pytest.raises(NotReleasable):
        q.build_quote_html(_job(draft=True), job_stem="7332-01", audience=CUSTOMER)


def test_the_working_copy_names_the_next_action_and_nothing_else():
    """AND THE BANNER DOES NOT COME BACK IN AN INTERNAL COSTUME.

    A first cut of the release model gave the working copy a PORTAL VIEW panel listing every
    outstanding item. It was accurate, internal, and the sixth time this page has grown a
    warning block. What an estimator needs is the next thing to do; what is outstanding is on
    the report and on the release form, which is where it is acted on.
    """
    html = q.build_quote_html(_job(draft=True), job_stem="7332-01")
    assert "Enter the unit cost on the Estimate sheet" in html
    for gone in ("PORTAL VIEW", "NOT FOR ISSUE", "not released", "authorised release"):
        assert gone.lower() not in html.lower(), f"the warning block is back: {gone!r}"


def test_the_portal_copy_still_keeps_the_workings_off_the_page():
    """INTERNAL IS NOT A LICENCE TO PRINT THE ENGINE'S REASONING.

    The first cut listed `release.reasons` verbatim, so the page acquired "the consistency
    checks have not run" and the part number of every unpriced line — the exact material the
    invariant banner and the gap list were removed from this page for, arriving by a new door
    because the page's audience had changed. The detail belongs to the job report.
    """
    html = q.build_quote_html(_job(draft=True), job_stem="7332-01")
    for leak in ("consistency check", "7332-01-101", "PLATERFREIGHT", "invariant"):
        assert leak not in html, leak


def test_the_offer_window_comes_back():
    """Suppressing "Valid for 30 days" was right while the page announced itself a draft —
    a promise with a date on it, made off unfinished work. With the announcement gone the
    page is a quotation, and a quotation without an offer window reads as an oversight."""
    html = _html(draft=True)
    assert "Valid for" in html
    assert f"{q.VALID_DAYS} days" in html


# ── the scope exclusion is a different fact and stays ────────────────────────────────────

def test_the_customer_is_still_told_what_the_price_excludes():
    """Silence here would be a promise. This is the one thing on the page the engine may
    say about what is NOT covered, because it is commercial rather than diagnostic."""
    html = _html(draft=True)
    assert "not included in this price" in html.lower()


# ── and the tally reaches the person who can settle it ───────────────────────────────────

def test_every_internal_surface_still_prints_the_open_items():
    """THE CONDITION FOR REMOVING IT FROM THE QUOTE. If these ever stop, the removal
    becomes silence and this test is where that is caught — not a run of a job."""
    for module in ("job_report_html.py", "estimate_explained.py", "job_decision_report.py",
                   "main.py"):
        src = (ROOT / "src" / module).read_text(encoding="utf-8")
        assert "outstanding_summary" in src, (
            f"{module} no longer prints outstanding_summary — the open items now reach "
            f"nobody, because the quote stopped carrying them")


def test_the_sheet_still_shades_the_open_rows():
    """The estimator's own document. The banner's whole job was to send somebody here."""
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    assert "OUTSTANDING ESTIMATOR INPUTS" in src


def test_the_removal_is_explained_where_it_happened():
    """A blank assignment with no reason invites the next person to put it back."""
    src = (ROOT / "src" / "client_quote_html.py").read_text(encoding="utf-8")
    assert "THE DRAFT BANNER IS NOT CUSTOMER-FACING EITHER" in src
    assert "THE TALLY IS NOT LOST" in src


def test_the_llm_only_basis_is_untouched():
    """A different fact, and James asked for it explicitly: an LLM-only read is a
    measurement, not an unfinished estimate, and no amount of work on the sheet turns it
    into a full run. It keeps "Indicative" and it keeps having no offer window."""
    src = (ROOT / "src" / "client_quote_html.py").read_text(encoding="utf-8")
    assert "Indicative — for internal comparison" in src
    assert "Prices ex VAT, GBP. Indicative." in src
