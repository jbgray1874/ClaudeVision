"""THE FILES BESIDE A RUN'S WORKBOOK ARE FILED WITH IT, WHEREVER THE WORKBOOK IS (12 Nov 2026).

Three finished estimates from the second runner went out as "not reported/unit" over a list
of files. Their records, covering notes and walkthroughs were on disk beside their workbooks,
in the MAIN checkout's estimates folder; the collector looked only in the slot's own tree and
logged "no pinned record among the files".
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "runner"))

import own_record as O  # noqa: E402

START = time.mktime((2026, 11, 12, 17, 11, 0, 0, 0, -1))
BOOK_AT = time.mktime((2026, 11, 12, 17, 17, 28, 0, 0, -1))


def _put(folder, name, at):
    p = folder / name
    p.write_text(name)
    os.utime(p, (at, at))
    return p


def _two_trees(tmp_path):
    slot = tmp_path / "ClaudeVision-s2"
    main = tmp_path / "ClaudeVision" / "output" / "estimates"
    for d in ("json", "logs", "estimates", "text", "csv", "sql"):
        (slot / "output" / d).mkdir(parents=True)
    main.mkdir(parents=True)
    book = _put(main, "10000-01-GA_20261112_171728.xlsx", BOOK_AT)
    for n in ("10000-01-GA_20261112_171728_record.json", "10000-01-GA_20261112_171728_covering_email.html",
              "10000-01-GA_20261112_171728_covering_email.txt", "10000-01-GA_20261112_171728_walkthrough.wav",
              "10000-01-GA_report.html", "10000-01-GA_quote_PORTAL.html"):
        _put(main, n, BOOK_AT + 5)
    _put(main, "10000-01-GA_20261111_140000_record.json", BOOK_AT - 90000)      # yesterday's run
    _put(main, "10000-01-GA_20261111_140000.xlsx", BOOK_AT - 90000)
    _put(main, "10000-02-GA_20261112_172108_record.json", BOOK_AT + 200)         # another job, same minute
    _put(main, "10000-02-GA_report.html", BOOK_AT + 200)
    _put(main, "10000-01-GA2_report.html", BOOK_AT + 5)                          # a different drawing
    _put(main, "10000-01-GA-02_report.html", BOOK_AT + 5)
    return slot, main, book


def test_what_is_named_for_the_workbook_or_written_with_it_is_the_runs(tmp_path):
    _slot, _main, book = _two_trees(tmp_path)
    got = sorted(p.name for p in O.beside_the_book(book, START))
    assert got == ["10000-01-GA_20261112_171728_covering_email.html",
                   "10000-01-GA_20261112_171728_covering_email.txt",
                   "10000-01-GA_20261112_171728_record.json",
                   "10000-01-GA_20261112_171728_walkthrough.wav",
                   "10000-01-GA_quote_PORTAL.html", "10000-01-GA_report.html"]


def test_an_older_report_of_the_same_job_is_not_taken(tmp_path):
    _slot, main, book = _two_trees(tmp_path)
    os.utime(main / "10000-01-GA_report.html", (START - 3600, START - 3600))
    assert "10000-01-GA_report.html" not in {p.name for p in O.beside_the_book(book, START)}


def test_the_collector_files_them_from_the_other_tree_and_the_price_is_found(tmp_path):
    import sdi_estimate_runner as R
    slot, _main, book = _two_trees(tmp_path)
    (slot / "output" / "json" / "10000-01-GA.json").write_text(
        '{"saved_output_paths": {"estimate_xlsx": %s}}' % __import__("json").dumps(str(book)))
    os.utime(slot / "output" / "json" / "10000-01-GA.json", (BOOK_AT, BOOK_AT))
    log = []
    filed = R.collect(slot, tmp_path / "share", {}, log, drawing_number="10000-01-GA", started_at=START)
    names = {f["name"] for f in filed}
    assert {"10000-01-GA_20261112_171728.xlsx", "10000-01-GA_20261112_171728_record.json",
            "10000-01-GA_20261112_171728_covering_email.html",
            "10000-01-GA_20261112_171728_walkthrough.wav", "10000-01-GA_report.html"} <= names, names
    assert not any(n.startswith("10000-02-GA") or "20261111" in n for n in names)
    assert any("found beside this run's workbook" in line for line in log)
    rec, why = O.own_record(filed, "10000-01-GA", START)
    assert rec and rec["name"] == "10000-01-GA_20261112_171728_record.json", why


# ── each checkout its own folder, and the run's own manifest ────────────────────────────

def test_a_checkout_writes_its_workbooks_into_its_own_folder(monkeypatch):
    import wb_populate as W
    monkeypatch.delenv("SDI_WB_OUTPUT_DIR", raising=False)
    assert Path(W.workbook_output_dir()) == ROOT / "output" / "estimates"
    assert "ClaudeVision\\output\\estimates\"," not in (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8"), \
        "no one path for every runner"
    monkeypatch.setenv("SDI_WB_OUTPUT_DIR", "/somewhere/else")
    assert W.workbook_output_dir() == "/somewhere/else"


def test_the_run_lists_its_own_files_and_the_collector_takes_exactly_those(tmp_path):
    import run_manifest as M
    import sdi_estimate_runner as R
    slot, main, book = _two_trees(tmp_path)
    far = tmp_path / "elsewhere" / "10000-01-GA_extra_sheet.csv"
    far.parent.mkdir()
    far.write_text("declared, and in neither tree")
    summary = {"saved_output_paths": {"estimate_xlsx": str(book), "extra": str(far)},
               "run_provenance": {"service_run_id": "run9acb83da", "run_id": "10000-01-GA-20261112-171714-abc",
                                  "runner_id": "DESK-s2", "engine_build": "abc1234",
                                  "submitted_scope": {"drawing_number": "10000-01-GA"}}}
    mf = M.write(book, summary, START)
    doc = M.read(book)
    assert mf.name == "10000-01-GA_20261112_171728_deliverables.json"
    assert doc["portal_run_id"] == "run9acb83da" and doc["drawing_number"] == "10000-01-GA"
    names = {f["name"] for f in doc["files"]}
    assert "10000-01-GA_20261112_171728_record.json" in names and "10000-01-GA_extra_sheet.csv" in names
    assert not any(n.startswith("10000-02-GA") or "20261111" in n for n in names)
    assert next(f["what"] for f in doc["files"] if f["name"].endswith("_covering_email.html")) == "the covering note"
    (slot / "output" / "json" / "10000-01-GA.json").write_text(json.dumps(summary))
    os.utime(slot / "output" / "json" / "10000-01-GA.json", (BOOK_AT, BOOK_AT))
    log = []
    filed = {f["name"] for f in R.collect(slot, tmp_path / "share", {}, log,
                                           drawing_number="10000-01-GA", started_at=START)}
    assert {"10000-01-GA_20261112_171728_deliverables.json", "10000-01-GA_extra_sheet.csv",
            "10000-01-GA_20261112_171728_record.json"} <= filed
    assert any("the run's manifest" in line for line in log)


def test_a_manifest_for_another_workbook_is_not_this_runs(tmp_path):
    import run_manifest as M
    _slot, main, book = _two_trees(tmp_path)
    M.path_for(book).write_text(json.dumps({"schema": M.SCHEMA, "workbook": "10000-02-GA_20261112_172108.xlsx",
                                            "files": [{"name": "x", "path": str(main / "10000-02-GA_report.html")}]}))
    assert M.read(book) == {} and M.listed(book) == []


def test_a_listed_file_that_is_gone_is_said(tmp_path):
    import run_manifest as M
    _slot, main, book = _two_trees(tmp_path)
    M.write(book, {}, START)
    (main / "10000-01-GA_20261112_171728_walkthrough.wav").unlink()
    assert M.absent(book) == ["10000-01-GA_20261112_171728_walkthrough.wav"]
