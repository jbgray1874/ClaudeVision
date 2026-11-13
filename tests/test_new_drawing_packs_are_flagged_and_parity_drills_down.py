"""New drawing packs on the design share are flagged on the control panel, and a parity
comparison can be opened line by line or re-run fresh (JG, 9 Nov 2026).

The sweep runs on the estimating machine: the first sweep is the baseline and flags nothing;
after it, a pack folder not seen before is NEW and one whose files changed is CHANGED. A year
folder is never a pack, an archive is never walked, a folder named with a drawing number at the
root is never a client. The service keeps what the sweep reported and what was dismissed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import design_sweep as ds  # noqa: E402

ROUTES = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
WALL = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-wall.html").read_text(encoding="utf-8")


def _share(tmp_path: Path) -> Path:
    w = tmp_path / "W"
    for d in ("M&S/0358141 Pantheon", "M&S/Archive/0123 old", "Harrods/2026/Projects/12693-01 Riser",
              "12345 stray", "Harrods/misc"):
        (w / d).mkdir(parents=True)
    (w / "M&S/0358141 Pantheon/a.pdf").write_text("x")
    (w / "Harrods/2026/Projects/12693-01 Riser/x.sldasm").write_text("x")
    (w / "Harrods/misc/notes.txt").write_text("x")
    return w


def test_packs_are_found_under_client_folders_only(tmp_path):
    w = _share(tmp_path)
    found = sorted((f["client"], f["name"], f["job"]) for f in ds.find_packs(w, 3))
    assert found == [("Harrods", "12693-01 Riser", "12693"), ("M&S", "0358141 Pantheon", "0358141")]
    assert ds.job_of("2026") == "" and ds.job_of("0358141 Pantheon") == "0358141"
    assert not ds.is_client_folder("12345 stray") and not ds.is_client_folder("Archive")


def test_the_first_sweep_is_the_baseline_and_new_or_changed_packs_are_flagged_after(tmp_path):
    w = _share(tmp_path)
    cfg = ds.settings({"SDI_DESIGN_SWEEP_ROOT": str(w), "SDI_DESIGN_SWEEP_SHOW_CHANGED": "1"})
    led = ds.load_ledger(tmp_path / "none.json")
    r1 = ds.sweep(cfg, led, now=1000.0, estimated=set())
    assert r1["baseline"] and r1["packs"] == 2 and r1["candidates"] == []
    (w / "M&S/0360001 New Unit").mkdir()
    (w / "M&S/0360001 New Unit/b.pdf").write_text("x")
    r2 = ds.sweep(cfg, led, now=2000.0, estimated={"0358141"})
    assert [(c["name"], c["status"], c["estimated"]) for c in r2["candidates"]] == [("0360001 New Unit", "new", False)]
    (w / "M&S/0358141 Pantheon/c.pdf").write_text("y")
    r3 = ds.sweep(cfg, led, now=3000.0, estimated={"0358141"})
    got = {c["name"]: (c["status"], c["estimated"]) for c in r3["candidates"]}
    assert got == {"0358141 Pantheon": ("changed", True), "0360001 New Unit": ("new", False)}
    r4 = ds.sweep(cfg, led, now=3000.0 + 15 * 86400, estimated=set())
    assert r4["candidates"] == [], "a candidate leaves the list after the keep window"


def test_the_ledger_survives_a_restart(tmp_path):
    w = _share(tmp_path)
    cfg = ds.settings({"SDI_DESIGN_SWEEP_ROOT": str(w), "SDI_DESIGN_SWEEP_LEDGER": str(tmp_path / "l.json")})
    led = ds.load_ledger(cfg["ledger"])
    ds.sweep(cfg, led, now=1000.0, estimated=set())
    ds.save_ledger(cfg["ledger"], led)
    again = ds.load_ledger(cfg["ledger"])
    r = ds.sweep(cfg, again, now=2000.0, estimated=set())
    assert not r["baseline"] and r["candidates"] == []


def test_an_unreadable_share_is_reported_not_crashed(tmp_path):
    cfg = ds.settings({"SDI_DESIGN_SWEEP_ROOT": str(tmp_path / "missing")})
    r = ds.sweep(cfg, ds.load_ledger(tmp_path / "x.json"), now=1.0, estimated=set())
    assert r["errors"] and "could not be read" in r["errors"][0] and r["packs"] == 0


def test_the_service_keeps_the_report_and_the_dismissals_and_the_wall_shows_them():
    for needle in ('@router.post("/design-sweep/report")', '@router.get("/design-sweep")',
                   '@router.post("/design-sweep/dismiss")', 'snap["design_sweep"] = design_sweep_for_wall()'):
        assert needle in ROUTES, needle
    assert 'id="designSweep"' in WALL and "renderDesignSweep(s.design_sweep || {});" in WALL
    assert '"/api/estimate/design-sweep/dismiss"' in WALL


def test_a_parity_comparison_opens_line_by_line_and_a_job_can_be_re_estimated():
    assert '@router.get("/parity/detail")' in ROUTES and '@router.post("/parity/rerun")' in ROUTES
    assert "target.relative_to(root)" in ROUTES, "only folders under the parity root are read"
    assert "staging clears that folder, so it is never its own source" in ROUTES
    assert "compare_with_manual=True" in ROUTES[ROUTES.index('@router.post("/parity/rerun")'):]
    assert 'data-pd="${esc(r.folder)}"' in WALL and "openParityDetail" in WALL
    assert '"/api/estimate/parity/rerun"' in WALL and 'id="rrGo"' in WALL


import pytest  # noqa: E402


@pytest.fixture
def service(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="fastapi not installed")
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SDI_PARITY_ROOT", str(tmp_path / "parity"))
    (tmp_path / "parity").mkdir()
    clash = ("config", "estimate_routes", "log_filters", "hr_routes", "docmgr",
             "self_running_switch", "estimate_email", "staging", "estimate_history")
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
        yield tc, tmp_path
    except Exception as exc:                                            # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    finally:
        sys.path.remove(backend)
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_the_service_shows_the_reported_candidates_and_dismisses_one(service):
    tc, tmp = service
    assert tc.get("/api/estimate/design-sweep").json()["state"] == "never"
    rep = {"swept_at": "2026-11-09T15:00:00Z", "root": "W:\\", "every_minutes": 60, "clients": 2, "packs": 3,
           "candidates": [{"folder": "W:\\M&S\\0360001 New Unit", "client": "M&S", "name": "0360001 New Unit",
                           "job": "0360001", "status": "new", "files": 1, "flagged_at": "2026-11-09T15:00:00Z",
                           "estimated": False},
                          {"folder": "W:\\Harrods\\12693-01", "client": "Harrods", "name": "12693-01", "job": "12693",
                           "status": "changed", "files": 4, "flagged_at": "2026-11-09T15:00:00Z", "estimated": True}]}
    assert tc.post("/api/estimate/design-sweep/report", json=rep).json()["candidates"] == 2
    got = tc.get("/api/estimate/design-sweep").json()
    assert got["state"] == "ok" and len(got["candidates"]) == 2
    after = tc.post("/api/estimate/design-sweep/dismiss", json={"folder": "W:\\Harrods\\12693-01"}).json()
    assert [c["name"] for c in after["candidates"]] == ["0360001 New Unit"] and after["dismissed"] == 1
    tc.post("/api/estimate/design-sweep/report", json=rep)
    assert len(tc.get("/api/estimate/design-sweep").json()["candidates"]) == 1, "a dismissal outlives the next sweep"


def test_a_comparison_folder_is_read_only_under_the_parity_root(service):
    tc, tmp = service
    cmp_dir = tmp / "parity" / "M&S" / "0358141" / "2026-11-09 15-00-00_abc"
    cmp_dir.mkdir(parents=True)
    (cmp_dir / "parity_index.json").write_text(json.dumps({
        "job": "0358141", "drawing": "0358141", "client": "M&S", "outcome": "within",
        "headline": {"ai_unit_cost_gbp": 101.0, "manual_unit_cost_gbp": 100.0, "pct_variance": 1.0},
        "lines": [{"kind": "cost", "label": "Material", "ai": 40.0, "manual": 42.0, "pct": -4.8, "status": "ok", "cell": "Estimate!M14"}]}),
        encoding="utf-8")
    d = tc.get("/api/estimate/parity/detail", params={"folder": str(cmp_dir)}).json()
    assert d["lines"][0]["label"] == "Material" and d["folder"] == str(cmp_dir)
    outside = tmp / "elsewhere"
    outside.mkdir()
    assert tc.get("/api/estimate/parity/detail", params={"folder": str(outside)}).status_code == 403


def test_only_new_folders_are_listed_and_a_folder_filled_after_the_first_look_is_new(tmp_path):
    """JG, 10 Nov 2026: "we need to find NEW folders, not changes". A new job's folder is made
    before its drawings arrive, so the first look saw it empty and later read it as changed."""
    w = _share(tmp_path)
    (w / "TTi").mkdir()
    (w / "TTi/12784 - Bolt Demo").mkdir()                       # made, still empty
    (w / "TTi/12784 - Bolt Demo/notes.txt").write_text("brief")
    cfg = ds.settings({"SDI_DESIGN_SWEEP_ROOT": str(w)})
    led = ds.load_ledger(tmp_path / "l.json")
    ds.sweep(cfg, led, now=1000.0, estimated=set())
    (w / "TTi/12784 - Bolt Demo/12784-00-GA.pdf").write_text("ga")    # its first drawing
    (w / "M&S/0358141 Pantheon/c.pdf").write_text("y")                 # a change to a pack
    r = ds.sweep(cfg, led, now=2000.0, estimated=set())
    assert [(c["name"], c["status"]) for c in r["candidates"]] == [("12784 - Bolt Demo", "new")]
    assert ds.settings({"SDI_DESIGN_SWEEP_SHOW_CHANGED": "1"})["show_changed"] is True


def test_a_pack_whose_folders_have_not_changed_is_not_listed_again(tmp_path, monkeypatch):
    """The sweep listed every file of 9,855 packs each pass and ran every three hours, not hourly."""
    w = _share(tmp_path)
    cfg = ds.settings({"SDI_DESIGN_SWEEP_ROOT": str(w)})
    led = ds.load_ledger(tmp_path / "l.json")
    ds.sweep(cfg, led, now=1000.0, estimated=set())
    listed = []
    real = ds.Path.rglob
    monkeypatch.setattr(ds.Path, "rglob", lambda self, pat: listed.append(self.name) or real(self, pat))
    ds.sweep(cfg, led, now=2000.0, estimated=set())
    assert listed == [], "no folder changed: nothing listed"
    import os, time
    pan = w / "M&S/0358141 Pantheon"
    (pan / "z.pdf").write_text("new")
    os.utime(pan, (time.time() + 10, time.time() + 10))
    ds.sweep(cfg, led, now=3000.0, estimated=set())
    assert listed == ["0358141 Pantheon"]


# ── one line per job, and what the files show, no more (JG and the reviewer, 12 Nov 2026) ────
def _cand(client, name, job, files, when="2026-11-11T09:00:00", first=None, est=False):
    return {"client": client, "name": name, "job": job, "folder": rf"\\share\{client}\{name}",
            "status": "new", "files": sum(1 for f in files if f.lower().endswith((".pdf", ".dxf", ".sldprt"))),
            "flagged_at": when, "first_seen": first or when, "estimated": est,
            "listing": {"files": [{"path": f, "modified": "2026-11-10T16:00:00", "size": 1} for f in files], "more": 0}}


def test_a_jobs_standard_folders_are_one_line_and_an_empty_one_awaits_drawings():
    import design_sweep as ds
    rows = [_cand("TTi", f"12781-{n}", "12781", []) for n in
            ("Technical", "Presentations", "Photos", "Creative", "2D")]
    rows += [_cand("TTi", "12792 - Temperature Gauge Display", "12792", []),
             _cand("Harrys", "12785 - Mini Branded Bay", "12785",
                   ["12785-01-GA.pdf", "12785-01-01M.SLDPRT", "12785-01-01M.dxf", "photo.jpg", "brief.docx"]),
             _cand("M&S", "info", "", ["a.pdf", "b.pdf"])]
    jobs = {(j["client"], j["job"] or j["name"]): j for j in ds.candidate_jobs(rows)}
    assert len(jobs) == 4
    j = jobs[("TTi", "12781")]
    assert len(j["folders"]) == 5 and j["stage"] == ds.STAGE_AWAITING and (j["pdfs"], j["cad"]) == (0, 0)
    assert jobs[("TTi", "12792")]["stage"] == ds.STAGE_AWAITING
    h = jobs[("Harrys", "12785")]
    assert (h["pdfs"], h["cad"], h["other"]) == (1, 2, 2) and h["stage"] == ds.STAGE_DETECTED
    assert h["name"] == "12785 - Mini Branded Bay" and h["newest_drawing"] == "2026-11-10T16:00:00"
    assert h["estimate"] == "no matching AI estimate found"
    assert jobs[("M&S", "info")]["stage"] == ds.STAGE_DETECTED and jobs[("M&S", "info")]["job"] == ""


def test_no_stage_claims_a_pack_is_complete_or_ready():
    import design_sweep as ds
    for stage in (ds.STAGE_AWAITING, ds.STAGE_DETECTED):
        assert "complete" not in stage and "ready" not in stage
    assert "not yet checked" in ds.STAGE_DETECTED


def test_first_detected_is_kept_apart_from_the_newest_drawing_and_drawings_come_first():
    import design_sweep as ds
    rows = [_cand("TTi", "12781-Technical", "12781", [], when="2026-11-12T08:00:00", first="2026-11-11T07:00:00"),
            _cand("TTi", "12781-2D", "12781", ["12781-01-GA.pdf"], when="2026-11-12T09:00:00", first="2026-11-11T07:00:00"),
            _cand("CCS", "12790 - Z-bends", "12790", [], when="2026-11-12T10:00:00")]
    jobs = ds.candidate_jobs(rows)
    assert [j["job"] for j in jobs] == ["12781", "12790"], "a job with drawings is listed before an empty one"
    assert jobs[0]["first_detected"] == "2026-11-11T07:00:00" and jobs[0]["flagged_at"] == "2026-11-12T09:00:00"
    assert jobs[0]["stage"] == ds.STAGE_DETECTED, "files arriving in a known folder update the same line"


def test_the_panel_draws_jobs_says_what_it_is_and_flags_an_overdue_sweep():
    page = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-wall.html").read_text(encoding="utf-8")
    assert "NEW JOB FOLDERS" in page and "not a list of packs ready to estimate" in page
    assert "d.jobs" in page and "data-dsjob" in page and "OVERDUE" in page
    for col in ("First detected", "PDF", "CAD", "Other", "Newest drawing file", "Stage"):
        assert f">{col}<" in page, col
