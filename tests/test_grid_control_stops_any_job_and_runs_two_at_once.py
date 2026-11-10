"""Grid Control (formerly the control panel) stops any job, and Self-Running can run two at once
(JG, 10 Nov 2026).

"be able to stop individual jobs whether they are set off as individual jobs or started from the
AI self running and also be able to stop jobs through the Grid Control". A stop by hand is
recorded on the run; Self-Running holds that row until it is marked Re-Run, instead of writing
it off as failed. A job is asked about on the service it was queued on (11896-02-01-GA was
written off as "the portal no longer knows this run" when the watcher was reinstalled with 8071
first and asked 8071 about a run queued on 8072). SDI_SELF_RUNNING_AT_ONCE=2 keeps two jobs
queued, so a second Grid Runner takes the second.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config  # noqa: E402
import live_enquiry_runner as ler  # noqa: E402
import self_running as sr  # noqa: E402

WALL = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-wall.html").read_text(encoding="utf-8")
PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
    encoding="utf-8")
ROUTES = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")


def _row(n, drawing, customer="M&S", qty="1, 40", completed=""):
    return ler.EnquiryRow(row=n, customer=customer, drawing=drawing, description="RAIL",
                          received=date(2026, 10, 23), ai_check="YES", quantities=qty)


@pytest.fixture
def share(tmp_path):
    root = tmp_path / "Live Enquiry"
    for d in ("0360001", "0360002", "0360003"):
        (root / "M&S" / d).mkdir(parents=True)
        (root / "M&S" / d / f"{d}-GA.pdf").write_bytes(b"%PDF-1.4 " + d.encode())
    return {"root": root, "ledger": tmp_path / "ledger.json",
            "workbook": tmp_path / "Live Enquiry.xlsx"}


class Portal:
    """Each run is running for `polls` status calls, then done or stopped by hand."""

    def __init__(self, server="http://localhost:8071", polls=2, stopped=()):
        self.server, self.polls, self.stopped = server, polls, set(stopped)
        self.started, self.asked, self.most_at_once = [], {}, 0

    def start(self, body):
        self.started.append(body["drawing_number"])
        rid = f"r{len(self.started)}"
        self.asked[rid] = 0
        live = sum(1 for n in self.asked.values() if n < self.polls)
        self.most_at_once = max(self.most_at_once, live)
        return {"run_id": rid, "output_path": "\\\\share\\x"}

    def status(self, run_id):
        if run_id not in self.asked:
            raise ler.PortalError(404, "No such run")
        self.asked[run_id] += 1
        if self.asked[run_id] < self.polls:
            return {"status": "running"}
        if run_id in self.stopped:
            return {"status": "error", "stopped_by_hand": True,
                    "error": "Released by hand from the page."}
        return {"status": "done", "engine_price_gbp": 10.0, "seconds": 60, "deliverables": []}


class Switch:
    def __init__(self):
        self.beats = []

    def beat(self, rep):
        self.beats.append(rep)
        return True


def _wait():
    return {"poll_seconds": 0, "sleep": lambda s: None}


# ── a stop by hand holds the row ──────────────────────────────────────────────────────
def test_a_job_stopped_by_hand_is_held_until_it_is_marked_re_run(share, monkeypatch):
    rows = [_row(5, "0360001")]
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": rows)
    sr.cycle(dict(share), Portal(stopped={"r1"}), Switch(), say=lambda s: None, wait=_wait())
    ledger = ler.load_ledger(share["ledger"])
    attempt = ledger["jobs"][ler.job_key(rows[0])]["attempts"][-1]
    assert attempt["stopped_by_hand"] is True
    d = ler.plan(rows, ler._sources(share["root"]), ledger)[0]
    assert d.status == "held" and "stopped by hand" in d.reason and "Re-Run" in d.reason
    again = Portal()
    sr.cycle(dict(share), again, Switch(), say=lambda s: None, wait=_wait())
    assert again.started == [], "a stopped job is not queued again on its own"
    ledger["jobs"][ler.job_key(rows[0])]["retry"] = True
    assert ler.plan(rows, ler._sources(share["root"]), ledger)[0].status == "ready"


def test_a_service_older_than_the_flag_is_read_by_its_stop_message():
    assert ler.stopped_by_hand({"error": "Released by hand from the page. The queue is free"})
    assert ler.stopped_by_hand({"error": "Released with the rest of this enquiry. It had not"})
    assert not ler.stopped_by_hand({"error": "Excel is busy"})


def test_the_service_records_a_stop_by_hand_on_the_run():
    assert ROUTES.count("run.stopped_by_hand = True") == 2, "single stop and enquiry stop"
    assert '"stopped_by_hand": self.stopped_by_hand' in ROUTES


# ── asked where it was queued ─────────────────────────────────────────────────────────
def test_a_job_is_asked_about_on_the_service_it_was_queued_on(tmp_path):
    a = Portal("http://localhost:8071")
    b = Portal("http://localhost:8072")
    b.asked["r9"] = 0
    ledger = {"jobs": {"k": {"attempts": [{"run_id": "r9", "status": "queued",
                                           "server": "http://localhost:8072"}]}}}
    ler.refresh_open_runs(ledger, a, [a, b])
    att = ledger["jobs"]["k"]["attempts"][0]
    assert att["status"] == "running" and b.asked["r9"] == 1
    # an older attempt with no server recorded is found on any service on the list
    old = {"jobs": {"k": {"attempts": [{"run_id": "r9", "status": "queued"}]}}}
    ler.refresh_open_runs(old, a, [a, b])
    assert old["jobs"]["k"]["attempts"][0]["status"] != "error"
    gone = {"jobs": {"k": {"attempts": [{"run_id": "zz", "status": "queued"}]}}}
    ler.refresh_open_runs(gone, a, [a, b])
    assert "no service on the list knows this run" in gone["jobs"]["k"]["attempts"][0]["error"]


def test_the_service_a_job_was_queued_on_is_written_in_the_ledger(share, monkeypatch):
    rows = [_row(5, "0360001")]
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": rows)
    sr.cycle(dict(share), Portal("http://localhost:8071"), Switch(), say=lambda s: None,
             wait=_wait())
    att = ler.load_ledger(share["ledger"])["jobs"][ler.job_key(rows[0])]["attempts"][-1]
    assert att["server"] == "http://localhost:8071"


# ── two at once ───────────────────────────────────────────────────────────────────────
def test_one_at_a_time_is_still_the_default(share, monkeypatch):
    assert config.SELF_RUNNING_AT_ONCE == 1 or os.getenv("SDI_SELF_RUNNING_AT_ONCE")
    monkeypatch.setattr(config, "SELF_RUNNING_AT_ONCE", 1)
    rows = [_row(5, "0360001"), _row(6, "0360002"), _row(7, "0360003")]
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": rows)
    p = Portal(polls=3)
    out = sr.cycle(dict(share), p, Switch(), say=lambda s: None, wait=_wait())
    assert len(p.started) == 3 and p.most_at_once == 1
    assert out["counts"].get("done") == 3


def test_two_at_once_keeps_two_jobs_queued_and_runs_every_ready_row(share, monkeypatch):
    monkeypatch.setattr(config, "SELF_RUNNING_AT_ONCE", 2)
    rows = [_row(5, "0360001"), _row(6, "0360002"), _row(7, "0360003")]
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": rows)
    p, sw = Portal(polls=3), Switch()
    out = sr.cycle(dict(share), p, sw, say=lambda s: None, wait=_wait())
    assert sorted(p.started) == ["0360001", "0360002", "0360003"]
    assert p.most_at_once == 2, "the second is queued while the first runs"
    assert out["counts"].get("done") == 3 and len(out["ran"]) == 3
    running = [b for b in sw.beats if b.get("phase") == "running"]
    assert any(b["current"].get("also") for b in running), "the card names the other job"


def test_two_at_once_still_obeys_the_switch(share, monkeypatch):
    monkeypatch.setattr(config, "SELF_RUNNING_AT_ONCE", 2)
    rows = [_row(5, "0360001"), _row(6, "0360002"), _row(7, "0360003")]
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": rows)

    class Off(Switch):
        def beat(self, rep):
            self.beats.append(rep)
            # on for reading the sheet and the first job, off from then on
            return len(self.beats) <= 2

    p = Portal(polls=2)
    sr.cycle(dict(share), p, Off(), say=lambda s: None, wait=_wait())
    assert p.started == ["0360001"]


# ── the pages ─────────────────────────────────────────────────────────────────────────
def test_grid_control_names_and_a_stop_on_every_running_and_queued_job():
    assert "<title>Grid Control</title>" in WALL and '<div class="sub">GRID CONTROL</div>' in WALL
    assert "<b>Fleet Grid Runners</b>" in WALL and "Fleet · runners" not in WALL
    assert "${stopBtn(r)}${badge(r.rag, WORD[r.rag])}" in WALL, "on each running lane"
    assert 'waiting " + fmtDur(n - (r.queued_at || n))}</span>${stopBtn(r)}' in WALL, "on the queue"
    assert '"/api/estimate/" + encodeURIComponent(id) + "/abandon"' in WALL
    assert ">Grid Control ↗</a>" in PAGE and ">Control panel ↗</a>" not in PAGE


def test_the_self_running_card_names_the_second_job():
    assert '" Also on the grid: " + cur.also.join(", ")' in PAGE


# ── a restarted watcher counts the jobs it already queued (JG, 10 Nov 2026) ─────────────
def test_a_restarted_watcher_waits_on_its_queued_jobs_before_queueing_more(share, monkeypatch):
    """Four of its jobs sat in the queue at once, one per restart of the watcher."""
    monkeypatch.setattr(config, "SELF_RUNNING_AT_ONCE", 1)
    rows = [_row(5, "0360001"), _row(6, "0360002"), _row(7, "0360003")]
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": rows)
    first = Portal(polls=99)                        # queued, and still queued when it stops
    ledger = ler.load_ledger(share["ledger"])
    d = ler.plan(rows[:1], ler._sources(share["root"]), ledger)[0]
    ler.queue_one(d, first, ledger, share["ledger"], say=lambda s: None)
    ler.save_ledger(share["ledger"], ledger)
    # the watcher restarts; the service still has r1 and finishes it after a few polls
    second = Portal(polls=3)
    second.asked["r1"] = 0
    said = []
    sr.cycle(dict(share), second, Switch(), say=said.append, wait=_wait())
    assert any("on the portal as run r1" in s and "waiting for it" in s for s in said)
    assert second.started == ["0360002", "0360003"], "nothing more until r1 had finished"
    assert second.most_at_once <= 1


def test_the_card_says_queued_until_a_grid_runner_takes_it():
    assert '(cur.state === "queued" ? "Queued " : "Running ")' in PAGE
    assert '", waiting for a free Grid Runner."' in PAGE


# ── 10 Nov 10:22: duplicate copies, ghosts, a Stop on every job ───────────────────────
def test_an_older_queued_copy_of_a_job_is_withdrawn_and_the_newest_kept(share, monkeypatch):
    """11896-04-00-GA ran on 8071 while an earlier copy waited on 8072 to run it again."""
    monkeypatch.setattr(config, "SELF_RUNNING_AT_ONCE", 1)
    rows = [_row(5, "0360001")]
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": rows)
    p8072, p8071 = Portal("http://localhost:8072", polls=99), Portal("http://localhost:8071", polls=2)
    ledger = ler.load_ledger(share["ledger"])
    d = ler.plan(rows, ler._sources(share["root"]), ledger)[0]
    ler.queue_one(d, p8072, ledger, share["ledger"], say=lambda s: None)     # r1 on 8072
    ler.queue_one(d, p8071, ledger, share["ledger"], say=lambda s: None)     # r1 on 8071
    ledger["jobs"][ler.job_key(rows[0])]["attempts"][1]["run_id"] = "n1"
    p8071.asked["n1"] = p8071.asked.pop("r1")
    ler.save_ledger(share["ledger"], ledger)
    withdrawn = []
    p8072.status = lambda rid: {"status": "queued"}          # still waiting on 8072
    p8072.abandon = lambda rid: withdrawn.append(rid) or {"ok": True}
    said = []
    sr.cycle(dict(share), p8071, Switch(), say=said.append, wait=_wait(), others=[p8071, p8072])
    assert withdrawn == ["r1"], "the older copy is withdrawn from the service it is on"
    a = ler.load_ledger(share["ledger"])["jobs"][ler.job_key(rows[0])]["attempts"]
    assert a[0]["withdrawn"] and a[0]["status"] == "error" and a[1]["status"] == "done"
    assert any("withdrew queued copy r1" in s for s in said)


def test_the_portal_client_can_stop_a_run():
    src = (ROOT / "src" / "live_enquiry_runner.py").read_text(encoding="utf-8")
    assert 'return self._call("POST", f"/api/estimate/{run_id}/abandon", {})' in src


def test_a_run_its_runner_has_left_is_freed_when_that_runner_beats_for_another_service():
    assert "_release_runs_its_runner_has_left(req.runner_id, now)" in ROUTES
    assert "if now - last < 120:" in ROUTES, "never a run with progress in the last two minutes"


def test_a_runner_heard_only_mid_job_is_named_by_its_machine():
    import importlib
    sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
    try:
        src = ROUTES
        assert "r.hostname = _host_of(req.runner_id)" in src
        import re
        m = re.search(r're\.match\(r"(.+?)", str\(runner_id', src)
        pat = re.compile(m.group(1))
        assert pat.match("DESKTOP-GFAAP80-90faa0001").group(1) == "DESKTOP-GFAAP80"
        assert pat.match("DESKTOP-GFAAP80-90faa0001-s2").group(1) == "DESKTOP-GFAAP80"
        assert pat.match("laptop") is None
    finally:
        sys.path.remove(str(ROOT / "sdi-intelligence-backend"))


def test_every_queued_or_running_job_has_its_own_stop_on_the_estimating_page():
    assert "data-self-stop='\" + selfEsc(r.run_id)" in PAGE
    assert '(r.status === "queued" || r.status === "running") && r.run_id' in PAGE
    assert 'await api("/api/estimate/grid/stop", {method:"POST"' in PAGE, "a job on the other service"
    assert '["running","queued or running"]' in PAGE
    assert "Also on this machine: the service on port" in PAGE and "Use one portal" not in PAGE
    rr = sr.recent_runs({"jobs": {"k": {"customer": "TTI", "drawing": "X", "attempts": [
        {"status": "queued", "run_id": "r9", "server": "http://localhost:8072",
         "queued_at": "2026-11-10T10:00:00"}]}}})
    assert rr[0]["run_id"] == "r9" and rr[0]["server"] == "http://localhost:8072"
