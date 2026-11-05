"""A drawing pack is read by ONE reader and handed back organised — no estimate (D-640).

JG, 2 Nov 2026: "can we build a SolidWorks drawing pack extract as a new button on the screen
... we pass in drawing files with a button that points to the same directory structure as the
Add Drawing Files button, and organise the output also so that it is meaningful data. Can we
also do another button that just runs an xAI and output exactly the organised, structured xAI
output."

The chain: the page's two buttons post the Drawings list to /api/estimate/pack-extract; the
service stages the files exactly as an estimate does and queues a run of its own job type,
handed only to a runner that says it can run one; the runner runs src/pack_extract.py instead
of main.py and files exactly the outputs it names.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "runner"))

import pack_extract as pe  # noqa: E402

PAGE = ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html"


def _extract():
    """12678-01-GA's shape: a shared rib (12 under 101SA x6, 4 under 102SA x2, 16 in the
    product), per-instance edges for 05M, a hollow base, an unreadable file, a drawing table."""
    return {"schema": "sw_native_extract.v4", "_manifest": {"solidworks_version": "2024"},
            "records": [
        {"title": "12678-01-GA", "doctype": 2, "assembly_part_number": "12678-01-GA",
         "bom": [{"part_number": "12678-01-06M", "qty": 16},
                 {"part_number": "12678-01-101SA", "qty": 6},
                 {"part_number": "12678-01-102SA", "qty": 2},
                 {"part_number": "12678-01-05M", "qty": 6}],
         "assembly_edges": [{"parent": "", "child": "12678-01-101SA", "qty": 6},
                            {"parent": "", "child": "12678-01-102SA", "qty": 2}]},
        {"title": "12678-01-101SA", "doctype": 2, "assembly_part_number": "12678-01-101SA",
         "assembly_edges": [{"parent": "12678-01-101SA", "child": "12678-01-06M", "qty": 12}]
         + [{"parent": "12678-01-101SA", "child": "12678-01-05M", "qty": 1}] * 6},
        {"title": "12678-01-102SA", "doctype": 2, "assembly_part_number": "12678-01-102SA",
         "assembly_edges": [{"parent": "12678-01-102SA", "child": "12678-01-06M", "qty": 4}]},
        {"title": "12678-01-06M", "doctype": 1, "custom_properties": {"Description": "RIB"},
         "route_signals": {"material": "Plain Carbon Steel", "thickness_mm": 2.0,
                           "bbox_mm": [2, 42, 90], "notes": ["REJECTED cut-list flat 1x1mm"]}},
        {"title": "12678-01-01J", "doctype": 1, "route_signals": {
            "material": "MDF", "bbox_mm": [552, 125, 370],
            "volume_mm3": 7825320.0, "surface_area_mm2": 987056.0}},
        {"title": "PLINTH FITTING", "doctype": 1, "errors": ["native extract failed"]},
        {"title": "12678-01-GA", "doctype": 3,
         "bom": [{"part_number": "12678-01-01J", "description": "BASE", "qty": 1}]},
    ]}


def _table(tables, name):
    header, rows = tables[name]
    return [dict(zip(header, r)) for r in rows]


def test_the_assembly_tree_says_each_per_parent_count_and_its_basis():
    tree = _table(pe.organise_sw(_extract()), "Assembly tree")
    rib = {r["parent"]: r for r in tree if r["child"] == "12678-01-06M"}
    assert rib["12678-01-101SA"]["per-parent count (derived)"] == 2
    assert rib["12678-01-102SA"]["per-parent count (derived)"] == 2
    assert "reassembling to exactly 16" in rib["12678-01-101SA"]["basis"]
    bracket = next(r for r in tree if r["child"] == "12678-01-05M")
    assert bracket["per-parent count (derived)"] == 1, "six sightings over six brackets"


def test_the_parts_carry_the_measured_geometry_and_the_failures_are_said():
    t = pe.organise_sw(_extract())
    parts = {r["part"]: r for r in _table(t, "Parts")}
    assert parts["12678-01-06M"]["gauge mm"] == 2.0
    assert parts["12678-01-06M"]["qty in product (model)"] == 16
    assert parts["12678-01-01J"]["volume cm3"] == 7825.3
    assert parts["12678-01-01J"]["envelope mm"] == "552 x 125 x 370"
    assert parts["PLINTH FITTING"]["read issues"] == "native extract failed"
    issues = _table(t, "Read issues")
    assert any(i["file"] == "12678-01-06M" and "REJECTED" in i["detail"] for i in issues)
    assert _table(t, "Drawing BOM tables")[0]["description"] == "BASE"
    summary = dict(t["Summary"][1])
    assert summary["parts the analyser could not measure"] == 1


def test_the_cli_organises_a_saved_extract_into_a_workbook_and_json(tmp_path, capsys):
    ex = tmp_path / "ex.json"
    ex.write_text(json.dumps(_extract()), encoding="utf-8")
    out = tmp_path / "out"
    assert pe.main(["sw", "--from-extract", str(ex), "--out", str(out),
                    "--name", "12678-01-GA"]) == 0
    marker = [ln for ln in capsys.readouterr().out.splitlines()
              if ln.startswith(pe.OUTPUTS_MARKER)][-1]
    written = json.loads(marker.split("=", 1)[1])
    assert [Path(w).name for w in written] == ["12678-01-GA_solidworks_pack.xlsx",
                                               "12678-01-GA_solidworks_pack.json"]
    from openpyxl import load_workbook
    wb = load_workbook(written[0])
    assert wb.sheetnames == ["Summary", "Parts", "Assembly tree", "Product BOM",
                             "Drawing BOM tables", "Custom properties", "Read issues"]
    body = json.loads(Path(written[1]).read_text(encoding="utf-8"))
    assert body["extract"]["schema"] == "sw_native_extract.v4"
    assert "Assembly tree" in body["tables"]


def test_the_xai_read_is_written_exactly_and_laid_out(tmp_path, monkeypatch):
    pdf = tmp_path / "12684-02-GA.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    answer = {"found": True, "top_assembly": "12684-02-GA",
              "bom": [{"item": 1, "part_number": "12684-02-101SA", "qty": 33},
                      {"item": 2, "part_number": "12684-02-102SA", "qty": 1}],
              "parts": [{"part_number": "12684-02-M04", "material": "MILD STEEL",
                         "thickness_mm": 3}],
              "_coverage": {"documents": 1, "pages": 9, "not_read": []},
              "_raw_response": "the model's own words"}
    import llm_full_extract as lfe
    monkeypatch.setattr(lfe, "extract_full_pack", lambda paths, **k: dict(answer))
    written = pe.xai_pack([str(tmp_path)], tmp_path / "out", "12684-02-GA")
    got = json.loads(written[0].read_text(encoding="utf-8"))
    assert got == answer, "the JSON is the read exactly as returned"
    tables = pe.organise_xai(answer)
    assert _table(tables, "Bom")[0]["qty"] == 33
    assert _table(tables, "Parts")[0]["thickness_mm"] == 3
    assert ["coverage.pages", 9] in tables["Summary"][1]
    assert not any("raw" in r[0] for r in tables["Summary"][1]), "raw text stays in the JSON"


def test_the_xai_extract_refuses_a_pack_with_no_pdf(tmp_path):
    with pytest.raises(SystemExit):
        pe.xai_pack([str(tmp_path)], tmp_path / "out", "x")


def test_the_runner_runs_the_extract_never_main_and_files_what_it_names(tmp_path):
    import sdi_estimate_runner as runner
    job = {"job_type": "sw_extract", "job_folder": str(tmp_path / "pack"),
           "output_path": str(tmp_path / "out"), "drawing_number": "12678-01-GA"}
    cmd = runner.pack_extract_command(Path("/engine"), Path("/py"), job)
    assert cmd[2].endswith("pack_extract.py") and cmd[3] == "sw"
    assert not any(c.endswith("main.py") for c in cmd)
    assert cmd[cmd.index("--name") + 1] == "12678-01-GA"
    f = tmp_path / "a.xlsx"
    f.write_bytes(b"x")
    log = ["noise",
           "PACK_EXTRACT_OUTPUTS=" + json.dumps([str(f), str(tmp_path / "missing.json")])]
    assert runner.pack_extract_outputs(log) == [{"name": "a.xlsx", "path": str(f)}]
    assert set(runner.RUNNER_CAPABILITIES) == {"sw_extract", "xai_extract"}
    src = (ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
    # Sent through runner_capabilities() since D-703, which adds "no_models" only to a
    # runner that can read no models; the pack-extract types are always in it.
    assert '"capabilities": runner_capabilities()' in src
    assert {"sw_extract", "xai_extract"} <= set(runner.runner_capabilities())


def test_the_page_has_both_buttons_on_the_drawings_list():
    page = PAGE.read_text(encoding="utf-8")
    assert 'id="pxSw"' in page and 'id="pxXai"' in page
    assert "SolidWorks pack extract" in page and "xAI extract" in page
    assert '"/api/estimate/pack-extract"' in page
    i = page.index("async function runPackExtract")
    body = page[i:i + 2500]
    assert "drawings.find(d => d.is_dir)" in body and "drawings.filter(d => !d.is_dir)" in body


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
             "self_running_switch", "estimate_email", "staging", "estimate_history")
    saved = {n: sys.modules.pop(n) for n in clash if n in sys.modules}
    backend = str(ROOT / "sdi-intelligence-backend")
    sys.path.insert(0, backend)
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
        sys.path.remove(backend)
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def _pack(share):
    pack = share / "M&S" / "12678-01-GA"
    pack.mkdir(parents=True)
    (pack / "12678-01-GA.SLDASM").write_bytes(b"model")
    (pack / "12678-01-GA.pdf").write_bytes(b"%PDF-1.4")
    return pack


def test_an_extract_is_queued_and_only_a_capable_runner_takes_it(client):
    tc, er, share = client
    pack = _pack(share)
    old = {"runner_id": "laptop", "hostname": "SDI-LAPTOP", "process": "1", "build": "x"}
    tc.post("/api/estimate/runner/claim", json=old)          # an older runner connects
    r = tc.post("/api/estimate/pack-extract", json={
        "kind": "sw", "client": "M&S", "drawing_number": "12678-01-GA",
        "job_folder": str(pack)})
    assert r.status_code == 503 and "restart it" in r.json()["detail"]
    tc.post("/api/estimate/runner/claim", json={**old, "capabilities": ["sw_extract",
                                                                       "xai_extract"]})
    # The capable runner was handed nothing yet (nothing queued); now queue it.
    r = tc.post("/api/estimate/pack-extract", json={
        "kind": "sw", "client": "M&S", "drawing_number": "12678-01-GA",
        "job_folder": str(pack)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_type"] == "sw_extract"
    assert body["output_path"].endswith("(SolidWorks pack extract)")
    staged = Path(er._RUNS[body["run_id"]].job_folder)
    assert (staged / "12678-01-GA.SLDASM").is_file(), "staged exactly as an estimate is"
    # An older runner is never handed it.
    none = tc.post("/api/estimate/runner/claim", json=old).json()
    assert none["run"] is None and "restarted on the current build" in none["reason"]
    got = tc.post("/api/estimate/runner/claim",
                  json={**old, "capabilities": ["sw_extract", "xai_extract"]}).json()
    assert got["run"]["job_type"] == "sw_extract"
    assert got["run"]["run_id"] == body["run_id"]


def test_an_extract_without_the_files_its_reader_needs_is_refused(client):
    tc, er, share = client
    pack = _pack(share)
    tc.post("/api/estimate/runner/claim", json={"runner_id": "laptop", "capabilities":
                                                ["sw_extract", "xai_extract"]})
    r = tc.post("/api/estimate/pack-extract", json={
        "kind": "xai", "client": "M&S", "drawing_number": "12678-01-GA",
        "files": [str(pack / "12678-01-GA.SLDASM")]})
    assert r.status_code == 400 and "PDF" in r.json()["detail"]
    r = tc.post("/api/estimate/pack-extract", json={
        "kind": "nope", "client": "M&S", "drawing_number": "x", "job_folder": str(pack)})
    assert r.status_code == 400
    r = tc.post("/api/estimate/pack-extract", json={
        "kind": "sw", "client": "M&S", "drawing_number": "x", "job_folder": "/etc"})
    assert r.status_code == 403
