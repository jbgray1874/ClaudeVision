"""THE ONE BUTTON (JG, 15 Nov 2026): "we want to just run that command button whenever
estimating / PMs say that the s.sheet has new rows / changes to it, so that our process finds
that s/sheet on the sharepoint, does the delta and prices any changes."

JG's acceptance standard, each point with the case that must NOT happen beside it:

  1. the master tracker is opened where it lives, read-only; no file is named or downloaded
  2. rows are compared by permanent AI Row ID, so sorting or inserting cannot confuse jobs
  3. new rows, rows that now have drawings, changed quantity / description / either feedback
     column, changed revision or pack contents are detected
  4. new / changed / unchanged / held, each with its reason
  5. only new rows and APPROVED changed rows run, two at once; unchanged finished work never
  6. previous results are kept
  NOT a trigger: a change to an AI-written cost, formatting, row order
  a second click or an uncertain reply never makes a duplicate, across both services
  the first baseline comes from work already finished

Before this work: /tti/run refused a row list, never passed --at-once or --drawings-only, and
started a second batch on a second click; there was no way to read the master without a
download, and no comparison at all.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
for _p in (str(ROOT / "src"), str(BACKEND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tti_batch_lock                                      # noqa: E402
import tti_changes                                         # noqa: E402
import tti_incremental as inc                              # noqa: E402
import tti_incremental_routes as routes                    # noqa: E402
import tti_tracker_source as source                        # noqa: E402

PAGE = (BACKEND / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")
HEADS = ["Description", "Quantity", "Previous Feedback", "Latest Feedback", "Drawing Number",
         "AI Cost", "AI Row ID"]


def _id(n) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"row-{n}"))


def _tracker(path: Path, lines, ids=True, order=None, dress=False) -> Path:
    """lines: (n, description, quantity, previous, latest, drawing cell, cost)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Jobs"
    ws.append(["A TRACKER OF JOBS"])
    ws.append(HEADS if ids else HEADS[:-1])
    for n, desc, qty, prev, late, dwg, cost in (order or lines):
        ws.append([desc, qty, prev, late, dwg, cost] + ([_id(n)] if ids else []))
    if dress:                                              # formatting only: no value changes
        from openpyxl.styles import Font, PatternFill
        for row in ws.iter_rows(min_row=3):
            for c in row:
                c.font = Font(bold=True, color="FF0000")
                c.fill = PatternFill("solid", fgColor="FFFF00")
        ws.column_dimensions["A"].width = 60
    wb.save(path)
    return path


LINES = [(1, "Counter", 2, "blue", "red door", "70001-01-GA", None),
         (2, "Header", 4, "", "gloss", "70002-01-GA REV B", None),
         (3, "Plinth", 1, "", "", "", None)]
FILES = {"70001-01-GA": [("//share/a/70001-01-GA.pdf", 10, 6000.0)],
         "70002-01-GA": [("//share/b/70002-01-GA.pdf", 20, 6000.0)]}


def _rows(path, files=FILES, **kw):
    return source.tracker_rows(path, None, lookup=lambda d: files.get(d, []), **kw)


# ── 1. the master is opened where it lives, and never written ─────────────────────────────

class _Book:
    def __init__(self, log, body=b"copy"):
        self.log, self.body = log, body

    def SaveCopyAs(self, path):
        self.log.append(("SaveCopyAs", path))
        Path(path).write_bytes(self.body)

    def Close(self, SaveChanges=True):
        self.log.append(("Close", SaveChanges))


def test_the_master_is_opened_by_its_address_copied_and_closed_without_saving(tmp_path):
    master = "https://example.sharepoint.com/sites/x/Shared%20Documents/TRACKER%20A.xlsx"
    log = []
    copy = source.snapshot(master + "?web=1", tmp_path / "out", master=master,
                           opener=lambda a: log.append(("Open", a)) or _Book(log))
    assert copy.parent == tmp_path / "out" and copy.read_bytes() == b"copy"
    assert log[0] == ("Open", master), "the browser view (?web=1) is not what Excel is given"
    assert [x[0] for x in log] == ["Open", "SaveCopyAs", "Close"] and log[-1] == ("Close", False)


def test_any_other_workbook_is_refused_and_nothing_is_opened(tmp_path):
    opened = []
    with pytest.raises(source.NotTheMaster):
        source.snapshot("https://example.sharepoint.com/sites/x/OTHER.xlsx", tmp_path,
                        master="https://example.sharepoint.com/sites/x/TRACKER.xlsx",
                        opener=lambda a: opened.append(a))
    with pytest.raises(source.NotTheMaster):
        source.snapshot("https://example.sharepoint.com/sites/x/TRACKER.xlsx", tmp_path, master="",
                        opener=lambda a: opened.append(a))
    assert opened == [] and list(tmp_path.iterdir()) == []


def test_a_master_on_disk_is_copied_and_left_byte_for_byte(tmp_path):
    master = _tracker(tmp_path / "MASTER.xlsx", LINES)
    before = master.read_bytes(), master.stat().st_mtime_ns
    a = source.snapshot(str(master), tmp_path / "out", master=str(master))
    b = source.snapshot(str(master), tmp_path / "out", master=str(master))
    assert a != b and a.read_bytes() == before[0], "each copy is kept; none overwrites another"
    assert (master.read_bytes(), master.stat().st_mtime_ns) == before


# ── 2-3. the rows, as the comparison needs them ───────────────────────────────────────────

def test_rows_carry_their_permanent_id_both_feedbacks_revision_and_pack(tmp_path):
    got = _rows(_tracker(tmp_path / "t.xlsx", LINES))
    assert got["row_id_column"] is True and got["rows_without_id"] == []
    one, two, three = got["rows"]
    assert (one["row_id"], one["drawing"], one["quantity"]) == (_id(1), "70001-01-GA", 2)
    assert (one["previous_feedback"], one["latest_feedback"]) == ("blue", "red door")
    assert two["revision"] == "B" and one["revision"] == ""
    assert one["pack_state"] == "ready" and one["pack_safe"] is True and one["pack_key"]
    assert three["pack_state"] == "missing" and any("drawing" in h.lower() for h in three["holds"])


def test_a_blank_quantity_is_a_hold_and_never_one(tmp_path):
    got = _rows(_tracker(tmp_path / "t.xlsx", [(1, "Counter", None, "", "", "70001-01-GA", None),
                                               (2, "Header", 4, "", "", "70002-01-GA", None)]))
    blank, whole = got["rows"]
    assert blank["quantity"] is None and any("uantity" in h for h in blank["holds"])
    assert whole["quantity"] == 4 and whole["holds"] == []


def test_a_tracker_without_ids_says_so_and_a_stale_index_or_a_held_out_drawing_is_a_hold(tmp_path):
    bare = _rows(_tracker(tmp_path / "bare.xlsx", LINES, ids=False))
    assert bare["row_id_column"] is False and bare["rows_without_id"] == [3, 4, 5]
    held = source.tracker_rows(_tracker(tmp_path / "t.xlsx", LINES), None, lookup=None,
                               index_problem="The drawing index is older than 26 hours",
                               hold_out=["70002-01-ga"])["rows"]
    assert all(any("index" in h for h in r["holds"]) for r in held[:2]) and held[0]["pack_state"] == "missing"
    assert any("SDI_TTI_HOLD_OUT" in h for h in held[1]["holds"])
    assert not any("SDI_TTI_HOLD_OUT" in h for h in held[0]["holds"])


def _base(tmp_path, lines=LINES, history="completed"):
    """The rows as last estimated: rows 1 and 2 finished and their AI cost on the sheet."""
    done = [(n, d, q, p, l, dw, 100.0 if dw else None) for n, d, q, p, l, dw, _ in lines]
    rows = _rows(_tracker(tmp_path / "base.xlsx", done))["rows"]
    return [dict(r, history=history if r["drawing"] else None, run_id="run-%d" % i if r["drawing"] else None)
            for i, r in enumerate(rows)], done


def _kinds(before, now):
    return {d["row_id"]: d for d in inc.decisions(before, now)}


@pytest.mark.parametrize("field,change", [
    ("quantity", lambda l: (l[0], l[1], 9, l[3], l[4], l[5], l[6])),
    ("description", lambda l: (l[0], "Counter, taller", l[2], l[3], l[4], l[5], l[6])),
    ("previous_feedback", lambda l: (l[0], l[1], l[2], "green", l[4], l[5], l[6])),
    ("latest_feedback", lambda l: (l[0], l[1], l[2], l[3], "blue door", l[5], l[6])),
    ("revision", lambda l: (l[0], l[1], l[2], l[3], l[4], l[5] + " REV C", l[6])),
])
def test_each_changed_input_is_a_changed_row_that_waits_for_a_tick(tmp_path, field, change):
    before, done = _base(tmp_path)
    now = _rows(_tracker(tmp_path / "now.xlsx", [change(done[0])] + done[1:]))["rows"]
    got = _kinds(before, now)
    assert got[_id(1)]["kind"] == "changed_completed" and got[_id(1)]["changed"] == [field]
    assert got[_id(1)]["eligible"] is False and got[_id(1)]["approvable"] is True
    assert got[_id(2)]["kind"] == "unchanged_completed" and got[_id(2)]["approvable"] is False


def test_changed_pack_contents_are_a_change_and_the_same_pack_is_not(tmp_path):
    before, done = _base(tmp_path)
    book = _tracker(tmp_path / "now.xlsx", done)
    resaved = dict(FILES, **{"70001-01-GA": [("//share/a/70001-01-GA.pdf", 11, 9000.0)]})
    got = _kinds(before, _rows(book, files=resaved)["rows"])
    assert got[_id(1)]["kind"] == "changed_completed" and got[_id(1)]["changed"] == ["pack_key"]
    assert _kinds(before, _rows(book)["rows"])[_id(1)]["kind"] == "unchanged_completed"


def test_a_new_row_and_a_row_that_now_has_its_drawing_are_new_work(tmp_path):
    before, done = _base(tmp_path)
    files = dict(FILES, **{"70003-01-GA": [("//share/c/70003-01-GA.pdf", 5, 6000.0)],
                           "70004-01-GA": [("//share/d/70004-01-GA.pdf", 5, 6000.0)]})
    now = _rows(_tracker(tmp_path / "now.xlsx", done[:2] + [
        (3, "Plinth", 1, "", "", "70003-01-GA", None), (4, "Shelf", 6, "", "", "70004-01-GA", None)]),
        files=files)["rows"]
    got = _kinds(before, now)
    assert got[_id(3)]["kind"] == "drawing_added" and got[_id(3)]["eligible"] is True
    assert got[_id(4)]["kind"] == "new_row" and got[_id(4)]["eligible"] is True
    assert [g for g in (got[_id(1)], got[_id(2)]) if g["eligible"] or g["kind"] != "unchanged_completed"] == []


# ── NOT a trigger: an AI-written cost, formatting, row order ──────────────────────────────

def test_a_changed_cost_formatting_and_row_order_trigger_nothing(tmp_path):
    before, done = _base(tmp_path)
    recost = [(n, d, q, p, l, dw, 555.5 if n == 1 else c) for n, d, q, p, l, dw, c in done]
    for name, kw in (("cost", dict(lines=recost)),
                     ("formatting", dict(lines=done, dress=True)),
                     ("order", dict(lines=done, order=[done[2], done[1], done[0]]))):
        now = _rows(_tracker(tmp_path / f"{name}.xlsx", **kw))["rows"]
        got = _kinds(before, now)
        assert [got[_id(n)]["kind"] for n in (1, 2)] == ["unchanged_completed"] * 2, name
        assert not any(d["eligible"] or d["approvable"] for d in got.values()), name
        assert all(d["changed"] == [] for d in got.values()), name
    moved = {r["row_id"]: r["row"] for r in now}
    assert moved[_id(1)] == 5 and moved[_id(3)] == 3, "the rows did move; identity followed the ID"


# ── 4-6 and the duplicate rules, through the two routes ───────────────────────────────────

class _Rig:
    """The router as the service mounts it, with the tracker and the batch stood in for."""

    def __init__(self, tmp_path, run_on=True, db=None):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        self.tmp, self.lines, self.files = tmp_path, list(LINES), dict(FILES)
        self.ids, self.sent, self.fail, self.busy, self.run_on = True, [], None, None, run_on
        self.status, self.alive = {}, None
        self.store = inc.Store(db or tmp_path / "state" / "changes.sqlite")
        app = FastAPI()
        app.include_router(routes.make_router(
            self.store, allowed_trackers={"master"}, snapshot=self.snapshot,
            submit=tti_changes.make_submit(self.spawn), check_key=lambda k: None,
            run_enabled=lambda: self.run_on, busy=lambda: self.busy,
            reconcile=tti_changes.make_reconcile(self.store, self.status.get, lambda: self.alive),
            ledgers=lambda: self.ledgers))
        self.ledgers = []
        self.tc = TestClient(app)

    def snapshot(self, tracker_id):
        book = _tracker(self.tmp / f"snap-{uuid.uuid4().hex[:6]}.xlsx", self.lines, ids=self.ids)
        return _rows(book, files=self.files)

    def spawn(self, **kw):
        self.sent.append(kw)
        if self.fail:
            raise self.fail
        return {"task_id": kw["task_id"], "status_url": "/x"}

    def post(self, action, **body):
        return self.tc.post(f"/api/estimate/tti/changes/{action}", json=dict(tracker_id="master", **body))

    def baseline(self):
        r = self.post("baseline", apply=True)
        assert r.status_code == 200, r.text
        return r.json()


def _finished(rig, plan_id, rows):
    rig.status[tti_changes.task_id_for(plan_id)] = {"finished": "2026-11-15T12:00:00", "rows": rows}


def test_check_answers_without_ids_and_nothing_can_be_run_from_it(tmp_path):
    rig = _Rig(tmp_path)
    rig.ids = False
    p = rig.post("check").json()
    assert p["message"] == routes.NO_IDS and p["plan_id"] is None and p["runnable"] is False
    assert len(p["decisions"]) == 3 and not any(d["eligible"] for d in p["decisions"])
    assert {d["group"] for d in p["decisions"]} == {"held"} and all(d["reasons"] for d in p["decisions"])
    assert rig.post("baseline", apply=True).status_code == 409
    assert rig.post("run", plan_id=str(uuid.uuid4())).status_code == 409 and rig.sent == []
    rig.ids = True                                          # the contrast: with IDs, only the baseline is missing
    assert rig.post("check").json()["message"] == routes.NO_BASELINE


def test_the_first_baseline_comes_from_finished_work_so_it_is_not_called_new(tmp_path):
    rig = _Rig(tmp_path)
    rig.lines = [(1, "Counter", 2, "blue", "red door", "70001-01-GA", 100.0)] + LINES[1:]
    rig.ledgers = [{"9|70001-01-GA|2": {"row": 9, "drawing": "70001-01-GA", "quantity": 2, "state": "done",
                                        "unit_cost": 100.0, "written": "P9 = 100.0", "run_id": "old-run"}}]
    assert rig.post("baseline", apply=False).json()["applied"] is False
    assert rig.post("check").json()["message"] == routes.NO_BASELINE, "counting is not applying"
    assert rig.baseline()["counts"] == {"completed": 1, "no_earlier_run": 2}
    p = rig.post("check").json()
    by = {d["row_id"]: d for d in p["decisions"]}
    assert by[_id(1)]["group"] == "unchanged" and by[_id(1)]["kind"] == "unchanged_completed"
    assert by[_id(2)]["group"] == "held", "an existing row never priced is not new work either"
    assert p["eligible"] == 0 and p["runnable"] is False
    assert rig.post("baseline", apply=True).status_code == 409, "a baseline is never reset from here"
    rig.lines.append((4, "Shelf", 6, "", "", "70001-01-GA", None))       # the contrast: a row added since
    rig.files["70001-01-GA"] = FILES["70001-01-GA"]
    rig.lines[-1] = (4, "Shelf", 6, "", "", "70004-01-GA", None)
    rig.files["70004-01-GA"] = [("//share/d/70004-01-GA.pdf", 5, 6000.0)]
    by = {d["row_id"]: d for d in rig.post("check").json()["decisions"]}
    assert by[_id(4)]["group"] == "new" and by[_id(4)]["eligible"] is True


def _ready(tmp_path, **kw):
    """Row 1 finished; row 4 new; then row 1's quantity changed."""
    rig = _Rig(tmp_path, **kw)
    rig.lines = [(1, "Counter", 2, "blue", "red door", "70001-01-GA", 100.0)] + LINES[1:]
    rig.ledgers = [{"k": {"drawing": "70001-01-GA", "quantity": 2, "state": "done", "unit_cost": 100.0,
                          "written": "P3", "run_id": "old-run"}}]
    rig.baseline()
    rig.lines[0] = (1, "Counter", 5, "blue", "red door", "70001-01-GA", 100.0)
    rig.lines.append((4, "Shelf", 6, "", "", "70004-01-GA", None))
    rig.files["70004-01-GA"] = [("//share/d/70004-01-GA.pdf", 5, 6000.0)]
    return rig


def test_new_rows_run_and_a_changed_row_runs_only_when_ticked(tmp_path):
    rig = _ready(tmp_path)
    p = rig.post("check").json()
    groups = {d["row_id"]: d["group"] for d in p["decisions"]}
    assert groups == {_id(1): "changed", _id(2): "held", _id(3): "held", _id(4): "new"}
    assert (p["eligible"], p["approvable"], p["runnable"], p["at_once"]) == (1, 1, True, 2)
    r = rig.post("run", plan_id=p["plan_id"])
    assert r.status_code == 200, r.text
    assert [s["rows"] for s in rig.sent] == ["6"] and rig.sent[0]["replace_costs"] is False, \
        "the unticked changed row is not priced, and nothing is replaced"
    assert rig.sent[0]["task_id"] == tti_changes.task_id_for(p["plan_id"])


def test_a_ticked_changed_row_goes_with_the_new_ones_and_only_then_replaces_its_cost(tmp_path):
    rig = _ready(tmp_path)
    p = rig.post("check").json()
    assert rig.post("run", plan_id=p["plan_id"], approved=[_id(2)]).status_code == 409, \
        "a row the preview did not offer as changed cannot be ticked in"
    assert rig.sent == []
    p = rig.post("check").json()
    assert rig.post("run", plan_id=p["plan_id"], approved=[_id(1)]).status_code == 200
    assert rig.sent[0]["rows"] == "3,6" and rig.sent[0]["replace_costs"] is True


def test_a_second_click_and_an_uncertain_reply_never_send_twice(tmp_path):
    rig = _ready(tmp_path)
    p = rig.post("check").json()
    assert rig.post("run", plan_id=p["plan_id"]).status_code == 200
    assert rig.post("run", plan_id=p["plan_id"]).status_code == 409 and len(rig.sent) == 1
    rig.alive = {"task_id": tti_changes.task_id_for(p["plan_id"])}
    again = rig.post("check").json()
    assert "still running" in again["last_batch"] and again["eligible"] == 0
    assert {d["kind"] for d in again["decisions"] if d["row_id"] in (_id(1), _id(4))} == {"held_active_batch"}
    assert rig.post("run", plan_id=again["plan_id"]).status_code == 409 and len(rig.sent) == 1

    lost = _ready(tmp_path / "lost")                        # the request left; the reply never came
    lost.fail = TimeoutError("connection dropped")
    q = lost.post("check").json()
    assert lost.post("run", plan_id=q["plan_id"]).status_code == 409 and len(lost.sent) == 1
    lost.fail = None
    lost.alive = {"task_id": "someone"}                     # a batch is alive: nothing is concluded
    q2 = lost.post("check").json()
    assert q2["eligible"] == 0 and lost.post("run", plan_id=q2["plan_id"]).status_code == 409
    assert len(lost.sent) == 1, "the intent was recorded before sending; it is reconciled, not resent"


def test_a_finished_batch_is_reconciled_from_its_own_status_and_previous_results_are_kept(tmp_path):
    rig = _ready(tmp_path)
    p = rig.post("check").json()
    assert rig.post("run", plan_id=p["plan_id"], approved=[_id(1)]).status_code == 200
    _finished(rig, p["plan_id"], [
        {"row": 3, "state": "done", "unit_cost": 140.0, "written": "P3 = 140.0", "run_id": "new-run"},
        {"row": 6, "state": "needs drawing", "why": "no drawing found"}])
    rig.lines[0] = (1, "Counter", 5, "blue", "red door", "70001-01-GA", 140.0)   # the cost the batch wrote
    nxt = rig.post("check").json()
    assert "1 of 2" in nxt["last_batch"]
    by = {d["row_id"]: d for d in nxt["decisions"]}
    assert by[_id(1)]["group"] == "unchanged", "the re-priced row is finished work again"
    assert by[_id(4)]["group"] == "held" and by[_id(4)]["kind"] == "held_previous_attempt", \
        "a row the batch could not start is shown, never silently sent again"
    with rig.store.connect() as db:
        kept = {r["row_id"]: r for r in json.loads(db.execute("SELECT rows_json FROM baseline").fetchone()[0])}
    assert kept[_id(1)]["run_id"] == "new-run"
    assert [x["run_id"] for x in kept[_id(1)]["previous_results"]] == ["old-run"]
    assert nxt["eligible"] == 0 and len(rig.sent) == 1


def test_an_unfinished_status_releases_nothing(tmp_path):
    rig = _ready(tmp_path)
    p = rig.post("check").json()
    assert rig.post("run", plan_id=p["plan_id"]).status_code == 200
    rig.status[tti_changes.task_id_for(p["plan_id"])] = {"state": "starting", "rows": []}
    nxt = rig.post("check").json()
    assert "without finishing" in nxt["last_batch"] and nxt["eligible"] == 0
    assert rig.store.active_plan("master")["plan_id"] == p["plan_id"]


def test_two_services_share_the_claim_so_only_one_of_them_sends(tmp_path):
    a = _ready(tmp_path)
    b = _Rig(tmp_path, db=a.store.path)
    b.lines, b.files = a.lines, a.files
    pa, pb = a.post("check").json(), b.post("check").json()
    assert pa["eligible"] == pb["eligible"] == 1
    assert a.post("run", plan_id=pa["plan_id"]).status_code == 200
    assert b.post("run", plan_id=pb["plan_id"]).status_code == 409
    assert len(a.sent) == 1 and b.sent == []


def test_pricing_is_off_until_the_switch_is_set_and_refused_while_a_batch_writes(tmp_path):
    rig = _ready(tmp_path, run_on=False)
    p = rig.post("check").json()
    assert p["eligible"] == 1 and p["runnable"] is False and routes.RUN_OFF in p["message"]
    assert rig.post("run", plan_id=p["plan_id"]).status_code == 409 and rig.sent == []
    rig.run_on, rig.busy = True, "A tracker batch is already running (task abc)."
    assert rig.post("run", plan_id=p["plan_id"]).status_code == 409 and rig.sent == []
    rig.busy = None                                         # the contrast: the same preview, now free
    assert rig.post("run", plan_id=p["plan_id"]).status_code == 200 and len(rig.sent) == 1
    assert tti_changes.run_enabled({}) is False and tti_changes.run_enabled({"SDI_TTI_CHANGES_RUN": "1"}) is True


# ── the batch route both buttons share ────────────────────────────────────────────────────

@pytest.fixture
def service(tmp_path, monkeypatch):
    pytest.importorskip("httpx", reason="httpx not installed (FastAPI's TestClient needs it)")
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("SDI_TTI_CHANGES_RUN", raising=False)
    monkeypatch.setenv("SDI_TTI_CENTRAL_SHEET", "")
    clash = ("config", "estimate_routes", "log_filters", "hr_routes", "docmgr",
             "self_running_switch", "estimate_email", "staging", "estimate_history")
    saved = {n: sys.modules.pop(n) for n in clash if n in sys.modules}
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import estimate_routes as er
    except Exception as exc:                                            # noqa: BLE001
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)
        pytest.skip(f"backend not importable here: {exc}")
    try:
        monkeypatch.setattr(er, "_ENGINE_PYTHON", sys.executable)
        monkeypatch.setattr(er.staging.config, "STAGING_ROOT", str(tmp_path / "stage"))
        monkeypatch.setattr(er.config, "API_KEY", "", raising=False)
        app = FastAPI()
        app.include_router(er.router)
        yield TestClient(app), er, tmp_path
    finally:
        for proc in er._TTI_PROCS.values():
            try:
                proc.kill()
                proc.wait(timeout=10)
            except Exception:                                           # noqa: BLE001
                pass
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_the_route_takes_a_row_list_and_always_asks_for_two_at_once_and_drawings_only(service):
    tc, er, tmp = service
    sheet = _tracker(tmp / "t.xlsx", LINES)
    seen = []
    real = er._tti_batch_args

    def spy(*a, **k):
        seen.append(real(*a, **k))
        return [sys.executable, "-c", "pass"]
    er._tti_batch_args = spy
    try:
        post = lambda **b: tc.post("/api/estimate/tti/run", json=dict(sheet=str(sheet), **b))
        assert post(rows="5 to 9").status_code == 400 and post(rows="5-").status_code == 400
        assert post(rows="134, 137; 5-12", dry_run=True).status_code == 200
        assert post(rows="5-12", dry_run=True, at_once=9, drawings_only=False).status_code == 200
    finally:
        er._tti_batch_args = real
    first, second = seen
    assert first[first.index("--rows") + 1] == "134,137,5-12"
    assert first[first.index("--at-once") + 1] == "2" and "--drawings-only" in first
    assert second[second.index("--at-once") + 1] == "2", "never more than the two Grid Runners"
    assert "--drawings-only" not in second and "--dry-run" in second
    sys.path.insert(0, str(ROOT / "src"))
    import tti_pricer
    assert tti_pricer.parse_rows(first[first.index("--rows") + 1]) == [5, 6, 7, 8, 9, 10, 11, 12, 134, 137]


def test_a_second_batch_that_writes_is_refused_while_the_first_is_alive(service):
    tc, er, tmp = service
    sheet = _tracker(tmp / "t.xlsx", LINES)
    real = er._tti_batch_args
    er._tti_batch_args = lambda *a, **k: [sys.executable, "-c", "import time; time.sleep(60)"]
    try:
        post = lambda dry: tc.post("/api/estimate/tti/run", json=dict(sheet=str(sheet), dry_run=dry))
        one = post(False)
        assert one.status_code == 200
        two = post(False)
        assert two.status_code == 409 and one.json()["task_id"] in two.json()["detail"]
        assert len(er._TTI_PROCS) == 1, "the refused click started no process"
        assert post(True).status_code == 200, "finding drawings writes nothing and is not refused"
        assert er._tti_busy(), "the changes button sees the same claim"
        proc = er._TTI_PROCS[one.json()["task_id"]]
        proc.kill()
        proc.wait(timeout=10)
        assert er._tti_busy() is None
        assert post(False).status_code == 200, "a claim whose process has ended is nobody's"
    finally:
        er._tti_batch_args = real


def test_the_claim_is_a_file_so_another_service_and_a_restart_both_see_it(tmp_path):
    lock = tmp_path / "state" / "tti" / "batch.lock"
    tti_batch_lock.claim(lock, "aaaa1111", os.getpid())                 # "the other service's" batch
    assert tti_batch_lock.holder(lock)["task_id"] == "aaaa1111"
    with pytest.raises(tti_batch_lock.Busy):
        tti_batch_lock.claim(lock, "bbbb2222", os.getppid())
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    tti_batch_lock.claim(tmp_path / "other.lock", "cccc3333", gone.pid)
    assert tti_batch_lock.holder(tmp_path / "other.lock") is None
    tti_batch_lock.claim(tmp_path / "other.lock", "dddd4444", os.getpid())
    assert tti_batch_lock.holder(tmp_path / "other.lock")["task_id"] == "dddd4444"


def test_the_buttons_are_mounted_and_check_says_plainly_when_no_master_is_set(service):
    tc, er, tmp = service
    r = tc.post("/api/estimate/tti/changes/check", json={"tracker_id": "master"})
    assert r.status_code == 409 and "SDI_TTI_CENTRAL_SHEET" in r.json()["detail"], r.text
    assert tc.post("/api/estimate/tti/changes/check", json={"tracker_id": "other"}).status_code == 400
    r = tc.post("/api/estimate/tti/changes/run", json={"tracker_id": "master", "plan_id": str(uuid.uuid4())})
    assert r.status_code == 409 and "SDI_TTI_CHANGES_RUN" in r.json()["detail"]
    assert er._TTI_PROCS == {}


def test_the_service_reads_the_master_through_the_engines_own_command(service, monkeypatch):
    tc, er, tmp = service
    master = _tracker(tmp / "MASTER.xlsx", LINES)
    monkeypatch.setenv("SDI_TTI_CENTRAL_SHEET", str(master))
    monkeypatch.setenv("SDI_DRAWING_INDEX", str(tmp / "none" / "index.json.gz"))
    before = master.read_bytes()
    p = tc.post("/api/estimate/tti/changes/check", json={"tracker_id": "master"})
    assert p.status_code == 200, p.text
    body = p.json()
    assert body["message"] == routes.NO_BASELINE and body["rows"] == 3
    assert all(any("drawing index" in x for x in d["reasons"]) for d in body["decisions"] if d["drawing"]), \
        "no index on this machine is said on every row; the share is never listed instead"
    assert master.read_bytes() == before


def test_the_page_offers_the_two_buttons_and_price_starts_disabled():
    assert 'id="ttiChgCheck"' in PAGE and '"/api/estimate/tti/changes/"' in PAGE
    assert '<button class="btn-run" id="ttiChgRun" type="button" disabled>' in PAGE
    assert "ttiChgPlan = null;                 /* never reused" in PAGE
    assert 'id="ttiFind"' in PAGE and 'id="ttiGo"' in PAGE, "the sheet buttons are still there"
