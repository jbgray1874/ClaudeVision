"""The estimating wall monitor, and the SolidWorks Document Manager extract button (D-737).

JG, 7 Nov 2026: "yes build the full-screen page for the wall monitor ... runtime stats, KPIs
around run times, etc. monitoring on activity, red amber green on running" and "we need a
document manager run button next to the xai and the solid works build also. the two yellow
buttons."

The wall's every figure and colour is worked out by estimate_wall (pure) and served at
/api/estimate/wall; the page only draws it. The third button reads the pack's models with the
Document Manager into the SolidWorks extract's own tables, on a runner that holds the key.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "runner"))

import pack_extract as pe  # noqa: E402

PAGE = BACKEND / "sdi-estimating-intelligence.html"
WALL = BACKEND / "sdi-estimating-wall.html"


def _wall():
    sys.path.insert(0, str(BACKEND))
    try:
        import estimate_wall
        return estimate_wall
    finally:
        sys.path.remove(str(BACKEND))


NOW = 1_800_000_000.0


def _done(i, minutes, ago_h=2.0, status="done", job_type="", error=""):
    fin = NOW - ago_h * 3600
    return {"run_id": f"d{i}", "drawing_number": f"D-{i}", "client": "C", "job_type": job_type,
            "status": status, "error": error, "queued_at": fin - minutes * 60 - 30,
            "started_at": fin - minutes * 60, "finished_at": fin, "runner": "L", "log": []}


def _running(elapsed_min, log=(), silent_s=5.0, job_type=""):
    st = NOW - elapsed_min * 60
    return {"run_id": "live", "drawing_number": "12002-02-GA", "client": "M&S",
            "job_type": job_type, "status": "running", "queued_at": st - 20, "started_at": st,
            "finished_at": None, "runner": "L", "log": list(log), "last_line_at": NOW - silent_s}


HISTORY = [_done(i, m) for i, m in enumerate((18, 20, 22, 19, 21))]          # median 20 min


# ── THE COLOURS ON A RUN ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("elapsed, log, silent, colour, words", [
    (10, ["engine started"], 5, "green", "on pace"),
    (24, ["engine started"], 5, "amber", "slower than usual"),
    (40, ["engine started"], 5, "red", "40 min in, expected about 20"),
    (10, ["engine started"], 900, "red", "log silent for 15 min"),
    (10, ["  ERROR: Excel could not open the template"], 5, "red", "an error line"),
    (10, ["Waiting for the desktop's SolidWorks: another run"], 5, "amber", "waiting for the desktop"),
    (10, ["Waiting for the desktop's SolidWorks: another run",
          "SolidWorks is free after 312 s: this run reads its models now."], 5, "green", "on pace"),
    (10, ["SWITCHING TO THE DOCUMENT MANAGER for this run's models"], 5, "amber", "Document Manager"),
])
def test_a_running_estimate_is_coloured_and_says_why(elapsed, log, silent, colour, words):
    w = _wall()
    exp = w.expected_seconds(HISTORY, NOW, 30)
    assert exp == 20 * 60
    rag, why = w.run_rag(_running(elapsed, log, silent), NOW, exp, w.thresholds())
    assert rag == colour and words in why, (rag, why)


def test_with_no_history_a_run_is_not_paced_against_a_guess():
    w = _wall()
    assert w.expected_seconds(HISTORY[:2], NOW, 30) is None
    rag, why = w.run_rag(_running(90), NOW, None)
    assert rag == "green" and "no history" in why


def test_the_stage_is_the_furthest_the_log_has_reached():
    w = _wall()
    assert w.stage_of([]) == (-1, "")
    log = ["engine started", "  [solidworks] model extract APPLIED", "  [graph] product is X",
           "  [pricing] price source reached."]
    assert w.stage_of(log) == (4, "Pricing")


# ── THE COLOURS ON A RUNNER ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("runner, colour, words", [
    ({"online": False}, "red", "offline"),
    ({"online": True, "conflict": True}, "red", "two processes"),
    ({"online": True, "build": "17df5ba7", "seconds_since_seen": 3}, "amber", "the service is on a509f73"),
    ({"online": True, "build": "a509f73a", "seconds_since_seen": 60}, "amber", "quiet for 60 s"),
    ({"online": True, "build": "a509f73a", "seconds_since_seen": 3}, "green", "ready"),
    ({"online": True, "build": "a509f73a", "seconds_since_seen": 60, "run_id": "x"}, "green", "working"),
])
def test_a_runner_is_coloured_and_says_why(runner, colour, words):
    w = _wall()
    rag, why = w.runner_rag(runner, "a509f73a1234")
    assert rag == colour and words in why, (rag, why)


# ── THE KPIs ─────────────────────────────────────────────────────────────────────────────

def test_the_kpis_count_estimates_and_extracts_apart():
    w = _wall()
    runs = HISTORY + [_done(9, 2, job_type="sw_extract"),
                      _done(10, 25, status="error", error="engine exited 1"),
                      _done(11, 5, status="error", error="abandoned by the estimator"),
                      _running(5), {**_running(0), "run_id": "q", "status": "queued",
                                    "started_at": None}]
    k = w.kpis(runs, NOW, max_runs=2)
    assert k["median_s_7d"] == 20 * 60                      # the 2-minute extract is not in it
    assert k["fastest_s_7d"] == 18 * 60
    assert k["success_rate_7d"] == round(100 * 5 / 6, 1)    # the stopped run is not a failure
    assert k["judged_7d"] == 6
    assert (k["running"], k["queued"], k["max_runs"], k["utilisation_pct"]) == (1, 1, 2, 50)
    assert k["p90_s_7d"] >= k["median_s_7d"]
    assert w.outcome(runs[-4]) == "failed" and w.outcome(runs[-3]) == "stopped"


def test_the_activity_chart_has_24_hours_and_the_trend_the_last_30():
    w = _wall()
    runs = HISTORY + [_done(20, 3, ago_h=1.5, job_type="xai_extract"),
                      _done(21, 30, ago_h=0.5, status="error", error="engine exited 1"),
                      _done(22, 20, ago_h=30)]                # outside the day
    s = w.series(runs, NOW)
    hours = s["activity_24h"]
    assert len(hours) == 24
    assert sum(h["done"] for h in hours) == 5
    assert sum(h["failed"] for h in hours) == 1 and sum(h["extracts"] for h in hours) == 1
    assert [r["outcome"] for r in s["run_times"]][-1] == "failed"
    assert all(r["seconds"] for r in s["run_times"])


# ── THE ONE ANSWER ───────────────────────────────────────────────────────────────────────

def test_the_snapshot_shows_the_planned_fleet_and_never_says_nominal_over_red(monkeypatch):
    w = _wall()
    monkeypatch.setenv("SDI_WALL_FLEET", "LAPTOP-1=Laptop,SDI-APP01=Server,NEWBOX=New box")
    runners = [{"runner_id": "l1", "hostname": "LAPTOP-1", "online": True, "run_id": "live",
                "seconds_since_seen": 2, "build": "a509f73a"}]
    snap = w.snapshot(HISTORY + [_running(45)], runners, now=NOW, max_runs=1,
                      service_commit="a509f73a")
    labels = {f["label"]: f for f in snap["fleet"]}
    assert labels["Laptop"]["rag"] == "green" and labels["Laptop"]["job"]["run_id"] == "live"
    assert labels["Server"]["rag"] == "grey" and labels["Server"]["planned"] is True
    assert labels["New box"]["rag_reason"] == "planned, not yet connected"
    assert snap["live"][0]["rag"] == "red"                  # 45 min against a 20 min median
    assert snap["banner_rag"] == "red" and "red" in snap["banner"]
    assert any("12002-02-GA" in a for a in snap["alerts"])
    assert snap["live"][0]["stage"] == "Staged" or snap["live"][0]["stage_index"] == -1
    assert snap["kpis"]["max_runs"] == 1 and len(snap["series"]["activity_24h"]) == 24


def test_with_no_runner_online_the_wall_says_estimates_cannot_run():
    w = _wall()
    snap = w.snapshot(HISTORY, [{"runner_id": "x", "hostname": "X", "online": False}],
                      now=NOW)
    assert snap["banner_rag"] == "red" and "No runner connected" in snap["banner"]


def test_the_page_draws_what_the_service_worked_out():
    page = WALL.read_text(encoding="utf-8")
    assert '"/api/estimate/wall"' in page
    for word in ("On pace", "Attention", "Action"):               # every colour has its word
        assert word in page
    assert "fetch(" in page and "http" not in page.split("<script>")[1].split("fetch(")[0]
    assert "<script src=" not in page and "<link " not in page, "no external files on the wall"
    app = (BACKEND / "app.py").read_text(encoding="utf-8")
    assert '@app.get("/estimating/wall")' in app and "sdi-estimating-wall.html" in app
    assert 'href="/estimating/wall"' in PAGE.read_text(encoding="utf-8")


# ── THE THIRD READER ─────────────────────────────────────────────────────────────────────

def _extract():
    return {"schema": "sw_docmgr_extract.v1", "reader": "solidworks_docmgr", "records": [
        {"title": "12002-02-GA", "doctype": 2, "assembly_part_number": "12002-02-GA",
         "bom": [{"part_number": "12002-02-101 SA", "qty": 1}], "reader": "solidworks_docmgr"},
        {"title": "12002-02-M01", "doctype": 1, "reader": "solidworks_docmgr",
         "custom_properties": {"Description": "BASE PLATE"},
         "not_saved": ["bbox_mm"], "route_signals": {"material": "Plain Carbon Steel",
                                                     "thickness_mm": 3.0}}]}


def test_the_document_manager_extract_uses_the_solidworks_tables(tmp_path):
    src = tmp_path / "x_docmgr_extract.json"
    src.write_text(json.dumps(_extract()), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    written = pe.dm_pack(None, out, "12002-02-GA", from_extract=src)
    names = sorted(p.name for p in written)
    assert names == ["12002-02-GA_docmgr_pack.json", "12002-02-GA_docmgr_pack.xlsx"]
    doc = json.loads((out / "12002-02-GA_docmgr_pack.json").read_text(encoding="utf-8"))
    assert doc["reader"] == "solidworks_docmgr"
    assert set(doc["tables"]) == set(pe.organise_sw(_extract()))


def test_the_document_manager_needs_its_key_and_never_puts_it_on_the_command_line(
        tmp_path, monkeypatch):
    monkeypatch.delenv(pe.DOCMGR_KEY_ENV, raising=False)
    with pytest.raises(SystemExit) as e:
        pe.run_docmgr(tmp_path, tmp_path / "o.json")
    assert "SDI_SW_DOCMGR_KEY" in str(e.value)
    monkeypatch.setenv(pe.DOCMGR_KEY_ENV, "secret-value-123")
    seen = {}

    class _P:
        returncode = 0
        stdout = "EXTRACT_PATH=" + str(tmp_path / "o.json")

    def _run(cmd, **kw):
        seen["cmd"] = cmd
        (tmp_path / "o.json").write_text("{}", encoding="utf-8")
        return _P()
    monkeypatch.setattr(pe.subprocess, "run", _run)
    assert pe.run_docmgr(tmp_path, tmp_path / "o.json") == tmp_path / "o.json"
    assert seen["cmd"][2].endswith("sw_docmgr_analyse.py")
    assert not any("secret-value-123" in c for c in seen["cmd"])


def test_the_runner_offers_the_extract_only_with_the_key(monkeypatch):
    import sdi_estimate_runner as runner
    monkeypatch.delenv("SDI_SW_DOCMGR_KEY", raising=False)
    monkeypatch.delenv("SDI_SW_DOCMGR", raising=False)
    assert "dm_extract" not in runner.runner_capabilities()
    monkeypatch.setenv("SDI_SW_DOCMGR_KEY", "k")
    caps = runner.runner_capabilities()
    assert "dm_extract" in caps and {"sw_extract", "xai_extract"} <= set(caps)
    cmd = runner.pack_extract_command(Path("/e"), Path("/py"), {
        "job_type": "dm_extract", "job_folder": "/pack", "output_path": "/out",
        "drawing_number": "12002-02-GA"})
    assert cmd[3] == "dm" and not any(c.endswith("main.py") for c in cmd)


def test_the_page_has_the_third_yellow_button():
    page = PAGE.read_text(encoding="utf-8")
    i = page.index('id="packExtractCard"')
    card = page[i:i + 3500]
    for bid in ('id="pxSw"', 'id="pxXai"', 'id="pxDm"'):
        assert bid in card
    assert card.count('class="btn-run"') == 3
    assert '["pxDm","dm","SolidWorks Document Manager extract"]' in page


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
        yield tc, er, share
    except Exception as exc:                                            # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    finally:
        sys.path.remove(str(BACKEND))
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_the_service_queues_the_document_manager_extract_only_for_a_runner_with_the_key(client):
    tc, er, share = client
    pack = share / "M&S" / "12002-02-GA"
    pack.mkdir(parents=True)
    (pack / "12002-02-GA.SLDASM").write_bytes(b"model")
    base = {"runner_id": "laptop", "hostname": "SDI-LAPTOP", "process": "1", "build": "x"}
    tc.post("/api/estimate/runner/claim", json={**base, "capabilities": ["sw_extract",
                                                                        "xai_extract"]})
    body = {"kind": "dm", "client": "M&S", "drawing_number": "12002-02-GA",
            "job_folder": str(pack)}
    r = tc.post("/api/estimate/pack-extract", json=body)
    assert r.status_code == 503 and "SDI_SW_DOCMGR_KEY" in r.json()["detail"]
    tc.post("/api/estimate/runner/claim", json={**base, "capabilities": [
        "sw_extract", "xai_extract", "dm_extract"]})
    r = tc.post("/api/estimate/pack-extract", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["job_type"] == "dm_extract"
    assert r.json()["output_path"].endswith("(SolidWorks Document Manager extract)")


def test_the_service_serves_the_wall(client):
    tc, er, share = client
    tc.post("/api/estimate/runner/claim", json={"runner_id": "laptop", "hostname": "L",
                                                "process": "1", "build": "x"})
    r = tc.get("/api/estimate/wall")
    assert r.status_code == 200, r.text
    snap = r.json()
    for key in ("banner", "banner_rag", "kpis", "series", "live", "fleet", "queue",
                "recent", "alerts", "stages"):
        assert key in snap
    assert snap["fleet"][0]["hostname"] == "L" and snap["fleet"][0]["rag"] in (
        "green", "amber")
    assert len(snap["series"]["activity_24h"]) == 24
    assert er.Run.__dataclass_fields__["last_line_at"].default == 0.0


# ── ALLOWED IS NOT STAFFED (D-753a) ──────────────────────────────────────────────────────

def test_a_slot_with_no_free_runner_is_not_shown_free(monkeypatch):
    """8 Nov: RUN 2 read "SLOT FREE, the next queued estimate starts here" with one runner
    online and busy. A runner takes one run at a time, so a second estimate would wait."""
    w = _wall()
    monkeypatch.setenv("SDI_WALL_FLEET", "LAPTOP-1=Laptop")
    busy = [{"runner_id": "l1", "hostname": "LAPTOP-1", "online": True, "run_id": "live",
             "seconds_since_seen": 2, "build": "a509f73a"}]
    snap = w.snapshot(HISTORY + [_running(5)], busy, now=NOW, max_runs=2, tail_lines=10)
    assert snap["kpis"]["max_runs"] == 2 and snap["kpis"]["free_runners"] == 0
    idle = busy + [{"runner_id": "l1-s2", "hostname": "LAPTOP-1", "online": True,
                    "run_id": None, "seconds_since_seen": 2, "build": "a509f73a"}]
    snap2 = w.snapshot(HISTORY + [_running(5)], idle, now=NOW, max_runs=2, tail_lines=10)
    assert snap2["kpis"]["free_runners"] == 1
    page = (Path(__file__).resolve().parents[1] / "sdi-intelligence-backend"
            / "sdi-estimating-wall.html").read_text(encoding="utf-8")
    assert "NO RUNNER FREE" in page and "install-runner-slot.ps1 -Slot 2" in page
