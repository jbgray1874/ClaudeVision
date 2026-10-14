"""POST /api/estimate/llm (D-526): a prompt and an image in, a queued LLM run out — the
partner endpoint (Muhammad's portal). The full /api/estimate wants file paths this service
can already see; a remote caller has none, so this one takes the image as an upload, files
the prompt as the enquiry brief, and queues the same LLM-only run the estimating page
queues. GET /{run_id}/summary reduces a run to what a partner page renders: the figure, the
caveats, and each deliverable as a download URL — never a disk path."""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PNG = (b"\x89PNG\r\n\x1a\n" + b"0" * 64)


@pytest.fixture(scope="module")
def harness():
    pytest.importorskip("multipart", reason="python-multipart not installed")
    pytest.importorskip("fastapi", reason="fastapi not installed")
    out = tempfile.mkdtemp()
    os.environ.setdefault("SDI_ESTIMATE_OUTPUT_ROOT", out)
    os.environ.setdefault("SDI_FILE_ROOTS", out)
    backend_dir = os.path.join(_REPO, "sdi-intelligence-backend")
    # Same isolation as test_estimate_override_endpoint: the backend's `config` must not be
    # the engine's already-imported src/config.
    _clash = ("config", "estimate_routes", "log_filters", "hr_routes")
    saved = {n: sys.modules.pop(n) for n in _clash if n in sys.modules}
    sys.path.insert(0, backend_dir)
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import estimate_routes as _er
        app = FastAPI()
        app.include_router(_er.router)
        tc = TestClient(app)
        key = getattr(_er.config, "API_KEY", "") or ""
        headers = {"X-SDI-Key": key} if key else {}
        yield tc, _er, headers
    finally:
        sys.path.remove(backend_dir)
        for n in _clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_a_prompt_and_an_image_queue_an_llm_run(harness, monkeypatch):
    tc, _er, headers = harness
    seen = {}

    def _fake_start(req, x_sdi_key=None):
        seen["req"] = req
        return {"run_id": "r-test-1", "status": "queued"}

    monkeypatch.setattr(_er, "start", _fake_start)
    r = tc.post("/api/estimate/llm", headers=headers,
                data={"prompt": "M&S tote trolley, mild steel frame, 49 kg stated",
                      "client": "M&S", "reference": "0356456",
                      "quantities": "1, 25, 50"},
                files={"image": ("trolley.png", _PNG, "image/png")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"] == "r-test-1"
    assert body["poll"] == "/api/estimate/r-test-1"
    assert body["summary"] == "/api/estimate/r-test-1/summary"
    req = seen["req"]
    assert req.method == "llm"
    assert req.enquiry_brief.startswith("M&S tote trolley")
    assert req.units == 1 and req.quantity_breaks == [25, 50]
    assert req.drawing_number == "0356456" and req.client == "M&S"
    assert req.files and req.files[0].endswith(".png")


def test_the_gate_refuses_what_cannot_be_estimated(harness, monkeypatch):
    tc, _er, headers = harness
    monkeypatch.setattr(_er, "start", lambda req, x_sdi_key=None: {"run_id": "x"})
    # a few words is not a brief
    r = tc.post("/api/estimate/llm", headers=headers, data={"prompt": "a box"},
                files={"image": ("a.png", _PNG, "image/png")})
    assert r.status_code == 400 and "brief" in r.text
    # a spreadsheet is not an image the read accepts
    r = tc.post("/api/estimate/llm", headers=headers,
                data={"prompt": "M&S tote trolley, mild steel frame"},
                files={"image": ("sheet.xlsx", b"zz", "application/octet-stream")})
    assert r.status_code == 400
    # no image at all
    r = tc.post("/api/estimate/llm", headers=headers,
                data={"prompt": "M&S tote trolley, mild steel frame"})
    assert r.status_code in (400, 422)


def test_the_summary_serves_download_urls_never_disk_paths(harness):
    tc, _er, headers = harness
    run = _er.Run(run_id="r-sum-1", client="M&S", drawing_number="0356456", units=1,
                  job_folder="", output_path="")
    run.status = "done"
    run.engine_price_gbp = 123.45
    run.deliverables = [
        {"name": "0356456_20261014_covering_email.html", "path": "C:/x/cover.html"},
        {"name": "0356456_20261014.xlsx", "path": "C:/x/book.xlsx"},
        {"name": "0356456_report.html", "path": "C:/x/report.html"},
    ]
    with _er._LOCK:
        _er._RUNS["r-sum-1"] = run
    try:
        r = tc.get("/api/estimate/r-sum-1/summary", headers=headers)
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["unit_cost_gbp"] == 123.45 and s["status"] == "done"
        assert s["summary_html"].endswith("covering_email.html")
        assert s["workbook_xlsx"].endswith(".xlsx")
        assert s["report_html"].endswith("report.html")
        assert all(d["download"].startswith("/api/estimate/r-sum-1/deliverables/")
                   for d in s["deliverables"])
        assert "C:/" not in r.text, "disk paths never leave the service"
        assert "not a quotation" in s["caution"] or "not an" in s["caution"]
        assert s["provisional"] is True
    finally:
        with _er._LOCK:
            _er._RUNS.pop("r-sum-1", None)
