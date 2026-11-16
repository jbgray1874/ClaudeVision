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
    assert switch_mod.heartbeat({"phase": "idle"}) == {"enabled": False, "run_now": False}


def test_a_press_is_on_and_asks_for_one_immediate_read(switch_mod):
    v = switch_mod.switch(True, by="James Gray")
    assert v["enabled"] and v["run_now_pending"] and v["switched_by"] == "James Gray"
    assert switch_mod.heartbeat({"phase": "idle"}) == {"enabled": True, "run_now": True}
    assert switch_mod.heartbeat({"phase": "idle"}) == {"enabled": True, "run_now": False}


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
    rows = [_row(5, "0351292"), _row(6, "0360001")]
    monkeypatch.setattr(ler, "read_sheet", lambda path, sheet="": rows)
    portal = FakePortal()
    out = sr.cycle(_settings(share), portal, FakeSwitch([]), say=lambda s: None,
                   wait={"poll_seconds": 0, "sleep": lambda s: None})
    assert sorted(portal.started) == ["0351292", "0360001"]
    assert out["counts"].get("done") == 2
    ledger = ler.load_ledger(share["ledger"])
    assert [v["status"] for v in ledger["collected"].values()] == ["copied"]


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
    assert beat == {"enabled": True, "run_now": True}
    seen = client.get("/api/estimate/self-running").json()
    assert seen["watcher"]["connected"] and seen["watcher"]["current"]["drawing"] == "0351292"
    off = client.post("/api/estimate/self-running/stop", json={}).json()
    assert off["enabled"] is False
    assert client.post("/api/estimate/self-running/heartbeat", json={}).json()["enabled"] is False
