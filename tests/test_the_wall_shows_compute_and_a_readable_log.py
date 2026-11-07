"""Compute on the wall, and a run log that can be read (D-743).

JG, 7 Nov 2026: "the writing is all cramped up.. can't read in the box. needs to be visible and
scrollable" and "a graphical representation of the compute resources available on the laptop
... what compute resource each job is taking and it updates dynamically and the remaining
compute is also available. we can then add the server downstairs and the new machine."

The runner measures its machine and its own engine's processes and sends the reading with the
calls it already makes; the service keeps only numbers; estimate_wall works out each machine's
shares and each run's own use; the page draws them, and its log box wraps and scrolls.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
WALL = BACKEND / "sdi-estimating-wall.html"
RUNNER = ROOT / "tools" / "runner" / "sdi_estimate_runner.py"
sys.path.insert(0, str(ROOT / "tools" / "runner"))

import sdi_estimate_runner as runner  # noqa: E402

NOW = 1_800_000_000.0


def _wall():
    sys.path.insert(0, str(BACKEND))
    try:
        import estimate_wall
        return estimate_wall
    finally:
        sys.path.remove(str(BACKEND))


# ── the runner measures ──────────────────────────────────────────────────────────────────

def test_the_runner_measures_its_machine_and_its_own_job():
    pytest.importorskip("psutil")
    busy = subprocess.Popen([sys.executable, "-c",
                             "import time\nt=time.time()\nwhile time.time()-t<3: pass"])
    try:
        runner._JOB_PIDS["run-1"] = busy.pid
        runner.sample_compute()                    # primes the counters
        time.sleep(1.0)
        got = runner.sample_compute()
    finally:
        runner._JOB_PIDS.pop("run-1", None)
        busy.wait()
    assert got["by"] == "psutil" and got["host"] and got["at"] > 0
    for k in ("cpu_pct", "threads", "mem_total_gb", "mem_used_gb", "mem_free_gb"):
        assert isinstance(got[k], (int, float))
    assert got["mem_used_gb"] + got["mem_free_gb"] == pytest.approx(got["mem_total_gb"], abs=0.05)
    job = got["jobs"]["run-1"]
    assert job["procs"] >= 1 and job["cpu_pct"] > 1.0          # a busy loop is measured
    assert isinstance(got["apps"], dict)


def test_without_psutil_the_runner_still_reads_what_it_can(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)            # import psutil now fails
    got = runner.sample_compute()
    assert got["by"] in ("windows", "none") and got["host"]
    assert got.get("jobs", {}) == {} and "error" not in got


def test_a_failed_reading_is_reported_never_raised(monkeypatch):
    monkeypatch.setattr(runner, "_sample_with_psutil",
                        lambda psutil: (_ for _ in ()).throw(RuntimeError("boom")))
    pytest.importorskip("psutil")
    got = runner.sample_compute()
    assert got["by"] == "none" and "boom" in got["error"]


def test_the_reading_rides_on_the_calls_the_runner_already_makes(monkeypatch):
    sent = []

    class Reply:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return {"run": None}

    class Requests:
        def post(self, url, json=None, headers=None, timeout=None):
            sent.append((url, json))
            return Reply()
    monkeypatch.setitem(runner._COMPUTE, "sample", {"by": "psutil", "cpu_pct": 12.0})
    runner._ask_for_work(Requests(), "http://svc", {}, "laptop", "1", "abc", None)
    assert sent[0][0].endswith("/runner/claim") and sent[0][1]["compute"]["cpu_pct"] == 12.0
    source = RUNNER.read_text(encoding="utf-8")
    assert '"process": process, "build": build, "compute": compute_now()}' in source  # heartbeat
    assert '"compute": compute_now()},' in source                                   # console
    assert "_JOB_PIDS[str(run_id)] = proc.pid" in source and 'getattr(proc, "pid", None)' in source
    assert "        _JOB_PIDS.pop(str(run_id), None)" in source                      # finally
    assert "start_compute_sampler()" in source.split("def main(")[1]


# ── the service keeps numbers ────────────────────────────────────────────────────────────

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


SAMPLE = {"host": "DESKTOP-GFAAP80", "by": "psutil", "at": 1.0, "cpu_pct": 46.04,
          "threads": 16, "mem_total_gb": 31.7, "mem_used_gb": 13.4, "mem_free_gb": 18.3,
          "disk_free_gb": 210.0, "evil": "<script>", "cpu_pct_text": "x",
          "apps": {"SolidWorks": {"cpu_pct": 14.0, "mem_gb": 2.6, "count": 1, "cmd": "x"}},
          "jobs": {"r1": {"cpu_pct": 7.5, "mem_gb": 0.7, "procs": 2}}}


def test_the_service_keeps_only_the_numbers_it_knows(client):
    tc, er = client
    r = tc.post("/api/estimate/runner/claim", json={"runner_id": "laptop", "hostname": "L",
                                                    "process": "1", "build": "x",
                                                    "compute": SAMPLE})
    assert r.status_code == 200, r.text
    kept = er._RUNNERS["laptop"].compute
    assert kept["cpu_pct"] == 46.04 and kept["host"] == "DESKTOP-GFAAP80"
    assert "evil" not in kept and "cpu_pct_text" not in kept
    assert kept["apps"]["SolidWorks"] == {"cpu_pct": 14.0, "mem_gb": 2.6, "count": 1}
    assert kept["jobs"]["r1"]["procs"] == 2 and kept["received_at"] > 0
    point = er._RUNNERS["laptop"].compute_history[-1]
    assert point[1] == 46.04 and point[2] == pytest.approx(42.3, abs=0.1)
    tc.post("/api/estimate/runner/claim", json={"runner_id": "laptop", "compute": "nonsense"})
    assert er._RUNNERS["laptop"].compute["cpu_pct"] == 46.04       # a bad reading is ignored


def test_the_heartbeat_and_the_console_carry_it_too(client):
    tc, er = client
    tc.post("/api/estimate/runner/heartbeat", json={"runner_id": "other", "hostname": "O",
                                                    "compute": {**SAMPLE, "cpu_pct": 11.0}})
    assert er._RUNNERS["other"].compute["cpu_pct"] == 11.0
    run = er.Run(run_id="r1", drawing_number="12002-02-GA", client="M&S", units=1,
                 job_folder="", output_path="", status="running", runner="laptop")
    er._RUNS["r1"] = run
    r = tc.post("/api/estimate/runner/r1/progress", json={
        "runner_id": "laptop", "lines": ["engine started"], "compute": {**SAMPLE, "cpu_pct": 55.0}})
    assert r.status_code == 200, r.text
    assert er._RUNNERS["laptop"].compute["cpu_pct"] == 55.0
    wall = tc.get("/api/estimate/wall").json()
    laptop = next(m for m in wall["compute"] if m["host"] == "DESKTOP-GFAAP80")
    assert laptop["connected"] and laptop["cpu_pct"] == 55.0


# ── the wall's arithmetic ────────────────────────────────────────────────────────────────

def _live(run_id, runner_id, drawing, holds_sw=False, waiting=False):
    return {"run_id": run_id, "runner": runner_id, "drawing_number": drawing,
            "sw_turn_at": NOW - 60 if holds_sw else 0.0,
            "sw_wait_since": NOW - 30 if waiting else 0.0}


def _runner(runner_id, host, sample, age=3.0):
    return {"runner_id": runner_id, "hostname": host,
            "compute": {**sample, "received_at": NOW - age},
            "compute_history": [[NOW - 10, 40.0, 41.0], [NOW - 5, 46.0, 42.0], [NOW - 2000, 99, 99]]}


def test_a_machine_shows_each_run_solidworks_excel_the_rest_and_what_is_free(monkeypatch):
    W = _wall()
    monkeypatch.setenv("SDI_WALL_FLEET", "DESKTOP-GFAAP80=Laptop,SDI-APP01=Server,NEWBOX=New box")
    base = {"host": "DESKTOP-GFAAP80", "by": "psutil", "cpu_pct": 46.0, "threads": 16,
            "mem_total_gb": 32.0, "mem_used_gb": 13.0, "mem_free_gb": 19.0,
            "apps": {"SolidWorks": {"cpu_pct": 14.0, "mem_gb": 2.6, "count": 1},
                     "Excel": {"cpu_pct": 3.0, "mem_gb": 0.5, "count": 1}}}
    runners = [_runner("lap", "DESKTOP-GFAAP80", {**base, "jobs": {"a": {"cpu_pct": 7.5, "mem_gb": 0.7, "procs": 2}}}),
               _runner("lap-s2", "DESKTOP-GFAAP80", {**base, "jobs": {"b": {"cpu_pct": 4.0, "mem_gb": 0.4, "procs": 1}}}, age=5)]
    live = [_live("a", "lap", "12002-02-GA", holds_sw=True), _live("b", "lap-s2", "11908-22-GA", waiting=True)]
    view = W.compute_view(runners, live, NOW)
    laptop, server, newbox = view["machines"]
    assert laptop["label"] == "Laptop" and laptop["connected"] and laptop["fresh"]
    kinds = [(x["kind"], x["label"], x["value"]) for x in laptop["cpu"]["segments"]]
    assert kinds == [("estimate", "Run 1 · 12002-02-GA", 7.5), ("estimate", "Run 2 · 11908-22-GA", 4.0),
                     ("solidworks", "SolidWorks", 14.0), ("excel", "Excel", 3.0)]
    assert laptop["cpu"]["other"] == 17.5 and laptop["cpu"]["free"] == 54.0
    assert laptop["mem"]["free"] == 19.0 and laptop["mem"]["other"] == pytest.approx(8.8)
    assert len(laptop["history"]) == 2                       # fifteen minutes, no more
    assert server == {"host": "SDI-APP01", "label": "Server", "connected": False, "planned": True}
    assert newbox["label"] == "New box" and not newbox["connected"]
    # SolidWorks is the holder's; Excel is nobody's while two runs share the machine.
    a, b = view["runs"]["a"], view["runs"]["b"]
    assert a["cpu_pct"] == 7.5 and a["solidworks"] == {"cpu_pct": 14.0, "mem_gb": 2.6}
    assert b["solidworks"] is None and a["excel"] is None and b["excel"] is None


def test_excel_is_a_runs_only_when_it_is_the_only_run_on_its_machine():
    W = _wall()
    s = {"host": "L", "by": "psutil", "cpu_pct": 30.0, "mem_total_gb": 16.0, "mem_used_gb": 8.0,
         "apps": {"Excel": {"cpu_pct": 5.0, "mem_gb": 0.5, "count": 1}},
         "jobs": {"a": {"cpu_pct": 10.0, "mem_gb": 1.0, "procs": 1}}}
    view = W.compute_view([_runner("lap", "L", s)], [_live("a", "lap", "D-1")], NOW)
    assert view["runs"]["a"]["excel"] == {"cpu_pct": 5.0, "mem_gb": 0.5}


def test_shares_read_seconds_apart_never_add_up_past_the_machine():
    W = _wall()
    s = {"host": "L", "by": "psutil", "cpu_pct": 10.0, "mem_total_gb": 16.0, "mem_used_gb": 4.0,
         "apps": {"SolidWorks": {"cpu_pct": 12.0, "mem_gb": 2.0, "count": 1}},
         "jobs": {"a": {"cpu_pct": 8.0, "mem_gb": 1.0, "procs": 1}}}
    m = W.compute_view([_runner("lap", "L", s)], [_live("a", "lap", "D-1")], NOW)["machines"][0]
    assert sum(x["value"] for x in m["cpu"]["segments"]) == pytest.approx(10.0, abs=0.02)
    assert m["cpu"]["other"] == 0.0


def test_an_old_reading_and_a_machine_without_psutil_say_so():
    W = _wall()
    s = {"host": "S", "by": "windows", "cpu_pct": 20.0, "mem_total_gb": 64.0, "mem_used_gb": 10.0,
         "jobs": {"a": {"cpu_pct": 5.0}}}
    view = W.compute_view([_runner("srv", "S", s, age=500)], [_live("a", "srv", "D-1")], NOW)
    m = view["machines"][0]
    assert m["fresh"] is False and m["age_s"] == 500
    assert m["cpu"]["segments"] == []                         # a stale job share is not shown
    assert "psutil" in m["note"]
    assert view["runs"]["a"]["per_process"] is False


def test_the_snapshot_carries_compute_and_eighty_lines_of_log():
    W = _wall()
    run = {"run_id": "a", "drawing_number": "D-1", "client": "C", "status": "running",
           "started_at": NOW - 60, "queued_at": NOW - 70, "runner": "lap",
           "log": [f"line {i}" for i in range(200)]}
    s = {"host": "L", "by": "psutil", "cpu_pct": 30.0, "mem_total_gb": 16.0, "mem_used_gb": 8.0,
         "jobs": {"a": {"cpu_pct": 10.0, "mem_gb": 1.0, "procs": 1}}}
    snap = W.snapshot([run], [{**_runner("lap", "L", s), "online": True}], now=NOW)
    assert len(snap["live"][0]["log_tail"]) == 80 and snap["live"][0]["log_tail"][-1] == "line 199"
    assert snap["live"][0]["compute"]["cpu_pct"] == 10.0
    assert snap["compute"][0]["host"] == "L"


# ── the page ─────────────────────────────────────────────────────────────────────────────

def test_the_log_wraps_scrolls_and_stays_where_it_is_read():
    page = WALL.read_text(encoding="utf-8")
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    term = css.split("\n  .term{", 1)[1].split("}", 1)[0]
    assert "overflow-y:auto" in term and "justify-content:flex-end" not in term
    assert ".term div{flex:none;white-space:pre-wrap;overflow-wrap:anywhere" in css
    assert ".term div:first-child{margin-top:auto}" in css      # few lines sit at the bottom
    assert "text-overflow:ellipsis}\n  .term .w" not in css     # no line is cut short
    assert 'keepScroll(".lanes .term[data-run]")' in page and "restore();" in page
    assert "slice(-14)" not in page
    assert 'id="logModal"' in page and "function openLog(" in page and 'data-log="' in page


def test_the_page_draws_compute_for_each_machine_and_each_run():
    page = WALL.read_text(encoding="utf-8")
    assert "renderFleet(s.fleet || [], s.compute || [])" in page
    for fn in ("function machineCompute(", "function laneCompute(", "function cbar(",
               "function sparkline("):
        assert fn in page
    assert "${laneCompute(r.compute)}" in page
    # The validated categorical slots 1 to 3, a neutral grey for the rest.
    assert 'const CMP = {estimate:"#3987e5", solidworks:"#d95926", excel:"#199e70", other:"#5b6b78"};' in page
    assert "Compute shows here once its runner connects." in page
    assert ">Free</span>" in page and "Everything else" in page
