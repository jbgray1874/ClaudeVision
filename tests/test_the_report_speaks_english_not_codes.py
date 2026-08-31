"""An estimator asked what the report meant, six times, in one message.

WHAT JAMES WROTE, reading the 10575-02 pack in the form it would be walked through with the
estimating team next week:

    "10575-01-013 — risk flag: customer_supplied_zero_cost. - what does this mean?"
    "high bend count; low extraction confidence (44%). - why is there low confidence? Did the
     LLM extract a high bend count and we are not confident of it's accuracy? What does a high
     bend count mean?"
    "what are the mixed conventions? ... Does the report state which drawings have mixed
     convention issues?"
    "I don't understand why price would not exist."
    "what is an unrecorded source?"
    "this also. it's all a bit like shrouded in codes. it's difficult to understand"

EVERY ONE OF THOSE IS A QUESTION THE DOCUMENT RAISED AND DECLINED TO ANSWER. The report is not
a log; it is the thing an estimator holds while deciding whether to send a number to a customer.
A page that prints an internal identifier has handed its job to the reader, and the reader's
options are to guess or to ask the person who wrote the engine — which does not scale past one
person and does not survive that person being on holiday.

FOUR SEPARATE FAULTS, AND ONLY ONE OF THEM IS VOCABULARY:

  A CODE WITH NO GLOSS.  `customer_supplied_zero_cost` read literally says a customer supplied
  something at no cost. What happened is that the engine recognised a free-issue item and
  deliberately costed it at nothing. Even guessing at the words gets it wrong.

  TWO FACTS JOINED BY A SEMICOLON.  "high bend count; low extraction confidence (26%)" — two
  unrelated observations, one clause, no subject. Read as one claim, which is what James did.

  A COUNT WHERE A LIST WAS NEEDED.  "4 distinct patterns" cannot be acted on and cannot be
  checked. It also was not a defect: three of the four patterns are how the pack distinguishes
  a fabricated part from a bought-in one.

  A QUESTION ASKED OF THE WRONG KIND OF LINE.  `no_price_source` — "no catalogue, price file or
  quote we can query holds this item" — printed against 10575-01-001, a folded steel bracket SDI
  makes. Nobody sells it. The catalogue was never where its price would come from, and the
  sentence is not an explanation but a category error. The same error, in another column, made
  the provenance table report a missing blank size for a bolt.

THE FIX IS ONE GLOSSARY, NOT SIX REWORDINGS. Three documents each carried their own partial
vocabulary, so the same flag was explained three ways or not at all depending which one you
opened. plain_english is the single place, and every entry answers the same three questions:
what was observed, what it does to the number, and who does what next.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import job_report_html as jrh                                          # noqa: E402
import plain_english as pe                                             # noqa: E402


# ── the codes James asked about ──────────────────────────────────────────────

@pytest.mark.parametrize("code", [
    "customer_supplied_zero_cost",
    "many_bends",
    "weld_required",
    "low_part_confidence",
    "missing_material_price",
    "missing_material_spec",
    "missing_labour_rate:laser_cutting",
])
def test_every_code_the_report_prints_has_a_meaning_and_an_action(code):
    """Not "has an entry" — has BOTH halves. A meaning with no action leaves the reader
    informed and stuck, which on a checklist is the same as unread."""
    assert len(pe.explain(code)) > 40, f"{code} has no real explanation"
    assert len(pe.action(code)) > 20, f"{code} says nothing about what to do"
    assert pe.label(code) and "_" not in pe.label(code), (
        f"{code} still shows as an identifier")


def test_the_free_issue_flag_says_the_zero_is_deliberate():
    """THE ONE THAT MISLEADS EVEN WHEN YOU READ THE WORDS. "customer_supplied_zero_cost" reads
    as a fault — something came in at zero and shouldn't have. It is a decision: the customer
    supplies the item, so SDI carries no money for it."""
    txt = pe.explain("customer_supplied_zero_cost").lower()
    assert "free-issue" in txt or "customer supplies" in txt
    assert "deliberate" in txt or "not a missing price" in txt
    assert "confirm" in pe.action("customer_supplied_zero_cost").lower()


def test_the_confidence_figure_says_what_it_is_an_average_of():
    """James: "Did the LLM extract a high bend count and we are not confident of it's
    accuracy?" No — the percentage is the mean across every field read for the part, and it
    happened to be printed beside a bend-count flag. The gloss has to say so explicitly,
    because the previous layout actively taught the wrong reading."""
    txt = pe.explain("low_part_confidence").lower()
    assert "average" in txt
    assert "not a judgement on any other flag" in txt or "not about any single value" in txt


def test_a_code_nobody_has_written_up_says_that_rather_than_nothing():
    """A glossary returning "" prints a blank cell, and a blank cell reads as nothing to
    report — the opposite of the truth. It also hides the gap from whoever would fill it."""
    txt = pe.explain("some_flag_invented_next_tuesday")
    assert "no plain-english entry" in txt.lower()
    assert "some_flag_invented_next_tuesday" in txt


# ── two facts are not one finding ────────────────────────────────────────────

def _review(*findings_per_part):
    return {"flagged_parts": [
        {"part": f"P{i}", "cost": None, "findings": list(f)}
        for i, f in enumerate(findings_per_part)], "provisional": []}


def test_findings_are_grouped_by_kind_not_strung_together_per_part():
    """WHAT IT LOOKED LIKE:

        * 10575-01-102 — high bend count; weld cue detected — verify weld/dress content; low
          extraction confidence (26%).
        * 10575-01-104 — weld cue detected — verify weld/dress content; low extraction
          confidence (26%).

    James: "same for all these. Can we be more specific somehow?" By the third line a reader
    has learned these lines all say the same thing, which is exactly when they stop reading."""
    html = jrh._render_checklist(_review(
        [{"code": "many_bends"}, {"code": "weld_required"}],
        [{"code": "weld_required"}],
    ), {})
    # each kind explained once
    assert html.count("Weld time and dress time are separate operations") == 1
    # and it lists the parts it applies to
    assert "P0" in html and "P1" in html
    # the semicolon soup is gone
    assert "high bend count; " not in html


def test_a_missing_rate_outranks_a_flag_that_only_asks_for_a_look():
    """ORDER IS WHAT IT DOES TO THE NUMBER. missing_labour_rate:laser_cutting means laser
    cutting on that part is costing NOTHING — the time is in the estimate and the money is
    not. It was appearing third in a semicolon chain on the second of three near-identical
    lines, which is where a reader has already stopped."""
    html = jrh._render_checklist(_review(
        [{"code": "many_bends"}],
        [{"code": "missing_labour_rate:laser_cutting"}],
    ), {})
    assert html.index("laser cutting") < html.index("3 or more bends")


def test_the_rate_gap_says_the_operation_is_costing_nothing():
    """"No labour rate found" is a database fact. "That operation is costing nothing" is the
    same fact stated as money, which is the only form an estimator can act on before a quote
    goes out."""
    txt = pe.explain("missing_labour_rate:laser_cutting")
    assert "costing nothing" in txt
    assert "laser cutting" in txt, "the operation is not named in its own explanation"


# ── the wrong question asked of the wrong line ───────────────────────────────

def test_a_part_sdi_makes_is_not_told_no_supplier_has_it():
    """10575-01-001 is a folded mild-steel bracket. James: "I don't understand why price would
    not exist." Nobody sells it — its cost is material plus labour, so a blank means a gauge,
    a blank size or a rate is missing, and the catalogue was never where to look."""
    cat, why, supersedes = pe.why_no_price("no_price_source", part_is_fabricated=True)
    assert "catalogue" not in cat.lower()
    assert "material plus labour" in why
    assert supersedes, ("the writer's own 'no catalogue row was found' line will print under "
                        "the correction and argue with it")


def test_a_bought_in_line_still_gets_the_catalogue_answer():
    """The correction must not swallow the case where it WAS the right question. BI-BOLT
    genuinely has no catalogue row, and that is genuinely what to chase."""
    cat, why, _ = pe.why_no_price("no_price_source", part_is_fabricated=False)
    assert "catalogue" in why.lower()
    assert "SDILive" in why


def test_the_unpriced_table_says_which_lines_sdi_makes():
    """The distinction has to be visible on the row, not only in the prose — otherwise a reader
    cannot tell why two lines with the same code carry different explanations."""
    html = jrh._unpriced_section({"final_estimate": {"material_rows": [
        {"part_number": "10575-01-001", "price_gbp": 0,
         "unpriced_reason": {"category": "no_price_source", "owner": "estimator",
                             "why": "x", "detail": "no catalogue row was found"}},
        {"part_number": "BI-BOLT", "price_gbp": 0,
         "unpriced_reason": {"category": "no_price_source", "owner": "estimator",
                             "why": "x", "detail": "no catalogue row was found"}},
    ]}})
    assert "SDI makes it" in html and "Bought in" in html
    assert "material plus labour" in html


# ── a count is not a list ────────────────────────────────────────────────────

def test_the_part_number_finding_names_the_conventions_it_found():
    """"4 distinct patterns" cannot be checked and cannot be acted on. James: "what are the
    mixed conventions? If it's mixed conventions from the drawings, this should be stated
    clearly." """
    dq = jrh._extract_drawing_quality({"part_estimates": [
        {"part_number": "10575-01-001"}, {"part_number": "10575-01-002"},
        {"part_number": "BI-BOLT"}, {"part_number": "FIXING2104"},
        {"part_number": "STD PART"},
    ]})
    assert dq["pn_pattern_count"] >= 3
    seen = {pn for names in dq["pn_examples"].values() for pn in names}
    assert {"10575-01-001", "BI-BOLT", "FIXING2104"} <= seen, (
        "the shapes are counted and the numbers behind them are thrown away")


def test_several_conventions_are_not_reported_as_a_defect():
    """AND IT WAS NOT WRONG IN THE FIRST PLACE. Three of the four patterns on 10575-02 are how
    the pack tells an estimator what kind of line each is: an SDI drawing number, a BI- prefix,
    a supplier's own code. Calling that an inconsistency trains a reader to skip the row, and
    the row is where a genuine oddity — a description sitting in the number column — would
    have to appear."""
    src = (ROOT / "src" / "job_report_html.py").read_text(encoding="utf-8")
    code = re.sub(r"#[^\n]*", " ", src)
    assert "Inconsistent part-number formats" not in code
    assert "Several part-number conventions" in code
