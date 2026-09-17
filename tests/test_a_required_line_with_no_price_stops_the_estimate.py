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


def test_the_list_says_what_would_answer_each_line():
    """Not what the reader should feel about it. James: "we don't need disclaimers.. the
    estimator will make any necessary changes before it gets sent out." The useful half is
    which lines are open and what would close them."""
    verdict = assess_release([dict(_FOUR[0], price_gbp=None)])
    assert verdict["headline"] == "1 required line(s) carry no price"
    assert "SDI Live" in verdict["what_to_do"]
    assert "must not" not in verdict["headline"], (
        "the refusal wording is back — it has been removed twice now")


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
    assert verdict["headline"] == "every required line is priced or ruled"


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


def test_no_deliverable_refuses_to_render_over_an_open_line():
    """THE THING THAT KEEPS COMING BACK. A red block on the quote was removed once for
    making the page unreadable; a hard refusal to render replaced it and was removed again.
    The estimator takes responsibility for what goes out. This test is here so the next
    person — including me — finds out immediately."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "src"
    for name in ("client_quote_html.py", "estimate_explained.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "NOT RELEASABLE" not in src, name
        assert "NotReleasable" not in src, name


# ── and the pad the 14:06 book actually carried ──────────────────────────────────────

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
