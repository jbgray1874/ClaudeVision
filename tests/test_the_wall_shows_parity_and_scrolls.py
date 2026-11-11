"""Parity on the control panel, and a wall that scrolls (D-741).

JG, 7 Nov 2026: "there is no scroll and the last runs on the left is cut off as a result, we
should see the parity runs and all kpis/ vizualizations built into this."

The parity view is worked out from the filed comparisons by parity_job.wall_summary, read by
the service in the background, and drawn by the wall below its operations view. Every figure
counts filed comparisons, or is a percentage of the manual sheet's figure, and says which.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
WALL = BACKEND / "sdi-estimating-wall.html"
sys.path.insert(0, str(ROOT / "src"))

import parity_job as pj  # noqa: E402

NOW = time.mktime((2026, 11, 7, 12, 0, 0, 0, 0, -1))


def _file(root, client, drawing, stamp, ai, manual, *, run="r1", lines=None, error="",
          quantity=None):
    folder = root / client / drawing / f"{stamp}_abcd1234"
    folder.mkdir(parents=True, exist_ok=True)
    pct = abs(ai - manual) / manual * 100.0 if ai is not None and manual else None
    index = {"stamp": stamp, "job": drawing[:5], "drawing": drawing, "client": client,
             "headline": {"ai_unit_cost_gbp": ai, "manual_unit_cost_gbp": manual,
                          "pct_variance": pct,
                          "status": pj._verdict(pct) if pct is not None else "review"},
             "quantity": quantity or {"comparable": True},
             "ai": {"run": run, "run_folder": "AISheets\\" + run},
             "lines": lines or [], "lines_from": "line by line" if lines else "money cells",
             "error": error, "report_html": "report.html", "walkthrough_wav": "spoken.wav"}
    index["outcome"] = pj.outcome_of(index)
    (folder / pj.INDEX_NAME).write_text(json.dumps(index), encoding="utf-8")
    return folder


def _lines(material_ai, material_manual):
    return [{"kind": "cost", "label": "Total material cost", "ai": material_ai,
             "manual": material_manual},
            {"kind": "cost", "label": "Customer rebate (fraction)", "ai": 0.02, "manual": 0.03,
             "fraction": True},
            {"kind": "commercial", "label": "Packaging", "ai": 5.0, "manual": 4.0}]


@pytest.fixture
def filed(tmp_path):
    root = tmp_path / "parity"
    # One drawing compared from two AI runs, the gap closing; then a comparison that failed.
    _file(root, "Acme", "12002-02-GA", "2026-10-20 10-00-00", 480.0, 400.0,
          run="2026-10-20 09-00-00 (1 off)", lines=_lines(130.0, 100.0))
    _file(root, "Acme", "12002-02-GA", "2026-11-06 10-00-00", 404.0, 400.0,
          run="2026-11-06 09-00-00 (1 off)", lines=_lines(102.0, 100.0))
    _file(root, "Acme", "12002-02-GA", "2026-11-07 08-00-00", None, None,
          run="2026-11-06 09-00-00 (1 off)", error="ExcelError: could not open")
    # The same run compared twice is not a re-estimate.
    _file(root, "Beta", "11908-22-GA", "2026-11-03 10-00-00", 90.0, 100.0, run="b1")
    _file(root, "Beta", "11908-22-GA", "2026-11-04 10-00-00", 90.0, 100.0, run="b1")
    # Exactly at the warning threshold, and just past it.
    _file(root, "Beta", "12677-01", "2026-11-05 10-00-00", 110.0, 100.0, run="c1")
    _file(root, "Gamma", "12693-03-GA", "2026-11-05 11-00-00", 110.5, 100.0, run="d1")
    # Quantities differ: counted apart, never a match or a miss.
    _file(root, "Gamma", "9287-10-GA", "2026-11-05 12-00-00", 100.0, 100.0, run="e1",
          quantity={"comparable": False, "note": "Quantities differ"})
    return root


def test_where_parity_stands_is_each_drawings_newest_comparison_that_compared(filed):
    out = pj.wall_summary(filed, now=NOW)
    k = out["kpis"]
    assert out["reachable"] is True
    assert k["drawings"] == 5 and k["compared"] == 4 and k["comparisons"] == 8
    # The failed comparison at 08:00 does not hide the 1% one from the day before.
    assert k["match"] == 1 and k["warning"] == 2 and k["fail"] == 1
    assert k["quantities_differ"] == 1 and k["not_compared"] == 0
    assert k["within_warning_pct"] == 75.0 and k["within_match_pct"] == 25.0
    assert k["ai_dearer"] == 3 and k["ai_cheaper"] == 1


def test_a_threshold_belongs_to_the_band_inside_it(filed):
    bins = pj.wall_summary(filed, now=NOW)["distribution"]
    by = {b["label"]: b for b in bins}
    assert by["within ±3%"]["count"] == 1                              # 12002 at +1%
    assert by["-10% to -3%"]["count"] == 1                             # 11908 at -10%, warning
    assert by["+3% to +10%"]["count"] == 1 and by["+3% to +10%"]["band"] == "warning"  # +10%
    assert by["+10% to +20%"]["count"] == 1 and by["+10% to +20%"]["band"] == "fail"   # +10.5%
    assert sum(b["count"] for b in bins) == 4


def test_the_sign_says_which_side_is_dearer():
    dearer = {"headline": {"ai_unit_cost_gbp": 110.0, "manual_unit_cost_gbp": 100.0}}
    cheaper = {"headline": {"ai_unit_cost_gbp": 90.0, "manual_unit_cost_gbp": 100.0}}
    at_qty = {"headline": {"ai_unit_cost_gbp": 150.0, "manual_unit_cost_gbp": 100.0},
              "quantity": {"ai_unit_at_manual_qty": 95.0}}
    unread = {"headline": {"ai_unit_cost_gbp": None, "manual_unit_cost_gbp": 100.0}}
    assert pj.signed_pct(dearer) == 10.0 and pj.signed_pct(cheaper) == -10.0
    assert pj.signed_pct(at_qty) == -5.0                     # at the manual's quantity
    assert pj.signed_pct(unread) is None


def test_re_estimating_counts_distinct_ai_runs_only(filed):
    movers = pj.wall_summary(filed, now=NOW)["movers"]
    assert movers["drawings"] == 1                           # 11908's two are one run
    row = movers["rows"][0]
    assert row["drawing"] == "12002-02-GA" and row["runs"] == 2
    assert row["first_pct"] == 20.0 and row["last_pct"] == 1.0
    assert row["change_abs_pct"] == -19.0 and movers["closer"] == 1


def test_cost_lines_leave_fractions_out(filed):
    areas = pj.wall_summary(filed, now=NOW)["cost_areas"]
    labels = [a["label"] for a in areas["areas"]]
    assert "Customer rebate (fraction)" not in labels
    assert labels[0] == "Total material cost" and "Packaging" in labels
    assert areas["from_comparisons"] == 1                    # only 12002's standing one
    material = areas["areas"][0]
    assert material["count"] == 1 and material["median_signed_pct"] == 2.0


def test_each_week_counts_a_drawing_once(filed):
    weeks = pj.wall_summary(filed, now=NOW, weeks=4)["trend"]
    assert [w["week"] for w in weeks] == ["2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02"]
    this = weeks[-1]
    assert this["comparisons"] == 7                          # every comparison filed that week
    assert this["drawings"] == 5 and this["compared"] == 4 and this["not_comparable"] == 1
    assert weeks[1]["compared"] == 1 and weeks[1]["fail"] == 1


def test_the_newest_comparisons_carry_their_report_and_their_reason(filed):
    recent = pj.wall_summary(filed, now=NOW, recent=3)["recent"]
    assert [r["stamp"] for r in recent] == ["2026-11-07 08-00-00", "2026-11-06 10-00-00",
                                            "2026-11-05 12-00-00"]
    assert recent[0]["outcome"] == "not compared" and "ExcelError" in recent[0]["error"]
    assert recent[1]["report_html"] == "report.html" and recent[1]["folder"]
    assert recent[2]["quantity_note"] == "Quantities differ"


def test_a_parity_folder_out_of_reach_says_so(tmp_path):
    out = pj.wall_summary(tmp_path / "nowhere", now=NOW)
    assert out["reachable"] is False and "could not be read" in out["note"]


def test_period_history_carries_its_variance(tmp_path):
    period = tmp_path / "_periods" / "2026-10-01 to 2026-10-31 (run 2026-11-01 10-00-00)"
    period.mkdir(parents=True)
    (period / "period_summary.json").write_text(json.dumps(
        {"kind": "period", "start": "2026-10-01", "end": "2026-10-31",
         "stats": {"compared": 14, "median_abs_pct": 7.4, "within_warning_pct": 64.3}}))
    row = pj.history(tmp_path)[0]
    assert row["median_abs_pct"] == 7.4 and row["within_warning_pct"] == 64.3


def test_the_command_line_answers_the_service_in_one_json_line(filed):
    proc = subprocess.run([sys.executable, str(ROOT / "src" / "parity_job.py"), "wall", "--json"],
                          capture_output=True, text=True, timeout=120, cwd=str(ROOT),
                          env={**__import__("os").environ, "SDI_PARITY_ROOT": str(filed)})
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout.strip().splitlines()[-1])
    assert body["schema"] == "sdi_parity_wall.v1" and body["kpis"]["drawings"] == 5


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


def _join_reads():
    for t in threading.enumerate():
        if t.name == "wall-parity":
            t.join(timeout=10)


def test_the_wall_reads_parity_in_the_background_and_never_waits_for_it(client, monkeypatch):
    tc, er = client
    gate = threading.Event()
    calls = []

    def slow(args, timeout=300):
        calls.append(args)
        gate.wait(5)
        return {"schema": "sdi_parity_wall.v1", "reachable": True, "kpis": {"drawings": 2},
                "recent": [{"folder": "/p/Acme/12002/2026_x", "report_html": "r.html",
                            "walkthrough_wav": "w.wav"}],
                "periods": [{"summary_html": "/p/_periods/x/period_summary.html"}]}
    monkeypatch.setattr(er, "_parity_job", slow)
    started = time.time()
    first = tc.get("/api/estimate/wall")
    assert first.status_code == 200 and time.time() - started < 3
    assert first.json()["parity"]["state"] == "reading"
    assert calls == [["wall"]]
    gate.set()
    _join_reads()
    ready = tc.get("/api/estimate/wall").json()["parity"]
    assert ready["state"] == "ready" and ready["kpis"]["drawings"] == 2
    assert ready["recent"][0]["report_url"].startswith("/api/file?path=")
    assert ready["recent"][0]["listen_url"].endswith("w.wav")
    assert ready["periods"][0]["summary_url"].startswith("/api/file?path=")
    assert len(calls) == 1                                   # not read again inside five minutes
    tc.get("/api/estimate/wall/parity", params={"refresh": 1})
    _join_reads()
    assert len(calls) == 2                                   # Read again reads it again


def test_a_parity_read_that_fails_is_said_and_the_wall_still_serves(client, monkeypatch):
    tc, er = client

    def refused(args, timeout=300):
        raise er.HTTPException(status_code=500, detail="Engine python not found")
    monkeypatch.setattr(er, "_parity_job", refused)
    assert tc.get("/api/estimate/wall").status_code == 200
    _join_reads()
    parity = tc.get("/api/estimate/wall").json()["parity"]
    assert parity["state"] == "unavailable" and "Engine python" in parity["read_error"]


def test_the_page_scrolls_and_nothing_in_recent_is_cut_off():
    page = WALL.read_text(encoding="utf-8")
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "overflow:hidden;\n       font-variant-numeric" not in css
    assert "overflow-y:auto" in css.split("\n  body{", 1)[1].split("}", 1)[0]
    assert "height:max(calc(100vh - 106px), 940px)" in css    # a short screen scrolls
    assert not __import__("re").search(r"(?<![-\w])height:100vh", css)  # no fixed screen height
    assert "position:sticky;bottom:0" in css                  # the ticker stays in view
    assert "rows.slice(0, 9)" not in page                     # every recent run, scrolled
    assert ".feed{padding:8px 12px 10px;overflow-x:hidden;overflow-y:auto" in css


def test_the_page_draws_parity_from_the_wall_read():
    page = WALL.read_text(encoding="utf-8")
    assert 'id="parity"' in page and 'id="navParity"' in page and 'id="cycleBtn"' in page
    for fn in ("renderParityKpis", "renderParityDist", "renderParityTrend", "renderParityWeeks",
               "renderParityAreas", "renderParityClients", "renderParityMovers",
               "renderParityRecent", "renderParityPeriods"):
        assert f"function {fn}(" in page
    assert "renderParity(s.parity)" in page
    assert "/api/estimate/wall/parity?refresh=1" in page
    assert 'href="/estimating#pjCard"' in page
    # Bands are the comparator's own thresholds, read from the service, never a target of the page's.
    assert "th.warning" in page and "on target" not in page
