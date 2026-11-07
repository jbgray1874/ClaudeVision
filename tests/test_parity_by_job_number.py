"""Parity by job number, as corrected by the review (D-619, D-621).

JG, 1 Nov 2026: compare one job by job number against "the most obvious s/sheet candidate",
save both sheets and the reports under AI Estimating\\parity, searchable, and compare "all
manual and AI estimates ran across two time periods". The review: match within the client and
the full drawing and ask when it is ambiguous; compare the filed copies and fingerprint them;
never use a summary other than the run's own; match quantities; Period A against Period B with
the incomparable pairs listed apart and repeat runs counted once.

The comparison itself is parity_run.run_parity, tested on its own; here a stand-in records what
it was handed and writes a report and a bundle, so these tests are about choosing, filing,
fingerprinting, quantities, searching and periods.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import parity_job  # noqa: E402


def _touch(path: Path, text: str = "x", age_days: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ai_run(aisheets: Path, client: str, drawing: str, stamp: str, units: int = 1,
            summary: bool = True, sweep: dict | None = None, record: bool = True) -> Path:
    folder = aisheets / client / drawing / f"{stamp} ({units} off)"
    digits = drawing.split("-")[0]
    book = _touch(folder / f"{digits}_{stamp[:10].replace('-', '')}_101500.xlsx", f"book {stamp}")
    _touch(folder / f"{drawing} Quote.html")
    if summary:
        body = {"estimate_summary": {"estimate_workbook_inputs": {"assumed_job_quantity": units}},
                "stamp": stamp}
        if sweep:
            body["quantity_sweep"] = {"rows": [{"quantity": q, "unit": u} for q, u in sweep.items()]}
        _touch(folder / f"{digits}.json", json.dumps(body))
    if record:
        _touch(folder / f"{drawing}_record.json", "{}")
    return book


@pytest.fixture()
def shares(tmp_path, monkeypatch):
    manual = tmp_path / "Manual Estimates"
    aisheets = tmp_path / "AISheets"
    parity = tmp_path / "parity"
    monkeypatch.setenv("SDI_MANUAL_ESTIMATES_ROOT", str(manual))
    monkeypatch.setenv("SDI_ESTIMATE_OUTPUT_ROOT", str(aisheets))
    monkeypatch.setenv("SDI_PARITY_ROOT", str(parity))
    return manual, aisheets, parity


def make_compare(manual_qty: float = 1, ai_unit: float = 421.37, manual_unit: float = 400.0,
                 status: str = "warning", pct: float = 5.3):
    calls = []

    def fake(ai, manual, out_dir, read_via_excel):
        calls.append({"ai": ai, "manual": manual, "out_dir": str(out_dir)})
        report = Path(out_dir) / "12677.full_parity.html"
        report.write_text("<h1>parity</h1>", encoding="utf-8")
        bundle = Path(out_dir) / "12677.full_parity.bundle.json"
        bundle.write_text(json.dumps({"money_cell_comparisons": [
            {"label": "Reference order quantity", "json_numeric": manual_qty,
             "workbook_cached_numeric": manual_qty, "status": "match", "cell": "D6"},
            {"label": "Sell / quoted price", "json_numeric": 560.0,
             "workbook_cached_numeric": 610.0, "pct_variance": 8.9, "status": "warning",
             "cell": "L111"}]}), encoding="utf-8")
        return {"bundle_html": str(report), "bundle_json": str(bundle), "bundle_csv": "",
                "headline": {"ai_unit_cost_gbp": ai_unit, "manual_unit_cost_gbp": manual_unit,
                             "gap_gbp": round(ai_unit - manual_unit, 2), "pct_variance": pct,
                             "status": status}}
    fake.calls = calls
    return fake


@pytest.fixture()
def compare():
    return make_compare()


# ── choosing the manual sheet ───────────────────────────────────────────────────────────

def test_the_highest_issue_in_the_job_folder_is_chosen(shares):
    manual, _, _ = shares
    job = manual / "2026" / "TTI" / "1282- MILWAUKEE RED 50cm PEG"
    _touch(job / "1282-MILWAUKEE 50CM PEG WALL BAY(ISS 6)-.xls", age_days=20)
    _touch(job / "1282-MILWAUKEE 50CM PEG WALL BAY(ISS 7)-.xls", age_days=10)
    _touch(job / "1282 copy of ISS 7.xls", age_days=1)
    _touch(job / "~$1282-MILWAUKEE.xls")
    _touch(job / "drawing.pdf")
    found = parity_job.find_manual("1282", client="TTI")
    assert [c["name"] for c in found] == ["1282-MILWAUKEE 50CM PEG WALL BAY(ISS 7)-.xls",
                                          "1282-MILWAUKEE 50CM PEG WALL BAY(ISS 6)-.xls",
                                          "1282 copy of ISS 7.xls"]
    d = parity_job.decide(found, "1282", "TTI")
    assert d["clear"] and d["pick"]["name"].endswith("(ISS 7)-.xls")
    assert "the highest issue of 2 sheets" in d["reason"]


def test_a_sheet_that_names_only_the_job_number_is_not_chosen_for_a_full_drawing(shares):
    """A job number can cover several drawings: 12677.xls is not assumed to be 12677-01-GA."""
    manual, _, _ = shares
    _touch(manual / "2026" / "Acme" / "12677 frame" / "12677 general.xls")
    found = parity_job.find_manual("12677-01-GA", client="Acme")
    d = parity_job.decide(found, "12677-01-GA", "Acme")
    assert not d["clear"] and "No sheet names 12677-01-GA" in d["reason"]


def test_the_sheet_naming_the_drawing_is_chosen_over_one_that_does_not(shares):
    manual, _, _ = shares
    job = manual / "2026" / "Acme" / "12677 frame"
    _touch(job / "12677 general.xlsx", age_days=1)
    _touch(job / "12677-01-GA estimate.xlsx", age_days=5)
    d = parity_job.decide(parity_job.find_manual("12677-01-GA", client="Acme"), "12677-01-GA", "Acme")
    assert d["clear"] and d["pick"]["name"] == "12677-01-GA estimate.xlsx"


def test_a_sheet_under_another_client_is_never_chosen_without_asking(shares):
    manual, _, _ = shares
    _touch(manual / "2026" / "Other Co" / "12677 something" / "12677-01-GA ISS 9.xls")
    found = parity_job.find_manual("12677-01-GA", client="Acme")
    assert found and found[0]["client_match"] == "other"
    d = parity_job.decide(found, "12677-01-GA", "Acme")
    assert not d["clear"] and "No sheet is under a client folder matching 'Acme'" in d["reason"]
    assert "'Other Co'" in d["reason"]


def test_the_runs_client_wins_over_a_better_named_sheet_elsewhere(shares):
    manual, _, _ = shares
    mine = _touch(manual / "2026" / "ACME LTD" / "12677" / "12677-01-GA ISS 1.xls")
    _touch(manual / "2026" / "Other Co" / "12677" / "12677-01-GA ISS 9.xls")
    d = parity_job.decide(parity_job.find_manual("12677-01-GA", client="Acme"), "12677-01-GA", "Acme")
    assert d["clear"] and d["pick"]["path"] == str(mine)


def test_two_equally_likely_sheets_are_a_choice_and_a_date_does_not_decide(shares):
    manual, _, _ = shares
    job = manual / "2026" / "Acme" / "12677"
    _touch(job / "12677-01-GA a.xls", age_days=1)
    _touch(job / "12677-01-GA b.xls", age_days=30)
    d = parity_job.decide(parity_job.find_manual("12677-01-GA", client="Acme"), "12677-01-GA", "Acme")
    assert not d["clear"] and "a date alone does not decide" in d["reason"]


def test_sheets_in_two_job_folders_are_a_choice(shares):
    manual, _, _ = shares
    _touch(manual / "2026" / "Acme" / "12677 frame" / "12677-01-GA ISS 2.xls")
    _touch(manual / "2026" / "Acme" / "12677 frame rework" / "12677-01-GA ISS 3.xls")
    d = parity_job.decide(parity_job.find_manual("12677-01-GA", client="Acme"), "12677-01-GA", "Acme")
    assert not d["clear"] and "in 2 folders" in d["reason"]


def test_the_newest_year_holding_the_job_is_searched_and_other_jobs_ignored(shares):
    manual, _, _ = shares
    _touch(manual / "2025" / "Acme" / "12677 old" / "12677 est.xls")
    _touch(manual / "2026" / "Acme" / "12677 new" / "12677 est.xls")
    _touch(manual / "2026" / "Acme" / "126770 another job" / "126770 est.xls")
    found = parity_job.find_manual("12677")
    assert len(found) == 1 and "12677 new" in found[0]["path"]


def test_templates_are_never_offered_and_no_job_number_is_a_plain_answer(shares):
    manual, _, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677 Blank Estimate.xls")
    assert parity_job.find_manual("12677") == []
    with pytest.raises(parity_job.ParityJobError, match="does not start with a job number"):
        parity_job.find_manual("frame")


def test_an_unreachable_manual_folder_is_named(shares, monkeypatch, tmp_path):
    monkeypatch.setenv("SDI_MANUAL_ESTIMATES_ROOT", str(tmp_path / "nowhere"))
    with pytest.raises(parity_job.ParityJobError, match="not reachable"):
        parity_job.find_manual("12677")


# ── the AI side ─────────────────────────────────────────────────────────────────────────

def test_the_newest_run_with_its_own_summary_and_record_is_found(shares):
    _, aisheets, _ = shares
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-30 09-00-00")
    newest = _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00", units=5)
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-11-01 08-00-00", summary=False)
    runs = parity_job.find_ai("12677-01-GA")
    assert runs[0]["workbook"] == str(newest) and runs[0]["units"] == 5
    assert runs[0]["record"].endswith("12677-01-GA_record.json")
    assert len(runs) == 2, "a run folder with no summary cannot be compared"


def test_a_workbook_with_no_summary_beside_it_is_refused(shares, compare):
    manual, aisheets, _ = shares
    sheet = _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    book = _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00", summary=False)
    with pytest.raises(parity_job.ParityJobError, match="No summary is filed beside"):
        parity_job.run_job("12677-01-GA", manual=str(sheet), ai=str(book), compare=compare)
    assert compare.calls == []


# ── one comparison: the filed copies ────────────────────────────────────────────────────

def test_the_filed_copies_are_what_is_compared_and_each_is_fingerprinted(shares, compare):
    manual, aisheets, parity = shares
    sheet = _touch(manual / "2026" / "Acme" / "12677 frame" / "12677-01-GA ISS 2.xls", "manual v1")
    book = _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00")
    idx = parity_job.run_job("12677-01-GA", compare=compare, comparison_id="c0ffee12",
                             now=time.mktime((2026, 11, 1, 14, 5, 0, 0, 0, -1)))
    folder = parity / "Acme" / "12677-01-GA" / "2026-11-01 14-05-00_c0ffee12"
    assert idx["folder"] == str(folder) and idx["comparison_id"] == "c0ffee12"
    assert sorted(p.name for p in (folder / "manual").iterdir()) == ["12677-01-GA ISS 2.xls"]
    assert sorted(p.name for p in (folder / "ai").iterdir()) == sorted(
        [book.name, "12677.json", "12677-01-GA_record.json"])
    # The copies were compared, not the originals.
    assert compare.calls[0]["manual"] == str(folder / "manual" / "12677-01-GA ISS 2.xls")
    assert compare.calls[0]["ai"] == str(folder / "ai" / "12677.json")
    saved = json.loads((folder / "parity_index.json").read_text("utf-8"))
    assert saved["schema"] == "sdi_parity_comparison.v2"
    assert saved["manual"]["source"] == str(sheet) and saved["manual"]["sha256"] == _sha(sheet)
    assert saved["ai"]["sha256"] == _sha(book)
    assert saved["ai"]["summary"]["sha256"] == _sha(book.parent / "12677.json")
    assert saved["ai"]["record"]["copied_as"] == "ai/12677-01-GA_record.json"
    assert saved["match"] == {"how": "found by job number", "client_matched": True,
                              "reason": "the run's client, names the drawing, issue 2"}
    assert saved["ai"]["date_basis"] == "the AI run folder's date and time"
    assert saved["manual"]["date_basis"] == "the sheet's file date"
    assert [x["label"] for x in saved["lines"]] == ["Reference order quantity", "Sell / quoted price"]
    assert saved["outcome"] == "warning"


def test_changing_the_original_afterwards_leaves_the_filed_copy_as_compared(shares, compare):
    manual, aisheets, _ = shares
    sheet = _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 2.xls", "as compared")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00")
    idx = parity_job.run_job("12677-01-GA", compare=compare)
    sheet.write_text("edited later", encoding="utf-8")
    kept = Path(idx["folder"]) / "manual" / sheet.name
    assert kept.read_text("utf-8") == "as compared"
    assert idx["manual"]["sha256"] == hashlib.sha256(b"as compared").hexdigest()


def test_an_ambiguous_choice_files_nothing_and_returns_every_candidate(shares, compare):
    manual, aisheets, parity = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA a.xls")
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA b.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00")
    with pytest.raises(parity_job.ParityChoiceNeeded) as caught:
        parity_job.run_job("12677-01-GA", compare=compare)
    assert len(caught.value.candidates) == 2 and compare.calls == []
    assert not parity.exists()


def test_sheets_chosen_by_hand_keep_their_client_and_run(shares, compare):
    manual, aisheets, _ = shares
    sheet = _touch(manual / "2026" / "Acme Ltd" / "elsewhere" / "frame costing.xlsx")
    book = _ai_run(aisheets, "Acme Ltd", "12677-01-GA", "2026-10-29 10-00-00")
    idx = parity_job.run_job("12677-01-GA", manual=str(sheet), ai=str(book), compare=compare)
    assert idx["client"] == "Acme Ltd" and idx["drawing"] == "12677-01-GA"
    assert idx["match"]["how"] == "chosen by hand"
    assert idx["ai"]["run"] == "2026-10-29 10-00-00"


def test_no_manual_estimate_or_no_ai_run_says_so(shares, compare):
    manual, aisheets, _ = shares
    (manual / "2026" / "Acme").mkdir(parents=True)
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00")
    with pytest.raises(parity_job.ParityJobError, match="No manual estimate was found for 12677"):
        parity_job.run_job("12677-01-GA", compare=compare)
    with pytest.raises(parity_job.ParityJobError, match="Run the estimate first"):
        parity_job.run_job("55555-01", compare=compare)


def test_a_comparison_that_fails_is_filed_with_its_reason(shares):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00")

    def broken(ai, manual, out_dir, read_via_excel):
        raise RuntimeError("JSON needs estimate_summary (dict).")
    with pytest.raises(parity_job.ParityJobError, match="could not be compared .*estimate_summary"):
        parity_job.run_job("12677-01-GA", compare=broken)
    found = parity_job.search("12677")
    assert len(found) == 1 and found[0]["outcome"] == "not compared"
    assert "estimate_summary" in found[0]["error"]


# ── quantities ──────────────────────────────────────────────────────────────────────────

def test_the_same_quantity_is_comparable(shares, compare):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00", units=1)
    idx = parity_job.run_job("12677-01-GA", compare=compare)
    assert idx["quantity"]["comparable"] and idx["quantity"]["ai"] == 1 == idx["quantity"]["manual"]


def test_a_different_quantity_is_compared_from_the_runs_sweep_where_it_priced_it(shares):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00", units=5,
            sweep={1: 410.0, 5: 300.0})
    idx = parity_job.run_job("12677-01-GA", compare=make_compare(manual_qty=1, manual_unit=400.0))
    q = idx["quantity"]
    assert q["ai_unit_at_manual_qty"] == 410.0 and q["gap_at_manual_qty"] == 10.0
    assert "compared at 1 off from the run's own quantity sweep" in q["note"]
    assert idx["outcome"] == q["status_at_manual_qty"] == "match"     # 2.4% within 3%


def test_a_quantity_the_run_did_not_price_is_not_counted_either_way(shares):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00", units=5)
    idx = parity_job.run_job("12677-01-GA", compare=make_compare(manual_qty=10, status="match"))
    assert idx["outcome"] == "quantities differ"
    assert "re-run the estimate at 10 off" in idx["quantity"]["note"]


# ── search ──────────────────────────────────────────────────────────────────────────────

def test_filed_comparisons_are_found_by_text_date_and_outcome(shares):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _touch(manual / "2026" / "TTI" / "1282 peg" / "1282-01 ISS 7.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00")
    _ai_run(aisheets, "TTI", "1282-01", "2026-10-31 12-00-00")
    parity_job.run_job("12677-01-GA", compare=make_compare(status="warning"),
                       now=time.mktime((2026, 10, 15, 9, 0, 0, 0, 0, -1)))
    parity_job.run_job("1282-01", compare=make_compare(status="match"),
                       now=time.mktime((2026, 11, 1, 9, 0, 0, 0, 0, -1)))
    assert [i["drawing"] for i in parity_job.search()] == ["1282-01", "12677-01-GA"]
    assert [i["drawing"] for i in parity_job.search("tti")] == ["1282-01"]
    assert [i["drawing"] for i in parity_job.search(start="2026-10-01", end="2026-10-31")] \
        == ["12677-01-GA"]
    assert [i["drawing"] for i in parity_job.search(outcome="match")] == ["1282-01"]
    with pytest.raises(parity_job.ParityJobError, match="YYYY-MM-DD"):
        parity_job.search(start="1/10/26")


# ── a period ────────────────────────────────────────────────────────────────────────────

def _october(manual, aisheets):
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-02 09-00-00")
    newest = _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-20 09-00-00")
    _ai_run(aisheets, "Acme", "55555-01", "2026-10-21 09-00-00")              # no manual
    _touch(manual / "2026" / "Acme" / "77777" / "77777-01 a.xls")
    _touch(manual / "2026" / "Acme" / "77777" / "77777-01 b.xls")
    _ai_run(aisheets, "Acme", "77777-01", "2026-10-22 09-00-00")              # ambiguous
    _ai_run(aisheets, "Acme", "66666-01", "2026-11-02 09-00-00")              # outside
    return newest


def test_a_period_counts_each_drawing_once_and_lists_the_rest_apart(shares, compare, tmp_path):
    manual, aisheets, parity = shares
    newest = _october(manual, aisheets)
    status = tmp_path / "state" / "p.json"
    out = parity_job.run_period("2026-10-01", "2026-10-31", compare=compare, say=lambda m: None,
                                status_file=status)
    outcomes = {r["drawing"]: r["outcome"] for r in out["rows"]}
    assert outcomes == {"12677-01-GA": "warning", "55555-01": "no manual", "77777-01": "ambiguous"}
    assert out["stats"]["runs_collapsed"] == 1 and out["stats"]["compared"] == 1
    assert compare.calls[0]["ai"].startswith(str(parity))         # the filed copy
    assert len(compare.calls) == 1
    folder = Path(out["folder"])
    share_page = (folder / "period_summary.html").read_text("utf-8")
    portal_page = (folder / "period_summary.portal.html").read_text("utf-8")
    assert 'href="../../Acme/12677-01-GA/' in share_page
    assert 'href="/api/file?path=' in portal_page and "12677.full_parity.html" in portal_page
    assert "Ambiguous: choose the manual sheet" in share_page and "2 runs, newest used" in share_page
    body = json.loads(status.read_text("utf-8"))
    assert body["finished"] is True and body["summary_portal_html"].endswith(".portal.html")
    assert parity_job.search("12677")[0]["made_by"] == "period 2026-10-01 to 2026-10-31"
    assert newest.exists()


def test_a_pair_already_compared_with_the_same_sheet_is_reused(shares, compare):
    manual, aisheets, _ = shares
    _october(manual, aisheets)
    parity_job.run_period("2026-10-01", "2026-10-31", compare=compare, say=lambda m: None)
    again = parity_job.run_period("2026-10-01", "2026-10-31", compare=compare, say=lambda m: None)
    assert len(compare.calls) == 1
    row = next(r for r in again["rows"] if r["drawing"] == "12677-01-GA")
    assert row["reused"] is True and row["outcome"] == "warning"


def test_a_preview_files_nothing(shares, compare):
    manual, aisheets, parity = shares
    _october(manual, aisheets)
    out = parity_job.run_period("2026-10-01", "2026-10-31", preview=True, compare=compare,
                                say=lambda m: None)
    assert {r["outcome"] for r in out["rows"]} == {"would compare", "no manual", "ambiguous"}
    assert compare.calls == [] and not parity.exists()


def test_a_period_backwards_is_refused(shares):
    with pytest.raises(parity_job.ParityJobError, match="end not before the start"):
        parity_job.runs_between("2026-10-31", "2026-10-01")


# ── the time frame is any two moments (D-625) ───────────────────────────────────────────

def test_one_day_is_a_period_on_its_own(shares, compare):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 09-15-00")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 14-30-00")
    out = parity_job.run_period("2026-10-31", "2026-10-31", preview=True, compare=compare,
                                say=lambda m: None)
    row = out["rows"][0]
    assert row["runs_in_period"] == 2 and "14-30-00" in row["ai_run"]


def test_a_time_narrows_the_period_within_a_day(shares, compare):
    """Two runs of the same drawing on the same day: 09:00 to 12:00 sees only the morning one,
    and an afternoon window only the afternoon one, so same-day runs can be compared apart."""
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 09-15-00")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 14-30-00")
    morning = parity_job.run_period("2026-10-31 09:00", "2026-10-31 12:00", preview=True,
                                    compare=compare, say=lambda m: None)
    assert [r["ai_run"] for r in morning["rows"]] == ["2026-10-31 09-15-00 (1 off)"]
    assert morning["rows"][0]["runs_in_period"] == 1
    afternoon = parity_job.run_period("2026-10-31 12:00", "2026-10-31 23:59", preview=True,
                                      compare=compare, say=lambda m: None)
    assert [r["ai_run"] for r in afternoon["rows"]] == ["2026-10-31 14-30-00 (1 off)"]


def test_an_end_given_to_the_minute_includes_that_whole_minute(shares, compare):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 12-00-30")
    out = parity_job.run_period("2026-10-31 09:00", "2026-10-31 12:00", preview=True,
                                compare=compare, say=lambda m: None)
    assert len(out["rows"]) == 1


def test_a_timed_period_files_to_a_folder_windows_accepts(shares, compare):
    """A boundary with a time carries ':', which Windows refuses in a folder name."""
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 09-15-00")
    out = parity_job.run_period("2026-10-31 09:00", "2026-10-31 12:00", compare=compare,
                                say=lambda m: None)
    folder = Path(out["folder"])
    assert folder.is_dir() and ":" not in folder.name
    assert (folder / "period_summary.html").is_file()


def test_a_backwards_or_nonsense_time_is_refused(shares):
    with pytest.raises(parity_job.ParityJobError, match="end not before the start"):
        parity_job.runs_between("2026-10-31 14:00", "2026-10-31 09:00")
    with pytest.raises(parity_job.ParityJobError, match="not a time of day"):
        parity_job.runs_between("2026-10-31 25:00", "2026-10-31")


def test_search_narrows_by_time_as_well_as_date(shares, compare):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 09-00-00")
    early = time.mktime((2026, 10, 31, 9, 15, 0, 0, 0, -1))
    late = time.mktime((2026, 10, 31, 14, 30, 0, 0, 0, -1))
    parity_job.run_job("12677-01-GA", compare=compare, now=early)
    parity_job.run_job("12677-01-GA", compare=compare, now=late)
    found = parity_job.search("12677", start="2026-10-31 12:00", end="2026-10-31")
    assert [x["stamp"] for x in found] == ["2026-10-31 14-30-00"]
    assert len(parity_job.search("12677", start="2026-10-31", end="2026-10-31")) == 2


def test_one_job_failing_does_not_stop_the_period(shares):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _touch(manual / "2026" / "Acme" / "12678" / "12678-01-GA ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-20 09-00-00")
    _ai_run(aisheets, "Acme", "12678-01-GA", "2026-10-20 10-00-00")
    good = make_compare(status="match")

    def flaky(ai, manual, out_dir, read_via_excel):
        if "12677" in manual:
            raise RuntimeError("the workbook could not be read")
        return good(ai, manual, out_dir, read_via_excel)
    out = parity_job.run_period("2026-10-01", "2026-10-31", compare=flaky, say=lambda m: None)
    assert [r["outcome"] for r in out["rows"]] == ["failed", "match"]


# ── two periods ─────────────────────────────────────────────────────────────────────────

def test_period_a_against_period_b(shares):
    manual, aisheets, parity = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _touch(manual / "2026" / "Acme" / "12678" / "12678-01-GA ISS 1.xls")
    _touch(manual / "2026" / "Beta" / "13000" / "13000-01 ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-09-10 09-00-00")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-10 09-00-00")
    _ai_run(aisheets, "Acme", "12678-01-GA", "2026-10-11 09-00-00")
    _ai_run(aisheets, "Beta", "13000-01", "2026-10-12 09-00-00")
    pcts = iter([12.0, 4.0, 2.0])

    def compare(ai, manual, out_dir, read_via_excel):
        pct = next(pcts)
        status = "match" if pct <= 3 else "warning" if pct <= 10 else "fail"
        return make_compare(pct=pct, status=status)(ai, manual, out_dir, read_via_excel)
    out = parity_job.compare_periods(("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-31"),
                                     client="Acme", compare=compare, say=lambda m: None)
    assert out["stats_a"]["compared"] == 1 and out["stats_b"]["compared"] == 2
    assert out["stats_a"]["median_abs_pct"] == 12.0 and out["stats_b"]["median_abs_pct"] == 3.0
    assert out["change"]["median_abs_pct"] == -9.0
    assert out["in_both"] == [{"drawing": "12677-01-GA", "client": "Acme", "pct_a": 12.0,
                               "pct_b": 4.0, "change": -8.0}]
    assert all(r["client"] == "Acme" for r in out["rows_a"] + out["rows_b"]), "client filter"
    folder = Path(out["folder"])
    assert folder.name.startswith("A 2026-09-01 to 2026-09-30 vs B 2026-10-01 to 2026-10-31 (run ")
    page = (folder / "comparison.portal.html").read_text("utf-8")
    assert "Drawings estimated in both periods" in page and "-8.0 pts" in page
    kinds = {h["kind"] for h in parity_job.history()}
    assert kinds == {"two periods"}
    only = parity_job.compare_periods(("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-31"),
                                      job="12678", preview=True, compare=compare, say=lambda m: None)
    assert [r["drawing"] for r in only["rows_b"]] == ["12678-01-GA"] and only["rows_a"] == []


# ── the command line the service calls ─────────────────────────────────────────────────

def test_find_says_whether_the_choice_is_clear(shares, capsys):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-20 09-00-00")
    assert parity_job.main(["find", "12677-01-GA", "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["client"] == "Acme" and out["decision"]["clear"] is True
    assert out["manual"][0]["name"] == "12677-01-GA ISS 1.xls" and len(out["ai"]) == 1


def test_an_ambiguous_job_exits_3_with_the_candidates_and_says_so_in_the_status(shares, capsys, tmp_path):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA a.xls")
    _touch(manual / "2026" / "Acme" / "12677" / "12677-01-GA b.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-20 09-00-00")
    status = tmp_path / "s.json"
    assert parity_job.main(["job", "12677-01-GA", "--json", "--status-file", str(status)]) == 3
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["choose"] is True and len(out["candidates"]) == 2
    assert json.loads(status.read_text("utf-8"))["state"] == "choose"


def test_no_manual_exits_2_and_a_period_that_cannot_start_says_so(shares, capsys, tmp_path, monkeypatch):
    shares[0].mkdir(parents=True)
    _ai_run(shares[1], "Acme", "99999-01", "2026-10-20 09-00-00")
    assert parity_job.main(["job", "99999-01", "--json"]) == 2
    assert "No manual estimate was found for 99999" in json.loads(
        capsys.readouterr().out.strip().splitlines()[-1])["error"]
    monkeypatch.setenv("SDI_ESTIMATE_OUTPUT_ROOT", str(tmp_path / "unreachable"))
    status = tmp_path / "p.json"
    assert parity_job.main(["period", "--from", "2026-10-01", "--to", "2026-10-31", "--json",
                            "--status-file", str(status)]) == 2
    body = json.loads(status.read_text("utf-8"))
    assert body["finished"] is True and "not reachable" in body["error"]


# ── a set of jobs (D-742) ───────────────────────────────────────────────────────────────
# JG, 7 Nov 2026: "I want to run one off jobs, compare a whole set of jobs v manual etc."

def test_a_set_names_its_jobs_and_compares_each_drawing_once(shares, compare, tmp_path):
    manual, aisheets, parity = shares
    _october(manual, aisheets)
    _touch(manual / "2026" / "Acme" / "12677" / "12677-02 ISS 1.xls")
    _ai_run(aisheets, "Acme", "12677-02", "2026-10-25 09-00-00")
    status = tmp_path / "state" / "set.json"
    out = parity_job.run_jobs("12677, 55555-01\n77777-01; 12677-01-GA 99999 hello",
                              compare=compare, say=lambda m: None, status_file=status)
    outcomes = {r["drawing"]: r["outcome"] for r in out["rows"]}
    # A bare job number takes every drawing estimated under it; a repeat is taken once.
    assert outcomes == {"12677-01-GA": "warning", "12677-02": "warning", "55555-01": "no manual",
                        "77777-01": "ambiguous", "99999": "no AI run"}
    assert out["jobs"] == ["12677", "55555-01", "77777-01", "12677-01-GA", "99999"]
    assert out["not_job_numbers"] == ["hello"]
    assert out["stats"]["compared"] == 2 and out["stats"]["no AI run"] == 1
    row = next(r for r in out["rows"] if r["drawing"] == "12677-01-GA")
    assert row["ai_run"].startswith("2026-10-20") and row["runs_in_period"] == 2
    folder = Path(out["folder"])
    assert folder.parent.name == "_periods" and folder.name.startswith("jobs 5 12677 to 99999")
    page = (folder / "jobs_summary.portal.html").read_text("utf-8")
    assert "a set of 5 jobs" in page and "No AI estimate found" in page
    body = json.loads(status.read_text("utf-8"))
    assert body["finished"] is True and body["kind"] == "jobs" and body["done"] == body["of"] == 4
    assert parity_job.history(parity)[0]["kind"] == "jobs"
    assert parity_job.history(parity)[0]["job_count"] == 5


def test_a_set_preview_files_nothing_and_a_client_narrows_it(shares, compare):
    manual, aisheets, parity = shares
    _october(manual, aisheets)
    _ai_run(aisheets, "Other", "12677-01-GA", "2026-10-28 09-00-00")
    out = parity_job.run_jobs(["12677-01-GA", "55555-01"], client="Acme", preview=True,
                              compare=compare, say=lambda m: None)
    assert {r["drawing"]: r["outcome"] for r in out["rows"]} == {
        "12677-01-GA": "would compare", "55555-01": "no manual"}
    assert next(r for r in out["rows"] if r["drawing"] == "12677-01-GA")["client"] == "Acme"
    assert compare.calls == [] and not parity.exists()


def test_a_set_with_no_job_number_in_it_is_refused(shares):
    with pytest.raises(parity_job.ParityJobError, match="not job numbers: hello, world"):
        parity_job.run_jobs("hello world", preview=True, say=lambda m: None)
