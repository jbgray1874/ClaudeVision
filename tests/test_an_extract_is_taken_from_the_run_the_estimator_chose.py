"""The extract buttons work from an explicitly chosen run (SCRUM-132, POR-06).

The three buttons on the estimating page, BOMs, Routes and BOMs and Routes, called an endpoint
that read `config.OUTPUT_ROOT` from the service's configuration, which never defined it: every
press was a server error, on the live service, while a source-text test reported it wired. It
also looked for the record where the runner files nothing. These tests drive the real endpoint
through FastAPI's TestClient with the service's ACTUAL configuration module, not a stub: a run
folder laid out as the runner files it, the three kinds, no run chosen, no record, two records,
empty routes, a path outside the allowed roots, and a download through /api/file's own rule.
The run's own extract files are served where it wrote them; otherwise the engine rebuilds them
out of process, and a machine without the engine's Python says so.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BACKEND = _REPO / "sdi-intelligence-backend"

pytest.importorskip("fastapi", reason="fastapi not installed")
pytest.importorskip("httpx", reason="httpx not installed (FastAPI's TestClient needs it)")


def _record(job="9439-07-04", routes=True):
    """The smallest record bom_and_route_extract tabulates: one BOM row, one route decision."""
    return {
        "job_output_stem": job, "processed_at": "2026-10-25T09:10:27+00:00",
        "declared_product": {"drawing_number": f"{job}-GA"},
        "manufacturing_writeup": {"parts": [{"part_number": f"{job}-01M", "description": "END FRAME",
                                             "quantity": 2}]},
        "estimate_summary": {
            "part_estimates": [{"part_number": f"{job}-01M", "description": "END FRAME",
                                "quantity": 2}],
            "canonical_route_shadow": {"decisions": ([
                {"operation": "laser_cutting", "status": "required",
                 "target_id": f"{job}-01M", "source": "dxf"}] if routes else []),
                "nodes": []}}}


@pytest.fixture()
def service(tmp_path, monkeypatch):
    share = tmp_path / "share"
    run = share / "Client A" / "9439-07-04" / "2026-10-25 09-10-27 (1 off)"
    run.mkdir(parents=True)
    saved = {n: sys.modules.pop(n) for n in ("estimate_routes",) if n in sys.modules}
    sys.path.insert(0, str(_BACKEND))
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import estimate_routes as er
        # THE SERVICE'S OWN CONFIGURATION MODULE, as the service loads it. Its roots are pointed
        # at the temporary share; nothing else about it is replaced.
        assert Path(er.config.__file__).resolve() == (_BACKEND / "config.py").resolve()
        assert not hasattr(er.config, "OUTPUT_ROOT"), \
            "the old endpoint read config.OUTPUT_ROOT; the real config has none"
        monkeypatch.setattr(er.config, "FILE_ROOTS", [str(share)], raising=False)
        monkeypatch.setattr(er.config, "API_KEY", "", raising=False)
        monkeypatch.setattr(er, "OUTPUT_ROOT", share)
        # The rebuild runs out of process in "the engine's Python"; here, this interpreter, so
        # the real command-line entry is exercised end to end.
        monkeypatch.setattr(er, "_ENGINE_PYTHON", sys.executable)
        app = FastAPI()
        app.include_router(er.router)
        yield TestClient(app), run, share
    finally:
        sys.path.remove(str(_BACKEND))
        sys.modules.pop("estimate_routes", None)
        sys.modules.update(saved)


def _post(tc, run, kind="both", **extra):
    body = {"kind": kind, "run_folder": str(run), "drawing_number": "9439-07-04"}
    body.update(extra)
    return tc.post("/api/estimate/extract", json=body)


@pytest.mark.parametrize("kind,sheet", [("boms", "boms"), ("routes", "routes"),
                                        ("both", "boms_and_routes")])
def test_each_button_builds_from_the_chosen_run(service, kind, sheet):
    tc, run, share = service
    (run / "9439-07-04.json").write_text(json.dumps(_record()), encoding="utf-8")
    r = _post(tc, run, kind)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["run_folder"] == str(run) and j["record"].endswith("9439-07-04.json")
    assert j["processed_at"] == "2026-10-25T09:10:27+00:00"
    assert any("Build" in ln for ln in j["lines"]), "every output names its build, or says it is not recorded"
    for f in (j["xlsx"], j["html"]):
        assert f and Path(f).is_file() and sheet in Path(f).name
        assert not Path(f).is_relative_to(run), "derived files never go into the run folder"
    assert all(d["url"].startswith("/api/file?path=") for d in j["downloads"])


def test_no_run_chosen_is_refused_and_nothing_is_guessed(service):
    tc, run, share = service
    (run / "9439-07-04.json").write_text(json.dumps(_record()), encoding="utf-8")
    r = tc.post("/api/estimate/extract", json={"kind": "both", "drawing_number": "9439-07-04"})
    assert r.status_code == 400 and "Choose the run" in r.json()["detail"]


def test_a_run_with_no_record_says_so(service):
    tc, run, share = service
    r = _post(tc, run)
    assert r.status_code == 404 and "no saved run record" in r.json()["detail"]


def test_two_records_and_none_named_for_the_drawing_is_not_guessed(service):
    tc, run, share = service
    (run / "a.json").write_text(json.dumps(_record("A")), encoding="utf-8")
    (run / "b.json").write_text(json.dumps(_record("B")), encoding="utf-8")
    r = _post(tc, run)
    assert r.status_code == 409 and "Nothing was guessed" in r.json()["detail"]


def test_a_record_with_no_routes_says_so(service):
    tc, run, share = service
    (run / "9439-07-04.json").write_text(json.dumps(_record(routes=False)), encoding="utf-8")
    j = _post(tc, run, "routes").json()
    assert any("NO route decisions" in ln for ln in j["lines"])


def test_a_folder_outside_the_allowed_roots_is_refused(service, tmp_path):
    tc, run, share = service
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "9439-07-04.json").write_text(json.dumps(_record()), encoding="utf-8")
    assert _post(tc, outside).status_code == 403


def test_the_saved_runs_are_listed_for_the_estimator_to_choose(service):
    tc, run, share = service
    (run / "9439-07-04.json").write_text(json.dumps(_record()), encoding="utf-8")
    j = tc.get("/api/estimate/extract/runs", params={"drawing_number": "9439-07-04"}).json()
    assert [r["run_folder"] for r in j["runs"]] == [str(run)]


def test_the_page_sends_the_chosen_run_and_links_through_the_portal():
    page = (_BACKEND / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")
    start = page.index("async function runExtract")
    body = page[start:page.index("\n}\n", start)]
    assert "run_folder" in body and "/api/file?path=" in body
    assert "file:///" not in body
    assert "Reading \" + drawings.length" not in body, "it reads no drawings; it must not say so"


def test_the_runs_own_files_are_served_without_a_rebuild(service, monkeypatch):
    tc, run, share = service
    rec = _record()
    rec["saved_output_paths"] = {
        "boms_and_routes_xlsx": r"C:\ClaudeVision\output\estimates\9439-07-04_boms_and_routes.xlsx",
        "boms_and_routes_html": r"C:\ClaudeVision\output\estimates\9439-07-04_boms_and_routes.html"}
    (run / "9439-07-04.json").write_text(json.dumps(rec), encoding="utf-8")
    (run / "9439-07-04_boms_and_routes.xlsx").write_bytes(b"the run's own workbook")
    (run / "9439-07-04_boms_and_routes.html").write_text("the run's own page", encoding="utf-8")
    import estimate_routes as er
    monkeypatch.setattr(er, "_ENGINE_PYTHON", "/nowhere/python")   # proves no rebuild ran
    j = _post(tc, run, "routes").json()
    assert j["xlsx"] == str(run / "9439-07-04_boms_and_routes.xlsx")
    assert any("the run itself wrote" in ln for ln in j["lines"])
    assert any("Routes sheet" in ln for ln in j["lines"])


def test_no_engine_python_and_no_own_files_says_so(service, monkeypatch):
    tc, run, share = service
    (run / "9439-07-04.json").write_text(json.dumps(_record()), encoding="utf-8")
    import estimate_routes as er
    monkeypatch.setattr(er, "_ENGINE_PYTHON", "/nowhere/python")
    r = _post(tc, run)
    assert r.status_code == 503 and "engine's Python" in r.json()["detail"]
