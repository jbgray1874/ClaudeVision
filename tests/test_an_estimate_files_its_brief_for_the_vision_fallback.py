"""An estimate files its enquiry brief, so the vision fallback can read it (D-598y).

A pack whose drawings no reader can read (lettering printed as outlines, or a scan) is priced
on an engine run from the vision read (D-598g), and that read takes the brief. The service
filed the brief only on LLM-only runs, and the estimate button never sent it, so a customer's
change to the drawing could not reach an estimate at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
    encoding="utf-8")
sys.path.insert(0, str(ROOT / "src"))


def test_the_service_files_the_brief_on_every_method():
    assert "_brief_status = _file_enquiry_brief(run, job, req.enquiry_brief)\n" in ROUTES
    assert 'if run.llm_only else "not_an_llm_read")' not in ROUTES


def test_the_estimate_button_sends_the_brief_box():
    engine = PAGE[PAGE.index("runBtn.onclick"):PAGE.index('api("/api/estimate",{method:"POST"')]
    assert 'enquiry_brief: (document.getElementById("enquiryBrief").value || "").trim() || null' \
        in engine


def test_the_box_no_longer_says_llm_read_only():
    label = PAGE[PAGE.index('<label class="note" for="enquiryBrief"'):PAGE.index('id="enquiryBrief" rows')]
    assert "LLM read only" not in label
    assert "no reader can read" in label


def test_the_fallback_reads_a_brief_filed_in_the_job_folder(tmp_path):
    import concept_scan
    (tmp_path / concept_scan.BRIEF_FILENAME).write_text("Customer: Example Ltd. 1 unit.\n",
                                                       encoding="utf-8")
    text, where = concept_scan.find_brief([None, tmp_path])
    assert text.startswith("Customer: Example Ltd")
    assert where.endswith(concept_scan.BRIEF_FILENAME)


# ── D-599a, SCRUM-107: a declared reference document rides an estimate too ─────────────────

def test_the_service_takes_a_reference_declaration_on_every_method():
    assert "Reference/standards documents ride on the LLM read method." not in ROUTES
    assert 'if _ref_docs and method != "llm":' not in ROUTES


def test_the_estimate_button_sends_the_ticked_reference_documents():
    engine = PAGE[PAGE.index("runBtn.onclick"):PAGE.index('api("/api/estimate",{method:"POST"')]
    assert "reference_documents: refDocs.size ? [...refDocs] : null" in engine


def test_the_engine_holds_a_declared_file_out_of_the_readers_on_any_run():
    scan = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    i = scan.index("_ref_names = set(_cs_ref.reference_documents_declared([job_folder]))")
    held = scan[i:i + 900]
    assert "reference_pdfs, pdfs = _held, _product_pdfs" in held
    assert "SDI_LLM_ONLY" not in held[:held.index("reference_pdfs, pdfs")]
