"""The report printed £102.70 and the quote printed a dash, about the same job.

James Gray, 22 September 2026, on the first Plan A render run: "Quote needs to have a
price — even if a bad one since we know it's only indicative... it keeps being over ridden."

He was right, and the run's own deliverables proved it against themselves. One report, two
answers, twenty lines apart:

    Summary  ·  Unit cost  PENDING — NOT TRACEABLE TO A WORKBOOK CELL
    Q&A      ·  What does a unit cost, and of what?  £102.70 — material £92.78 + labour £0.00

The refusal DISCARDED the figure rather than labelling it. `_price_fact` asked
`publishable_total` whether the number could be traced to a signed-off cell, got "no", and
returned `amount: None` — so every surface downstream, including the estimator's own
_quote_LLM-ONLY.html, had nothing left to show.

WHAT IS AND IS NOT CHANGED. The customer document is untouched and still fails closed: a
released quotation prints a figure only when it traces. What changes is the INTERNAL pages —
_quote_PORTAL.html and _quote_LLM-ONLY.html — whose entire purpose is to show the estimator
what the run produced, and which already declare "Indicative — for internal comparison" in
their own Basis row. A dash there protects nobody; it sends somebody to a second document to
read the number this one is about.

The safety was never the rendered figure. It is the audience: what may reach a customer is
decided by `customer_releasable` and by which file is named, served and attached — none of
which this page's arithmetic can affect.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import client_quote_html                                               # noqa: E402
import quote_state                                                     # noqa: E402
from quote_state import CUSTOMER, PORTAL                               # noqa: E402


def _summary(**over):
    """A run whose workbook holds a total that does not trace — the Plan A render case."""
    s = {
        "job_number": "bdab4adf-3340-40M&S",
        "llm_only": True,
        "estimate_summary": {
            "estimate_workbook_inputs": {"assumed_job_quantity": 1},
            "workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": 102.6994967},
            "part_estimates": [],
        },
        # No final_estimate.totals.unit_cell, so the traceability check refuses.
        "final_estimate": {"totals": {}},
    }
    s.update(over)
    return s


# ── the fact, kept through the refusal ──────────────────────────────────────────────

def test_the_refusal_no_longer_throws_the_figure_away():
    fact = quote_state._price_fact(_summary())
    assert fact["amount"] is None, "it must still refuse to call this a traceable price"
    assert fact["workbook_amount"] == pytest.approx(102.6994967), (
        "the number the workbook holds was discarded with the refusal")


def test_a_traceable_job_is_unaffected():
    """The ordinary path must not change shape: a job that traces still publishes."""
    fact = quote_state._price_fact(_summary(
        final_estimate={"totals": {"unit_cell": "Estimate!M170",
                                   "unit_cell_value": 102.6994967}}))
    assert fact.get("workbook_amount") == pytest.approx(102.6994967)


def test_a_workbook_with_no_figure_at_all_stays_empty():
    """Nothing is invented. No total anywhere means no total on the page."""
    s = _summary()
    s["estimate_summary"]["workbook_equivalent_pricing"] = {}
    assert quote_state._price_fact(s)["workbook_amount"] is None


# ── what each page shows ────────────────────────────────────────────────────────────

def test_the_internal_page_prints_the_workbooks_own_figure():
    html = client_quote_html.build_quote_html(_summary(), job_stem="bdab4adf",
                                              audience=PORTAL)
    assert "&mdash;" not in html.split("Unit price")[-1][:400], (
        "the estimator's own page still shows a dash for a figure the workbook holds")
    assert "indicative, from the workbook" in html
    assert "has not been traced" in html, "it must say what kind of figure this is"


def test_the_figure_shown_is_the_workbooks_marked_up_once():
    """Not re-derived, not re-marked-up twice: the same arithmetic the priced path uses."""
    html = client_quote_html.build_quote_html(_summary(), job_stem="bdab4adf",
                                              audience=PORTAL)
    expected = client_quote_html._money(102.6994967 * client_quote_html.MARKUP_FACTOR)
    assert expected in html, expected


def test_the_customer_document_is_unchanged_and_still_fails_closed():
    """THE HALF THAT MUST NOT MOVE. An untraceable figure never becomes a customer's."""
    from quote_state import NotReleasable
    with pytest.raises(NotReleasable):
        client_quote_html.build_quote_html(_summary(), job_stem="bdab4adf",
                                           audience=CUSTOMER)


def test_a_job_with_no_figure_still_asks_for_one():
    """The estimator action survives for the case it was written for — a workbook with no
    total at all. That is a different sentence from 'indicative', and both are needed."""
    s = _summary()
    s["estimate_summary"]["workbook_equivalent_pricing"] = {}
    html = client_quote_html.build_quote_html(s, job_stem="bdab4adf", audience=PORTAL)
    assert "Enter the unit cost on the Estimate sheet" in html
    assert "indicative, from the workbook" not in html


def test_the_console_calls_the_file_what_it_is(tmp_path, capsys):
    """James Gray, 22 Sep 2026: "The console message also says 'client quote written' even
    when the result is `_quote_PORTAL.html`; it should say 'portal estimate written' unless
    it is actually releasable."

    It is the filename fault in the other place a document is identified without opening it.
    An operator watching the run was told the release gate had passed when it had not.
    """
    import json

    jp = tmp_path / "bdab4adf.json"
    jp.write_text(json.dumps(_summary()), encoding="utf-8")
    out = client_quote_html.generate_quote_files(str(jp), out_dir=str(tmp_path))

    assert Path(out).name.endswith("_quote_PORTAL.html"), out
    printed = capsys.readouterr().out
    assert "portal estimate written" in printed, printed
    assert "client quote written" not in printed, printed

    # The noun and the filename must be decided by the SAME fact, or they drift apart again.
    src = (ROOT / "src" / "client_quote_html.py").read_text(encoding="utf-8")
    assert "'client quote' if _releasable else 'portal estimate'" in src
    assert "if _releasable\n" in src, "the filename no longer branches on the same fact"


def test_the_page_still_carries_no_warning_block():
    """Six removals and counting. The indicative line is ONE sentence naming the next
    action — not a banner, not a catalogue of what is outstanding."""
    html = client_quote_html.build_quote_html(_summary(), job_stem="bdab4adf",
                                              audience=PORTAL)
    for banned in ("DO NOT", "NOT FOR ISSUE", "PRICE PENDING", "PORTAL VIEW",
                   "MEASUREMENT RUN"):
        assert banned not in html.upper(), banned
