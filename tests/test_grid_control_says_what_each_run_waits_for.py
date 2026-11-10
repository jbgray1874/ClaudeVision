"""Grid Control says what each run is doing or waiting for, and how complete a finished one is
(JG, 10 Nov 2026). Acceptance, as asked: an xAI 429 and its recovery, a slow but healthy run, a
finished run with a missing cost, and the extract-only server runner that must never take an
estimate. Also: xAI busy is waited for, not taken as an answer."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
sys.path.insert(0, str(ROOT / "tools" / "runner"))

import estimate_wall as ew                                         # noqa: E402
import xai_models as xm                                            # noqa: E402


class Busy(Exception):
    def __init__(self, msg, status=429):
        super().__init__(msg)
        self.status_code = status


CAPACITY = "Error code: 429 - resource-exhausted: The model is currently at capacity due to high demand"


# ── xAI busy is a wait ───────────────────────────────────────────────────────────────────

def test_a_capacity_429_is_waited_for_and_the_recovery_is_said(monkeypatch):
    monkeypatch.delenv("SDI_XAI_RETRY_SECONDS", raising=False)
    calls, slept, said = [], [], []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise Busy(CAPACITY)
        return "answer"
    assert xm.call_with_retry(fn, "grok-4.7", sleep=slept.append, say=said.append) == "answer"
    assert slept == [20.0, 60.0]
    assert "capacity (HTTP 429) on the drawing read: try 1 of 4 failed; next try in 20 s" in said[0]
    assert "recovered on the drawing read: try 3 of 4 answered after 80 s" in said[-1]


def test_xai_that_stays_busy_is_given_up_and_said_not_taken_as_empty(monkeypatch):
    monkeypatch.setenv("SDI_XAI_RETRY_SECONDS", "1,2")
    said = []
    with pytest.raises(Busy):
        xm.call_with_retry(lambda: (_ for _ in ()).throw(Busy(CAPACITY)), "m",
                           sleep=lambda s: None, say=said.append)
    assert "gave up on the drawing read after 3 tries and 3 s" in said[-1]
    assert "NOT done" in said[-1]


def test_an_error_waiting_cannot_cure_is_not_retried(monkeypatch):
    slept = []
    with pytest.raises(Busy):
        xm.call_with_retry(lambda: (_ for _ in ()).throw(Busy("Incorrect API key", 401)), "m",
                           sleep=slept.append, say=lambda m: None)
    assert slept == []


@pytest.mark.parametrize("exc,kind", [(Busy(CAPACITY), "capacity"),
                                      (Busy("Too Many Requests"), "rate limit"),
                                      (TimeoutError("Request timed out"), "timeout"),
                                      (Busy("Bad gateway", 502), "server error"),
                                      (Busy("bad request", 400), "")])
def test_what_counts_as_busy(exc, kind):
    assert xm.busy_kind(exc) == kind


# ── what a running run is doing ──────────────────────────────────────────────────────────

def _run(log, last_at=1000.0, **kw):
    return {"run_id": "r1", "status": "running", "started_at": 900.0, "last_line_at": last_at,
            "log": log, **kw}


def test_an_xai_wait_shows_its_kind_try_and_countdown():
    d = ew.doing(_run(["[llm-full-extract] reading", "   [xai-wait] capacity (HTTP 429) on the "
                       "drawing read: try 2 of 4 failed; next try in 60 s, 20 s waited so far"]),
                 now=1030.0)
    assert d["what"] == "waiting for xAI" and d["waiting"]
    assert d["next_try_at"] == 1060.0
    assert "capacity (HTTP 429) on the drawing read: try 2 of 4 failed" in d["detail"]


def test_after_recovery_the_run_is_back_to_its_stage():
    d = ew.doing(_run(["[xai-wait] capacity (HTTP 429) on the drawing read: try 1 of 4 failed; "
                       "next try in 20 s, 0 s waited so far",
                       "[xai-wait] recovered on the drawing read: try 2 of 4 answered after 20 s",
                       "[pricing] parts priced"]), now=1001.0)
    assert d["what"] == "pricing" and not d["waiting"]


def test_a_slow_but_healthy_run_says_what_it_is_doing_and_that_it_is_talking():
    d = ew.doing(_run(["[solidworks] reading 26 files", "[workbook] writing"], last_at=1000.0),
                 now=1005.0)
    assert d["what"] == "writing the workbook (Excel)" and d["fresh"]


def test_a_live_process_that_says_nothing_is_not_read_as_work():
    d = ew.doing(_run(["[pricing] parts priced"], last_at=1000.0), now=1000.0 + 3600)
    assert not d["fresh"] and d["silent_s"] == 3600.0


def test_a_solidworks_wait_is_named():
    d = ew.doing(_run(["Waiting for the desktop's SolidWorks: 12677-01-GA (run 4b1c2d) has had "
                       "it for 6 min."], sw_wait_since=990.0), now=1000.0)
    assert d["what"] == "waiting for SolidWorks" and "has had it for 6 min" in d["detail"]


# ── finished is not complete ─────────────────────────────────────────────────────────────

def _done(review):
    return {"run_id": "r2", "status": "done", "started_at": 1, "finished_at": 2,
            **({"review": review} if review is not None else {})}


def test_a_finished_estimate_with_a_missing_cost_is_red_not_completed():
    q = ew.quality(_done({"total": 3, "missing": 2, "provisional": 1}))
    assert q == {"state": "missing costs", "rag": "red",
                 "label": "Finished: 2 missing costs, 1 provisional"}


def test_provisional_is_amber_and_nothing_open_is_complete():
    assert ew.quality(_done({"total": 2, "missing": 0, "provisional": 2}))["state"] == "provisional"
    assert ew.quality(_done({"total": 0, "missing": 0}))["state"] == "complete"
    assert ew.quality(_done(None))["state"] == "not reviewed"


def test_the_wall_sends_the_doing_and_the_quality():
    snap = ew.snapshot([_run(["[pricing] x"]), _done({"total": 1, "missing": 1})], [], now=1001.0)
    assert snap["live"][0]["doing"]["what"] == "pricing"
    assert snap["recent"][0]["quality"]["state"] == "missing costs"
    html = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-wall.html").read_text(encoding="utf-8")
    assert "function doingLine(d)" in html and "next try in" in html and "Missing costs" in html


# ── the extract-only runner (the server, no Excel) ───────────────────────────────────────

def test_an_extract_only_runner_offers_extracts_only(monkeypatch):
    import sdi_estimate_runner as rn
    monkeypatch.setenv("SDI_RUNNER_EXTRACT_ONLY", "1")
    monkeypatch.setenv("SDI_SW_DOCMGR_KEY", "k")
    monkeypatch.setenv("SDI_SW_RUN_ANALYSER", "0")
    caps = rn.runner_capabilities()
    assert "extract_only" in caps and "xai_extract" in caps and "dm_extract" in caps
    assert "sw_extract" not in caps and "bom_routes" not in caps
    monkeypatch.setenv("SDI_RUNNER_EXTRACT_ONLY", "0")
    assert "extract_only" not in rn.runner_capabilities()


@pytest.fixture
def service(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="fastapi not installed")
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    clash = ("config", "estimate_routes", "log_filters", "hr_routes", "docmgr",
             "self_running_switch", "estimate_email", "staging", "estimate_history")
    saved = {n: sys.modules.pop(n) for n in clash if n in sys.modules}
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
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_the_service_never_hands_an_estimate_to_an_extract_only_runner(service, tmp_path):
    tc, er = service
    est = er.Run(run_id="est1", client="M&S", drawing_number="12345-01-GA", units=1,
                 job_folder=str(tmp_path), output_path="x")
    er._RUNS["est1"] = est
    server = {"runner_id": "SDI-APP01-0123abcd", "hostname": "SDI-APP01",
              "capabilities": ["extract_only", "xai_extract", "dm_extract"]}
    got = tc.post("/api/estimate/runner/claim", json=server).json()
    assert got["run"] is None
    assert "takes pack extracts only (no Excel here)" in got["reason"]
    ext = er.Run(run_id="ext1", client="M&S", drawing_number="12345-01-GA", units=1,
                 job_folder=str(tmp_path), output_path="y")
    ext.job_type = "xai_extract"
    er._RUNS["ext1"] = ext
    got = tc.post("/api/estimate/runner/claim", json=server).json()
    assert got["run"]["run_id"] == "ext1", "the extract, never the estimate queued before it"
    er._RUNS["ext1"].status = "done"
    laptop = {"runner_id": "DESKTOP-GFAAP80-89abcdef", "hostname": "DESKTOP-GFAAP80",
              "capabilities": ["sw_extract", "xai_extract", "bom_routes", "desktop_token"]}
    got = tc.post("/api/estimate/runner/claim", json=laptop).json()
    assert got["run"]["run_id"] == "est1"
