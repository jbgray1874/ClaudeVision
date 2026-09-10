"""A run that produced no workbook must not be reported as done.

10575-02 on 25 Aug ran for 971 seconds, exited 0, and filed exactly two files:

    10575-02.json          the engine's summary
    10575-02_run.log       the console transcript

No workbook. No client quote. No job report. No parity bundle. The service recorded
status "done", error "", engine_price_gbp null — so the page said the estimate was ready and
sent an estimator to a folder with nothing in it they could open.

Exit code 0 says the engine did not crash. It does not say it produced an estimate. `collect()`
already warned when NOTHING was copied; the case that actually happened was files copied and no
.xlsx among them, which nothing checked.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "runner", _ROOT / "tools" / "runner" / "sdi_estimate_runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


THE_RUN = [                              # exactly what 10575-02 filed
    {"name": "10575-02.json", "path": "x"},
    {"name": "10575-02_run.log", "path": "y"},
]
A_GOOD_RUN = THE_RUN + [{"name": "10575-02_20260825_173036.xlsx", "path": "z"}]


def _has_workbook(filed):
    """The rule, as both call sites apply it."""
    return any(f["name"].lower().endswith(".xlsx") for f in filed)


def test_the_run_that_happened_is_not_a_complete_run():
    assert not _has_workbook(THE_RUN)


def test_a_run_with_a_workbook_is():
    assert _has_workbook(A_GOOD_RUN)


def test_an_uppercase_extension_still_counts():
    assert _has_workbook([{"name": "10575-02.XLSX", "path": "z"}])


def test_a_json_named_like_a_workbook_does_not_count():
    """`10575-02.xlsx.json` ends in .json. Matching anywhere in the name rather than at the
    end would call this an estimate."""
    assert not _has_workbook([{"name": "10575-02.xlsx.json", "path": "z"}])


def test_both_call_sites_use_the_same_rule():
    """The warning in collect() and the status decision must agree. If one is relaxed and the
    other is not, the log says one thing and the page says another — which is the shape of the
    original bug, not a fix for it."""
    src = (_ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
    rule = 'f["name"].lower().endswith(".xlsx") for f in filed'
    assert src.count(rule) == 2, f"expected the rule at both call sites, found {src.count(rule)}"


def test_the_deliverables_are_still_filed_on_failure():
    """The summary and the log are exactly what is needed to work out why it produced nothing,
    so failing the run must not throw them away."""
    src = (_ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
    at = src.index("The engine finished without producing a workbook")
    call = src[src.rindex("_finish(", 0, at):src.index("return", at)]
    assert "log, filed" in call, "the failed run must still file what the engine did write"


def test_the_zero_file_case_is_still_covered_separately():
    """The pre-existing warning must survive: nothing copied at all is a different diagnosis
    from a summary with no workbook, and collapsing them loses that."""
    src = (_ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
    assert "NOTHING was copied" in src
    assert "NO WORKBOOK" in src


# ── every artefact goes to the estimate folder, not two of nine ───────────────────────

def test_the_collector_watches_every_folder_the_engine_writes_to():
    """JAMES'S RULE, AND THE RUN THAT BROKE IT: "the s/sheet and all reports and logs, etc.
    always need to be written to the estimate output folder".

    0359342 produced nine artefacts and filed TWO. The engine prints all four of its output
    folders under "Output files:" on every run — json, text, logs, csv — and writes the
    workbook, quote, report and covering note into estimates. The collector watched estimates
    and json only, so the run log and the write-up were never copied and the estimator's
    folder held nothing to read.
    """
    r = runner

    for folder in ("estimates", "json", "text", "logs", "csv"):
        assert folder in r.WATCHED_DIRS, folder


def test_the_artefact_suffixes_cover_what_the_engine_actually_emits():
    """A watched folder with an unwatched suffix files nothing. The run log is .log, the
    write-up .txt, the SQL export .sql — all named in the engine's own console output."""
    r = runner

    for suffix in (".xlsx", ".html", ".json", ".log", ".csv", ".txt", ".sql"):
        assert suffix in r.DELIVERABLE_SUFFIXES, suffix


def test_a_report_and_a_log_are_filed_alongside_the_workbook(tmp_path):
    """End to end over a fake output tree: one artefact in each watched folder, all filed."""
    r = runner

    engine_root = tmp_path / "engine"
    written = {
        "estimates/0359342_20260910_123656.xlsx": "wb",
        "estimates/0359342_report.html": "report",
        "estimates/0359342_quote.html": "quote",
        "json/0359342.json": "{}",
        "text/0359342.txt": "write-up",
        "logs/0359342.log": "log",
        "csv/part_estimate_inputs.csv": "a,b",
    }
    before = r.snapshot(engine_root)            # nothing exists yet
    for rel, body in written.items():
        target = engine_root / "output" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    log: list = []
    filed = r.collect(engine_root, tmp_path / "dest", before, log, drawing_number="0359342")
    names = {f["name"] for f in filed}
    # collect() also writes its own console transcript last, so it contains the filing result.
    assert names == {Path(k).name for k in written} | {"0359342_run.log"}, names
    assert not any("NO WORKBOOK" in line for line in log), log
    assert all((tmp_path / "dest" / n).is_file() for n in names)
