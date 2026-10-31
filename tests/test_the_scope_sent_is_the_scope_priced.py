"""The scope sent is the scope priced, and the book says whether it was (D-604).

THE HPP 01:12 RUN OF 31 OCT. The main estimator went out as Samsung / TG_Standalone, with no
enquiry brief and no reference document, after a day of agreeing Pixel Inspiration, HPP unit
Design, the Samsung guide as a reference and a customer-only brief. The boxes still held an
earlier job's values, and a reload had cleared the brief and the ticks. The LLM button had
shown a receipt of what it would send since D-479; the main estimator sent whatever was on the
page without a word, and nothing between the page and the book could say what had been meant.

So, end to end: the page shows the scope before it is sent and stops a run whose brief or
references the service did not file; the service keeps the scope as submitted and hands it to
the runner; the runner hands it to the engine; and the book's first page compares what reached
the engine with what was submitted.
"""
from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
    encoding="utf-8")
ROUTES = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")

import run_provenance as rp  # noqa: E402


def _main_button() -> str:
    return PAGE[PAGE.index("runBtn.onclick = async"):PAGE.index("let seen = 0;",
                                                                  PAGE.index("runBtn.onclick = async"))]


# ── the page ─────────────────────────────────────────────────────────────────────────────

def test_the_main_button_shows_the_scope_before_it_sends_it():
    body = _main_button()
    receipt = body.index('confirm("Main SDI estimator.')
    for field in ("CUSTOMER: ", "DRAWING NUMBER: ", "QUANTITY: ", "PRODUCT: ",
                  "REFERENCE/STANDARDS: ", "ENQUIRY BRIEF: ", "DELIVERY: "):
        assert field in body[receipt:receipt + 2000], field
    assert receipt < body.index('api("/api/estimate",{method:"POST"'), "shown before it is sent"


def test_the_main_button_asks_before_running_without_a_brief():
    body = _main_button()
    ask = body.index('confirm("No enquiry brief is typed.')
    assert ask < body.index('api("/api/estimate",{method:"POST"')


def test_the_main_button_stops_a_run_whose_brief_or_references_were_not_filed():
    body = _main_button()
    after = body[body.index("const started = await r.json();"):]
    assert 'started.enquiry_brief !== "filed"' in after
    assert "!Array.isArray(started.reference_documents)" in after
    assert after.count('/abandon", {method:"POST"}') >= 2, "each one stops the run"


# ── the service ──────────────────────────────────────────────────────────────────────────

class _Run:
    client, drawing_number, units = "Pixel Inspiration", "HPP unit Design", 1


def test_the_service_keeps_the_scope_as_submitted():
    import estimate_routes as er
    scope = er.submitted_scope(_Run(), "both", "  Customer brief text  ", "filed",
                               ["Samsung guide.pdf"])
    assert scope == {"client": "Pixel Inspiration", "drawing_number": "HPP unit Design",
                     "units": 1, "method": "both", "brief_chars": 19, "brief_status": "filed",
                     "reference_documents": ["Samsung guide.pdf"]}
    said = er.scope_sentence(scope)
    assert "customer Pixel Inspiration" in said and "drawing HPP unit Design" in said
    assert "brief 19 chars (filed)" in said and "reference documents: Samsung guide.pdf" in said


def test_the_service_records_it_and_hands_it_to_the_runner():
    assert "run.submitted_scope = submitted_scope(run, method, req.enquiry_brief, _brief_status," in ROUTES
    claim = ROUTES[ROUTES.index("def claim("):ROUTES.index("def _file_enquiry_brief(")]
    assert '"submitted_scope": dict(run.submitted_scope),' in claim
    assert '"submitted_scope": dict(self.submitted_scope),' in ROUTES, "and on the run's status"


def test_the_runner_hands_it_to_the_engine(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools" / "runner"))
    import sdi_estimate_runner as runner
    (tmp_path / "output" / "estimates").mkdir(parents=True)
    (tmp_path / "output" / "json").mkdir(parents=True)
    tpl = tmp_path / "Blank Estimate Sheet  WB 2026.xlsx"
    tpl.write_bytes(b"present is all the runner checks")
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(tpl))
    seen = {}

    class _Done:
        returncode = 0
        stdout = iter(())

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(runner.subprocess, "Popen",
                        lambda *a, **k: (seen.update(k.get("env") or {}), _Done())[1])

    class _Req:
        def post(self, *a, **k):
            class _R:
                @staticmethod
                def raise_for_status():
                    return None
            return _R()

    scope = {"client": "Pixel Inspiration", "brief_chars": 1970,
             "reference_documents": ["Samsung guide.pdf"]}
    job = {"run_id": "r1", "client": "Pixel Inspiration", "units": 1,
           "drawing_number": "HPP unit Design", "job_folder": str(tmp_path),
           "output_path": str(tmp_path / "share"), "submitted_scope": scope}
    runner._execute(_Req(), "http://x/api/estimate", {}, job, tmp_path, Path("python"), "rnr")
    assert json.loads(seen[rp.SUBMITTED_SCOPE_ENV]) == scope


# ── the engine and the book ──────────────────────────────────────────────────────────────

def _job(tmp_path, brief="", refs=()):
    if brief:
        (tmp_path / "ENQUIRY_BRIEF.txt").write_text(brief, encoding="utf-8")
    if refs:
        (tmp_path / "REFERENCE_DOCUMENTS.json").write_text(json.dumps({"files": list(refs)}),
                                                            encoding="utf-8")
    return {"job_folder": str(tmp_path), "customer": "Pixel Inspiration",
            "declared_product": "HPP unit Design", "requested_order_quantity": 1}


def _submit(monkeypatch, **over):
    scope = {"client": "Pixel Inspiration", "drawing_number": "HPP unit Design", "units": 1,
             "method": "both", "brief_chars": 20, "brief_status": "filed",
             "reference_documents": ["Samsung guide.pdf"]}
    scope.update(over)
    monkeypatch.setenv(rp.SUBMITTED_SCOPE_ENV, json.dumps(scope))


def test_a_scope_that_arrived_whole_says_as_submitted(tmp_path, monkeypatch):
    _submit(monkeypatch)
    s = _job(tmp_path, brief="x" * 20, refs=["Samsung guide.pdf"])
    rp.record(s)
    assert rp.scope_mismatches(s) == []
    assert rp.scope_text(s) == ("customer Pixel Inspiration · drawing HPP unit Design · 1 off"
                                " · as submitted")


def test_the_overnight_run_would_have_said_what_was_lost(tmp_path, monkeypatch):
    """Pixel submitted, Samsung received, no brief and no reference in the folder."""
    _submit(monkeypatch)
    s = _job(tmp_path)
    s.update(customer="Samsung", declared_product="TG_Standalone")
    rp.record(s)
    bad = rp.scope_mismatches(s)
    assert "customer submitted as Pixel Inspiration, received as Samsung" in bad
    assert "drawing submitted as HPP unit Design, received as TG_Standalone" in bad
    assert "a brief of 20 characters was submitted and none reached the job folder" in bad
    assert "declared reference not received: Samsung guide.pdf" in bad
    assert "⚠ NOT AS SUBMITTED" in rp.scope_text(s)


def test_a_stale_brief_nobody_submitted_is_named(tmp_path, monkeypatch):
    _submit(monkeypatch, brief_chars=0, reference_documents=[])
    s = _job(tmp_path, brief="left from an earlier run")
    rp.record(s)
    assert any(m.startswith("no brief was submitted, yet one of") for m in rp.scope_mismatches(s))


def test_a_run_with_no_submission_says_so_and_compares_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(rp.SUBMITTED_SCOPE_ENV, raising=False)
    s = _job(tmp_path)
    rp.record(s)
    assert rp.scope_mismatches(s) == []
    assert rp.scope_text(s).endswith("no submission recorded to compare with")


def test_the_scope_row_is_on_the_books_first_page(tmp_path, monkeypatch):
    _submit(monkeypatch)
    s = _job(tmp_path)
    rp.record(s)
    labels = [k for k, _ in rp.facts(s)]
    assert labels[:2] == ["Run ID", "Scope"]
    assert "Scope: customer Pixel Inspiration" in rp.workbook_line(s)


def test_the_saved_record_keeps_the_customer_the_run_was_given():
    main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert 'received_customer=str(summary.get("customer") or ""))' in main
    s = {"run_provenance": {"machine": "M", "received_customer": "Pixel Inspiration",
                            "submitted_scope": {"client": "Samsung"}, "received_scope": {}}}
    assert rp.scope_mismatches(s) == ["customer submitted as Samsung, received as Pixel Inspiration"]
