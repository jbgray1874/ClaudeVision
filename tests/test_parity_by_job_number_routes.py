"""The service routes for parity by job number (D-619, D-621), and the runner's filing.

The routes run src/parity_job.py in the engine's Python; here that is this interpreter, with
the three shares in a temporary folder, so find, search and a preview are the real thing end to
end. A background comparison is started with Popen stubbed, and its status file written as the
command line writes it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_estimate_queue import api  # noqa: E402,F401


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture()
def shares(api, tmp_path, monkeypatch):
    er, _ = api
    manual, aisheets, parity = tmp_path / "Manual", tmp_path / "AISheets", tmp_path / "parity"
    for name, path in (("SDI_MANUAL_ESTIMATES_ROOT", manual),
                       ("SDI_ESTIMATE_OUTPUT_ROOT", aisheets), ("SDI_PARITY_ROOT", parity)):
        monkeypatch.setenv(name, str(path))
    monkeypatch.setattr(er, "_ENGINE_PYTHON", sys.executable)
    monkeypatch.setattr(er, "PARITY_ROOT", parity)
    er._PARITY_RUNNING.clear()
    sheet = _touch(manual / "2026" / "Acme" / "12677 frame" / "12677-01-GA ISS 2.xls")
    run = aisheets / "Acme" / "12677-01-GA" / "2026-10-31 11-00-00 (1 off)"
    book = _touch(run / "12677_20261031_110000.xlsx")
    _touch(run / "12677.json", "{}")
    return er, sheet, book, parity


@pytest.fixture()
def popen(shares, monkeypatch):
    er = shares[0]
    started = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            started.append(cmd)
    monkeypatch.setattr(er.subprocess, "Popen", FakePopen)
    return started


def _status_path(cmd):
    return Path(cmd[cmd.index("--status-file") + 1])


def test_find_lists_both_sides_with_links_and_the_decision(shares):
    er, sheet, book, _ = shares
    body = er.parity_find(job="12677-01-GA")
    assert body["manual"][0]["path"] == str(sheet)
    assert body["manual"][0]["url"].startswith("/api/file?path=")
    assert body["ai"][0]["workbook"] == str(book)
    assert body["client"] == "Acme" and body["decision"]["clear"] is True


def test_find_without_a_job_number_is_a_400_in_plain_words(shares):
    er = shares[0]
    with pytest.raises(er.HTTPException) as caught:
        er.parity_find(job="frame")
    assert caught.value.status_code == 400
    assert "does not start with a job number" in caught.value.detail


def test_a_hand_picked_sheet_outside_the_shares_is_refused(shares):
    er = shares[0]
    with pytest.raises(er.HTTPException) as caught:
        er.parity_job_run(er.ParityJobRequest(job="12677", manual_path=r"C:\Windows\x.xls"))
    assert caught.value.status_code == 403


def test_one_comparison_runs_in_the_background_and_its_result_carries_links(shares, popen):
    er, sheet, book, parity = shares
    body = er.parity_job_run(er.ParityJobRequest(job="12677-01-GA", manual_path=str(sheet),
                                                 ai_path=str(book), client="Acme"))
    cmd = popen[0]
    assert body["started"] is True and body["status_url"].endswith(body["task_id"])
    assert cmd[cmd.index("--manual") + 1] == str(sheet) and cmd[cmd.index("--ai") + 1] == str(book)
    assert cmd[cmd.index("--client") + 1] == "Acme"
    assert er.parity_task_status(body["task_id"])["state"] == "starting"
    folder = parity / "Acme" / "12677-01-GA" / "2026-11-01 14-05-00_ab12cd34"
    _status_path(cmd).write_text(json.dumps({"state": "done", "finished": True, "result": {
        "folder": str(folder), "report_html": "12677.full_parity.html", "bundle_json": "b.json",
        "bundle_csv": "", "manual": {"copied_as": "manual/x.xls"},
        "ai": {"copied_as": "ai/y.xlsx"}, "outcome": "match"}}))
    done = er.parity_task_status(body["task_id"])["result"]
    assert "12677.full_parity.html" in done["report_url"]
    assert done["manual_url"].endswith("_ab12cd34/manual/x.xls")
    assert done["ai_url"].endswith("_ab12cd34/ai/y.xlsx")
    assert done["bundle_csv_url"] is None


def test_the_same_comparison_asked_again_while_running_is_not_started_twice(shares, popen):
    er, sheet, book, _ = shares
    req = er.ParityJobRequest(job="12677-01-GA", manual_path=str(sheet), ai_path=str(book))
    first = er.parity_job_run(req)
    again = er.parity_job_run(req)
    assert again["already_running"] is True and again["task_id"] == first["task_id"]
    assert len(popen) == 1
    _status_path(popen[0]).write_text(json.dumps({"state": "done", "finished": True}))
    assert er.parity_job_run(req)["started"] is True and len(popen) == 2


def test_an_ambiguous_choice_comes_back_with_the_candidates_to_choose_from(shares, popen):
    er = shares[0]
    body = er.parity_job_run(er.ParityJobRequest(job="12677-01-GA"))
    _status_path(popen[0]).write_text(json.dumps({
        "state": "choose", "finished": True, "choose": True, "error": "2 sheets are equally likely",
        "candidates": [{"path": r"\\srv\Manual\a.xls"}, {"path": r"\\srv\Manual\b.xls"}]}))
    status = er.parity_task_status(body["task_id"])
    assert status["state"] == "choose" and status["candidates"][0]["url"].startswith("/api/file?path=")


def test_reports_lists_what_has_been_filed_by_outcome_and_the_periods(shares):
    er, _, _, parity = shares
    for name, outcome in (("2026-11-01 14-05-00_aaaa1111", "match"),
                          ("2026-11-01 15-05-00_bbbb2222", "fail")):
        _touch(parity / "Acme" / "12677-01-GA" / name / "parity_index.json", json.dumps({
            "job": "12677", "drawing": "12677-01-GA", "client": "Acme",
            "stamp": name[:19], "report_html": "r.html", "outcome": outcome,
            "manual": {"copied_as": "manual/a.xls"}, "ai": {"copied_as": "ai/b.xlsx"}}))
    period = parity / "_periods" / "2026-10-01 to 2026-10-31 (run 2026-11-01 15-00-00)"
    _touch(period / "period_summary.json", json.dumps({"kind": "period", "start": "2026-10-01",
                                                       "end": "2026-10-31",
                                                       "stats": {"compared": 3}}))
    body = er.parity_reports(q="acme")
    assert [r["outcome"] for r in body["reports"]] == ["fail", "match"]
    assert [r["outcome"] for r in er.parity_reports(outcome="match")["reports"]] == ["match"]
    assert "r.html" in body["reports"][0]["report_url"]
    assert body["periods"][0]["compared"] == 3
    assert "period_summary.portal.html" in body["periods"][0]["summary_url"]
    with pytest.raises(er.HTTPException) as caught:
        er.parity_reports(start="1/10/26")
    assert caught.value.status_code == 400


def test_a_period_runs_in_the_background_with_its_filters(shares, popen):
    er = shares[0]
    body = er.parity_period(er.ParityPeriodRequest(start="2026-10-01", end="2026-10-31",
                                                   client="Acme", job="12677"))
    cmd = popen[0]
    assert cmd[cmd.index("--from") + 1] == "2026-10-01" and cmd[cmd.index("--client") + 1] == "Acme"
    assert cmd[cmd.index("--job") + 1] == "12677" and body["period_id"] == body["task_id"]
    _status_path(cmd).write_text(json.dumps({
        "finished": True, "done": 1, "of": 1,
        "summary_html": r"\\srv\parity\_periods\x\period_summary.html",
        "summary_portal_html": r"\\srv\parity\_periods\x\period_summary.portal.html",
        "rows": [{"folder": r"\\srv\parity\Acme\1", "report": "r.html", "outcome": "match"}]}))
    done = er.parity_period_status(body["task_id"])
    assert "period_summary.portal.html" in done["summary_url"]
    assert "r.html" in done["rows"][0]["report_url"]


def test_a_period_preview_answers_at_once(shares):
    er = shares[0]
    body = er.parity_period(er.ParityPeriodRequest(start="2026-10-01", end="2026-10-31",
                                                   preview=True))
    assert body["rows"][0]["outcome"] == "would compare" and body["preview"] is True


def test_two_periods_are_compared_in_the_background(shares, popen):
    er = shares[0]
    body = er.parity_two_periods(er.ParityTwoPeriodsRequest(
        a_start="2026-09-01", a_end="2026-09-30", b_start="2026-10-01", b_end="2026-10-31",
        client="Acme"))
    cmd = popen[0]
    assert cmd[1].endswith("parity_job.py") and cmd[2] == "periods"
    assert cmd[cmd.index("--a-from") + 1] == "2026-09-01" and cmd[cmd.index("--b-to") + 1] == "2026-10-31"
    assert body["started"] is True


def test_two_periods_preview_answers_at_once(shares):
    er = shares[0]
    preview = er.parity_two_periods(er.ParityTwoPeriodsRequest(
        a_start="2026-09-01", a_end="2026-09-30", b_start="2026-10-01", b_end="2026-10-31",
        preview=True))
    assert preview["rows_a"] == [] and preview["rows_b"][0]["outcome"] == "would compare"


def test_an_unknown_or_malformed_task_id_is_a_404(shares):
    er = shares[0]
    for tid in ("0123456789ab", "../../etc"):
        with pytest.raises(er.HTTPException) as caught:
            er.parity_task_status(tid)
        assert caught.value.status_code == 404


def test_a_run_with_a_manual_estimate_tells_the_runner_where_to_file_its_parity(api):
    er, root = api
    from test_estimate_queue import _check_in, _request
    _check_in(er)
    sheet = _touch(root / "manual" / "12677.xls")
    req = _request(er, root)
    req.manual_workbook = str(sheet)
    er.start(req)
    job = _check_in(er)["run"]
    assert job["manual_workbook"] == str(sheet) and job["parity_root"] == str(er.PARITY_ROOT)
    assert job["compare_with_manual"] is False


def test_a_run_asked_to_compare_when_it_finishes_tells_the_runner_so(api):
    er, root = api
    from test_estimate_queue import _check_in, _request
    _check_in(er)
    req = _request(er, root)
    req.compare_with_manual = True
    er.start(req)
    job = _check_in(er)["run"]
    assert job["compare_with_manual"] is True and job["parity_root"] == str(er.PARITY_ROOT)


def test_a_run_without_either_files_no_parity(api):
    er, root = api
    from test_estimate_queue import _check_in, _request
    _check_in(er)
    er.start(_request(er, root))
    assert _check_in(er)["run"]["parity_root"] == ""


# ── at the time of a run: the runner files the comparison too ──────────────────────────

def _runner():
    sys.path.insert(0, str(ROOT / "tools" / "runner"))
    import sdi_estimate_runner
    return sdi_estimate_runner


def _filed(tmp_path):
    run = tmp_path / "AISheets" / "Acme" / "12677-01-GA" / "2026-11-01 09-00-00 (1 off)"
    book = _touch(run / "12677_20261101_090000.xlsx")
    quote = _touch(run / "12677-01-GA Quote.html")
    _touch(run / "12677.json", "{}")
    return [{"name": quote.name, "path": str(quote)}, {"name": book.name, "path": str(book)},
            {"name": "12677.json", "path": str(run / "12677.json")}]


class _Done:
    def __init__(self, code, body):
        self.returncode, self.stdout, self.stderr = code, json.dumps(body), ""


def test_the_runner_files_the_comparison_with_the_engines_workbook(tmp_path, monkeypatch):
    runner = _runner()
    filed = _filed(tmp_path)
    manual = _touch(tmp_path / "Manual" / "12677.xls")
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw["env"]["SDI_PARITY_ROOT"]))
        return _Done(0, {"folder": str(tmp_path / "parity" / "Acme" / "x")})
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    log = []
    job = {"run_id": "abc123", "drawing_number": "12677-01-GA", "client": "Acme",
           "manual_workbook": str(manual), "parity_root": str(tmp_path / "parity")}
    folder = runner.file_parity(job, filed, ROOT, Path(sys.executable), log)
    cmd, root = calls[0]
    assert folder.endswith("x") and root == str(tmp_path / "parity")
    assert cmd[cmd.index("--ai") + 1] == filed[1]["path"], "the engine's workbook, not the quote"
    assert cmd[cmd.index("--manual") + 1] == str(manual)
    assert cmd[cmd.index("--made-by") + 1] == "run abc123"
    assert log == [f"[parity] comparison filed to {folder}"]


def test_compare_when_finished_finds_the_sheet_and_an_unclear_one_is_left_to_a_person(tmp_path, monkeypatch):
    runner = _runner()
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _Done(3, {"error": "2 sheets are equally likely", "choose": True})
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    log = []
    job = {"run_id": "abc123", "drawing_number": "12677-01-GA", "client": "Acme",
           "manual_workbook": "", "compare_with_manual": True,
           "parity_root": str(tmp_path / "parity")}
    assert runner.file_parity(job, _filed(tmp_path), ROOT, Path(sys.executable), log) == ""
    assert "--manual" not in calls[0] and calls[0][calls[0].index("--client") + 1] == "Acme"
    assert "not a clear choice" in log[0] and "Choose it on the parity card" in log[0]


def test_a_comparison_that_fails_is_logged_and_the_run_carries_on(tmp_path):
    runner = _runner()
    filed = _filed(tmp_path)
    manual = _touch(tmp_path / "Manual" / "12677.xls", "not a workbook")
    log = []
    job = {"run_id": "abc123", "drawing_number": "12677-01-GA", "manual_workbook": str(manual),
           "parity_root": str(tmp_path / "parity")}
    assert runner.file_parity(job, filed, ROOT, Path(sys.executable), log) == ""
    assert log and log[0].startswith("[parity] NOT filed to the parity folder")


def test_no_manual_and_no_compare_or_no_parity_root_files_nothing(tmp_path, monkeypatch):
    runner = _runner()
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("not called"))
    log = []
    for job in ({"manual_workbook": "", "parity_root": str(tmp_path)},
                {"manual_workbook": str(tmp_path / "m.xls"), "parity_root": ""}):
        assert runner.file_parity(job, _filed(tmp_path), ROOT, Path(sys.executable), log) == ""
    assert log == []
