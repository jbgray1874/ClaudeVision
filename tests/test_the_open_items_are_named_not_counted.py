"""A count tells an estimator to go and hunt. A list is a question he can answer.

The quote page's banner read:

    DRAFT — not for issue · 4 prices missing + 1 market figure to replace + 2 manufacturing
    decisions

Which four? He has to open the workbook and find out, and a warning he cannot act on is a
warning he learns to skip. Every one of those rows already knows its own part, so the names
cost nothing: "pack & delivery, M4 screw, wood screw, 06A" is a list somebody settles in a
minute.

The counts are untouched — `phrase` is what half a dozen surfaces already print and they must
keep agreeing. `named_phrase` is the same tally with the names appended, for the surfaces
that have room, and `open_items` is the list itself for anything that wants to lay it out.

Advisory rows (a house rate marked indicative) are deliberately left out of the names: they
are not what is blocking, and padding the blocker list with them is how a list becomes a
count again.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from costed_facts import outstanding_summary                            # noqa: E402


def _job(*decisions):
    """A costed_job record, which outstanding_summary takes directly."""
    return {"decisions_required": list(decisions), "release": {"draft": True}}


def _d(part, kind="missing_price"):
    return {"part": part, "kind": kind, "issue": f"{part} carries no price"}


def test_the_names_are_on_the_record():
    out = outstanding_summary(_job(
        _d("PACKAGING"), _d("DELIVERY"), _d("FIXING"), _d("STD PART")))
    assert out["open_items"] == ["PACKAGING", "DELIVERY", "FIXING", "STD PART"]


def test_the_named_phrase_carries_the_tally_and_the_list():
    out = outstanding_summary(_job(_d("PACKAGING"), _d("FIXING")))
    assert out["named_phrase"].startswith("2 prices missing")
    assert "PACKAGING, FIXING" in out["named_phrase"]


def test_the_counts_are_exactly_as_they_were():
    """Six surfaces print `phrase`; they must keep agreeing to the character."""
    out = outstanding_summary(_job(
        _d("PACKAGING"), _d("FIXING"),
        _d("12349-02-69-06A", "manufacturing_decision")))
    assert out["phrase"] == "2 prices missing + 1 manufacturing decision"
    assert out["blocking"] == 3 and out["total"] == 3


def test_an_advisory_rate_is_not_named_among_the_blockers():
    out = outstanding_summary(_job(_d("FIXING"), _d("LASER", "indicative_rate")))
    assert out["open_items"] == ["FIXING"]
    assert out["advisory"] == 1


def test_a_long_list_is_trimmed_rather_than_run_on():
    out = outstanding_summary(_job(*[_d(f"PART-{n:02d}") for n in range(9)]))
    assert "and 3 more" in out["named_phrase"]
    assert len(out["open_items"]) == 9


def test_a_clean_job_says_so():
    out = outstanding_summary(_job())
    assert out["named_phrase"] == "nothing outstanding"
    assert out["open_items"] == []


def test_the_same_part_twice_is_named_once():
    out = outstanding_summary(_job(_d("FIXING"), _d("fixing")))
    assert out["open_items"] == ["FIXING"]


def test_the_named_phrase_reaches_the_estimator_not_the_customer():
    """THE SURFACE THIS WAS BUILT FOR TURNED OUT TO BE THE WRONG ONE.

    The named list was added to the client quotation's banner, and that is where it did
    the most harm: it put SDI's part numbers and open questions on the one document a
    customer reads, and it described the moment the engine finished rather than the moment
    the quote is issued — which is after an estimator has settled every item on it.

    The names were the right idea on the wrong page. They now appear on the surfaces the
    person who can answer them actually works from."""
    src = (ROOT / "src" / "client_quote_html.py").read_text(encoding="utf-8")
    assert 'draft_block = ""  # retained' in src
    # And the names still reach the surfaces that can act on them. The rendered proof is in
    # tests/test_a_draft_is_an_internal_word.py; this is the wiring.
    for module in ("job_report_html.py", "estimate_explained.py", "job_decision_report.py"):
        text = (ROOT / "src" / module).read_text(encoding="utf-8")
        assert "outstanding_summary" in text, module
