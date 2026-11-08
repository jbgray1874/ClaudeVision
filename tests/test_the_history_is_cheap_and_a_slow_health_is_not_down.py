"""The control panel's history never stalls the service, and a slow health check is not a dead
service (D-745).

7 Nov 2026: after D-744 both laptop services were reported "down - nothing answered" while the
8071 log showed it serving the control panel. Two causes were in reach of the code. The History
view read what each run's models were read by with case-blind regexes over its whole console,
twice per run: 300 runs of 4,000 lines held the interpreter for 25 s, and every other request
waited behind it. And the check scripts gave /api/health 4 s, while health asks the database,
which alone may wait 5 s to connect, and the shares.

A restart keeps only the end of a run's console, where the model read is not, so what read a
run's models is now worked out from its whole console when it finishes and saved with it.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
START = ROOT / "tools" / "start"
NOW = time.mktime((2026, 11, 7, 20, 0, 0, 0, 0, -1))


def _wall():
    sys.path.insert(0, str(BACKEND))
    try:
        import estimate_wall
        return estimate_wall
    finally:
        sys.path.remove(str(BACKEND))


class Counted(list):
    """A console that counts how often it is read through."""
    reads = 0

    def __iter__(self):
        type(self).reads += 1
        return super().__iter__()


def _run(i, log, status="done", job_type=""):
    fin = NOW - 3600 - i * 600
    return {"run_id": f"r{i}", "drawing_number": f"D-{i}", "client": "Acme", "units": 1,
            "status": status, "job_type": job_type, "queued_at": fin - 700,
            "started_at": fin - 600, "finished_at": fin, "runner": "DESKTOP-GFAAP80-90faa0001",
            "log": log, "review": {"total": 3}}


# ── what read the models, said as before, found cheaply ─────────────────────────────────

@pytest.mark.parametrize("lines, kind", [
    (["[solidworks] model extract APPLIED for 4 parts"], "sw"),
    (["Native extract applied", "SolidWorks could not open 02.SLDPRT"], "sw_partial"),
    (["model extract applied", "SWITCHING TO THE DOCUMENT MANAGER"], "dm_fallback"),
    (["Document Manager BACKUP reader filled 2 files"], "dm_fallback"),
    (["the extract was NOT APPLIED", "model extract applied"], "drawings"),
    (["the estimate goes on without its models"], "drawings"),
])
def test_the_evidence_is_said_as_before(lines, kind):
    W = _wall()
    assert W.evidence(_run(1, ["[scan] staged"] + lines))["kind"] == kind
    assert W.evidence_from_log(lines)["kind"] == kind


def test_a_running_estimate_that_has_not_read_its_models_says_so():
    W = _wall()
    assert W.evidence(_run(1, ["[pricing] parts priced"], status="running"))["kind"] == "pending"
    assert W.evidence_from_log(["[pricing] parts priced"])["kind"] == "pending"


def test_a_run_restored_with_only_the_end_of_its_log_is_not_known_never_not_reached():
    W = _wall()
    log = ["… 3600 earlier line(s) are in the run's .log file", "[deliverables] filed to x"]
    ev = W.evidence(_run(2, log))
    assert ev["kind"] == "unknown" and ev["label"].startswith("Not known")
    assert W.evidence(_run(3, log, status="running"))["kind"] == "pending"


def test_a_finished_run_is_read_by_what_was_kept_when_it_finished():
    W = _wall()
    run = _run(4, ["… 3600 earlier line(s) are in the run's .log file"])
    run["evidence_kept"] = {"kind": "sw", "label": "SolidWorks measured model", "why": "w",
                            "caution": False, "lines": 4001}
    assert W.evidence(run) == {"kind": "sw", "label": "SolidWorks measured model", "why": "w",
                               "caution": False}


def test_the_stage_is_found_as_before():
    W = _wall()
    assert W.stage_of(["engine started", "[pricing] parts priced"]) == (4, "Pricing")
    assert W.stage_of(["[workbook] built", "[scan] again"]) == (5, "Workbook")
    assert W.stage_of([]) == (-1, "")


# ── the history reads each console once, and quickly ────────────────────────────────────

def test_the_history_reads_each_console_once_and_a_kept_one_not_at_all():
    W = _wall()
    Counted.reads = 0
    runs = [_run(i, Counted(["[scan] staged", "model extract APPLIED"] * 50)) for i in range(20)]
    first = W.history_view(runs, now=NOW)
    assert Counted.reads == 20                                 # once each, not twice
    assert first["evidence"][0] == {"kind": "sw", "label": "SolidWorks measured model",
                                    "count": 20, "caution": False}
    for r in runs:
        r["evidence_kept"] = {"kind": "sw", "label": "SolidWorks measured model", "why": "",
                              "caution": False, "lines": 100}
    again = W.history_view(runs, now=NOW)
    assert Counted.reads == 20                                 # what was kept is used instead
    assert again["evidence"] == first["evidence"]


def test_a_month_of_long_consoles_is_read_in_seconds_not_half_a_minute():
    W = _wall()
    line = "[pricing] part 12002-02-GA-%04d priced at 12.34 GBP with route laser>bend>weld>powder"
    runs = []
    for i in range(300):
        log = [line % j for j in range(4000)]
        if i % 3 == 0:
            log.insert(2000, "[solidworks] model extract APPLIED for 4 parts")
        runs.append(_run(i, log))
    t = time.perf_counter()
    out = W.history_view(runs, now=NOW, days=30)
    took = time.perf_counter() - t
    assert out["totals"]["estimates"] == 300
    assert took < 6.0, f"{took:.1f}s (25 s before D-745)"


# ── the service keeps the evidence through a restart, and reads the history once ────────

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


def _finished(er, run_id, log):
    t = time.time()
    run = er.Run(run_id=run_id, drawing_number="12002-02-GA", client="Acme", units=1,
                 job_folder="", output_path="", status="done", runner="laptop",
                 queued_at=t - 900, started_at=t - 840, finished_at=t - 60)
    run.log = list(log)
    return run


def test_a_finished_run_keeps_what_read_its_models_through_a_restart(client):
    tc, er = client
    import estimate_history
    log = ["[scan] staged", "[solidworks] model extract APPLIED for 4 parts"] + \
          [f"[pricing] line {i}" for i in range(4000)]
    run = _finished(er, "a1b2c3d4e5f6", log)
    er._keep(run)
    assert run.evidence_kept["kind"] == "sw" and run.evidence_kept["lines"] == len(log)
    back = estimate_history.load(er.Run)["a1b2c3d4e5f6"]
    assert len(back.log) < 500 and "earlier line(s)" in back.log[0]      # only the end kept
    assert back.evidence_kept["kind"] == "sw"
    er._keep(back)                                     # saved again after the restart
    assert back.evidence_kept["kind"] == "sw"          # never re-read from the trimmed end
    er._RUNS.clear()
    er._RUNS[back.run_id] = back
    rows = tc.get("/api/estimate/wall/history").json()["service"]["runs"]
    assert rows[0]["evidence"] == "SolidWorks measured model"


def test_open_panels_share_one_reading_of_the_history(client, monkeypatch):
    tc, er = client
    import estimate_wall
    er._RUNS["r1"] = _finished(er, "r1", ["[scan] staged"])
    monkeypatch.setattr(er, "filed_for_wall", lambda force=False: {"state": "ready"})
    calls = []
    real = estimate_wall.history_view
    monkeypatch.setattr(estimate_wall, "history_view",
                        lambda runs, **kw: calls.append(kw) or real(runs, **kw))
    for _ in range(3):
        assert tc.get("/api/estimate/wall/history").status_code == 200
    assert len(calls) == 1
    tc.get("/api/estimate/wall/history?refresh=1")
    tc.get("/api/estimate/wall/history?days=7")
    assert len(calls) == 3                             # asked again, or for another period


# ── a slow health check is not a dead service ───────────────────────────────────────────

def test_the_service_check_waits_for_health_and_tells_slow_from_down():
    ps = (START / "check-services.ps1").read_text(encoding="utf-8")
    assert ps.isascii()
    body = ps[ps.index("foreach ($p in $Ports)"):]
    assert '/api/health" -UseBasicParsing -TimeoutSec 20' in body
    assert "-TimeoutSec 4" not in body.split("api/estimate/speech")[0]
    assert '"http://localhost:$p/api/estimate/speech" -UseBasicParsing -TimeoutSec 5' in body
    assert "the database or a share is not answering" in body
    assert 'Write-Host ("        health: {0}" -f $note)' in body
    note = ps[ps.index("function Get-HealthNote"):ps.index("$up = 0")]
    assert "database $($h.database.status)" in note and "share(s) not reachable" in note
    assert "if ($h.file_roots) {" in note              # no roots listed is not a root down
    assert "slow, {0:N0} s to reply" in note


def test_the_restart_waits_for_health_and_says_a_running_service_is_running():
    ps = (START / "restart-service.ps1").read_text(encoding="utf-8")
    assert ps.isascii()
    assert '/api/health" -TimeoutSec 4' not in ps and '/api/health" -TimeoutSec 6' not in ps
    assert '"http://localhost:$Port/api/health" -TimeoutSec 15' in ps
    assert '"http://localhost:$Port/api/health" -TimeoutSec 20' in ps
    branch = ps[ps.index("# UP, BUT ITS HEALTH CHECK GIVES NO REPLY (D-745)"):]
    assert branch.index("/api/estimate/speech") < branch.index("NOT answering on $Port")
    assert "RUNNING on {0}, serving commit {1}{2}, but /api/health gave no reply in 20 s." in branch
    assert "Do not start a run until /api/health answers again." in branch
