"""The automated e-mail IS the engine's covering note — written last, and saying what the
record says.

The chain: main.py writes <stem>_covering_email.html (subject in an HTML comment); the runner
files it with the other deliverables; the portal's mail service prefers it as the message body
and attaches the rest, holding the customer quote while the estimate is provisional.

Two things were wrong with that chain on 7332-01. The note was written BEFORE the consistency
checks ran and before the quote and the report existed — so it said PROVISIONAL whatever the
job was (the flag was never passed), and its "Attached:" line named the files that happened
to exist at that moment: the JSON, and not the report. And the service's plain-text
alternative was a tag-strip of the HTML that ran every table cell into the next.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SRC = (ROOT / "src" / "main.py").read_text(encoding="utf-8")


def _load_estimate_email():
    spec = importlib.util.spec_from_file_location(
        "estimate_email_under_test", ROOT / "sdi-intelligence-backend" / "estimate_email.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── written last ──────────────────────────────────────────────────────────────

def test_the_note_is_written_after_the_checks_and_after_the_report():
    noted = SRC.index("from estimate_explained import covering_email as _covering_email")
    checked = SRC.index("_inv = _check_job(_target)")
    reported = SRC.index("from job_report_html import generate_report as _gen_job_report")
    quoted = SRC.index("from client_quote_html import generate_quote_files as _gen_quote")
    assert checked < noted, "the note is written before the consistency checks run"
    assert reported < noted, "the note is written before the report exists"
    assert quoted < noted, "the note is written before the quote exists"


def test_the_note_is_told_whether_the_job_is_provisional():
    i = SRC.index("from estimate_explained import covering_email as _covering_email")
    call = SRC[i:i + 900]
    assert "provisional=_provisional" in call, "the flag defaults to True and is never passed"
    block = SRC[i - 2500:i]
    assert "_rel3.get(\"draft\")" in block and "may_quote_firm" in block, (
        "the flag is not read from the record's release and the checks' verdict")


def test_the_attached_line_names_what_the_service_will_attach():
    i = SRC.index("from estimate_explained import covering_email as _covering_email")
    block = SRC[i - 2500:i]
    for excluded in ('"json"', '"covering_email"', '"quantity_variants"'):
        assert excluded in block, f"{excluded} is listed as attached and it is not"
    assert '_k == "quote" and _provisional' in block, (
        "the quote is named as attached while the service holds it")
    assert '["report"] = str(_rhtml)' in SRC and '["quote"] = str(_qpath)' in SRC, (
        "the report and the quote are never recorded, so the note cannot name them")


def test_the_engine_files_a_plain_text_alternative():
    i = SRC.index("from estimate_explained import covering_email as _covering_email")
    assert '.with_suffix(".txt").write_text(_note["text"]' in SRC[i:i + 1600]


# ── the service reads it ──────────────────────────────────────────────────────

def test_the_service_prefers_the_engines_plain_text(tmp_path):
    em = _load_estimate_email()
    html = tmp_path / "7332-01_20260906_171743_covering_email.html"
    html.write_text("<!-- subject: 7332-01 — SDI Intelligence estimate, PROVISIONAL. -->\n"
                    "<table><tr><td>Material</td><td>£40.89</td></tr></table>",
                    encoding="utf-8")
    (tmp_path / "7332-01_20260906_171743_covering_email.txt").write_text(
        "Material  £40.89\n", encoding="utf-8")
    note = em.engine_note([{"path": str(html)}])
    assert note["subject"].startswith("7332-01 — SDI Intelligence estimate")
    assert note["text"] == "Material  £40.89\n"


def test_the_service_still_reads_a_note_with_no_text_sibling(tmp_path):
    em = _load_estimate_email()
    html = tmp_path / "x_covering_email.html"
    html.write_text("<!-- subject: s -->\n<p>hello</p>", encoding="utf-8")
    note = em.engine_note([{"path": str(html)}])
    assert "hello" in note["text"]


# ── the note itself, when the job is not provisional ──────────────────────────

def test_a_firm_note_does_not_say_provisional(tmp_path):
    import pytest
    openpyxl = pytest.importorskip("openpyxl")
    import estimate_explained as ee
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws["D6"] = 6
    ws["C9"] = "Bill of Materials (Per Unit)"
    ws["H9"] = "Part code"
    ws.cell(10, 3, "P/P  FELT PAD")
    ws.cell(10, 8, "P/P")
    ws.cell(10, 10, 0.2)
    ws.cell(10, 11, 4)
    for name in ("AI Material Detail", "AI Price Provenance", "Canonical Route"):
        wb.create_sheet(name)
    xlsx = tmp_path / "j.xlsx"
    wb.save(xlsx)
    jp = tmp_path / "j.json"
    jp.write_text('{"final_estimate": {"totals": {"material_gbp": 0.8, "labour_gbp": 1.0, '
                  '"unit_gbp": 1.8}, "labour_rows": [], "material_rows": []}}',
                  encoding="utf-8")
    note = ee.covering_email(xlsx, jp, deliverables=["j.xlsx"], provisional=False)
    assert "PROVISIONAL" not in note["subject"]
    assert "No customer quote" not in note["text"]
