"""The tracker batch reads every feedback column and keeps two jobs open (JG, 14 Nov 2026).

The conference tracker now has Previous Feedback in G and Latest Feedback in H. The reader took
the first column headed Feedback only, and its default notes column is G: with the defaults H
never reached the brief (row 7's red-door instruction was lost), and pointing --col-notes at H
labelled the older G text "Latest feedback". And the batch queued one estimate and waited for
it, so the second Grid Runner sat idle through every batch: "we want two at once.. we have two
runners".

  * each feedback column is read and said under the sheet's own heading, once;
  * --at-once 2 keeps two runs open; the tracker is still written by the one process, a
    finished run at a time; a later row for a drawing still running waits for that run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import tti_pricer as tp  # noqa: E402
import test_tti_pricer_prices_each_row_and_fills_ai_cost as base  # noqa: E402


def _tracker(tmp_path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["B1"], ws["G1"], ws["H1"], ws["L1"], ws["N1"], ws["P1"] = (
        "Item Description", "Previous Feedback", "Latest Feedback", "Drawing Number", "Quantity", "AICost")
    ws["B2"], ws["G2"], ws["H2"], ws["L2"], ws["N2"] = "Door unit", "handles to be chrome", "doors to be RED", "12345-00-GA", 3
    ws["B3"], ws["G3"], ws["L3"], ws["N3"] = "Plinth", "as Rome", "12346-00-GA", 1
    p = tmp_path / "T.xlsx"
    wb.save(p)
    return p


def _rows(p, notes="G"):
    return tp.read_rows(p, {"drawing": "L", "notes": notes, "thumbs": ["I", "J"], "cost": "P"})


def test_both_feedback_columns_reach_the_brief_each_under_its_own_heading(tmp_path):
    got = _rows(_tracker(tmp_path))
    brief = tp.brief_for(got["rows"][0])
    assert "Previous Feedback: handles to be chrome." in brief
    assert "Latest Feedback: doors to be RED." in brief, "column H was dropped with the defaults"
    assert brief.count("handles to be chrome") == 1 and "Notes:" not in brief
    assert got["header"]["feedback"] == ["H: Latest Feedback"] and got["header"]["notes"] == "Previous Feedback"


def test_the_older_text_is_never_called_the_latest(tmp_path):
    """--col-notes H used to carry both, with G's older text labelled "Latest feedback"."""
    brief = tp.brief_for(_rows(_tracker(tmp_path), notes="H")["rows"][0])
    assert "Latest Feedback: doors to be RED." in brief
    assert "Previous Feedback: handles to be chrome." in brief
    assert "Latest feedback: handles" not in brief and "Latest Feedback: handles" not in brief


def test_a_row_with_no_latest_feedback_says_only_what_it_has(tmp_path):
    brief = tp.brief_for(_rows(_tracker(tmp_path))["rows"][1])
    assert "Previous Feedback: as Rome." in brief and "Latest Feedback" not in brief


def test_a_sheet_with_a_plain_notes_column_reads_as_before(tmp_path):
    """Contrast: Notes stays Notes, and a single Feedback column is said under its heading."""
    r = tp.read_rows(base._sheet(tmp_path), {"drawing": "L", "notes": "G", "thumbs": ["I", "J"], "cost": "P"})["rows"][0]
    assert "Notes: MDF, white gloss." in tp.brief_for(r) and "Feedback" not in tp.brief_for(r)


# ── two at once ────────────────────────────────────────────────────────────────────────────
class Portal:
    """Runs stay 'running' until released, so the test sees how many are open together."""

    def __init__(self):
        self.started, self.open, self.most_open, self.polls = [], set(), 0, 0

    def start(self, body):
        rid = f"r{len(self.started) + 1}"
        self.started.append(body)
        self.open.add(rid)
        self.most_open = max(self.most_open, len(self.open))
        return {"run_id": rid}

    def status(self, run_id):
        self.polls += 1
        if run_id in self.open and self.polls % 3 == 0:      # each ends after a few polls
            self.open.discard(run_id)
        if run_id in self.open:
            return {"status": "running", "run_id": run_id}
        body = self.started[int(run_id[1:]) - 1]             # the run prices its breaks too
        return {"status": "done", "run_id": run_id, "output_path": f"X:\\out\\{run_id}",
                "quantity_prices": [{"quantity": q, "unit_gbp": 100.0 + int(run_id[1:])}
                                    for q in [body["units"], *body.get("quantity_breaks", [])]]}


def _batch(tmp_path, monkeypatch, at_once):
    sheet = base._sheet(tmp_path)
    base._areas(tmp_path, monkeypatch)
    written = []
    monkeypatch.setattr(tp.SheetWriter, "__init__", lambda self, s, n, c: (
        setattr(self, "sheet", s), setattr(self, "sheet_name", n), setattr(self, "col", c),
        setattr(self, "backup", None), setattr(self, "how", "test")) and None)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: written.append((row, value)))
    monkeypatch.setattr(tp, "row_cells", lambda *a, **k: {})
    monkeypatch.setattr(tp, "check_write", lambda *a, **k: "")
    portal = Portal()
    rep = tp.run_batch(base._args(sheet, replace_costs=True, at_once=at_once, copy_to="none"),
                       portal=portal, status_path=tmp_path / "s.json", sleep=lambda s: None)
    return portal, rep, written


def test_two_runs_are_open_together_and_every_row_is_written_once(tmp_path, monkeypatch):
    portal, rep, written = _batch(tmp_path, monkeypatch, at_once=2)
    assert len(portal.started) == 3 and portal.most_open == 2, "two runners, two jobs at once"
    assert sorted(row for row, _ in written) == [3, 4, 6], "each row's cost written, once"
    assert all(r["state"] == "done" for r in rep["rows"]) and rep.get("finished")
    by_row = {r["row"]: r for r in rep["rows"]}
    assert {row: cost for row, cost in written} == {r: by_row[r]["unit_cost"] for r in (3, 4, 6)}, \
        "each cost on its own row, not its neighbour's"


def test_one_at_a_time_is_unchanged(tmp_path, monkeypatch):
    """Contrast: the default still queues a job and waits for it."""
    portal, rep, written = _batch(tmp_path, monkeypatch, at_once=1)
    assert len(portal.started) == 3 and portal.most_open == 1
    assert sorted(row for row, _ in written) == [3, 4, 6]


def test_a_second_row_for_a_drawing_still_running_waits_for_that_run(tmp_path, monkeypatch):
    """One run per drawing, each quantity a break of it: with two open, the second row for the
    same drawing must not start a second run of it."""
    sheet = base._sheet(tmp_path)
    wb = openpyxl.load_workbook(sheet)
    ws = wb.active
    ws["B7"], ws["D7"], ws["G7"], ws["L7"] = "Counter unit again", 9, "MDF, white gloss", "TTI-10234"
    wb.save(sheet)
    base._areas(tmp_path, monkeypatch)
    monkeypatch.setattr(tp.SheetWriter, "__init__", lambda self, s, n, c: (
        setattr(self, "sheet", s), setattr(self, "sheet_name", n), setattr(self, "col", c),
        setattr(self, "backup", None), setattr(self, "how", "test")) and None)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)
    monkeypatch.setattr(tp, "row_cells", lambda *a, **k: {})
    monkeypatch.setattr(tp, "check_write", lambda *a, **k: "")
    portal = Portal()
    tp.run_batch(base._args(sheet, replace_costs=True, at_once=2, copy_to="none"),
                 portal=portal, status_path=tmp_path / "s.json", sleep=lambda s: None)
    assert [b["drawing_number"] for b in portal.started].count("TTI-10234") == 1
