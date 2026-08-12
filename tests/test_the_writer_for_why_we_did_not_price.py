"""Every blank price on the sheet says which kind of nothing it is.

THE READER EXISTED AND THE WRITER DID NOT. price_provenance has carried the unpriced
vocabulary since the day it was written, and invariants.check_every_unpriced_line_says_why
has read `row["unpriced_reason"]` for exactly as long. Nothing anywhere set it. So the check
whose entire purpose is to stop a blank cell reading as free ran on every job and reported on
no line of any of them -- built is not wired, pointing the other way for once, and the
harder direction to notice: the check was green.

WHY THE DISTINCTION IS WORTH THE CODE. 11650's cabinet BOM carries sixteen fabricated lines
at GBP 0.00 whose material is costed in the Sheet Steel block, beside a lock, a mag catch and
a set of feet that nobody has priced at all. On the sheet they are identical -- a blank in
the price column -- and they need opposite actions: one set must NOT be priced, on pain of
doubling the material total, and the other must be. A checklist that cannot tell them apart
is one an estimator stops working, and what gets lost is the half that was real.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import price_provenance as pp                                        # noqa: E402
import estimator_inputs as ei                                        # noqa: E402
import wep_readback_from_xlsx as wep                                 # noqa: E402
from invariants import check_every_unpriced_line_says_why as check   # noqa: E402


# ── the categories, decided from the record and never from a name ───────────────────
@pytest.mark.parametrize("record,category,owner", [
    # The majority case, and the one that must never reach the estimator's list.
    ({"_bom_cross_reference": True}, pp.NOT_APPLICABLE, "nobody"),
    ({"_duplicate_of": "FIXING1081"}, pp.NOT_APPLICABLE, "nobody"),
    ({"_canonical_kind": "assembly"}, pp.NOT_APPLICABLE, "nobody"),
    # A figure exists and we decided not to stand behind it. The blank is a policy.
    ({"_ai_indicative_gbp": 86.04}, pp.POLICY_WITHHELD, "estimator"),
    ({"_consumable_qty_unknown": True}, pp.NOT_MEASURED, "estimator"),
    # Nothing we can query holds this item -- the commonest reason on an SDI sheet.
    ({"part_number": "MAG CATCH"}, pp.NO_PRICE_SOURCE, "estimator"),
])
def test_each_kind_of_blank_is_named_from_the_record(record, category, owner):
    reason = ei.unpriced_reason_for_row(record)
    assert reason["category"] == category
    assert reason["owner"] == owner


def test_no_price_source_is_not_dressed_up_as_a_missing_dimension():
    """Both send the line to the estimator, and forcing this one to borrow NOT_MEASURED would
    print "the dimension or quantity it needs was never measured" against a fitting whose
    dimensions are perfectly well known and whose problem is that no catalogue covers it.
    Different action -- ask the supplier, load a price file -- and a checklist that describes
    it wrongly is one people stop trusting."""
    text = pp.describe_unpriced(pp.NO_PRICE_SOURCE)
    assert "never measured" not in text
    assert "catalogue, price file or quote" in text
    assert pp.unpriced_reason(pp.NO_PRICE_SOURCE)["undercharging"] is False


def test_a_cross_reference_is_nobodys_job():
    """Asking someone to price it is asking for the double-count back."""
    reason = ei.unpriced_reason_for_row({"_bom_cross_reference": True})
    assert reason["owner"] == "nobody" and not reason["undercharging"]
    assert "double" in reason["detail"]


# ── the writer, on rows shaped like the ones the sheet gives back ───────────────────
def _es():
    return {"part_estimates": [
        {"part_number": "11650-01-01M", "_bom_cross_reference": True},
        {"part_number": "ESSENTRA FOOT-466122", "_duplicate_of": "FIXING1081"},
        {"part_number": "MAG CATCH"},
    ]}


def _rows():
    return [
        # The fabricated blocks carry NO part code column -- the number is the first word of
        # the description. Reading only the code column leaves every one of them unexplained.
        {"part_code": "", "description": "11650-01-01M  LH UPRIGHT — costed in Sheet Steel below",
         "total_value_gbp": 0},
        {"part_code": "ESSENTRA FOOT-466122", "description": "foot", "total_value_gbp": 0},
        {"part_code": "MAG CATCH", "description": "HAFELE 246.41.745", "total_value_gbp": None},
        {"part_code": "FIXING1081", "description": "foot", "total_value_gbp": 0.46},
    ]


def test_every_unpriced_row_is_stamped_and_priced_rows_are_left_alone():
    rows = _rows()
    assert wep._explain_unpriced_rows(rows, _es()) == 3
    assert [r.get("unpriced_reason", {}).get("category") for r in rows] == [
        pp.NOT_APPLICABLE, pp.NOT_APPLICABLE, pp.NO_PRICE_SOURCE, None]


def test_a_fabricated_row_is_joined_by_the_first_word_of_its_description():
    """The BOM block has a Part code column and the fabricated blocks do not. Joining on the
    code alone explains the bought-ins and silently leaves the sixteen cross-reference rows
    blank -- which is the majority of the sheet and the whole point of the exercise."""
    rows = _rows()
    wep._explain_unpriced_rows(rows, _es())
    assert rows[0]["unpriced_reason"]["category"] == pp.NOT_APPLICABLE


def test_a_row_no_record_matches_is_loudly_unexplained_not_silently_skipped():
    """Falling silent for a row whose part record cannot be found reproduces exactly the
    failure this exists to end. UNEXPLAINED is the honest answer -- we did not price it and
    we cannot say why -- and the invariant reports it."""
    rows = [{"part_code": "GHOST", "description": "?", "total_value_gbp": 0}]
    wep._explain_unpriced_rows(rows, _es())
    assert rows[0]["unpriced_reason"]["category"] == pp.UNEXPLAINED


def test_an_empty_job_does_not_raise():
    assert wep._explain_unpriced_rows([], {}) == 0
    assert wep._explain_unpriced_rows([{"total_value_gbp": 0}], {}) == 1


# ── and the check that has been reporting nothing now reports ───────────────────────
def _job(rows):
    return {"estimate_summary": {"final_estimate": {"material_rows": rows}}}


def test_the_invariant_was_green_on_a_sheet_full_of_unexplained_blanks():
    """The state before this change: every unpriced row carried no reason, so the check found
    nothing to say. It is the shape of failure that survives longest -- a guard reporting
    CLEAR because nobody ever gave it anything to read."""
    silent = [{"part_number": "MAG CATCH", "price_gbp": 0}]
    assert [v["code"] for v in check(_job(silent))] == ["unpriced_line_says_why"]


def test_a_stamped_sheet_passes_and_a_cross_reference_raises_nothing():
    rows = _rows()
    wep._explain_unpriced_rows(rows, _es())
    for r in rows:
        r["price_gbp"] = r.get("total_value_gbp")
    assert check(_job(rows)) == []


def test_an_engine_gap_is_still_reported_as_undercharging():
    """The narrowing must not silence the finding worth a person's time: work that is really
    done, really invoiced, and that nothing on the sheet asks anybody to price."""
    rows = [{"part_number": "VINYL-01", "price_gbp": 0,
             "unpriced_reason": pp.unpriced_reason(pp.NO_VOCABULARY, "REEDED VINYL")}]
    assert [v["code"] for v in check(_job(rows))] == ["unpriced_because_the_engine_cannot"]


# ── the wiring ──────────────────────────────────────────────────────────────────────
def test_the_writer_is_called_on_the_real_readback_path():
    """This module is the one that proved a vocabulary can exist for months with no writer.
    Defining a second one and not calling it would be the same defect wearing this change's
    clothes."""
    src = Path(wep.__file__).read_text(encoding="utf-8")
    body = src[src.index("def stamp_real_totals_into_json"):]
    assert "_explain_unpriced_rows(" in body, \
        "the explainer is defined and never called from the read-back"
    assert body.index("_explain_unpriced_rows(") < body.index("should_stamp_final_estimate"), \
        "rows are stamped into final_estimate before they carry their reasons"


# ── and the report says it, ordered by who has to act ───────────────────────────────
import job_report_html as jrh                                        # noqa: E402


def _report(rows):
    return jrh._unpriced_section(
        {"estimate_summary": {"final_estimate": {"material_rows": rows}}})


def test_the_engine_gap_leads_because_it_is_the_only_one_worth_interrupting_for():
    """An engine gap is work that will be done and invoiced with nothing on the sheet asking
    anyone to price it. No estimator input can fix it. Everything else on this table is
    either somebody's task or correctly nil, so the one that under-charges the job leads."""
    html = _report([
        {"part_number": "NIL-1", "price_gbp": 0,
         "unpriced_reason": pp.unpriced_reason(pp.NOT_APPLICABLE, "costed in Sheet Steel")},
        {"part_number": "ASK-1", "price_gbp": 0,
         "unpriced_reason": pp.unpriced_reason(pp.NO_PRICE_SOURCE, "HAFELE 246.41.745")},
        {"part_number": "GAP-1", "price_gbp": 0,
         "unpriced_reason": pp.unpriced_reason(pp.NO_VOCABULARY, "REEDED VINYL")}])
    assert html.index("GAP-1") < html.index("ASK-1") < html.index("NIL-1")
    assert "under-charged" in html


def test_the_three_owners_are_counted_separately():
    html = _report([
        {"part_number": "A", "price_gbp": 0,
         "unpriced_reason": pp.unpriced_reason(pp.NOT_APPLICABLE)},
        {"part_number": "B", "price_gbp": 0,
         "unpriced_reason": pp.unpriced_reason(pp.NOT_APPLICABLE)},
        {"part_number": "C", "price_gbp": 0,
         "unpriced_reason": pp.unpriced_reason(pp.NO_PRICE_SOURCE)}])
    assert "<b>1</b> waiting on the estimator" in html
    assert "<b>2</b> correctly nil" in html


def test_a_priced_row_is_not_listed_as_a_blank():
    html = _report([{"part_number": "PRICED", "price_gbp": 0.46}])
    assert "PRICED" not in html and "carries a price" in html


def test_blanks_with_no_reasons_are_a_warning_not_an_empty_table():
    """The vocabulary existed for months with no writer and the check stayed green throughout.
    A report that quietly shows an empty table when the stamping did not run would let exactly
    that happen again, one layer up."""
    html = _report([{"part_number": "X", "price_gbp": 0}])
    assert "warn" in html and "no recorded reason" in html


def test_the_section_is_wired_into_the_report():
    src = Path(jrh.__file__).read_text(encoding="utf-8")
    import ast
    body = ast.unparse(next(n for n in ast.walk(ast.parse(src))
                            if isinstance(n, ast.FunctionDef) and n.name == "_render_verdict"))
    assert "_unpriced_section" in body, "the section is defined and never called"


if __name__ == "__main__":                                            # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
