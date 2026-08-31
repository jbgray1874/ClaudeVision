"""Section 11 sent an estimator to find two prices the job had already worked out.

WHAT IT PRINTED, on 10575-02, under a heading that says who acts:

    10575-01-001   no_price_source   no catalogue, price file or quote holds this item   estimator
    10575-01-012   no_price_source   same                                                estimator

James: "001 IS in Sheet Steel (the BOM dash is 'costed below'). 012 HAS £0.21 in Provenance.
The 'no catalogue' line is the WRONG BUCKET. Don't send those to Tim as 'you must find a
price.'"

THE SECTION WAS READING ONE TABLE AND ANSWERING FOR THE JOB. It walked
final_estimate.material_rows and treated every zero as a line nobody had priced. A material row
is zero for two quite different reasons: nothing costed the part, or the part's material is
carried on ANOTHER row — a sheet-steel stream line covering every part nested from that sheet,
which is why the part's own row shows a dash. The dash means "costed below". The engine knows
which is which: part_estimates holds the per-part figure that AI Provenance prints two tabs
away.

WHY THIS IS WORSE THAN AN EMPTY SECTION. An estimator sent to find a price that already exists
goes and finds it — two tabs away, in the same workbook — and from then on discounts the whole
section, including the lines where the gap is real. On this job that was BI-BOLT, which
genuinely has no price anywhere and is the one thing on the list worth a phone call. Three
lines of noise buried it.

AND THE MOVED ROWS ARE NAMED, NOT DROPPED. A row that simply disappeared would read, to anyone
who saw it last week, as a finding somebody suppressed. Saying where the money is turns the
omission into the answer, and it is the same sentence that stops the next reader chasing it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import job_report_html as jrh                                          # noqa: E402


def _reason(cat="no_price_source", owner="estimator"):
    return {"category": cat, "owner": owner, "why": "x", "detail": "no catalogue row"}


def _summary(rows, estimates):
    return {"final_estimate": {"material_rows": rows},
            "estimate_summary": {"part_estimates": estimates}}


JOB = _summary(
    rows=[
        {"part_number": "10575-01-001", "price_gbp": 0, "unpriced_reason": _reason()},
        {"part_number": "10575-01-012", "price_gbp": 0, "unpriced_reason": _reason()},
        {"part_number": "BI-BOLT", "price_gbp": 0, "unpriced_reason": _reason()},
    ],
    estimates=[
        # in Sheet Steel — the material is real and sits on the stream row
        {"part_number": "10575-01-001",
         "material_estimate": {"extended_material_cost_gbp": 40.62}},
        {"part_number": "10575-01-012",
         "material_estimate": {"extended_material_cost_gbp": 0.21}},
        # genuinely nothing, anywhere
        {"part_number": "BI-BOLT", "material_estimate": {"extended_material_cost_gbp": 0.0},
         "extended_total_cost_gbp": 0.0},
    ])


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_a_part_costed_on_another_row_is_not_sent_to_the_estimator():
    """THE DEFECT, STATED. Nobody needs to find a price for 10575-01-001: the job costed it at
    £40.62 and put the figure on the sheet-steel row."""
    html = jrh._unpriced_section(JOB)
    rows = html[html.index("<tbody>"):]
    assert "10575-01-001" not in rows, "a part with a price is still in the who-acts table"
    assert "10575-01-012" not in rows


def test_the_line_that_really_has_no_price_is_still_there():
    """The correction must not swallow the finding. BI-BOLT has nothing anywhere, and it is the
    one line on this job worth a phone call."""
    html = jrh._unpriced_section(JOB)
    rows = html[html.index("<tbody>"):]
    assert "BI-BOLT" in rows


def test_the_count_reflects_what_is_actually_outstanding():
    """"4 blank line(s): 4 waiting on the estimator" was the headline. Three of them were not."""
    txt = _text(jrh._unpriced_section(JOB))
    assert "1 blank line(s)" in txt
    assert "1 waiting on the estimator" in txt


def test_the_moved_rows_are_named_and_say_where_the_money_is():
    """A row that just vanished reads as a finding somebody suppressed — and leaves the next
    reader to rediscover the same thing."""
    txt = _text(jrh._unpriced_section(JOB))
    assert "2 line(s) show zero here and ARE costed" in txt
    assert "£40.62" in txt and "£0.21" in txt
    assert "AI Provenance" in txt, "it does not say where to find the figures"
    assert "not waiting on anybody" in txt or "not waiting on anyone" in txt


def test_a_job_with_nothing_outstanding_still_explains_its_zeros():
    """The all-clear case has to carry the same explanation, or a reader sees a table of zeros
    and a sentence saying everything is priced, and believes neither."""
    ok = _summary(
        rows=[{"part_number": "10575-01-001", "price_gbp": 0, "unpriced_reason": _reason()}],
        estimates=[{"part_number": "10575-01-001",
                    "material_estimate": {"extended_material_cost_gbp": 40.62}}])
    txt = _text(jrh._unpriced_section(ok))
    assert "Every material line on this job carries a price" in txt
    assert "ARE costed" in txt and "£40.62" in txt


def test_a_part_with_no_material_but_a_total_still_counts_as_costed():
    """A bought-in carries its money as a total rather than as material. Reading only the
    material field would send every priced bought-in to the estimator."""
    bi = _summary(
        rows=[{"part_number": "FIXING2104", "price_gbp": 0, "unpriced_reason": _reason()}],
        estimates=[{"part_number": "FIXING2104", "material_estimate": {},
                    "extended_total_cost_gbp": 12.40}])
    html = jrh._unpriced_section(bi)
    assert "<tbody>" not in html or "FIXING2104" not in html[html.index("<tbody>"):]
    assert "£12.40" in _text(html)


def test_a_genuinely_unpriced_part_is_not_rescued_by_a_zero_estimate():
    """The check must be that a cost EXISTS, not that a record exists. A part_estimates entry
    of 0.00 is the engine agreeing there is nothing there."""
    html = jrh._unpriced_section(JOB)
    assert "BI-BOLT" in html[html.index("<tbody>"):]
