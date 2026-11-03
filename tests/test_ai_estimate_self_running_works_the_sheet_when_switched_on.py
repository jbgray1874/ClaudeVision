"""AI Estimate Self-Running works the Live Enquiry sheet when, and only when, it is switched on
(D-588).

James Gray, 23 Oct 2026: a new button on the portal, "AI Estimate Self-Running" — the code
provisionally worked on that works through the Live Enquiry spreadsheet, finds every job not yet
worked on, extracts its drawing pack and runs it.

The button is a switch held by the service. The work is done by a watcher on the estimating
machine (src/self_running.py), which asks on every beat and does nothing unless it has just been
told yes: it reads the sheet with the Live Enquiry runner's own reader, collects a waiting row's
drawings from Production with the collector's own search into the runner's folder layout, and
runs every ready row through the portal one after another. Switched off, the job in progress
finishes and nothing more is queued.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import live_enquiry_runner as ler  # noqa: E402
import self_running as sr  # noqa: E402

PAGE = ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html"
ROUTES = ROOT / "sdi-intelligence-backend" / "estimate_routes.py"


# ── the button, and the wire between it and the service ──────────────────────────────

def test_the_button_is_on_the_page_with_its_name():
    page = PAGE.read_text(encoding="utf-8")
    at = page.index('id="selfRun"')
    assert "AI Estimate Self-Running" in page[at:at + 400]
    assert 'id="selfStop"' in page and 'id="selfStatus"' in page


def test_the_page_posts_to_paths_the_router_serves():
    page = PAGE.read_text(encoding="utf-8")
    routes = ROUTES.read_text(encoding="utf-8")
    assert '"/api/estimate/self-running"' in page
    assert '"/api/estimate/self-running/" + (on ? "start" : "stop")' in page
    for path in ('@router.get("/self-running")', '@router.post("/self-running/start")',
                 '@router.post("/self-running/stop")', '@router.post("/self-running/heartbeat")'):
        assert path in routes, path
    assert ler.Portal("http://x").self_running.__doc__
    assert "/api/estimate/self-running/heartbeat" in (ROOT / "src" /
                                                      "live_enquiry_runner.py").read_text()


def test_self_running_is_never_read_as_a_run_id():
    """FastAPI matches routes in the order they are defined: GET /self-running after the
    catch-all GET /{run_id} would be answered as an unknown run."""
    routes = ROUTES.read_text(encoding="utf-8")
    assert routes.index('@router.get("/self-running")') < routes.index('@router.get("/{run_id}")')


# ── the service's switch ─────────────────────────────────────────────────────────────

@pytest.fixture
def switch_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path))
    sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
    import importlib
    import self_running_switch as m
    importlib.reload(m)
    yield m
    sys.path.remove(str(ROOT / "sdi-intelligence-backend"))


def test_off_until_someone_presses_it(switch_mod):
    v = switch_mod.view()
    assert v["enabled"] is False and v["watcher"]["connected"] is False
    _hb = switch_mod.heartbeat({"phase": "idle"})
    assert (_hb["enabled"], _hb["run_now"], _hb["toggled_epoch"]) == (False, False, 0.0)


def test_a_press_is_on_and_asks_for_one_immediate_read(switch_mod):
    v = switch_mod.switch(True, by="James Gray")
    assert v["enabled"] and v["run_now_pending"] and v["switched_by"] == "James Gray"
    _hb = switch_mod.heartbeat({"phase": "idle"})
    assert _hb["enabled"] is True and _hb["run_now"] is True and _hb["toggled_epoch"] > 0
    _again = switch_mod.heartbeat({"phase": "idle"})
    assert (_again["enabled"], _again["run_now"]) == (True, False), "one press, one read"


def test_stop_is_off(switch_mod):
    switch_mod.switch(True)
    switch_mod.switch(False)
    assert switch_mod.heartbeat({"phase": "running"})["enabled"] is False
    assert switch_mod.view()["switched_off_at"]


def test_a_quiet_watcher_is_not_connected_not_idle(switch_mod):
    switch_mod.heartbeat({"phase": "idle"}, now=1000.0)
    assert switch_mod.view(now=1000.0 + 60)["watcher"]["connected"] is True
    gone = switch_mod.view(now=1000.0 + switch_mod.STALE_SECONDS + 1)["watcher"]
    assert gone["connected"] is False and gone["seconds_since"] > switch_mod.STALE_SECONDS


def test_the_last_cycles_tally_survives_a_short_beat(switch_mod):
    switch_mod.heartbeat({"phase": "waiting", "counts": {"ready": 2}, "recent": [{"drawing": "A"}]})
    switch_mod.heartbeat({"phase": "idle"})
    w = switch_mod.view()["watcher"]
    assert w["counts"] == {"ready": 2} and w["recent"] == [{"drawing": "A"}]
    assert w["phase"] == "idle"


# ── the card's run window (D-626) ────────────────────────────────────────────────────
#
# JG, 2 Nov 2026: the price of each quantity ran (D-610's quantity_prices, carried through
# here untouched), "only show the number ran for the past week and a max of 100, or we'll
# run out of space".

def _ledger_of(attempts):
    return {"jobs": {str(i): {"customer": "TTI", "drawing": f"J{i}", "attempts": [a]}
                     for i, a in enumerate(attempts)}}


def test_the_card_lists_the_past_week_only_and_at_most_100():
    from datetime import datetime
    now = datetime(2026, 11, 2, 12, 0, 0)
    attempts = [{"status": "done", "queued_at": "2026-11-01T10:00:00",
                 "finished_at": "2026-11-01T10:40:00",
                 "quantity_prices": [{"quantity": 1, "unit_gbp": 421.37},
                                     {"quantity": 10, "unit_gbp": 300.0}]},
                {"status": "done", "queued_at": "2026-10-25T10:00:00",
                 "finished_at": "2026-10-25T10:40:00"},          # 8 days old — off the card
                {"status": "error", "queued_at": "2026-10-20T10:00:00",
                 "finished_at": "2026-10-20T10:10:00"}]
    rows = sr.recent_runs(_ledger_of(attempts), now=now)
    assert [r["drawing"] for r in rows] == ["J0"]
    assert rows[0]["quantity_prices"][1] == {"quantity": 10, "unit_gbp": 300.0}
    many = [{"status": "done", "queued_at": f"2026-11-01T10:00:{s % 60:02d}",
             "finished_at": "2026-11-01T11:00:00"} for s in range(130)]
    assert len(sr.recent_runs(_ledger_of(many), now=now)) == 100


def test_a_run_still_going_stays_on_the_card_whatever_its_age():
    from datetime import datetime
    rows = sr.recent_runs(_ledger_of([
        {"status": "running", "queued_at": "2026-10-01T10:00:00"},
        {"status": "queued", "queued_at": "2026-09-01T10:00:00"}]),
        now=datetime(2026, 11, 2, 12, 0, 0))
    assert {r["status"] for r in rows} == {"running", "queued"}


# ── the watcher obeys the switch ─────────────────────────────────────────────────────

class _Unreachable:
    def self_running(self, report):
        raise ler.PortalError(0, "no answer")


def test_a_portal_that_cannot_be_heard_is_off():
    assert sr.Switch(_Unreachable(), say=lambda s: None).beat({}) is False


class FakePortal:
    def __init__(self):
        self.started = []

    def start(self, body):
        self.started.append(body["drawing_number"])
        return {"run_id": f"r{len(self.started)}", "output_path": "\\\\share\\AISheets\\x"}

    def status(self, run_id):
        return {"status": "done", "engine_price_gbp": 99.0, "seconds": 60,
                "output_path": "\\\\share\\AISheets\\x", "deliverables": []}


class FakeSwitch:
    def __init__(self, answers):
        self.answers, self.beats = list(answers), []

    def beat(self, rep):
        self.beats.append(rep)
        return self.answers.pop(0) if self.answers else True


def _row(n, drawing, customer="M&S", qty="1, 40"):
    return ler.EnquiryRow(row=n, customer=customer, drawing=drawing, description="RAIL",
                          received=date(2026, 10, 23), ai_check="YES", quantities=qty)


@pytest.fixture
def share(tmp_path, monkeypatch):
    root = tmp_path / "Live Enquiry"
    prod = tmp_path / "Production"
    (prod / "M&S" / "ROL").mkdir(parents=True)
    (prod / "M&S" / "ROL" / "0351292-GA-RAIL.pdf").write_bytes(b"%PDF-1.4 rail")
    (root / "M&S" / "0360001").mkdir(parents=True)
    (root / "M&S" / "0360001" / "0360001-GA.pdf").write_bytes(b"%PDF-1.4 other")
    monkeypatch.setenv("PRODUCTION_ROOT", str(prod))
    monkeypatch.setenv("STATE_FILE", str(tmp_path / "collector_state.json"))
    return {"root": root, "prod": prod, "ledger": tmp_path / "ledger.json",
            "workbook": tmp_path / "Live Enquiry.xlsx"}


def _settings(share):
    return {"root": share["root"], "ledger": share["ledger"], "workbook": share["workbook"]}


def test_a_waiting_rows_drawings_are_collected_into_the_runners_layout(share):
    ledger = ler.load_ledger(share["ledger"])
    decisions = ler.plan([_row(5, "0351292")], ler._sources(share["root"]), ledger)
    assert decisions[0].status == "waiting"
    got = sr.collect_missing_packs(decisions, share["root"], ledger, say=lambda s: None)
    assert got[0]["status"] == "copied"
    copied = share["root"] / "M&S" / "0351292" / "0351292-GA-RAIL.pdf"
    assert copied.is_file()
    again = ler.plan([_row(5, "0351292")], ler._sources(share["root"]), ledger)
    assert again[0].status == "ready", "the runner finds what was collected"


def test_a_pack_not_in_production_is_not_searched_every_cycle(share):
    ledger = ler.load_ledger(share["ledger"])
    decisions = ler.plan([_row(7, "9999999")], ler._sources(share["root"]), ledger)
    now = datetime(2026, 10, 23, 10, 0)
    first = sr.collect_missing_packs(decisions, share["root"], ledger, say=lambda s: None, now=now)
    assert first[0]["status"] == "not_found"
    soon = sr.collect_missing_packs(decisions, share["root"], ledger, say=lambda s: None,
                                    now=now + timedelta(hours=1))
    assert soon == []
    later = sr.collect_missing_packs(decisions, share["root"], ledger, say=lambda s: None,
                                     now=now + timedelta(hours=24))
    assert later and later[0]["status"] == "not_found"


def test_a_dry_run_copies_nothing_and_records_nothing(share):
    ledger = ler.load_ledger(share["ledger"])
    decisions = ler.plan([_row(5, "0351292")], ler._sources(share["root"]), ledger)
    sr.collect_missing_packs(decisions, share["root"], ledger, dry_run=True, say=lambda s: None)
    assert not (share["root"] / "M&S" / "0351292" / "0351292-GA-RAIL.pdf").exists()
    assert not ledger.get("collected")


def test_one_cycle_collects_then_runs_every_ready_job_in_turn(share, monkeypatch):
    # Collecting from Production is switched on for this test; it is off by default (D-608).
    monkeypatch.setattr(sr.config, "LIVE_ENQUIRY_COLLECT_FROM_PRODUCTION", True)
    rows = [_row(5, "0351292"), _row(6, "0360001")]
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": rows)
    portal = FakePortal()
    out = sr.cycle(_settings(share), portal, FakeSwitch([]), say=lambda s: None,
                   wait={"poll_seconds": 0, "sleep": lambda s: None})
    assert sorted(portal.started) == ["0351292", "0360001"]
    assert out["counts"].get("done") == 2
    ledger = ler.load_ledger(share["ledger"])
    assert [v["status"] for v in ledger["collected"].values()] == ["copied"]


def test_by_default_a_cycle_takes_packs_from_the_live_enquiry_folder_only(share, monkeypatch):
    """JG, 31 Oct 2026 (D-608): until the extraction endpoint is ready the drawings are looked
    for under the Live Enquiry root, and nothing is copied in from Production."""
    monkeypatch.setattr(sr.config, "LIVE_ENQUIRY_COLLECT_FROM_PRODUCTION", False)
    rows = [_row(5, "0351292"), _row(6, "0360001")]
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": rows)
    portal = FakePortal()
    out = sr.cycle(_settings(share), portal, FakeSwitch([]), say=lambda s: None,
                   wait={"poll_seconds": 0, "sleep": lambda s: None})
    assert portal.started == ["0360001"], "only the pack already in the Live Enquiry folder"
    assert out["collected"] == []
    assert not (share["root"] / "M&S" / "0351292").exists(), "nothing copied from Production"
    assert out["counts"].get("waiting") == 1


def test_switched_off_between_jobs_queues_nothing_more(share, monkeypatch):
    rows = [_row(5, "0351292"), _row(6, "0360001")]
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": rows)
    portal = FakePortal()
    # beat 1: reading the sheet; beat 2: before the first job (on); beat 3: before the second (off)
    sr.cycle(_settings(share), portal, FakeSwitch([True, True, False]), say=lambda s: None,
             wait={"poll_seconds": 0, "sleep": lambda s: None})
    assert len(portal.started) == 1


def test_the_page_is_told_which_job_is_running(share, monkeypatch):
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": [_row(6, "0360001")])
    switch = FakeSwitch([])
    sr.cycle(_settings(share), FakePortal(), switch, say=lambda s: None,
             wait={"poll_seconds": 0, "sleep": lambda s: None})
    running = [b for b in switch.beats if b.get("phase") == "running"]
    assert running and running[0]["current"]["drawing"] == "0360001"


class _SlowPortal(FakePortal):
    """Running on the first status call, done on the second."""
    def __init__(self):
        super().__init__()
        self.calls = 0

    def status(self, run_id):
        self.calls += 1
        if self.calls == 1:
            return {"status": "running"}
        return super().status(run_id)


def test_the_job_self_running_started_is_reported_with_its_run_id(share, monkeypatch):
    """No browser tab started it, so no tab had its id; the page stops it by this one."""
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": [_row(6, "0360001")])
    monkeypatch.setattr(sr.time, "sleep", lambda s: None)
    switch = FakeSwitch([])
    sr.cycle(_settings(share), _SlowPortal(), switch, say=lambda s: None)
    during = [b for b in switch.beats
              if b.get("phase") == "running" and (b.get("current") or {}).get("run_id")]
    assert during and during[0]["current"]["run_id"] == "r1"


def test_the_card_stops_the_job_by_the_reported_run_id():
    page = PAGE.read_text(encoding="utf-8")
    assert 'id="selfJobStop"' in page
    handler = page[page.index("selfJobBtn.onclick"):]
    handler = handler[:handler.index("refreshSelf();")]
    assert '"/abandon"' in handler and "dataset.runId" in handler


# ── the four routes, served ──────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    """The backend's router in a real FastAPI app, isolated as the override endpoint's test
    isolates it: the engine's `config` is already imported under the same name."""
    pytest.importorskip("fastapi", reason="fastapi not installed")
    import os
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path))
    os.environ.setdefault("SDI_FILE_ROOTS", str(tmp_path))
    clash = ("config", "estimate_routes", "log_filters", "hr_routes", "docmgr",
             "self_running_switch", "estimate_email")
    saved = {n: sys.modules.pop(n) for n in clash if n in sys.modules}
    backend = str(ROOT / "sdi-intelligence-backend")
    sys.path.insert(0, backend)
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import estimate_routes as er
        app = FastAPI()
        app.include_router(er.router)
        tc = TestClient(app)
        key = getattr(er.config, "API_KEY", "") or ""
        if key:
            tc.headers.update({"X-SDI-Key": key})
        yield tc
    except Exception as exc:                                            # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    finally:
        sys.path.remove(backend)
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_the_routes_switch_it_and_hear_the_watcher(client):
    assert client.get("/api/estimate/self-running").json()["enabled"] is False
    on = client.post("/api/estimate/self-running/start", json={}).json()
    assert on["enabled"] is True and "no self-running watcher is connected" in on["note"]
    beat = client.post("/api/estimate/self-running/heartbeat",
                       json={"phase": "running", "current": {"drawing": "0351292"}}).json()
    assert beat["enabled"] is True and beat["run_now"] is True
    assert beat["toggled_epoch"] > 0, "the beat says when the switch was last pressed (D-644)"
    seen = client.get("/api/estimate/self-running").json()
    assert seen["watcher"]["connected"] and seen["watcher"]["current"]["drawing"] == "0351292"
    off = client.post("/api/estimate/self-running/stop", json={}).json()
    assert off["enabled"] is False
    assert client.post("/api/estimate/self-running/heartbeat", json={}).json()["enabled"] is False


def test_a_row_made_ready_during_a_job_runs_in_the_same_cycle(share, monkeypatch):
    """D-639: the sheet is read again after each finished job. A row added while the first
    job ran is next, not left for the next cycle 15 minutes after this one ends."""
    reads = {"n": 0}

    def _read(path, sheet=""):
        reads["n"] += 1
        rows = [_row(6, "0360001")]
        if reads["n"] > 1:                      # the line was added while 0360001 ran
            (share["root"] / "M&S" / "0360002").mkdir(parents=True, exist_ok=True)
            (share["root"] / "M&S" / "0360002" / "0360002-GA.pdf").write_bytes(b"%PDF-1.4")
            rows.append(_row(7, "0360002"))
        return rows
    monkeypatch.setattr(ler, "read_sheet", _read)
    portal = FakePortal()
    out = sr.cycle(_settings(share), portal, FakeSwitch([]), say=lambda s: None,
                   wait={"poll_seconds": 0, "sleep": lambda s: None})
    assert portal.started == ["0360001", "0360002"]
    assert out["counts"].get("done") == 2


def test_a_failed_row_is_tried_once_a_cycle_not_looped(share, monkeypatch):
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": [_row(6, "0360001")])

    class _Failing(FakePortal):
        def status(self, run_id):
            return {"status": "error", "error": "boom"}
    portal = _Failing()
    sr.cycle(_settings(share), portal, FakeSwitch([]), say=lambda s: None,
             wait={"poll_seconds": 0, "sleep": lambda s: None})
    assert portal.started == ["0360001"]


def test_a_stop_sent_from_the_card_stays_said_until_the_watcher_reports():
    """D-643: the 20-second refresh overwrote "Stop requested", and the card drew "running"
    from the watcher's last report, so a stop that had landed read as one that did nothing.
    The page remembers the run it stopped, says so on every refresh, and treats a 409 (the
    service already holds it stopped) as landed."""
    page = PAGE.read_text(encoding="utf-8")
    assert "const selfStopped = {};" in page
    assert "STOP SENT at" in page
    assert "if(r.ok || r.status === 409){" in page
    assert "selfJobBtn.disabled = !!stoppedAt;" in page


def test_a_stopped_job_is_let_go_of_before_the_sheet_is_read_again(share, monkeypatch):
    """D-649: the card drew "running" (and its Stop button "Stopping") from the watcher's last
    report, which said running until the sheet and the Live Enquiry folders had been read
    again for the next job. The watcher reports the moment a job ends, with no job current."""
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": [_row(6, "0360001")])

    class _Stopped(FakePortal):
        def status(self, run_id):
            return {"status": "error", "error": "Released by hand from the page."}
    switch = FakeSwitch([])
    sr.cycle(_settings(share), _Stopped(), switch, say=lambda s: None,
             wait={"poll_seconds": 0, "sleep": lambda s: None})
    phases = [b.get("phase") for b in switch.beats]
    assert "running" in phases and "between jobs" in phases
    ended = switch.beats[phases.index("between jobs")]
    assert phases.index("running") < phases.index("between jobs")
    assert not ended.get("current"), "the ended job is no longer reported as current"
    assert "0360001" in ended["message"] and "ended without an estimate" in ended["message"]


def test_a_running_job_is_checked_every_ten_seconds(share, monkeypatch):
    """D-649: the watcher asked after a job every 30s, so a stop pressed on the page waited up
    to half a minute before the watcher even noticed."""
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": [_row(6, "0360001")])
    slept = []
    monkeypatch.setattr(sr.time, "sleep", slept.append)
    sr.cycle(_settings(share), FakePortal(), FakeSwitch([]), say=lambda s: None)
    assert sr.JOB_POLL_SECONDS == 10
    assert slept and set(slept) == {10}


def test_the_card_asks_every_five_seconds_while_a_stop_is_pending():
    """D-649: after Stop, the card is refreshed every 5s (for a minute at most) until the
    watcher reports the job ended, not at the page's usual 20s."""
    page = PAGE.read_text(encoding="utf-8")
    handler = page[page.index("selfJobBtn.onclick = async"):]
    handler = handler[:handler.index("refreshSelf();\nsetInterval(refreshSelf, 20000);")]
    assert "quickSelf();" in handler
    assert "}, 5000);" in page[page.index("function quickSelf()"):]
    assert "if(!stoppedAt && selfQuick){ clearInterval(selfQuick); selfQuick = null; }" in page



class _SwitchPortal:
    def __init__(self, server, answer=None, down=False):
        self.server, self.answer, self.down, self.reports = server, answer or {}, down, []

    def self_running(self, rep):
        if self.down:
            raise ler.PortalError(0, "no answer")
        self.reports.append(rep)
        return dict(self.answer)


def test_the_watcher_reports_to_every_service_and_obeys_the_latest_press():
    """D-644: the phone's switch was on a service the watcher never reported to, and said
    "not connected". The beat now goes to every service on the list; the switch pressed most
    recently on any of them is obeyed, so Off pressed anywhere still stops it."""
    laptop = _SwitchPortal("http://localhost:8072", {"enabled": False, "toggled_epoch": 100.0})
    phone = _SwitchPortal("http://localhost:8071",
                          {"enabled": True, "run_now": True, "toggled_epoch": 200.0})
    sw = sr.Switch([laptop, phone], say=lambda s: None)
    assert sw.beat({"phase": "idle"}) is True and sw.last["run_now"] is True
    assert laptop.reports and phone.reports, "both services hear the watcher"
    laptop.answer = {"enabled": False, "toggled_epoch": 300.0}       # Off pressed later
    assert sw.beat({"phase": "idle"}) is False
    assert sw.last["run_now"] is False


def test_a_service_that_cannot_be_reached_is_left_out_and_none_is_off():
    said = []
    up = _SwitchPortal("a", {"enabled": True, "toggled_epoch": 5.0})
    down = _SwitchPortal("b", down=True)
    sw = sr.Switch([down, up], say=said.append)
    assert sw.beat({}) is True
    sw.beat({})
    assert len(said) == 1, "an unreachable service is said once, not every beat"
    assert sr.Switch([_SwitchPortal("c", down=True)], say=lambda s: None).beat({}) is False


def test_a_service_takes_a_newer_press_the_watcher_passes_on(switch_mod):
    """D-650: each screen showed its own switch. The laptop page read "Switched off" while
    the watcher ran jobs on an On pressed later on the phone. A press passed on by the
    watcher is taken when it is newer, without asking for another immediate read."""
    switch_mod.switch(False)
    mine = switch_mod.heartbeat({"phase": "idle"})["toggled_epoch"]
    later = {"enabled": True, "toggled_epoch": mine + 60, "switched_by": "the phone",
             "switched_on_at": "2026-11-03T15:00:00+00:00"}
    hb = switch_mod.heartbeat({"phase": "running", "obeyed": later})
    assert hb["enabled"] is True and hb["run_now"] is False
    assert hb["toggled_epoch"] == mine + 60
    v = switch_mod.view()
    assert v["enabled"] is True and v["switched_by"] == "the phone"
    assert v["switched_on_at"] == "2026-11-03T15:00:00+00:00"
    assert "obeyed" not in v["watcher"], "the relay is not part of what the watcher said"


def test_an_older_press_passed_on_changes_nothing(switch_mod):
    switch_mod.switch(True)
    mine = switch_mod.heartbeat({"phase": "idle"})["toggled_epoch"]
    hb = switch_mod.heartbeat({"phase": "idle",
                               "obeyed": {"enabled": False, "toggled_epoch": mine - 60}})
    assert hb["enabled"] is True and hb["toggled_epoch"] == mine


def test_a_press_here_is_newer_than_one_taken_from_a_machine_whose_clock_is_ahead(switch_mod):
    """Off pressed on the laptop must not read as older than an On taken from SDI-App01 a
    few seconds fast, or the watcher would obey the On and pass it straight back."""
    import time as _t
    ahead = _t.time() + 300
    switch_mod.heartbeat({"obeyed": {"enabled": True, "toggled_epoch": ahead}})
    switch_mod.switch(False)
    hb = switch_mod.heartbeat({"phase": "idle"})
    assert hb["enabled"] is False and hb["toggled_epoch"] > ahead


def test_the_watcher_passes_the_press_in_force_to_a_service_that_is_behind():
    laptop = _SwitchPortal("http://localhost:8072", {"enabled": False, "toggled_epoch": 100.0})
    phone = _SwitchPortal("http://10.0.0.5:8071",
                          {"enabled": True, "toggled_epoch": 200.0, "switched_by": "the phone"})
    sw = sr.Switch([laptop, phone], say=lambda s: None)
    assert sw.beat({"phase": "idle"}) is True
    told = [r for r in laptop.reports if "obeyed" in r]
    assert len(told) == 1 and told[0]["obeyed"]["enabled"] is True
    assert told[0]["obeyed"]["toggled_epoch"] == 200.0
    assert told[0]["obeyed"]["switched_by"] == "the phone"
    assert not [r for r in phone.reports if "obeyed" in r], "the service it came from is not told"


def test_an_older_service_without_a_press_time_is_not_asked_every_beat():
    old = _SwitchPortal("old", {"enabled": False})
    new = _SwitchPortal("new", {"enabled": True, "toggled_epoch": 50.0})
    sw = sr.Switch([old, new], say=lambda s: None)
    sw.beat({})
    sw.beat({})
    assert len(old.reports) == 2 and not [r for r in old.reports if "obeyed" in r]


def test_every_screen_shows_the_switch_in_force_after_one_beat(switch_mod):
    """End to end on the service's own code: the laptop switched off, the phone's On later."""
    import time as _t
    switch_mod.switch(False)

    class _Laptop:
        server = "http://localhost:8072"

        def self_running(self, rep):
            return switch_mod.heartbeat(rep)
    phone = _SwitchPortal("http://10.0.0.5:8071",
                          {"enabled": True, "toggled_epoch": _t.time() + 1,
                           "switched_by": "the phone"})
    assert sr.Switch([_Laptop(), phone], say=lambda s: None).beat({"phase": "idle"}) is True
    v = switch_mod.view()
    assert v["enabled"] is True and v["switched_by"] == "the phone"


def test_reinstalling_the_watcher_restarts_it_with_its_new_settings():
    """D-648: re-running install-self-running-task.ps1 with SDI-App01 added changed the task
    and left the old watcher running (MultipleInstances IgnoreNew), still reporting to the
    laptop only. The install now stops the running watcher before registering, clears a lock
    whose process is gone, and prints what the new watcher reports to."""
    ps = (ROOT / "tools" / "start" / "install-self-running-task.ps1").read_text(encoding="utf-8")
    stop = ps.index("Stop-ScheduledTask -TaskName $TaskName")
    assert stop < ps.index("Register-ScheduledTask -TaskName $TaskName")
    assert '$_.CommandLine -like "*self_running.py*"' in ps
    assert '"live_enquiry.lock"' in ps and "Get-Process -Id ([int]$holder)" in ps
    assert "reporting to|did not answer" in ps
    assert all(ord(c) < 128 for c in ps)
