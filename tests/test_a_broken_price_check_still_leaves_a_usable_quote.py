"""When the traceability check itself breaks, the price goes and the document stays.

James Gray, 18 September 2026:

    "Draft quote may always be generated in the portal."
    "That is fail-closed for price, but it violates your rule that a draft quote must still be
     generated in the portal for estimator editing."

THREE SHAPES WERE TRIED AND TWO OF THEM WERE WRONG.

    except Exception: pass          leaves the old unit price LIVE when the guard breaks —
                                    the one failure mode a guard exists for, on the page a
                                    customer keeps.
    no handling at all              a raising check takes the whole quotation down, so an
                                    estimator has no draft to work from and no way to see
                                    what the pack priced.
    refuse the figure, keep the     the price disappears, the specification, the included
    page, and say so                operations and the scope stay, and the box says which
                                    state it is in.

So this test breaks `publishable_total` on purpose and asserts all three of the things the
third shape has to do at once: the HTML still comes out, no money reaches it, and the page
says it is pending rather than leaving a blank somebody fills in from memory.

It renders the DOCUMENT. Source-grepping `client_quote_html.py` for a try/except would pass
against a file whose handler assigns a variable nothing prints — which is precisely the state
this file was written to catch.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import client_quote_html  # noqa: E402
from client_quote_html import build_quote_html  # noqa: E402

_UNIT = 149.87
_QTY = 20


def _summary():
    """A job whose total IS traceable — so a broken check is the only thing that can stop it."""
    return {
        "manufacturing_writeup": {"parts": [{"part_number": "401912-02-001", "quantity": 1}]},
        "final_estimate": {"totals": {"unit_cell": "Estimate!M105",
                                      "unit_cell_value": _UNIT}},
        "estimate_summary": {
            "workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": _UNIT},
            "estimate_workbook_inputs": {"assumed_job_quantity": _QTY},
            "part_estimates": [{"part_number": "401912-02-001", "quantity": 1,
                                "material": "Mild steel", "finish": "Powder coated"}],
        },
    }


def _money_in(html: str):
    """Every currency figure on the page, as floats, so nothing is missed by wording."""
    return [float(m.replace(",", ""))
            for m in re.findall(r"£\s*([0-9][0-9,]*\.?[0-9]*)", html)]


class _Exploded(RuntimeError):
    pass


def _raise(*_a, **_k):
    raise _Exploded("the traceability check exploded")


# ── the baseline: with the check working, this job DOES carry a price ────────────────
def test_the_same_job_prices_normally_when_the_check_works():
    html = build_quote_html(_summary(), job_stem="401912-02")
    figures = _money_in(html)
    assert figures, "the fixture must price, or the failure case proves nothing"
    assert max(figures) >= _UNIT, figures


# ── and when the check itself raises ────────────────────────────────────────────────
def _broken_quote(monkeypatch):
    monkeypatch.setattr(client_quote_html, "publishable_total", _raise)
    return build_quote_html(_summary(), job_stem="401912-02")


def test_the_quote_is_still_generated(monkeypatch):
    html = _broken_quote(monkeypatch)
    assert html and "<html" in html.lower()
    # A usable portal document, not a stub: the job is still identified and the working
    # an estimator edits around is still on the page.
    assert "401912-02" in html
    assert "What's included" in html


def test_no_unit_or_customer_price_reaches_the_page(monkeypatch):
    html = _broken_quote(monkeypatch)
    figures = _money_in(html)
    assert not figures, f"a broken check must not leave money on the quote: {figures}"
    # And specifically neither the cost nor anything marked up from it.
    assert "149.87" not in html
    assert "%.2f" % (_UNIT * client_quote_html.MARKUP_FACTOR) not in html
    assert "%.2f" % (_UNIT * client_quote_html.MARKUP_FACTOR * _QTY) not in html


def test_the_page_says_it_is_pending_traceability(monkeypatch):
    html = _broken_quote(monkeypatch)
    assert "PRICE PENDING" in html
    # Not a blank waiting for a number: the caption where the figure was says what it is.
    assert "awaiting a traceable price" in html


def test_the_engines_own_reason_stays_off_the_customers_page(monkeypatch):
    """The reason is the estimator's, not the customer's.

    The first cut printed `publishable_total`'s `why` verbatim in the pending note — which in
    the disagreement case reads "the proposed total (£149.87) does not match what
    Estimate!M105 holds (£321.88)". Two figures neither of which may be published, a cell
    reference into our own spreadsheet, and the workings of an internal disagreement, on the
    one document that leaves the building.
    """
    html = _broken_quote(monkeypatch)
    assert "traceable" in html.lower(), "the page must still read as pending traceability"
    for leak in ("Estimate!M", "publishable_total", "_Exploded", "exploded", "Traceback"):
        assert leak not in html, f"the quotation carries an engine internal: {leak}"
    # And it does not describe itself with the internal word for an unfinished document.
    assert "draft" not in html.lower()
