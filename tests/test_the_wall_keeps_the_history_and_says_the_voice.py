"""The control panel's history, the voice it reports, and a page that moves only when asked
(D-744).

JG, 7 Nov 2026: "the control panel should have the entire stats / history of runs and parity
runs, etc. and we can build vizuals around that and details", "the voice has regressed back to
the old one again" and "The control panel scrolls down by itself. let's stop that also."
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
WALL = BACKEND / "sdi-estimating-wall.html"
sys.path.insert(0, str(ROOT / "src"))

import run_history as rh  # noqa: E402

NOW = time.mktime((2026, 11, 7, 20, 0, 0, 0, 0, -1))


def _filed(root, client, drawing, stamp, units, summary):
    folder = root / client / drawing / f"{stamp} ({units} off)"
    folder.mkdir(parents=True, exist_ok=True)
    digits = drawing.split("-")[0]
    (folder / f"{digits}_{stamp[:10].replace('-', '')}_101500.xlsx").write_text("book")
    if summary is not None:
        (folder / f"{digits}.json").write_text(json.dumps(summary))
    return folder


@pytest.fixture
def aisheets(tmp_path):
    root = tmp_path / "AISheets"
    price = lambda v: {"final_estimate": {"totals": {"unit_gbp": v}}}             # noqa: E731
    _filed(root, "Acme", "12002-02-GA", "2026-11-07 13-19-52", 1, price(408.74))
    _filed(root, "Acme", "12002-02-GA", "2026-11-07 18-51-34", 1, price(400.12))
    _filed(root, "Acme", "12002-02-GA", "2026-11-06 10-00-00", 5, price(125.81))   # another qty
    _filed(root, "Acme", "12002-02-GA", "2026-11-05 10-00-00", 1, {})              # no price
    _filed(root, "Beta", "11908-22-GA", "2026-10-03 09-00-00", 1,
           {"headline_cost_price": {"total_unit_cost_gbp": 312.6}})
    _filed(root, "Beta", "11908-22-GA", "2026-09-03 09-00-00", 1, None)            # no summary
    (root / "Beta" / "11908-22-GA" / "notes").mkdir()                              # not a run
    return root


def test_every_filed_estimate_is_read_with_its_own_unit_cost(aisheets):
    found = rh.filed_runs(aisheets)
    assert [r["stamp"] for r in found["runs"]] == ["2026-11-07 18-51-34", "2026-11-07 13-19-52",
                                                   "2026-11-06 10-00-00", "2026-11-05 10-00-00",
                                                   "2026-10-03 09-00-00"]
    assert found["runs"][0]["unit_gbp"] == 400.12 and found["runs"][3]["unit_gbp"] is None
    assert found["runs"][4]["unit_gbp"] == 312.6             # the runner's later key
    assert found["incomplete"] == 1                          # a workbook with no summary


def test_a_summary_is_read_once_and_kept(aisheets, tmp_path, monkeypatch):
    cache = tmp_path / "state" / "run_history_cache.json"
    rh.filed_runs(aisheets, cache)
    assert json.loads(cache.read_text())["schema"] == rh.CACHE_SCHEMA
    read = []
    real = Path.read_text

    def counting(self, *a, **k):
        if self.suffix == ".json" and self.name != cache.name:
            read.append(self.name)
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", counting)
    again = rh.filed_runs(aisheets, cache)
    assert read == [] and again["runs"][0]["unit_gbp"] == 400.12


def test_a_drawing_is_compared_with_itself_only_at_the_same_quantity(aisheets):
    out = rh.summary(rh.filed_runs(aisheets), now=NOW, months=3)
    t = out["totals"]
    assert t["estimates"] == 5 and t["drawings"] == 2 and t["clients"] == 2
    assert t["re_estimated"] == 1 and t["priced"] == 4 and t["not_priced"] == 1
    rep = out["repeats"][0]
    assert rep["drawing"] == "12002-02-GA" and rep["runs"] == 4 and rep["units"] == 1
    assert rep["points"] == [["2026-11-07 13-19-52", 408.74], ["2026-11-07 18-51-34", 400.12]]
    assert rep["change_gbp"] == -8.62 and rep["change_pct"] == -2.1
    assert rep["other_quantities"] == 1 and rep["not_priced"] == 1
    assert [m["month"] for m in out["months"]] == ["2026-09", "2026-10", "2026-11"]
    assert [m["estimates"] for m in out["months"]] == [0, 1, 4]
    assert out["clients"][0] == {"client": "Acme", "estimates": 4, "drawings": 1,
                                 "first": "2026-11-05", "last": "2026-11-07"}
    assert out["recent"][0]["workbook"].endswith(".xlsx")


def test_aisheets_out_of_reach_is_said(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "src" / "run_history.py"), "--json"],
                          capture_output=True, text=True, timeout=60, cwd=str(ROOT),
                          env={**os.environ, "SDI_ESTIMATE_OUTPUT_ROOT": str(tmp_path / "nowhere")})
    assert proc.returncode == 2 and "not reachable" in json.loads(proc.stdout)["error"]


# ── the service's own record ────────────────────────────────────────────────────────────

def _wall():
    sys.path.insert(0, str(BACKEND))
    try:
        import estimate_wall
        return estimate_wall
    finally:
        sys.path.remove(str(BACKEND))


def _run(i, status, minutes, days_ago, runner="DESKTOP-GFAAP80-90faa0001", log=(), review=None,
         job_type="", client="Acme"):
    fin = NOW - days_ago * 86400
    return {"run_id": f"r{i}", "drawing_number": f"D-{i % 3}", "client": client, "units": 1,
            "status": status, "job_type": job_type, "queued_at": fin - minutes * 60 - 60,
            "started_at": fin - minutes * 60, "finished_at": fin, "runner": runner,
            "log": list(log), "review": review or {}, "engine_price_gbp": 400.0 + i,
            "error": "engine exited 1" if status == "error" else ""}


def test_the_history_counts_outcomes_times_machines_and_evidence():
    W = _wall()
    sw = ["[solidworks] model extract APPLIED"]
    runs = [_run(1, "done", 10, 1, log=sw, review={"total": 4, "phrase": "x"}),
            _run(2, "done", 20, 2, log=sw, review={"total": 8}),
            _run(3, "done", 30, 3, runner="SDI-APP01-77aa11",
                 log=["SWITCHING TO THE DOCUMENT MANAGER"], client="Beta"),
            _run(4, "error", 5, 4),
            _run(5, "done", 3, 1, job_type="sw_extract"),
            _run(6, "done", 15, 45)]                                        # outside 30 days
    v = W.history_view(runs, now=NOW, days=30)
    t = v["totals"]
    assert t["estimates"] == 4 and t["extracts"] == 1 and t["done"] == 3 and t["failed"] == 1
    assert t["success_pct"] == 75.0 and t["median_s"] == 1200.0 and t["engine_hours"] == 1.0
    assert t["open_items_median"] == 6.0 and t["with_review"] == 2
    assert len(v["daily"]) == 30 and sum(d["done"] for d in v["daily"]) == 3
    assert {e["kind"]: e["count"] for e in v["evidence"]} == {"sw": 2, "dm_fallback": 1}
    assert {m["machine"]: m["runs"] for m in v["machines"]} == {"DESKTOP-GFAAP80": 4, "SDI-APP01": 1}
    assert v["clients"][0]["client"] == "Acme" and v["clients"][0]["failed"] == 1
    assert [r["run_id"] for r in v["runs"]] == ["r1", "r5", "r2", "r3", "r4"]
    assert v["runs"][0]["open_items"]["total"] == 4 and v["runs"][0]["evidence"] == "SolidWorks measured model"


# ── the service ─────────────────────────────────────────────────────────────────────────

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
             "estimate_wall", "voicecrm_speech")
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


def test_the_voice_says_which_setting_is_missing_never_its_value(client, monkeypatch):
    tc, er = client
    import voicecrm_speech as vs
    monkeypatch.setattr(vs, "KEY", "")
    monkeypatch.setattr(vs, "REGION", "uksouth")
    body = tc.get("/api/estimate/speech").json()
    assert body["speech_tts"] is False and body["speech_missing"] == ["SDI_SPEECH_KEY"]
    assert "SDI_SPEECH_KEY is not set" in body["speech_reason"]
    wall = tc.get("/api/estimate/wall").json()
    assert any(a.startswith("Voice: the pages are using the device's own voice") for a in wall["alerts"])
    monkeypatch.setattr(vs, "KEY", "secret-value-123")
    body = tc.get("/api/estimate/speech").json()
    assert body["speech_tts"] is True and body["speech_reason"] == ""
    assert "secret-value-123" not in json.dumps(body)
    assert not any(a.startswith("Voice:") for a in tc.get("/api/estimate/wall").json()["alerts"])


def test_the_history_route_gives_runs_now_and_reads_aisheets_behind(client, monkeypatch):
    tc, er = client
    run = er.Run(run_id="r1", drawing_number="12002-02-GA", client="Acme", units=1,
                 job_folder="", output_path="", status="done", runner="laptop",
                 queued_at=NOW - 900, started_at=NOW - 840, finished_at=time.time() - 60)
    er._RUNS["r1"] = run
    monkeypatch.setattr(er, "_engine_ready", lambda: None)

    class Done:
        returncode = 0
        stderr = ""
        stdout = json.dumps({"totals": {"estimates": 9}, "recent": [
            {"drawing": "12002-02-GA", "workbook": "/s/AISheets/Acme/12002-02-GA/x/12002.xlsx"}]})
    calls = []
    monkeypatch.setattr(er.subprocess, "run", lambda args, **kw: calls.append(args) or Done())
    first = tc.get("/api/estimate/wall/history").json()
    assert first["service"]["totals"]["estimates"] == 1 and first["kept_days"] == 30.0
    for t in __import__("threading").enumerate():
        if t.name == "wall-history":
            t.join(timeout=10)
    again = tc.get("/api/estimate/wall/history").json()
    assert again["filed"]["state"] == "ready" and again["filed"]["totals"]["estimates"] == 9
    assert again["filed"]["recent"][0]["book_url"].startswith("/api/file?path=")
    assert calls[0][1].endswith("run_history.py") and "--cache" in calls[0]
    assert len(calls) == 1                               # not read again inside ten minutes


# ── the page ────────────────────────────────────────────────────────────────────────────

def test_the_page_moves_only_when_somebody_asks():
    page = WALL.read_text(encoding="utf-8")
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "scroll-behavior:smooth" not in css
    assert 'href="#parity"' not in page and 'href="#ops"' not in page
    assert 'history.replaceState(null, "", location.pathname + location.search);' in page
    assert '["wheel", "touchstart"].forEach(ev => addEventListener(ev, () => { if(cycleT) cycle(false); }' in page
    assert "overflow-anchor:none" in css
    assert 'if(e.key === "c" || e.key === "C")' not in page          # no key starts the cycle


def test_the_page_draws_the_history():
    page = WALL.read_text(encoding="utf-8")
    assert 'id="history"' in page and 'id="navHistory"' in page
    for fn in ("readHistory", "renderHistory", "renderHDaily", "renderHTimes", "renderHMonths",
               "renderHEvidence", "renderHClients", "renderHRepeats", "renderHRuns",
               "renderHFiled", "searchParity"):
        assert f"function {fn}(" in page
    assert "/api/estimate/wall/history" in page and "/api/estimate/parity/reports" in page
    assert "setInterval(() => readHistory(false), 60000);" in page    # never on the 4 s beat


def test_check_services_says_which_voice_each_service_gives():
    ps1 = (ROOT / "tools" / "start" / "check-services.ps1").read_text(encoding="utf-8")
    assert '/api/estimate/speech' in ps1 and "voice: neural" in ps1
    assert all(ord(c) < 128 for c in ps1)
