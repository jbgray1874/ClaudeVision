"""JG, 22 Nov 2026, looking at the wall during the overnight drawing run: "Description not
recorded looks not great". The request carried a job_title for the drop-off folder's name and
the run never kept it, and the drawing pricer never sent one at all, so every card said
"Description not recorded". A run now keeps its title and its tracker row, both batches send
them, and the wall reads them from the run rather than from its log."""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "sdi-intelligence-backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

spec = importlib.util.spec_from_file_location("estimate_wall", ROOT / "sdi-intelligence-backend/estimate_wall.py")
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)


def test_the_wall_reads_the_title_and_row_the_run_kept_without_opening_its_log():
    class Console(list):
        def __iter__(self):
            raise AssertionError("the log was read although the run carries its own title and row")
    r = dict(source="tti", drawing_number="12802-00-GA2", units=6, job_title="PRINTED DISPLAY BOARDS",
             source_row=136, log=Console(["anything"]))
    assert W.display_identity(r) == dict(description="PRINTED DISPLAY BOARDS", source_row=136, units=6)
    assert W._summary(r)["description"] == "PRINTED DISPLAY BOARDS"


def test_a_run_without_them_still_says_so_and_a_bad_row_is_not_a_row():
    r = dict(source="tti", drawing_number="12802-00-GA2", units=6, source_row="row 136", log=[])
    assert W.display_identity(r) == dict(description="", source_row=None, units=6)


def test_the_drawing_pricer_sends_the_sheets_description_and_row():
    src = (ROOT / "src" / "tti_pricer.py").read_text(encoding="utf-8")
    body = src[src.index('body = {"client": args.client, "drawing_number": r["drawing"]'):]
    body = body[:body.index("pack_manifest")]
    assert '"job_title": str(r.get("description") or "").strip()[:240]' in body
    assert '"source_row": int(r["row"])' in body


def test_the_concept_batch_sends_its_row():
    src = (ROOT / "src" / "tti_concept_batch.py").read_text(encoding="utf-8")
    assert "'job_title':item['description'][:180],'source_row':item['row']" in src


@pytest.fixture()
def er(monkeypatch, tmp_path):
    pytest.importorskip("fastapi", reason="fastapi not installed")
    import estimate_routes
    estimate_routes._RUNS.clear()
    estimate_routes._RUNNERS.clear()
    monkeypatch.setattr(estimate_routes, "_other_local_services", lambda port: [])
    monkeypatch.setattr(estimate_routes.staging, "staging_root", lambda: tmp_path / "stage")
    monkeypatch.setattr(estimate_routes, "_within_a_root", lambda p: Path(p))
    monkeypatch.setattr(estimate_routes, "OUTPUT_ROOT", tmp_path / "out")
    monkeypatch.setattr(estimate_routes.config, "API_KEY", "portal-key", raising=False)
    estimate_routes._RUNNERS["LAPTOP-abc"] = estimate_routes.Runner(runner_id="LAPTOP-abc", hostname="LAPTOP")
    drop = tmp_path / "dropoff"
    drop.mkdir()
    monkeypatch.setenv("SDI_PACK_DROPOFF_DIR", str(drop))
    return estimate_routes


def test_a_queued_run_keeps_its_title_and_row_in_its_json(er, tmp_path):
    src = tmp_path / "share" / "TTI" / "12802-00-GA2"
    src.mkdir(parents=True)
    (src / "12802-00-GA2_revA.pdf").write_bytes(b"%PDF-1.4 the drawing")
    out = er.start(er.EstimateRequest(
        client="TTI", drawing_number="12802-00-GA2", units=6, job_folder=str(src),
        job_title="PRINTED DISPLAY BOARDS", source_row=136, source="tti",
        pack_manifest={"status": "verified", "references_read": True, "missing": []}),
        x_sdi_key="portal-key")
    run = er._RUNS[out["run_id"]]
    j = json.loads(json.dumps(run.as_json()))
    assert j["job_title"] == "PRINTED DISPLAY BOARDS" and j["source_row"] == 136
    assert W._summary(j)["description"] == "PRINTED DISPLAY BOARDS"
    assert W._summary(j)["source_row"] == 136
