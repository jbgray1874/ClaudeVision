"""Parity by job number: find both estimates, compare them, file the comparison (D-619).

JG, 1 Nov 2026: compare one job "by job number ... the manual estimates live at
K:\\Estimating\\Completed\\Manual Estimates\\2026\\$client.. we take the most obvious s/sheet
candidate and we run a parity against it from our AI estimate with html outputs. the s/sheets
that are used are stored at K:\\Estimating\\Completed\\AI Estimating\\parity and below this for
every run we save down the two s/sheets compared and the parity reports that are available to
be searched through ... also, can run a search and comparison between all manual and AI
estimates ran across two time periods."

The comparison itself is parity_run.run_parity, tested on its own; here it is a stand-in that
records what it was handed and writes a report, so these tests are about finding, filing and
searching.
"""
from __future__ import annotations

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


def _ai_run(aisheets: Path, client: str, drawing: str, stamp: str, units: int = 1,
            summary: bool = True) -> Path:
    folder = aisheets / client / drawing / f"{stamp} ({units} off)"
    digits = drawing.split("-")[0]
    book = _touch(folder / f"{digits}_{stamp[:10].replace('-', '')}_101500.xlsx")
    _touch(folder / f"{drawing} Quote.html")
    if summary:
        _touch(folder / f"{digits}.json", json.dumps({"stamp": stamp}))
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


@pytest.fixture()
def compare():
    calls = []

    def fake(ai, manual, out_dir, read_via_excel):
        calls.append({"ai": ai, "manual": manual, "out_dir": str(out_dir)})
        html = Path(out_dir) / "12677.full_parity.html"
        html.write_text("<h1>parity</h1>", encoding="utf-8")
        bundle = Path(out_dir) / "12677.full_parity.bundle.json"
        bundle.write_text("{}", encoding="utf-8")
        return {"bundle_html": str(html), "bundle_json": str(bundle), "bundle_csv": "",
                "headline": {"ai_unit_cost_gbp": 421.37, "manual_unit_cost_gbp": 400.0,
                             "gap_gbp": 21.37, "pct_variance": 5.3, "status": "warning"}}
    fake.calls = calls
    return fake


# ── finding the manual estimate ─────────────────────────────────────────────────────────

def test_the_job_folder_under_the_client_is_found_and_the_latest_issue_chosen(shares):
    manual, _, _ = shares
    job = manual / "2026" / "TTI" / "1282- MILWAUKEE RED 50cm PEG"
    _touch(job / "1282-MILWAUKEE 50CM PEG WALL BAY(ISS 6)-.xls", age_days=20)
    _touch(job / "1282-MILWAUKEE 50CM PEG WALL BAY(ISS 7)-.xls", age_days=10)
    _touch(job / "1282 copy of ISS 7.xls", age_days=1)
    _touch(job / "~$1282-MILWAUKEE.xls")
    _touch(job / "drawing.pdf")
    found = parity_job.find_manual("1282")
    assert [c["name"] for c in found] == ["1282-MILWAUKEE 50CM PEG WALL BAY(ISS 7)-.xls",
                                          "1282-MILWAUKEE 50CM PEG WALL BAY(ISS 6)-.xls",
                                          "1282 copy of ISS 7.xls"]
    assert found[0]["client"] == "TTI" and found[0]["year"] == "2026"
    assert "issue 7" in found[0]["why"]
    assert "copy" in found[-1]["why"]


def test_a_workbook_naming_the_full_drawing_beats_one_that_does_not(shares):
    manual, _, _ = shares
    job = manual / "2026" / "Acme" / "12677 frame"
    _touch(job / "12677 general.xlsx", age_days=1)
    _touch(job / "12677-01-GA estimate.xlsx", age_days=5)
    found = parity_job.find_manual("12677-01-GA")
    assert found[0]["name"] == "12677-01-GA estimate.xlsx"
    assert "names the drawing" in found[0]["why"]


def test_the_newest_year_holding_the_job_wins_and_other_jobs_are_ignored(shares):
    manual, _, _ = shares
    _touch(manual / "2025" / "Acme" / "12677 old" / "12677 est.xls")
    _touch(manual / "2026" / "Acme" / "12677 new" / "12677 est.xls")
    _touch(manual / "2026" / "Acme" / "126770 another job" / "126770 est.xls")
    _touch(manual / "2026" / "Acme" / "1267 short" / "1267 est.xls")
    found = parity_job.find_manual("12677-01-GA")
    assert len(found) == 1 and "2026" in found[0]["path"] and "12677 new" in found[0]["path"]


def test_a_loose_workbook_in_the_client_folder_is_found(shares):
    manual, _, _ = shares
    _touch(manual / "2026" / "Acme" / "12677-01-GA rev B.xlsm")
    assert parity_job.find_manual("12677")[0]["name"] == "12677-01-GA rev B.xlsm"


def test_templates_are_never_offered(shares):
    manual, _, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677 Blank Estimate.xls")
    assert parity_job.find_manual("12677") == []


def test_no_job_number_is_a_plain_answer(shares):
    with pytest.raises(parity_job.ParityJobError, match="does not start with a job number"):
        parity_job.find_manual("frame")


def test_an_unreachable_manual_folder_is_named(shares, monkeypatch, tmp_path):
    monkeypatch.setenv("SDI_MANUAL_ESTIMATES_ROOT", str(tmp_path / "nowhere"))
    with pytest.raises(parity_job.ParityJobError, match="not reachable"):
        parity_job.find_manual("12677")


# ── finding the AI estimate ─────────────────────────────────────────────────────────────

def test_the_newest_ai_run_with_a_summary_is_chosen(shares):
    _, aisheets, _ = shares
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-30 09-00-00")
    newest = _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00", units=5)
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-11-01 08-00-00", summary=False)
    runs = parity_job.find_ai("12677-01-GA")
    assert runs[0]["workbook"] == str(newest) and runs[0]["units"] == 5
    assert runs[0]["summary"].endswith("12677.json")
    assert len(runs) == 2, "a run folder with no summary cannot be compared"


def test_the_exact_drawing_ranks_before_a_sibling_of_the_same_job(shares):
    _, aisheets, _ = shares
    _ai_run(aisheets, "Acme", "12677-02-GA", "2026-11-01 08-00-00")
    exact = _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-30 08-00-00")
    assert parity_job.find_ai("12677-01-GA")[0]["workbook"] == str(exact)


# ── one job, filed ──────────────────────────────────────────────────────────────────────

def test_one_job_is_compared_and_both_sheets_and_the_report_are_filed(shares, compare):
    manual, aisheets, parity = shares
    sheet = _touch(manual / "2026" / "Acme" / "12677 frame" / "12677-01-GA ISS 2.xls")
    book = _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00")
    idx = parity_job.run_job("12677-01-GA", compare=compare,
                             now=time.mktime((2026, 11, 1, 14, 5, 0, 0, 0, -1)))
    folder = parity / "Acme" / "12677-01-GA" / "2026-11-01 14-05-00"
    assert idx["folder"] == str(folder)
    names = sorted(p.name for p in folder.iterdir())
    assert names == sorted(["manual - 12677-01-GA ISS 2.xls", f"ai - {book.name}",
                            "ai - 12677.json", "12677.full_parity.html",
                            "12677.full_parity.bundle.json", "parity_index.json"])
    # The run's own summary went in, not its workbook, so the engine's JSON folder cannot
    # substitute a newer run's reading.
    assert compare.calls[0]["ai"].endswith(os.path.join("2026-10-31 11-00-00 (1 off)", "12677.json"))
    assert compare.calls[0]["manual"] == str(sheet)
    saved = json.loads((folder / "parity_index.json").read_text("utf-8"))
    assert saved["manual"]["source"] == str(sheet)
    assert saved["ai"]["run"] == "2026-10-31 11-00-00"
    assert saved["report_html"] == "12677.full_parity.html"
    assert saved["headline"]["status"] == "warning"


def test_a_second_comparison_in_the_same_second_gets_its_own_folder(shares, compare):
    manual, aisheets, parity = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00")
    when = time.mktime((2026, 11, 1, 14, 5, 0, 0, 0, -1))
    first = parity_job.run_job("12677-01-GA", compare=compare, now=when)
    second = parity_job.run_job("12677-01-GA", compare=compare, now=when)
    assert first["folder"] != second["folder"] and second["folder"].endswith("(2)")


def test_sheets_chosen_by_hand_keep_their_client_and_run(shares, compare):
    manual, aisheets, parity = shares
    sheet = _touch(manual / "2026" / "Acme Ltd" / "elsewhere" / "frame costing.xlsx")
    book = _ai_run(aisheets, "Acme Ltd", "12677-01-GA", "2026-10-29 10-00-00")
    idx = parity_job.run_job("12677-01-GA", manual=str(sheet), ai=str(book), compare=compare)
    assert idx["client"] == "Acme Ltd" and idx["drawing"] == "12677-01-GA"
    assert idx["manual"]["why"] == "chosen by hand"
    assert idx["ai"]["run"] == "2026-10-29 10-00-00"
    assert compare.calls[0]["ai"].endswith("12677.json")


def test_a_comparison_that_fails_is_filed_with_its_reason_and_found_by_search(shares):
    manual, aisheets, parity = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00")

    def broken(ai, manual, out_dir, read_via_excel):
        raise RuntimeError("JSON needs estimate_summary (dict).")
    with pytest.raises(parity_job.ParityJobError, match="could not be compared .*estimate_summary"):
        parity_job.run_job("12677-01-GA", compare=broken)
    found = parity_job.search("12677")
    assert len(found) == 1 and "estimate_summary" in found[0]["error"]
    assert found[0]["manual"]["copied_as"] == "manual - 12677.xls"


def test_no_manual_estimate_says_where_it_looked(shares, compare):
    manual, aisheets, _ = shares
    (manual / "2026" / "Acme").mkdir(parents=True)
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00")
    with pytest.raises(parity_job.ParityJobError, match="No manual estimate was found for 12677"):
        parity_job.run_job("12677-01-GA", compare=compare)
    assert compare.calls == []


def test_no_ai_estimate_says_run_it_first(shares, compare):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677.xls")
    aisheets.mkdir()
    with pytest.raises(parity_job.ParityJobError, match="Run the estimate first"):
        parity_job.run_job("12677-01-GA", compare=compare)


# ── search ──────────────────────────────────────────────────────────────────────────────

def test_filed_comparisons_are_found_by_text_and_by_date(shares, compare):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677.xls")
    _touch(manual / "2026" / "TTI" / "1282 peg" / "1282 ISS 7.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-31 11-00-00")
    _ai_run(aisheets, "TTI", "1282-01", "2026-10-31 12-00-00")
    parity_job.run_job("12677-01-GA", compare=compare,
                       now=time.mktime((2026, 10, 15, 9, 0, 0, 0, 0, -1)))
    parity_job.run_job("1282-01", compare=compare,
                       now=time.mktime((2026, 11, 1, 9, 0, 0, 0, 0, -1)))
    assert [i["drawing"] for i in parity_job.search()] == ["1282-01", "12677-01-GA"]
    assert [i["drawing"] for i in parity_job.search("tti")] == ["1282-01"]
    assert [i["drawing"] for i in parity_job.search("12677")] == ["12677-01-GA"]
    assert [i["drawing"] for i in parity_job.search(start="2026-10-01", end="2026-10-31")] \
        == ["12677-01-GA"]
    with pytest.raises(parity_job.ParityJobError, match="YYYY-MM-DD"):
        parity_job.search(start="1/10/26")


def test_search_before_anything_is_filed_is_empty(shares):
    assert parity_job.search() == []


# ── a period ────────────────────────────────────────────────────────────────────────────

def test_a_period_compares_the_newest_run_of_each_drawing_and_writes_one_summary(shares, compare):
    manual, aisheets, parity = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-02 09-00-00")
    newest = _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-20 09-00-00")
    _ai_run(aisheets, "Acme", "55555-01", "2026-10-21 09-00-00")          # no manual estimate
    _ai_run(aisheets, "Acme", "66666-01", "2026-11-02 09-00-00")          # outside the period
    out = parity_job.run_period("2026-10-01", "2026-10-31", compare=compare, say=lambda m: None)
    assert (out["compared"], out["no_manual"], out["failed"]) == (1, 1, 0)
    assert [r["drawing"] for r in out["rows"]] == ["12677-01-GA", "55555-01"]
    assert compare.calls[0]["ai"].startswith(str(newest.parent))
    folder = Path(out["folder"])
    assert folder.parent == parity / "_periods"
    assert folder.name.startswith("2026-10-01 to 2026-10-31 (run ")
    page = (folder / "period_summary.html").read_text("utf-8")
    assert "12677-01-GA" in page and "£421.37" in page and "+5.3%" in page
    assert 'href="../../Acme/12677-01-GA/' in page
    status = json.loads((folder / "status.json").read_text("utf-8"))
    assert status["finished"] is True and status["done"] == status["of"] == 2
    # Each compared job is filed like a single one, so search finds it too.
    assert [i["drawing"] for i in parity_job.search("12677")] == ["12677-01-GA"]
    assert parity_job.search("12677")[0]["made_by"] == "period 2026-10-01 to 2026-10-31"


def test_the_service_status_file_follows_the_period_and_the_period_is_listed(shares, compare,
                                                                            tmp_path):
    manual, aisheets, parity = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-20 09-00-00")
    status = tmp_path / "state" / "period-1.json"
    out = parity_job.run_period("2026-10-01", "2026-10-31", compare=compare, say=lambda m: None,
                                status_file=status)
    body = json.loads(status.read_text("utf-8"))
    assert body["finished"] is True and body["folder"] == out["folder"]
    assert body["summary_html"].endswith("period_summary.html")
    listed = parity_job.periods()
    assert len(listed) == 1 and listed[0]["start"] == "2026-10-01" and listed[0]["compared"] == 1


def test_a_period_that_cannot_start_says_so_in_the_status_file(shares, tmp_path, monkeypatch):
    monkeypatch.setenv("SDI_ESTIMATE_OUTPUT_ROOT", str(tmp_path / "unreachable"))
    status = tmp_path / "state" / "period-2.json"
    assert parity_job.main(["period", "--from", "2026-10-01", "--to", "2026-10-31", "--json",
                            "--status-file", str(status)]) == 2
    body = json.loads(status.read_text("utf-8"))
    assert body["finished"] is True and "not reachable" in body["error"]


def test_a_preview_files_nothing(shares, compare):
    manual, aisheets, parity = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-20 09-00-00")
    out = parity_job.run_period("2026-10-01", "2026-10-31", preview=True, compare=compare,
                                say=lambda m: None)
    assert out["rows"][0]["outcome"] == "would compare" and compare.calls == []
    assert not parity.exists()


def test_a_period_backwards_is_refused(shares):
    with pytest.raises(parity_job.ParityJobError, match="end not before the start"):
        parity_job.runs_between("2026-10-31", "2026-10-01")


def test_one_job_failing_does_not_stop_the_period(shares):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677.xls")
    _touch(manual / "2026" / "Acme" / "12678" / "12678.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-20 09-00-00")
    _ai_run(aisheets, "Acme", "12678-01-GA", "2026-10-20 10-00-00")

    def flaky(ai, manual, out_dir, read_via_excel):
        if "12677" in manual:
            raise RuntimeError("the workbook could not be read")
        return {"headline": {"status": "match"}}
    out = parity_job.run_period("2026-10-01", "2026-10-31", compare=flaky, say=lambda m: None)
    assert [r["outcome"] for r in out["rows"]] == ["failed", "compared"]
    assert "could not be read" in out["rows"][0]["note"]


# ── the command line the service calls ─────────────────────────────────────────────────

def test_the_command_line_answers_in_one_json_line(shares, capsys):
    manual, aisheets, _ = shares
    _touch(manual / "2026" / "Acme" / "12677" / "12677.xls")
    _ai_run(aisheets, "Acme", "12677-01-GA", "2026-10-20 09-00-00")
    assert parity_job.main(["find", "12677-01-GA", "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["manual"][0]["name"] == "12677.xls" and len(out["ai"]) == 1


def test_the_command_line_exits_2_with_the_reason(shares, capsys):
    shares[0].mkdir(parents=True)
    assert parity_job.main(["job", "99999", "--json"]) == 2
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "No manual estimate was found for 99999" in out["error"]
