"""A line with no price must say which kind of nothing it is.

A price says where it came from. A BLANK said nothing at all, so every unpriced line looked
identical. On 11650-05 five bill-of-materials lines carried no price for four different
reasons:

    11650-04-01A / 03A   no blank size was ever measured        -> the estimator's
    BI-SCREW             an AI figure exists, policy withholds  -> the estimator's
    PACKAGING/DELIVERY   order-level, not a per-unit price      -> the estimator's
    the vinyl finish     no rate exists in this engine at all   -> OURS

Only the last of those is an under-charge. It looks exactly like the other three on the
sheet, and it will be done and invoiced whether or not anybody prices it. "Not priced"
hides that difference, and hiding it is how a job quietly goes out light.

THE CATEGORY SAYS WHOSE PROBLEM IT IS. That is the whole reason this vocabulary exists
rather than a free-text note.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import invariants                                                   # noqa: E402
import price_provenance as pp                                       # noqa: E402
from invariants import (WARNING,                                    # noqa: E402
                        check_every_unpriced_line_says_why as check)


def _job(rows):
    return {"estimate_summary": {"final_estimate": {"material_rows": list(rows)}}}


def _row(code, price=0, reason=None, **kw):
    r = {"part_number": code, "price_gbp": price}
    if reason is not None:
        r["unpriced_reason"] = reason
    r.update(kw)
    return r


# ── the vocabulary ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("category,owner,undercharging", [
    (pp.NOT_MEASURED,    "estimator", False),
    (pp.POLICY_WITHHELD, "estimator", False),
    (pp.ORDER_LEVEL,     "estimator", False),
    (pp.NO_VOCABULARY,   "engine",    True),
    (pp.MISREAD,         "engine",    True),
    (pp.NOT_APPLICABLE,  "nobody",    False),
    (pp.UNEXPLAINED,     "engine",    True),
])
def test_each_reason_names_an_owner_and_says_whether_it_undercharges(
        category, owner, undercharging):
    r = pp.unpriced_reason(category)
    assert r["owner"] == owner
    assert r["undercharging"] is undercharging
    assert r["why"], "a reason with no sentence explains nothing"


def test_an_unrecognised_category_becomes_unexplained_not_silently_accepted():
    """A typo must not create a new kind of nothing that nobody is responsible for."""
    r = pp.unpriced_reason("probably_fine")
    assert r["category"] == pp.UNEXPLAINED and r["undercharging"] is True


def test_the_sheet_text_tells_the_reader_who_must_act():
    assert "ESTIMATOR TO PRICE" in pp.describe_unpriced(pp.NOT_MEASURED)
    assert "UNDER-CHARGED" in pp.describe_unpriced(pp.NO_VOCABULARY)
    assert "nothing to charge" in pp.describe_unpriced(pp.NOT_APPLICABLE)


def test_the_detail_is_carried_into_the_sentence():
    text = pp.describe_unpriced(pp.NOT_MEASURED, "Part Length / Width")
    assert "Part Length / Width" in text


# ── the guard ───────────────────────────────────────────────────────────────────────
def test_a_line_with_no_reason_is_reported():
    """The failure this exists to make impossible: a blank that reads as free."""
    out = check(_job([_row("MYSTERY")]))
    assert len(out) == 1 and out[0]["severity"] == WARNING
    assert "MYSTERY" in out[0]["message"] and "reads as free" in out[0]["message"]


def test_an_engine_gap_is_reported_separately_from_a_missing_datum():
    """Two findings, because they need different people. Folding them into one count would
    bury the only line nobody is going to act on."""
    out = check(_job([
        _row("11650-04-01A", reason=pp.unpriced_reason(pp.NOT_MEASURED, "L/W")),
        _row("VINYL-01", reason=pp.unpriced_reason(pp.NO_VOCABULARY, "REEDED VINYL"))]))
    codes = {f["code"] for f in out}
    assert codes == {"unpriced_because_the_engine_cannot"}, \
        "a properly-explained estimator line was reported, or the engine gap was not"
    assert "UNDER-CHARGED" in out[0]["message"]
    assert "no estimator input can fix it" in out[0]["message"]


def test_a_fully_explained_job_is_silent():
    out = check(_job([
        _row("A", reason=pp.unpriced_reason(pp.NOT_MEASURED)),
        _row("B", reason=pp.unpriced_reason(pp.POLICY_WITHHELD)),
        _row("C", reason=pp.unpriced_reason(pp.ORDER_LEVEL)),
        _row("D", reason=pp.unpriced_reason(pp.NOT_APPLICABLE))]))
    assert out == []


def test_a_priced_line_is_never_asked_to_explain_itself():
    assert check(_job([_row("PRICED", price=12.5)])) == []


def test_a_reason_stamped_as_unexplained_counts_as_silent():
    """Recording the absence of a reason is not recording a reason."""
    out = check(_job([_row("X", reason=pp.unpriced_reason("nonsense"))]))
    assert len(out) == 1 and out[0]["code"] == "unpriced_line_says_why"


def test_a_job_with_no_material_rows_says_nothing():
    """A read-back that found no material rows is a real answer and reports nothing.

    A job with NO final_estimate is not. This asserted `check({}) == []` — encoding the
    silent pass — and the Excel COM read-back fails for reasons nothing to do with the
    estimate: Excel busy or absent, a workbook that will not open. On exactly the
    runs where least is known, the check reported a clean sheet."""
    assert check(_job([])) == []
    assert [v["severity"] for v in check({})] == ["unverified"]


def test_an_unreadable_summary_is_unevaluated_not_clean():
    out = check("not a job")
    assert len(out) == 1 and out[0]["severity"] == "unverified"


def test_the_check_is_registered():
    assert check in invariants.CHECKS


def test_the_two_findings_have_different_codes():
    """One code for both would make it impossible to filter the under-charges out of a
    week's runs, which is the report an estimating manager actually wants."""
    out = check(_job([_row("A"), _row("B", reason=pp.unpriced_reason(pp.NO_VOCABULARY))]))
    assert len({f["code"] for f in out}) == 2


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
