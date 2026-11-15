"""THE NEXT N JOBS ON THE SHEET, ONE JOB BY NAME, AND A ROW RUN AGAIN (JG, 15 Nov 2026).

"we need to change the TTI button area to set the number of jobs we want to run next based on
where we are on the sheet list. we probably need a re-run ... so that we can re run a row we
already have ran ... if we can allow someone to type in or select from a list the drawing packs
and do the estimate one by one."

Before this the batch took the whole sheet or the rows typed by hand; a row that had finished
could not be priced again (its finished run was simply used again); the command line and the
page each kept their own history of a sheet; and a batch started in a command window took no
claim, so the page could start a second writer beside it.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
sys.path.insert(0, str(ROOT / "tests"))

import tti_pricer as tp  # noqa: E402
from test_tti_pricer_prices_each_row_and_fills_ai_cost import FakePortal, _areas, _args  # noqa: E402
from test_the_tracker_batch_runs_the_rows_named_on_their_own_briefs_and_never_lists_the_share_in_silence import _tracker  # noqa: E402
from test_the_tracker_changes_button_prices_only_what_changed import service  # noqa: E402,F401

JOBS = ["TTI-20001", "TTI-20002", "TTI-20003", "TTI-20004"]


class _Portal(FakePortal):
    """Each run reports its own request's units, whichever run is asked about."""

    def status(self, run_id):
        body = self.started[int(run_id[1:]) - 1]
        return {"status": "done", "output_path": f"X:\\out\\{run_id}",
                "quantity_prices": [{"quantity": body["units"], "unit_gbp": self.price}]}


def _sheet(tmp_path, monkeypatch, drawings):
    sheet = _tracker(tmp_path, [(d, f"Item {i}", "", "", 2) for i, d in enumerate(drawings)])
    design, _proto, _tech = _areas(tmp_path, monkeypatch)
    for d in JOBS:
        tech = design / "Conference 2027" / f"{d} Stand" / "Technical"
        tech.mkdir(parents=True, exist_ok=True)
        (tech / f"{d} rev A.pdf").write_text(d)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)
    return sheet


def _go(sheet, portal, status=None, **kw):
    return tp.run_batch(_args(sheet, drawings_only=True, **kw), portal=portal, status_path=status,
                        sleep=lambda s: None)


def _sent(portal):
    return [b["drawing_number"] for b in portal.started]


# ── which rows are next ───────────────────────────────────────────────────────────────────
def _rows(*specs):
    return [{"row": n, "drawing": d, "quantity": 1, "cost_before": c} for n, d, c in specs]


def test_next_is_sheet_order_with_a_drawing_no_cost_no_earlier_attempt_and_not_held():
    rows = _rows((3, "A", None), (4, "", None), (5, "B", 12.5), (6, "C", None), (7, "D", None),
                 (8, "E", None), (9, "F", None), (10, "G", 0))
    ledger = {"6|C|1": {"row": 6, "drawing": "C", "state": tp.OUTCOME_NOT_KNOWN},
              "9|F|3": {"row": 9, "drawing": "F", "state": "done", "run_id": "abc"}}
    nxt, passed = tp.next_rows(rows, ledger, held_rows=[7], held_drawings=["e"])
    assert [r["row"] for r in nxt] == [3]
    why = {p["row"]: p["why"] for p in passed}
    assert why[4] == "no drawing number" and why[5] == "has a cost" and why[10] == "has a cost"
    assert "earlier attempt is on record (outcome not known)" in why[6] and "--rows 6" in why[6]
    assert why[7].startswith("held: this row") and why[8].startswith("held: this drawing")
    assert "run abc" in why[9], "another quantity's entry for the same row and drawing is still history"


def test_the_starting_row_only_moves_where_looking_starts():
    rows = _rows((3, "A", None), (4, "B", None), (5, "C", None))
    nxt, passed = tp.next_rows(rows, {}, from_row=4)
    assert [r["row"] for r in nxt] == [4, 5] and passed == []


# ── the batch ─────────────────────────────────────────────────────────────────────────────
def test_next_two_starts_exactly_the_first_two_and_looks_no_further(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path, monkeypatch, JOBS)
    portal = _Portal()
    rep = _go(sheet, portal, next=2)
    assert _sent(portal) == JOBS[:2]
    assert [r["row"] for r in rep["rows"]] == [2, 3] and rep["next"]["stopped_before_row"] == 4


def test_without_next_the_whole_sheet_runs_as_before(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path, monkeypatch, JOBS)
    portal = _Portal()
    _go(sheet, portal)
    assert _sent(portal) == JOBS


def test_a_row_that_finds_no_pack_is_listed_and_does_not_use_up_a_place(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path, monkeypatch, ["TTI-99999", JOBS[0], JOBS[1], JOBS[2]])
    portal = _Portal()
    rep = _go(sheet, portal, next=2)
    assert _sent(portal) == JOBS[:2]
    assert rep["rows"][0]["state"] == "needs drawing" and len(rep["rows"]) == 3


def test_the_second_next_carries_on_from_where_the_first_stopped(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path, monkeypatch, JOBS)
    status = tmp_path / "status.json"
    _go(sheet, _Portal(), status, next=2)
    portal = _Portal()
    rep = _go(sheet, portal, status, next=2)
    assert _sent(portal) == JOBS[2:], "the rows already run were sent again"
    assert {p["row"] for p in rep["next"]["passed_over"]} == {2, 3}


def test_a_held_row_is_never_next_and_one_job_is_run_by_naming_its_drawing(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path, monkeypatch, JOBS)
    portal = _Portal()
    _go(sheet, portal, next=2, hold_rows="2, 4")
    assert _sent(portal) == [JOBS[1], JOBS[3]]
    one = _Portal()
    _go(sheet, one, drawings=JOBS[2].lower())
    assert _sent(one) == [JOBS[2]]


# ── a row run again ───────────────────────────────────────────────────────────────────────
def test_a_finished_row_is_not_priced_twice_unless_run_again_is_asked(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path, monkeypatch, JOBS[:1])
    status = tmp_path / "status.json"
    first = _Portal()
    _go(sheet, first, status)
    assert _sent(first) == JOBS[:1]
    quiet = first                                  # the service still holds run r1
    before = len(quiet.started)
    _go(sheet, quiet, status, rows="2")
    assert len(quiet.started) == before, "naming a finished row started a second estimate"
    rep = _go(sheet, quiet, status, rows="2", run_again=True, replace_costs=True)
    assert len(quiet.started) == before + 1
    row = rep["rows"][0]
    assert row["run_id"] == "r2" and "earlier run r1" in row["run_again"]
    entry = next(iter(json.loads((tmp_path / "tracker.ledger.json").read_text()).values()))
    assert entry["run_id"] == "r2" and [e["run_id"] for e in entry["earlier"]] == ["r1"]
    assert entry["earlier"][0]["unit_cost"] is not None, "the earlier result was not kept"


def test_run_again_is_refused_for_a_row_that_never_finished(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path, monkeypatch, JOBS[:1])
    portal = _Portal()
    rep = _go(sheet, portal, tmp_path / "status.json", rows="2", run_again=True, replace_costs=True)
    assert portal.started == [] and rep["rows"][0]["state"] == "held: not a finished row"


def test_run_again_needs_the_rows_named_and_next_takes_no_row_list(tmp_path):
    for argv in (["--run-again"], ["--run-again", "--next", "2", "--rows", "3"], ["--next", "2", "--rows", "3"]):
        with pytest.raises(SystemExit):
            tp.main(["--sheet", str(tmp_path / "s.xlsx"), "--dry-run"] + argv)


# ── one history, one writer ───────────────────────────────────────────────────────────────
def test_a_sheets_history_is_read_from_every_place_a_batch_keeps_it(tmp_path):
    mine, theirs = tmp_path / "cli" / "t.ledger.json", tmp_path / "page" / "t.ledger.json"
    for f in (mine, theirs):
        f.parent.mkdir()
    mine.write_text(json.dumps({"3|A|1": {"row": 3, "state": "running", "updated": "2026-11-15T10:00:00"},
                                "4|B|1": {"row": 4, "state": "done", "updated": "2026-11-15T12:00:00"}}))
    theirs.write_text(json.dumps({"3|A|1": {"row": 3, "state": "done", "updated": "2026-11-15T11:00:00"},
                                  "4|B|1": {"row": 4, "state": "running", "updated": "2026-11-15T09:00:00"},
                                  "5|C|1": {"row": 5, "state": tp.OUTCOME_NOT_KNOWN, "updated": "2026-11-15T09:30:00"}}))
    ledger, said = tp.load_ledgers(mine, [theirs.parent, tmp_path / "absent"])
    assert ledger["3|A|1"]["state"] == "done" and ledger["4|B|1"]["state"] == "done"
    assert ledger["5|C|1"]["state"] == tp.OUTCOME_NOT_KNOWN and "2 row(s)" in said[0]
    assert tp.load_ledgers(mine, [])[0]["3|A|1"]["state"] == "running", "nothing else was asked for"


def test_a_command_line_batch_claims_the_one_writer_and_gives_it_up(tmp_path, monkeypatch):
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    import tti_batch_lock
    lock = tmp_path / "state" / "tti" / "batch.lock"
    assert tp.claim_one_writer("mine") == "" and tti_batch_lock.holder(lock)["pid"] == os.getpid()
    assert tp.claim_one_writer("mine again") == "", "its own claim is not a refusal"
    tp.release_one_writer()
    assert tti_batch_lock.holder(lock) is None
    tti_batch_lock.claim(lock, "the page's batch", os.getppid())          # another live process
    assert "already running (task the page's batch)" in tp.claim_one_writer("mine")
    tp.release_one_writer()
    assert tti_batch_lock.holder(lock)["task_id"] == "the page's batch", "another batch's claim was removed"


# ── the page's button asks the batch for the same things ──────────────────────────────────
def test_the_sheet_button_passes_next_the_starting_row_the_drawings_and_run_again(service, tmp_path):  # noqa: F811
    tc, er, tmp = service
    sheet = _tracker(tmp_path, [(JOBS[0], "Item", "", "", 2)])
    seen = []
    real = er._tti_batch_args

    def spy(*a, **k):
        seen.append(real(*a, **k))
        return [sys.executable, "-c", "pass"]
    er._tti_batch_args = spy
    try:
        post = lambda **b: tc.post("/api/estimate/tti/run", json=dict(sheet=str(sheet), dry_run=True, **b))
        assert post(next=5, from_row=9).status_code == 200
        assert post(rows="9", run_again=True).status_code == 200
        assert post(drawings="12181-00-GA ; 12181-00-GA2").status_code == 200
        assert post().status_code == 200
        for bad in (dict(next=5, rows="3"), dict(next=51), dict(run_again=True),
                    dict(next=2, run_again=True, rows="3"), dict(drawings="x && del")):
            assert post(**bad).status_code == 400, bad
    finally:
        er._tti_batch_args = real
    nxt, again, named, plain = seen
    assert nxt[nxt.index("--next") + 1] == "5" and nxt[nxt.index("--from-row") + 1] == "9"
    assert "--run-again" in again and again[again.index("--rows") + 1] == "9"
    assert named[named.index("--drawings") + 1] == "12181-00-GA,12181-00-GA2"
    assert not {"--next", "--run-again", "--drawings", "--from-row"} & set(plain)
    assert all(a[a.index("--at-once") + 1] == "2" for a in seen)
