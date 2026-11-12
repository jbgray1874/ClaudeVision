"""THE FILES BESIDE A RUN'S WORKBOOK ARE FILED WITH IT, WHEREVER THE WORKBOOK IS (12 Nov 2026).

Three finished estimates from the second runner went out as "not reported/unit" over a list
of files. Their records, covering notes and walkthroughs were on disk beside their workbooks,
in the MAIN checkout's estimates folder; the collector looked only in the slot's own tree and
logged "no pinned record among the files".
"""
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
