"""The service routes for parity by job number (D-619): find, compare one, search, a period.

The routes run src/parity_job.py in the engine's Python; here that is this interpreter, with
the three shares in a temporary folder, so find and search are the real thing end to end. The
comparison itself needs real workbooks and is tested in test_parity_by_job_number.py; here the
run route is checked for what it passes on and what it hands back.
"""
from __future__ import annotations

import json
import sys
import time
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
    sheet = _touch(manual / "2026" / "Acme" / "12677 frame" / "12677-01-GA ISS 2.xls")
    run = aisheets / "Acme" / "12677-01-GA" / "2026-10-31 11-00-00 (1 off)"
    book = _touch(run / "12677_20261031_110000.xlsx")
    _touch(run / "12677.json", "{}")
    return er, sheet, book, parity


def test_find_lists_both_sides_with_links(shares):
    er, sheet, book, _ = shares
    body = er.parity_find(job="12677-01-GA")
    assert body["manual"][0]["path"] == str(sheet)
    assert body["manual"][0]["url"].startswith("/api/file?path=")
    assert body["ai"][0]["workbook"] == str(book)


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


def test_comparing_one_job_passes_the_choices_and_links_the_filed_files(shares, monkeypatch):
    er, sheet, book, parity = shares
    seen = {}

    def fake(args, timeout=300):
        seen["args"] = args
        return {"folder": str(parity / "Acme" / "12677-01-GA" / "2026-11-01 14-05-00"),
                "report_html": "12677.full_parity.html", "bundle_json": "b.json",
                "bundle_csv": "", "manual": {"copied_as": "manual - x.xls"},
                "ai": {"copied_as": "ai - y.xlsx"}, "headline": {"status": "match"}}
    monkeypatch.setattr(er, "_parity_job", fake)
    body = er.parity_job_run(er.ParityJobRequest(job="12677-01-GA", manual_path=str(sheet),
                                                 ai_path=str(book)))
    assert seen["args"][:2] == ["job", "12677-01-GA"]
    assert ["--manual", str(sheet)] == seen["args"][seen["args"].index("--manual"):][:2]
    assert ["--ai", str(book)] == seen["args"][seen["args"].index("--ai"):][:2]
    assert "12677.full_parity.html" in body["report_url"]
    assert "manual%20-%20x.xls" in body["manual_url"] and "ai%20-%20y.xlsx" in body["ai_url"]
    assert body["bundle_csv_url"] is None


def test_reports_lists_what_has_been_filed_and_the_periods(shares):
    er, _, _, parity = shares
    folder = parity / "Acme" / "12677-01-GA" / "2026-11-01 14-05-00"
    _touch(folder / "parity_index.json", json.dumps({
        "job": "12677", "drawing": "12677-01-GA", "client": "Acme",
        "stamp": "2026-11-01 14-05-00", "report_html": "r.html",
        "manual": {"copied_as": "manual - a.xls"}, "ai": {"copied_as": "ai - b.xlsx"}}))
    period = parity / "_periods" / "2026-10-01 to 2026-10-31 (run 2026-11-01 15-00-00)"
    _touch(period / "period_summary.json", json.dumps({"start": "2026-10-01",
                                                       "end": "2026-10-31", "compared": 3}))
    body = er.parity_reports(q="acme")
    assert [r["drawing"] for r in body["reports"]] == ["12677-01-GA"]
    assert "r.html" in body["reports"][0]["report_url"]
    assert body["periods"][0]["compared"] == 3
    assert "period_summary.html" in body["periods"][0]["summary_url"]
    assert er.parity_reports(q="nothing-like-it")["reports"] == []


def test_a_period_runs_in_the_background_and_its_progress_is_read_back(shares, monkeypatch):
    er = shares[0]
    started = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            started.append(cmd)
    monkeypatch.setattr(er.subprocess, "Popen", FakePopen)
    body = er.parity_period(er.ParityPeriodRequest(start="2026-10-01", end="2026-10-31"))
    pid = body["period_id"]
    cmd = started[0]
    assert cmd[cmd.index("--from") + 1] == "2026-10-01" and "--status-file" in cmd
    assert er.parity_period_status(pid)["done"] == 0
    # The CLI writes the same file as it goes; here, its last write.
    status = Path(cmd[cmd.index("--status-file") + 1])
    status.write_text(json.dumps({"finished": True, "done": 1, "of": 1,
                                  "summary_html": r"\\srv\parity\_periods\x\period_summary.html",
                                  "rows": [{"folder": r"\\srv\parity\Acme\1",
                                            "report": "r.html", "outcome": "compared"}]}))
    done = er.parity_period_status(pid)
    assert done["finished"] is True and "period_summary.html" in done["summary_url"]
    assert "r.html" in done["rows"][0]["report_url"]


def test_a_period_preview_answers_at_once(shares):
    er = shares[0]
    body = er.parity_period(er.ParityPeriodRequest(start="2026-10-01", end="2026-10-31",
                                                   preview=True))
    assert body["rows"][0]["outcome"] == "would compare" and body["preview"] is True


def test_an_unknown_or_malformed_period_id_is_a_404(shares):
    er = shares[0]
    for pid in ("0123456789ab", "../../etc"):
        with pytest.raises(er.HTTPException) as caught:
            er.parity_period_status(pid)
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


def test_a_run_without_one_files_no_parity(api):
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


def test_the_runner_files_the_comparison_with_the_engines_workbook(tmp_path, monkeypatch):
    runner = _runner()
    filed = _filed(tmp_path)
    manual = _touch(tmp_path / "Manual" / "12677.xls")
    calls = []

    class Done:
        returncode = 0
        stdout = json.dumps({"folder": str(tmp_path / "parity" / "Acme" / "x")})
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append((cmd, kw["env"]["SDI_PARITY_ROOT"]))
        return Done()
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    log = []
    job = {"run_id": "abc123", "drawing_number": "12677-01-GA", "manual_workbook": str(manual),
           "parity_root": str(tmp_path / "parity")}
    folder = runner.file_parity(job, filed, ROOT, Path(sys.executable), log)
    cmd, root = calls[0]
    assert folder.endswith("x") and root == str(tmp_path / "parity")
    assert cmd[cmd.index("--ai") + 1] == filed[1]["path"], "the engine's workbook, not the quote"
    assert cmd[cmd.index("--manual") + 1] == str(manual)
    assert cmd[cmd.index("--made-by") + 1] == "run abc123"
    assert log == [f"[parity] comparison filed to {folder}"]


def test_a_comparison_that_fails_is_logged_and_the_run_carries_on(tmp_path):
    runner = _runner()
    filed = _filed(tmp_path)
    manual = _touch(tmp_path / "Manual" / "12677.xls", "not a workbook")
    log = []
    job = {"run_id": "abc123", "drawing_number": "12677-01-GA", "manual_workbook": str(manual),
           "parity_root": str(tmp_path / "parity")}
    assert runner.file_parity(job, filed, ROOT, Path(sys.executable), log) == ""
    assert log and log[0].startswith("[parity] NOT filed to the parity folder")


def test_no_manual_estimate_or_no_parity_root_files_nothing(tmp_path, monkeypatch):
    runner = _runner()
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("not called"))
    log = []
    for job in ({"manual_workbook": "", "parity_root": str(tmp_path)},
                {"manual_workbook": str(tmp_path / "m.xls"), "parity_root": ""}):
        assert runner.file_parity(job, _filed(tmp_path), ROOT, Path(sys.executable), log) == ""
    assert log == []
