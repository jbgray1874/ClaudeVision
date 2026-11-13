"""A FINISHED RUN'S BUNDLE IS RECOVERED WITHOUT RERUNNING IT (reviewer, 12 Nov 2026).

"Recover the existing deliverables against their exact run IDs, previewing changes first. No
recalculation solely to repair an email, and no automatic resend."
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bundle_recover as B  # noqa: E402

START = time.mktime((2026, 11, 12, 17, 11, 0, 0, 0, -1))
AT = time.mktime((2026, 11, 12, 17, 17, 28, 0, 0, -1))
BOOK = "10000-01-GA_20261112_171728.xlsx"


def _world(tmp_path, record_run="run9acb83da", record_drawing="10000-01-GA"):
    est = tmp_path / "checkout" / "output" / "estimates"
    share = tmp_path / "share" / "A" / "10000-01-GA"
    est.mkdir(parents=True), share.mkdir(parents=True)
    for n in (BOOK, BOOK[:-5] + "_covering_email.html", BOOK[:-5] + "_walkthrough.wav", "10000-01-GA_report.html"):
        (est / n).write_text(n)
        os.utime(est / n, (AT + 3, AT + 3))
    (est / (BOOK[:-5] + "_record.json")).write_text(json.dumps({"run_provenance": {
        "service_run_id": record_run, "submitted_scope": {"drawing_number": record_drawing}}}))
    os.utime(est / (BOOK[:-5] + "_record.json"), (AT + 6, AT + 6))
    (share / BOOK).write_text("the filed workbook")
    run = {"run_id": "run9acb83da", "status": "done", "drawing_number": "10000-01-GA", "started_at": START,
           "engine_price_gbp": None, "deliverables": [{"name": BOOK, "path": str(share / BOOK)},
                                                      {"name": "10000-01-GA_run.log", "path": str(share / "x.log")}]}
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "run9acb83da.json").write_text(json.dumps(run))
    return est, share, runs, run


def test_the_runs_own_files_are_proposed_and_proved_by_its_run_id(tmp_path):
    est, share, _runs, run = _world(tmp_path)
    p = B.proposal(run, [est])
    assert not p["held"] and p["proved_by"] == "its record names this portal run"
    assert sorted(x["name"] for x in p["add"]) == [
        "10000-01-GA_20261112_171728_covering_email.html", "10000-01-GA_20261112_171728_record.json",
        "10000-01-GA_20261112_171728_walkthrough.wav", "10000-01-GA_report.html"]
    assert all(x["to"].startswith(str(share)) for x in p["add"])


def test_a_record_for_another_run_or_drawing_is_left_and_said(tmp_path):
    est, _s, _r, run = _world(tmp_path, record_run="someotherrun")
    assert "names portal run someotherrun, not this run" in B.proposal(run, [est])["held"]
    est2, _s, _r, run2 = _world(tmp_path / "b", record_drawing="20000-09")
    assert "is for 20000-09, not 10000-01-GA" in B.proposal(run2, [est2])["held"]


def test_a_run_that_already_has_its_record_or_did_not_finish_is_not_touched(tmp_path):
    est, share, _r, run = _world(tmp_path)
    whole = dict(run, deliverables=run["deliverables"] + [{"name": BOOK[:-5] + "_record.json", "path": "x"}])
    assert B.proposal(whole, [est]) is None
    assert B.proposal(dict(run, status="error"), [est]) is None


def test_showing_changes_nothing_and_applying_copies_lists_and_keeps_the_original(tmp_path, capsys):
    est, share, runs, _run = _world(tmp_path)
    before = (runs / "run9acb83da.json").read_text()
    assert B.main(["--runs", str(runs), "--from", str(est)]) == 0
    assert "Nothing was changed" in capsys.readouterr().out
    assert (runs / "run9acb83da.json").read_text() == before and sorted(p.name for p in share.iterdir()) == [BOOK]
    assert B.main(["--runs", str(runs), "--from", str(est), "--apply"]) == 0
    after = json.loads((runs / "run9acb83da.json").read_text())
    names = {d["name"] for d in after["deliverables"]}
    assert BOOK[:-5] + "_record.json" in names and BOOK[:-5] + "_covering_email.html" in names
    assert (share / (BOOK[:-5] + "_walkthrough.wav")).is_file()
    assert (share / BOOK).read_text() == "the filed workbook", "nothing is overwritten"
    assert after["engine_price_gbp"] is None, "the price is price_correct's to put back, from the record"
    kept = list((runs / "corrections").glob("run9acb83da.*.before.json"))
    assert len(kept) == 1 and kept[0].read_text() == before
    capsys.readouterr()
    assert B.main(["--runs", str(runs), "--from", str(est)]) == 0
    assert "0 run(s) to recover" in capsys.readouterr().out
