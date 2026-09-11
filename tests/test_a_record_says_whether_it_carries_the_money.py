"""Twenty-three candidate records, none able to evidence the price, and none of them said so.

That is the week this module closes. Searching for the run behind an accepted GBP 80.09 workbook,
every archived 7332-01 summary looked like a candidate — right job, right quantity, right part
count, plausible timestamps — and not one carried `final_estimate.totals`. The absence was
discoverable only by running the costing code over each record and noticing the totals came back
None.

The skip that produces such a record is deliberate and stays: populate_workbook returns a path or
nothing, the read-back needs Excel COM, and an estimate that fails because a diagnostic could not
open a spreadsheet is worse than one that completes and says what it lacks. The defect was the
silence, not the skip.

So a record now declares which of three states it is in, and the run stamps that declaration
whether or not the workbook stage completed — the case worth stamping being precisely the one
where it did not.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import money_provenance as mp                                            # noqa: E402
import invariants as inv                                                 # noqa: E402

TOTALS = {"material_gbp": 40.89, "labour_gbp": 33.59, "unit_gbp": 80.09}


def _pre_workbook() -> dict:
    """Shaped like every archived 7332-01 summary: what the engine handed TO Excel."""
    return {"estimate_summary": {"part_estimates": [{"part_number": "7332-01-002"}]}}


def _accepted_rows_only() -> dict:
    record = _pre_workbook()
    record["workbook_labour"] = {"rows": [
        {"workbook_row": 10, "part_numbers": ["7332-01-002"], "wb_operation": "Tube Bend"}]}
    return record


def _excel_calculated(totals: dict = None) -> dict:
    record = _pre_workbook()
    record["final_estimate"] = {"schema": "final_estimate.v2", "source": "excel_calculated",
                               "totals": dict(TOTALS if totals is None else totals),
                               "labour_rows": [{"workbook_row": 10}]}
    return record


# ── the three states ──────────────────────────────────────────────────────────────────


def test_a_pre_workbook_record_says_it_cannot_evidence_a_price():
    verdict = mp.describe(_pre_workbook())
    assert verdict["state"] == mp.PRE_WORKBOOK
    assert verdict["can_evidence_a_price"] is False
    assert "handed TO Excel" in verdict["why"]
    assert "different calculator" in verdict["why"], \
        "and says WHY the two figures differ, which is the question that took a week"


def test_accepted_rows_without_totals_are_a_state_of_their_own():
    """Parts and operations become attributable while money does not. Collapsing this into
    "pre-workbook" would lose the distinction that makes a structural baseline possible."""
    verdict = mp.describe(_accepted_rows_only())
    assert verdict["state"] == mp.ACCEPTED_ROWS_ONLY
    assert verdict["can_evidence_a_price"] is False
    assert "attributable and money is not" in verdict["why"]


def test_a_read_back_record_can_evidence_its_price():
    verdict = mp.describe(_excel_calculated())
    assert verdict["state"] == mp.EXCEL_CALCULATED
    assert verdict["can_evidence_a_price"] is True


def test_a_partial_read_back_cannot_evidence_a_price_either():
    """Excel carries an error cell back as null, never as zero. Two totals out of three is not
    a price, and treating it as one is how a #DIV/0! becomes a figure that reconciles."""
    verdict = mp.describe(_excel_calculated({**TOTALS, "labour_gbp": None}))
    assert verdict["state"] == mp.EXCEL_CALCULATED
    assert verdict["can_evidence_a_price"] is False, "a missing total is missing data"
    assert "labour_gbp" in verdict["why"]
    assert "never zero" in verdict["why"]


def test_the_skip_reason_is_carried_so_absence_becomes_because():
    """"This record has no totals" and "this record has no totals BECAUSE" are the difference
    between a mystery and a repair."""
    verdict = mp.describe(_pre_workbook(),
                          skip_reason="populate_workbook returned no path")
    assert verdict["evidence"]["workbook_stage_skipped_because"] == (
        "populate_workbook returned no path")
    assert "populate_workbook returned no path" in verdict["why"]


@pytest.mark.parametrize("nesting", ["top", "estimate_summary"])
def test_both_nestings_are_read(nesting):
    """Both spellings are live in this pipeline, and a reader that knows only one reports a
    present block as absent — which is exactly how the route came to read as missing."""
    record = _pre_workbook()
    block = {"totals": dict(TOTALS), "labour_rows": [{"workbook_row": 1}]}
    if nesting == "top":
        record["final_estimate"] = block
    else:
        record["estimate_summary"]["final_estimate"] = block
    assert mp.describe(record)["can_evidence_a_price"] is True


def test_the_evidence_names_what_is_present_and_what_is_missing():
    verdict = mp.describe(_excel_calculated({**TOTALS, "unit_gbp": None}))
    totals = verdict["evidence"]["final_estimate.totals"]
    assert sorted(totals["present"]) == ["labour_gbp", "material_gbp"]
    assert totals["missing"] == ["unit_gbp"]


def test_a_malformed_record_is_pre_workbook_not_an_exception():
    for broken in (None, [], "not a record", 7):
        verdict = mp.describe(broken)
        assert verdict["can_evidence_a_price"] is False


# ── stamping, and reading a stamp back ────────────────────────────────────────────────


def test_stamping_writes_the_verdict_onto_the_record():
    record = _pre_workbook()
    verdict = mp.stamp(record, skip_reason="Excel COM unavailable")
    assert record["money_provenance"] is verdict
    assert record["money_provenance"]["state"] == mp.PRE_WORKBOOK


def test_a_stamped_record_is_not_re_judged_by_a_later_different_rule():
    """A consumer must not have to know whether a record was stamped, and a stamped verdict must
    win — otherwise the same file answers differently depending on which build reads it."""
    record = _excel_calculated()
    record["money_provenance"] = {"schema": mp.SCHEMA, "state": mp.PRE_WORKBOOK,
                                  "can_evidence_a_price": False, "why": "stamped at run time"}
    assert mp.can_evidence_a_price(record) is False, "the stamp wins over re-derivation"


def test_an_unstamped_record_is_judged_rather_than_assumed_good():
    assert mp.can_evidence_a_price(_excel_calculated()) is True
    assert mp.can_evidence_a_price(_pre_workbook()) is False


# ── the invariant ─────────────────────────────────────────────────────────────────────


def test_a_record_with_no_declaration_is_reported():
    findings = inv.check_the_record_declares_whether_it_carries_the_money(_pre_workbook())
    assert findings and findings[0]["code"] == "money_provenance_undeclared"
    assert findings[0]["severity"] == inv.WARNING
    assert "twenty-three archived 7332-01 summaries" in findings[0]["message"]


def test_a_record_declaring_it_cannot_evidence_a_price_is_reported():
    record = _pre_workbook()
    mp.stamp(record, skip_reason="Excel COM unavailable")
    findings = inv.check_the_record_declares_whether_it_carries_the_money(record)
    assert findings
    assert findings[0]["code"] == "money_provenance_cannot_evidence_a_price"
    assert "must not be frozen as a money-bearing replay baseline" in findings[0]["message"]


def test_it_is_a_warning_not_blocking_because_a_pre_workbook_record_is_legitimate():
    """On a machine without Excel it is the only kind of record there is. Blocking would stop
    every such run; the requirement is that it cannot be MISTAKEN for a priced one."""
    record = _pre_workbook()
    mp.stamp(record)
    findings = inv.check_the_record_declares_whether_it_carries_the_money(record)
    assert all(f["severity"] == inv.WARNING for f in findings)


def test_a_stamped_and_priced_record_passes_clean():
    record = _excel_calculated()
    mp.stamp(record)
    assert inv.check_the_record_declares_whether_it_carries_the_money(record) == []


def test_the_check_is_registered_or_it_never_runs():
    """A check that exists and is not in CHECKS is indistinguishable from one that passes —
    the same silent-absence failure this whole module is about."""
    assert inv.check_the_record_declares_whether_it_carries_the_money in inv.CHECKS


def test_a_malformed_summary_is_unevaluated_not_a_pass():
    findings = inv.check_the_record_declares_whether_it_carries_the_money("not a summary")
    assert findings, "an unreadable summary has been CHECKED for nothing, and must say so"


# ── the run stamps it, whether or not the workbook stage completed ─────────────────────


def test_the_run_stamps_money_provenance_unconditionally():
    """The case worth stamping is the one where the workbook stage did NOT run, so the stamp
    must not sit inside `if xlsx_path:`."""
    source = (ROOT / "src" / "main.py").read_text(encoding="utf-8", errors="ignore")
    assert "import money_provenance as _mp" in source
    assert "_mp.stamp(_mp_doc, skip_reason=_mp_skip)" in source
    # the reason is collected for every way the stage can fail to produce totals
    for reason in ("populate_workbook returned no path",
                   "the read-back could not obtain the calculated totals",
                   "the read-back raised"):
        assert reason in source, reason


def test_the_run_says_out_loud_when_a_record_cannot_evidence_a_price():
    source = (ROOT / "src" / "main.py").read_text(encoding="utf-8", errors="ignore")
    assert "THIS RECORD CANNOT EVIDENCE A PRICE" in source


def test_the_freeze_tool_reads_the_records_own_declaration():
    """Rather than re-deriving the rule: a record stamped by the run that produced it knows
    things the tool cannot see, including why the workbook stage did not complete."""
    source = (ROOT / "tools" / "freeze_replay_fixture.py").read_text(
        encoding="utf-8", errors="ignore")
    assert "import money_provenance as _mp" in source
    assert "record_money_provenance" in source
    assert "workbook_stage_skipped_because" in source


# ── who gets told ─────────────────────────────────────────────────────────────────────


def test_an_undeclared_record_is_the_engines_fault():
    """Would a perfect engine raise it? No — declaring what a record contains costs nothing and
    needs no drawing, no supplier and no estimator."""
    import engine_discoveries as ed
    assert ed.classify("money_provenance_undeclared") == "engine"


def test_a_record_honestly_declaring_it_cannot_price_is_NOT_counted_as_a_confession():
    """On a machine with no Excel a pre-workbook record is the only kind there is, and the engine
    behaved properly: it completed, declined to invent the sheet's arithmetic, and said what it
    lacks. Counting that as a defect would make the number that must fall RISE every time the
    engine was honest about its environment — and would push whoever is driving it toward
    suppressing the declaration rather than fixing the read-back."""
    import engine_discoveries as ed
    assert ed.classify("money_provenance_cannot_evidence_a_price") == "environment"


def test_it_is_not_filed_against_the_drawing_office():
    """The drawing office cannot install Excel. Sending a missing read-back to them is the same
    misdirection as asking for a vector export of a file that already is one."""
    import engine_discoveries as ed
    import estimating_review as er
    kind = ed.classify("money_provenance_cannot_evidence_a_price")
    assert kind != "drawing"
    assert er._BUCKET_FOR[kind] == er.INFORMATION
