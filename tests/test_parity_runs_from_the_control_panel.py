"""Parity run from the control panel, and every comparison's progress on it (D-742).

JG, 7 Nov 2026: "I want to run one off jobs, compare a whole set of jobs v manual etc. and see
the output in the main screen."

The wall asks the service's own parity routes: one job (find, then compare), a set of jobs by
number, or a period, each previewed before anything is compared. Every comparison the service
started in the last twelve hours is read back from its status file onto the wall, wherever it
was started, with each drawing's outcome as it lands.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
WALL = BACKEND / "sdi-estimating-wall.html"


@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="fastapi not installed")
    share = tmp_path / "share"
    (share / "stage").mkdir(parents=True)
    (share / "out").mkdir()
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SDI_FILE_ROOTS", str(share))
    monkeypatch.setenv("SDI_STAGING_ROOT", str(share / "stage"))
    monkeypatch.setenv("SDI_ESTIMATE_OUTPUT_ROOT", str(share / "out"))
    clash = ("config", "estimate_routes", "log_filters", "hr_routes", "docmgr",
             "self_running_switch", "estimate_email", "staging", "estimate_history",
             "estimate_wall")
    saved = {n: sys.modules.pop(n) for n in clash if n in sys.modules}
    sys.path.insert(0, str(BACKEND))
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import estimate_routes as er
        er._RUNS.clear()
        er._RUNNERS.clear()
        er._PARITY_TASKS.clear()
        er._PARITY_RUNNING.clear()
        app = FastAPI()
        app.include_router(er.router)
        tc = TestClient(app)
        key = getattr(er.config, "API_KEY", "") or ""
        if key:
            tc.headers.update({"X-SDI-Key": key})
        yield tc, er
    except Exception as exc:                                            # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    finally:
        sys.path.remove(str(BACKEND))
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_a_set_preview_names_its_jobs_and_what_is_left_out(client, monkeypatch):
    tc, er = client
    seen = []

    def answer(args, timeout=300):
        seen.append(args)
        return {"kind": "jobs", "rows": [], "stats": {}, "not_job_numbers": []}
    monkeypatch.setattr(er, "_parity_job", answer)
    r = tc.post("/api/estimate/parity/jobs", json={
        "text": "12002, 11908-22-GA\n12002 hello; --rm", "client": "Acme", "preview": True})
    assert r.status_code == 200, r.text
    assert seen == [["jobs", "12002", "11908-22-GA", "--client", "Acme", "--preview"]]
    assert r.json()["not_job_numbers"] == ["hello", "--rm"]     # never handed to the command


def test_a_set_with_no_job_number_or_too_many_is_refused(client):
    tc, _ = client
    r = tc.post("/api/estimate/parity/jobs", json={"text": "hello world", "preview": True})
    assert r.status_code == 400 and "not job numbers: hello, world" in r.json()["detail"]
    many = " ".join(str(10000 + i) for i in range(201))
    r = tc.post("/api/estimate/parity/jobs", json={"text": many, "preview": True})
    assert r.status_code == 400 and "more than one set takes (200)" in r.json()["detail"]


def test_a_set_runs_in_the_background_with_a_name_the_wall_can_show(client, monkeypatch):
    tc, er = client
    started = []
    monkeypatch.setattr(er, "_engine_ready", lambda: None)
    monkeypatch.setattr(er.subprocess, "Popen", lambda args, **kw: started.append(args))
    r = tc.post("/api/estimate/parity/jobs", json={"jobs": ["12002", "11908-22-GA"],
                                                    "client": "Acme"})
    assert r.status_code == 200 and r.json()["started"] is True
    tid = r.json()["task_id"]
    assert started[0][2:6] == ["jobs", "12002", "11908-22-GA", "--client"]
    assert er._PARITY_TASKS[tid]["kind"] == "jobs"
    assert er._PARITY_TASKS[tid]["label"] == "2 jobs: 12002 … 11908-22-GA · Acme"
    again = tc.post("/api/estimate/parity/jobs", json={"jobs": ["11908-22-GA", "12002"],
                                                        "client": "acme"}).json()
    assert again["already_running"] is True and again["task_id"] == tid   # never twice


def _status(er, tid, body, age_s=0.0):
    path = er._parity_status_file(tid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")
    if age_s:
        t = time.time() - age_s
        os.utime(path, (t, t))
    return path


def test_the_wall_shows_every_comparison_of_the_last_twelve_hours(client):
    tc, er = client
    er._PARITY_TASKS["aaaa0001"] = {"label": "3 jobs: 12002 … 12677-01-GA", "kind": "jobs",
                                    "started_at": time.time() - 60}
    _status(er, "aaaa0001", {"kind": "jobs", "done": 2, "of": 3, "rows": [
        {"drawing": "12002-02-GA", "client": "Acme", "outcome": "match", "pct": 1.2,
         "folder": "/p/Acme/12002-02-GA/x", "report": "r.html"},
        {"drawing": "55555-01", "client": "Acme", "outcome": "no manual"}]})
    _status(er, "bbbb0002", {"state": "done", "finished": True, "result": {
        "drawing": "11908-22-GA", "client": "Beta", "outcome": "warning", "folder": "/p/x",
        "report_html": "r.html", "walkthrough_wav": "w.wav",
        "headline": {"ai_unit_cost_gbp": 90.0, "manual_unit_cost_gbp": 100.0},
        "quantity": {"comparable": True}}}, age_s=120)
    _status(er, "cccc0003", {"state": "choose", "finished": True, "choose": True,
                             "error": "2 sheets are equally likely", "candidates": [{}, {}]},
            age_s=200)
    _status(er, "dddd0004", {"kind": "period", "start": "2026-10-01", "end": "2026-10-31",
                             "done": 1, "of": 9, "rows": []}, age_s=3600)
    _status(er, "eeee0005", {"state": "done", "finished": True}, age_s=13 * 3600)
    tasks = tc.get("/api/estimate/wall").json()["parity_tasks"]
    assert [t["task_id"] for t in tasks] == ["aaaa0001", "bbbb0002", "cccc0003", "dddd0004"]
    running, job, choose, stalled = tasks
    assert running["state"] == "running" and running["label"].startswith("3 jobs")
    assert running["done"] == 2 and running["of"] == 3
    assert running["rows"][0]["report_url"].startswith("/api/file?path=")
    assert running["rows"][1]["report_url"] is None
    assert job["state"] == "done" and job["result"]["signed_pct"] == -10.0
    assert job["result"]["listen_url"].endswith("w.wav")
    assert choose["state"] == "choose" and choose["candidates"] == 2
    assert stalled["state"] == "stalled"                      # nothing written for an hour
    assert stalled["label"] == "2026-10-01 to 2026-10-31"     # named from its own file


def test_a_comparison_that_filed_something_reads_the_parity_view_again(client):
    tc, er = client
    now = time.time()
    er._PARITY_WALL.update(at=now - 300, tried=now - 300)
    done = [{"updated_at": now - 5, "finished": True, "done": 1, "preview": False}]
    assert er._parity_moved(done) is True
    er._PARITY_WALL.update(at=now - 30, tried=now - 30)
    assert er._parity_moved(done) is False                    # read under a minute ago
    er._PARITY_WALL.update(at=now - 300, tried=now - 300)
    assert er._parity_moved([{"updated_at": now - 400, "finished": True, "done": 1}]) is False
    assert er._parity_moved([{"updated_at": now - 5, "finished": False, "done": 0}]) is False


def test_the_wall_runs_parity_through_the_services_own_routes():
    page = WALL.read_text(encoding="utf-8")
    for route in ("/api/estimate/parity/find?job=", '"/api/estimate/parity/job"',
                  '"/api/estimate/parity/jobs"', '"/api/estimate/parity/period"'):
        assert route in page
    for tab in ('data-tab="one"', 'data-tab="set"', 'data-tab="period"'):
        assert tab in page
    assert ".tabpane[hidden]" in page                         # one tab at a time
    assert "function renderParityTasks(" in page and "renderParityTasks(s.parity_tasks" in page
    assert "COMPARE ALL" in page and 'id="setRun" disabled' in page and 'id="perRun" disabled' in page
    assert "is never guessed" in page and "data-choose" in page
    # A path is sent only when it differs from what the service would choose itself.
    assert "if(!d.clear || picked.value !== d.path) body.manual_path" in page


def test_typing_in_a_box_never_toggles_full_screen_or_jumps_the_page():
    page = WALL.read_text(encoding="utf-8")
    assert 'const typing = e => e.target && /^(input|textarea|select)$/i.test(e.target.tagName);' in page
    assert 'if(!typing(e) && (e.key === "f" || e.key === "F")) fullscreen();' in page
    assert "if(typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;" in page
