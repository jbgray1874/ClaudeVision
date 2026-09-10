r"""
test_the_pack_says_more_than_we_read.py

"WHEN I OPEN UP DXF FILES THEY CONTAIN ONLY IMAGES."

That is what the viewer shows. It is not what the file holds. Every flat export in SDI's own
corpus is vector geometry — 117620202M_0.9mm_MS_revA.DXF is 55 LINEs, 2 CIRCLEs and 2 ARCs
across two layers, SLD-0 carrying the profile and BENDLINES carrying the folds. Its blank
measures 1009.49 x 363.91 and its holes are Ø5.0, and not one of those is a printed
dimension: a circle carries its centre and radius, so the circle IS its diameter. The GA
export beside it holds 64 MTEXT and 20 DIMENSION entities and a stated weight of 384g.

So the question worth asking is not what the files contain. It is which of it we READ, which
part we attached it to, and whether it reached the price — because three different failures
look identical from outside the engine:

    the file did not have it          nothing anyone can do
    we did not read it                a reader to fix
    we read it and dropped it later   a pipeline join to fix, and the worst of the three,
                                      because the evidence was in the building all along

source_drawing_data.xlsx exists to tell those apart. It prices nothing and decides nothing.
These tests cover the two ways an audit fails: by being wrong about what happened, and by
breaking the job it was supposed to be auditing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from source_drawing_data import (                                        # noqa: E402
    SHEETS,
    build_tables,
    write_source_drawing_data,
)


def _summary() -> dict:
    return {
        "pages": [{"page_number": 1, "source_pdf_name": "0359342_REV_4.pdf"},
                  {"page_number": 2, "source_pdf_name": "0359342_REV_4.pdf"}],
        "document_analysis": {
            "bom_rows": [{"part_number": "MBY432", "description": "Prong", "quantity": 56,
                          "material_text": "Steel, Mild Wire Ø8mm", "source_page": 24}],
            "pack_issues": [{"code": "cad_not_read",
                             "message": "2 CAD files in the job folder were not read",
                             "files": ["7332-01-GA_revK.dwg"]}]},
        "estimate_summary": {
            "part_estimates": [{
                "part_number": "MBY432", "normalized_material": "MILD_STEEL",
                "quantity": 56, "wire_gauge_mm": 8.0, "wire_length_mm": 219.6,
                "review_flags": ["MBY432 is round stock and its LENGTH is not known"],
                "_displaced": {"blank_length_mm": [
                    {"value": 400.0, "source": "inference", "applied": False,
                     "displaced_by": "estimator_read_drawing"}]}}],
            "canonical_route": {"decisions": [
                {"operation": "laser_cutting", "part_number": "MBY432",
                 "status": "not_applicable",
                 "reason": "not physically possible on stock form 'wire'"}]}},
    }


def test_every_sheet_the_audit_promises_is_written(tmp_path: Path):
    path = write_source_drawing_data(_summary(), tmp_path, job="0359342")
    assert path is not None and path.name == "0359342_source_drawing_data.xlsx"
    import openpyxl
    assert openpyxl.load_workbook(path).sheetnames == list(SHEETS)


def test_a_file_nothing_read_is_listed_as_not_read(tmp_path: Path):
    """The most important row in the workbook. A CAD file nobody opened is invisible in every
    other deliverable — the estimate simply prices what it has."""
    files = build_tables(_summary())["Files"]
    unread = [f for f in files if f["read"] == "NO"]
    assert unread and "7332-01-GA_revK.dwg" in unread[0]["file"]


def test_a_value_that_lost_to_a_stronger_source_says_so_rather_than_vanishing():
    """Read, attached to the right part, then beaten — that is CORRECT behaviour and the
    audit must show it as such. Otherwise every displaced reading looks like a miss and the
    real misses are lost in the noise."""
    facts = build_tables(_summary())["Facts"]
    lost = [f for f in facts if f["field"] == "blank_length_mm" and f["value"] == 400.0]
    assert lost, "a displaced reading must appear, not disappear"
    assert "beaten by a stronger source" in lost[0]["outcome"]
    assert "estimator_read_drawing" in lost[0]["outcome"], "and name what beat it"


def test_the_figures_the_price_rests_on_are_marked_used():
    facts = build_tables(_summary())["Facts"]
    used = {f["field"] for f in facts if f["outcome"].startswith("USED")}
    assert {"wire_gauge_mm", "wire_length_mm", "quantity"} <= used


def test_the_bom_row_carries_its_material_as_printed():
    """The cell as the drawing office typed it, not the normalised code — the audit is about
    what was on the page."""
    rows = build_tables(_summary())["BOM rows"]
    assert rows[0]["material_as_printed"] == "Steel, Mild Wire Ø8mm"
    assert rows[0]["quantity"] == 56


def test_a_refused_operation_appears_with_its_reason():
    ops = build_tables(_summary())["Operations"]
    assert ops[0]["status"] == "not_applicable"
    assert "stock form 'wire'" in ops[0]["reason"]


def test_an_unresolved_datum_reaches_the_not_extracted_sheet():
    rows = build_tables(_summary())["Not extracted"]
    assert any("LENGTH is not known" in r["detail"] for r in rows)
    assert any("not read" in r["detail"] for r in rows)


def test_an_empty_job_still_produces_a_readable_workbook(tmp_path: Path):
    """An audit that crashes on a thin job is an audit nobody can rely on."""
    path = write_source_drawing_data({}, tmp_path, job="empty")
    assert path is not None
    import openpyxl
    book = openpyxl.load_workbook(path)
    assert book.sheetnames == list(SHEETS)
    assert "No files recorded" in str(book["Files"].cell(row=1, column=1).value)


@pytest.mark.parametrize("broken", [None, [], "not a summary", {"pages": "wrong type"}])
def test_a_malformed_summary_never_breaks_the_run(broken, tmp_path: Path):
    """It audits the job; it must never be the reason the job fails."""
    try:
        write_source_drawing_data(broken if isinstance(broken, dict) else {}, tmp_path)
    except Exception as err:                                             # noqa: BLE001
        pytest.fail(f"the audit raised into the run: {type(err).__name__}: {err}")


def test_the_run_writes_it_beside_the_estimate():
    """Wired into main so it is produced every run, not on request — the value of an audit
    nobody remembers to ask for is zero."""
    source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "write_source_drawing_data(" in source
    assert 'OUTPUT_DIR / "estimates"' in source
    assert "source_drawing_data" in source
