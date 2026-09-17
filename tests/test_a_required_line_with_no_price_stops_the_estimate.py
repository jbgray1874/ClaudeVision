r"""A felt pad, a pallet, a clip and a screw each get an allowed price or block release.

James Gray, 18 September 2026:

    "we should have a price for everything.. why would a price be 0 when we have so many
     layers including llm"

    "replacing five old tests with one policy test is not enough on its own. We need
     end-to-end coverage that a felt pad, pallet, clip and screw each either obtain an
     allowed price or block release visibly. Otherwise the code has removed bad prices but
     could still ship missing ones."

That is the whole point of this file, and it is named after the four items.

D-095 withdrew the typed commodity prices, which on its own made the estimate WORSE: the
pad went from a wrong price to no price, and no price reaches the sheet as a blank the
total steps over. A zero is the one answer that is never true — the pad costs something.
An estimate that adds up as though it costs nothing does not look incomplete, it looks
FINISHED, which is worse than looking wrong.

So there are two halves and both are tested here: what counts as an answer, and what
happens to a line that has not got one.

    1  the current SDI Live / UDEF rate
    2  a supplier catalogue or API
    3  an identified current quote for this job
    4  an LLM-supported indicative price, WITH its evidence

Rung 4 is the one that needs guarding. A researched figure and a figure typed into a config
file look identical on a sheet, and the ones just deleted were labelled INDICATIVE too.
What separates them is that a researched price can be checked: it names its source, the
date it was true, what it is per, and the quantity it was found at.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from release_gate import (LLM_INDICATIVE_LABEL, assess_release,  # noqa: E402
                          evidence_gaps, is_evidenced_indicative, line_is_answered)

# The four items James named, as they arrive off a drawing.
_FOUR = [
    {"code": "P/P", "description": "BLACK FELT PAD, SELF-ADHESIVE, 25mm DIA"},
    {"code": "PALLET", "description": "EURO PALLET 1200x1000"},
    {"code": "STD PART", "description": "PERFO PLASTIC LOCKING CLIP"},
    {"code": "FIX019", "description": "3.5x19mm WOOD SCREW"},
]

_GOOD_EVIDENCE = {
    "source": "https://example-supplier.co.uk/felt-pads-25mm (trade list)",
    "as_of": "2026-09-18",
    "unit_basis": "each",
    "quantity_basis": "pack of 100",
}


# ── the four items, unpriced, block release ──────────────────────────────────────────

def test_each_of_the_four_blocks_release_when_nothing_priced_it():
    for item in _FOUR:
        verdict = assess_release([dict(item, price_gbp=None)], job="7332-01")
        assert not verdict["releasable"], item["description"]
        assert verdict["lines_blocking"] == 1


def test_all_four_together_block_and_every_one_is_named():
    verdict = assess_release([dict(i, price_gbp=None) for i in _FOUR], job="7332-01")
    assert not verdict["releasable"]
    assert verdict["lines_blocking"] == 4
    named = " ".join(b["description"] for b in verdict["blocking"])
    for item in _FOUR:
        assert item["description"] in named, item["description"]


def test_a_zero_is_treated_as_no_price_not_as_a_free_part():
    """The exact failure: a withdrawn literal leaves a blank, and a blank totals as nothing.
    'a zero on a quote is a free part'."""
    verdict = assess_release([dict(_FOUR[0], price_gbp=0.0)])
    assert not verdict["releasable"]


def test_the_verdict_tells_the_reader_what_to_do_not_only_what_is_wrong():
    """An incomplete estimate that says only 'incomplete' gets released by somebody in a
    hurry."""
    verdict = assess_release([dict(_FOUR[0], price_gbp=None)])
    assert "NOT RELEASABLE" in verdict["headline"]
    assert "must not be read as a unit price" in verdict["headline"]
    assert "free issue, not required, excluded" in verdict["what_to_do"]


# ── and pass when something priced them ──────────────────────────────────────────────

def test_a_live_or_catalogue_price_answers_the_line():
    """Rungs 1 to 3 need no evidence block: somebody outside this engine stands behind
    them."""
    for rung in ("udef_sqlserver", "sqlserver", "supplier_catalogue", "current_quote"):
        verdict = assess_release([dict(_FOUR[0], price_gbp=0.18, rung=rung)])
        assert verdict["releasable"], rung


def test_all_four_priced_is_releasable():
    verdict = assess_release([dict(i, price_gbp=1.00, rung="udef_sqlserver")
                              for i in _FOUR])
    assert verdict["releasable"]
    assert verdict["lines_blocking"] == 0
    assert "RELEASABLE" in verdict["headline"]


# ── rung 4: the evidence is the admission ticket ─────────────────────────────────────

def test_an_evidenced_llm_price_may_contribute_to_the_total():
    """James: "an LLM indicative price may contribute to the estimate total"."""
    line = dict(_FOUR[0], price_gbp=0.18, rung="llm_indicative", evidence=_GOOD_EVIDENCE)
    assert line_is_answered(line)
    assert assess_release([line])["releasable"]


def test_an_llm_price_without_evidence_does_not():
    """Which is the whole difference between rung 4 and the literals just deleted — those
    were labelled INDICATIVE too."""
    line = dict(_FOUR[0], price_gbp=0.18, rung="llm_indicative", evidence={})
    assert not line_is_answered(line)
    assert not assess_release([line])["releasable"]


def test_each_missing_piece_of_evidence_is_named_in_words():
    """"Not evidenced" tells an estimator nothing they can act on."""
    for field in ("source", "as_of", "unit_basis", "quantity_basis"):
        partial = {k: v for k, v in _GOOD_EVIDENCE.items() if k != field}
        gaps = evidence_gaps(partial)
        assert len(gaps) == 1, field
        assert gaps[0], field
    assert evidence_gaps(_GOOD_EVIDENCE) == []


def test_the_blocking_row_says_which_evidence_was_missing():
    line = dict(_FOUR[0], price_gbp=0.18, rung="llm_indicative",
                evidence={k: v for k, v in _GOOD_EVIDENCE.items() if k != "as_of"})
    verdict = assess_release([line])
    assert not verdict["releasable"]
    assert "date" in verdict["blocking"][0]["why"]


def test_an_indicative_price_of_zero_is_not_a_price_however_well_evidenced():
    assert not is_evidenced_indicative(dict(_GOOD_EVIDENCE, price_gbp=0))


def test_the_label_is_one_spelling_everywhere():
    """Workbook, report and quote. A reader who has seen it once recognises it anywhere."""
    assert LLM_INDICATIVE_LABEL == "LLM indicative - review required"


# ── a zero somebody DECIDED is an answer ─────────────────────────────────────────────

def test_a_ruled_zero_does_not_block():
    """Free-issued, not required, excluded by the estimator, customer-supplied. Each is a
    decision somebody made, which is what separates it from a gap."""
    for reason in ("free_issue", "not_required", "estimator_excluded", "customer_supplied"):
        line = dict(_FOUR[1], price_gbp=0.0, zero_reason=reason)
        assert line_is_answered(line), reason
        assert assess_release([line])["releasable"], reason


def test_a_line_marked_not_required_does_not_block():
    assert assess_release([dict(_FOUR[1], price_gbp=None, required=False)])["releasable"]


def test_an_invented_reason_does_not_excuse_a_blank():
    """The control: any string in zero_reason would make the gate useless."""
    line = dict(_FOUR[1], price_gbp=0.0, zero_reason="probably fine")
    assert not line_is_answered(line)


# ── and the gate is wired where the estimate is judged ───────────────────────────────

def test_the_estimate_carries_the_release_verdict():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimator.py"
           ).read_text(encoding="utf-8")
    assert "from release_gate import assess_release" in src
    assert '"release": _release,' in src


def test_a_gate_that_cannot_run_fails_closed():
    """An estimate nobody checked is not an estimate that passed."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimator.py"
           ).read_text(encoding="utf-8")
    start = src.index("except Exception as _e:", src.index("from release_gate import"))
    block = src[start:start + 700]
    assert '"releasable": False' in block


def test_the_report_leads_with_the_block_rather_than_the_total():
    """James: "It must never show a normal-looking £108.89 unit price that quietly excludes
    four required costs." So the reader meets the verdict before the number."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" /
           "estimate_explained.py").read_text(encoding="utf-8")
    assert "NOT RELEASABLE" in src
    assert src.index("NOT RELEASABLE") < src.index("This job is priced ")


# ── the quote, which is the one document that leaves the building ────────────────────
#
# The 14:06 six-off run went out at £127.86 a unit and £767.17 an order with plating,
# plater freight, packaging and delivery all at £0.00 — four required costs silently
# excluded from a page a customer would have read as a price. It even listed "Tube bending
# and forming" among what was included, on a leg Howard had ruled has no bend.
#
# The gate had already decided. The REPORT consulted it and the QUOTE never asked.

def _blocked_summary():
    return {"data_sufficiency": {"release": {
        "releasable": False,
        "headline": "NOT RELEASABLE - 4 required line(s) carry no price.",
        "what_to_do": "Price each line below.",
        "blocking": [{"code": "PACKAGING", "why": "no price from any rung"},
                     {"code": "DELIVERY", "why": "no price from any rung"}],
    }}}


def test_a_blocked_estimate_cannot_be_rendered_as_a_quotation():
    import client_quote_html
    import pytest as _pytest
    with _pytest.raises(client_quote_html.NotReleasable):
        client_quote_html.build_quote_html(_blocked_summary(), job_stem="7332-01")


def test_the_refusal_names_the_lines_that_block_it():
    import client_quote_html
    try:
        client_quote_html.build_quote_html(_blocked_summary(), job_stem="7332-01")
    except client_quote_html.NotReleasable as exc:
        assert "PACKAGING" in str(exc) and "DELIVERY" in str(exc)
    else:
        raise AssertionError("it rendered")


def test_it_raises_rather_than_rendering_a_page_with_a_banner():
    """A quotation that is wrong about the money has no safe rendering. A banner at the top
    of an otherwise normal-looking page is an invitation to scroll past — and this file
    already records that a previous banner was removed for making the page unreadable."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" /
           "client_quote_html.py").read_text(encoding="utf-8")
    assert "raise NotReleasable(" in src
    assert src.index("raise NotReleasable(") < src.index("job_number, rev, product ="), (
        "the gate must be asked before the page is laid out, not after")


def test_the_refusal_is_written_to_a_file_whose_name_says_so():
    """A run that merely failed to produce a quote looks, from a folder listing, exactly
    like one that has not finished — and last run's quote for the same job is still sitting
    there ready to be attached to an email by mistake."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" /
           "client_quote_html.py").read_text(encoding="utf-8")
    assert "_quote_NOT-RELEASABLE.html" in src
    assert "NO QUOTE WRITTEN" in src


def test_a_releasable_estimate_still_quotes():
    """The control. If it refused everything the gate would be a wall, not a gate."""
    import client_quote_html
    html = client_quote_html.build_quote_html(
        {"data_sufficiency": {"release": {"releasable": True}}}, job_stem="7332-01")
    assert "<" in html and len(html) > 200


def test_the_ai_market_figure_off_the_1406_book_does_not_count_as_answered():
    """The felt pad came back at £0.22 from the pre-existing web/AI rung, labelled "AI
    market indication (RS Components +2 more)". It names something like a source and
    nothing else: no date, no unit basis, no quantity basis. Under the rung-4 standard it
    is not a price, and the estimate blocks rather than totalling it."""
    pad = {"code": "P/P", "description": "BLACK FELT PAD", "price_gbp": 0.22,
           "rung": "web_ai_fallback",
           "evidence": {"source": "RS Components +2 more (AI-indicative - verify)"}}
    assert not line_is_answered(pad)
    assert not assess_release([pad])["releasable"]
