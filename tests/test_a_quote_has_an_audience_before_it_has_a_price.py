"""The portal always has a page; the customer gets one only when somebody authorised it.

James Gray, 18 September 2026:

    "`PRICE PENDING` on a 'quotation' is still a customer-facing disclaimer. You were clear
     that incomplete estimates must not be released; the portal needs an editable quote view,
     not an incomplete quote for a customer to see."

    "* `portal_editable`: always true once a quote page is generated;
     * `customer_releasable`: true only after traceable price, commercial inputs, and
       estimator authorisation;
     * pending wording/reason: visible only in the internal portal;
     * export, email attachment, print/share: disabled while `customer_releasable` is false."

A DISCLAIMER IS EVIDENCE THAT THE WRONG DOCUMENT IS BEING PRODUCED. Every notice this page
has carried and lost said the same thing in a different voice — the red LLM-only block, the
invariant banner, "DRAFT — not for issue", the gap list, and last of all PRICE PENDING. Each
was removed for the same reason and each came back somewhere else, because the page kept being
asked to apologise for a state it should not have been in. The state is the fixable part: an
incomplete quotation is not a customer document, so it is not produced as one.

WHAT THIS FILE HOLDS, AND WHY EACH HALF MATTERS AS MUCH AS THE OTHER:

    the portal never loses its page       failing closed on the DOCUMENT was the D-144 fault
                                          and it is the easiest one to reintroduce, because
                                          every gate added here makes it a line of code away
    the customer page needs all six       a gate whose default is "release it" is not a gate,
                                          and an absent record is not a satisfied one
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from client_quote_html import build_quote_html                          # noqa: E402
from quote_state import (CUSTOMER, NotReleasable, PORTAL,               # noqa: E402
                         audience_for, quote_state)

_UNIT = 149.87


def _released():
    """A record with all six gates satisfied."""
    return {
        "job_output_stem": "401912-02",
        "estimate_summary": {
            "workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": _UNIT},
            "estimate_workbook_inputs": {"assumed_job_quantity": 20},
            "part_estimates": [{"part_number": "401912-02-001", "quantity": 1,
                                "description": "DIVIDER"}],
        },
        "final_estimate": {
            "totals": {"unit_cell": "Estimate!M105", "unit_cell_value": _UNIT,
                       "unit_gbp": _UNIT, "source": "excel_calculated"},
            "material_rows": [{"description": "401912-02-001 DIVIDER",
                               "part_number": "401912-02-001", "block": "steel",
                               "qty_per_unit": 1, "total_value_gbp": 62.0,
                               "charged_cell": "Estimate!M63", "supplier": "SDI Live"}],
            "labour_rows": [],
        },
        "invariants": {"violations": [], "may_quote_firm": True},
        "commercial_inputs": {"complete": True},
        "quote_release": {"authorised_by": "Dave Shepherd",
                          "authorised_at": "2026-09-18T15:40"},
    }


def _gates(record):
    return {b["gate"] for b in quote_state(record)["blocking"]}


# ── the control: all six satisfied ──────────────────────────────────────────────────

def test_a_settled_and_authorised_record_is_releasable():
    """A gate that refuses everything is not a gate, and this is where that is caught."""
    state = quote_state(_released())
    assert state["customer_releasable"] is True, state["blocking"]
    assert audience_for(_released()) == CUSTOMER


# ── each gate, removed one at a time ────────────────────────────────────────────────

def test_an_untraceable_price_blocks_release():
    record = _released()
    record["final_estimate"]["totals"].pop("unit_cell")
    assert "traceable_price" in _gates(record)


def test_a_cell_that_disagrees_with_the_figure_blocks_release():
    """The worse failure than an unsourced number: a wrong citation stops the checking an
    unsourced one invites."""
    record = _released()
    record["final_estimate"]["totals"]["unit_cell_value"] = 321.88
    assert "traceable_price" in _gates(record)


def test_an_open_line_on_the_record_blocks_release():
    record = _released()
    record["final_estimate"]["material_rows"][0]["total_value_gbp"] = None
    assert "record_outstanding" in _gates(record)


def test_a_record_that_cannot_evidence_a_price_blocks_release():
    record = _released()
    record["money_provenance"] = {"can_evidence_a_price": False, "state": "sum_is_div_zero"}
    assert "money_not_evidenced" in _gates(record)


def test_the_wrong_batch_quantity_blocks_release():
    """Every setup amortisation and per-order division on the sheet is for that batch."""
    record = _released()
    record["requested_order_quantity"] = 50
    record["quantity"] = 1
    assert "wrong_quantity" in _gates(record)


def test_commercial_inputs_must_be_recorded_complete():
    record = _released()
    record.pop("commercial_inputs")
    assert "commercial_inputs" in _gates(record)


def test_named_outstanding_commercial_inputs_are_listed():
    """The estimator's own headings, in their words — the engine does not invent the list."""
    record = _released()
    record["commercial_inputs"] = {"complete": True,
                                   "items": {"margin": 0.25, "delivery": None}}
    state = quote_state(record)
    said = [b["what"] for b in state["blocking"] if b["gate"] == "commercial_inputs"]
    assert said and "delivery" in said[0]
    assert "margin" not in said[0], "a completed input is not outstanding"


def test_authorisation_needs_a_name_and_a_time():
    """An authorisation with nobody's name on it is not one: the point of the record is that
    somebody is answerable for the figure that went out."""
    for release in ({}, {"authorised_by": "Dave Shepherd"}, {"authorised_at": "2026-09-18"}):
        record = _released()
        record["quote_release"] = release
        assert "authorisation" in _gates(record), release


def test_an_empty_record_fails_closed_on_every_gate():
    """Absent is not satisfied. A gate whose default is 'release it' is not a gate."""
    state = quote_state({})
    assert state["customer_releasable"] is False
    assert {"traceable_price", "commercial_inputs", "authorisation"} <= _gates({})


# ── and the half that must never fail closed ────────────────────────────────────────

def test_the_portal_always_has_a_page():
    """THE D-144 LESSON, HELD HERE SO IT IS NOT RELEARNED. Every gate above makes it one line
    of code to take the estimator's page away, and the estimator's page is how the gates get
    closed in the first place."""
    for record in ({}, {"estimate_summary": {}}, _released()):
        assert quote_state(record)["portal_editable"] is True
        html = build_quote_html(record, job_stem="401912-02")
        assert html and "<html" in html.lower()
        assert "Specification" in html, "a stub is not an editable working copy"


def test_asking_for_a_customer_document_you_may_not_have_says_so():
    with pytest.raises(NotReleasable) as exc:
        build_quote_html({}, job_stem="401912-02", audience=CUSTOMER)
    assert "authorised" in str(exc.value), "the refusal must name what is missing"


def test_the_released_record_does_produce_a_customer_document():
    html = build_quote_html(_released(), job_stem="401912-02", audience=CUSTOMER)
    assert "PORTAL VIEW" not in html
    assert "PRICE PENDING" not in html
    assert "£" in html, "a released quotation carries its price"


# ── export, print and share ─────────────────────────────────────────────────────────

def test_the_portal_copy_does_not_print():
    """Print-to-PDF is how an HTML view becomes a document somebody emails, and it is the one
    route no server-side gate can see. It replaces the page rather than watermarking it: a
    watermark still produces a PDF of a quotation, and somebody will crop it."""
    html = build_quote_html({}, job_stem="401912-02")
    assert "working copy" in html
    assert build_quote_html(_released(), job_stem="401912-02").count("working copy") == 0
    # AND IT SAYS NOTHING ABOUT ISSUING. The page is simply not the customer's document yet,
    # so it does not produce one; that is a fact about the file, not a caveat on the print.
    assert "not released for customer issue" not in html


def test_the_portal_copy_is_not_named_like_a_quotation(tmp_path):
    """A file called `401912-02_quote.html` on the share is a quotation as far as anyone
    reading the folder is concerned, and the way an unreleased one goes out is that somebody
    attaches it without opening it."""
    import json
    from pathlib import Path

    from client_quote_html import generate_quote_files

    def _write(record, name):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(record), encoding="utf-8")
        return Path(generate_quote_files(str(p), out_dir=str(tmp_path),
                                         job_stem="401912-02")).name

    assert _write({}, "open") == "401912-02_quote_PORTAL.html"
    assert _write(_released(), "done") == "401912-02_quote.html"


def test_the_email_attaches_the_quote_only_when_it_is_releasable():
    """THE ATTACHMENT HALF, at the one place attachments are chosen.

    It asked `_provisional`, which is a different and looser question — it knows nothing about
    commercial inputs and nothing about anybody authorising anything — so a quote could be
    attached to a note going out while both were still open.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src" / "main.py").read_text(
        encoding="utf-8")
    assert "from quote_state import quote_state" in src
    assert '_k == "quote" and not _releasable' in src
    # Fail closed on the AUDIENCE: a release gate that cannot run has not said yes.
    at = src.index("except Exception as _exc_qs:")
    assert '"customer_releasable": False' in src[at:at + 400]


def test_the_two_audiences_are_the_only_two():
    assert {PORTAL, CUSTOMER} == {"portal", "customer"}
