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


# ── the file itself, opened independently of the reader ───────────────────────────────

UPLOADS = Path("/root/.claude/uploads/09b98f42-bd9e-534a-8993-f8eb3975326c")
FLAT = UPLOADS / "f124e9e8-117620202M_0.9mm_MS_revA.DXF"
GA = UPLOADS / "77e80e31-0355255__A4_Table_Top_Graphic_Holder__10975_REV_B.DXF"
real_dxf = pytest.mark.skipif(not FLAT.exists(), reason="corpus DXF not present here")


@real_dxf
def test_a_flat_export_measures_its_own_blank_holes_and_bends():
    """SDI's own 117620202M, measured from its entities. None of these is a printed
    dimension: a circle carries its centre and radius, so the circle IS its diameter."""
    from dxf_probe import probe_dxf
    probe = probe_dxf(FLAT)
    assert probe["readable"] and probe["looks_like_flat_export"]
    assert probe["blank_length_mm"] == pytest.approx(1009.49, abs=0.05)
    assert probe["blank_width_mm"] == pytest.approx(363.91, abs=0.05)
    assert probe["hole_diameters_mm"] == [5.0]
    assert probe["hole_count"] == 2
    assert probe["bend_line_count"] == 5
    assert "BENDLINES" in probe["layers"]
    assert probe["entities_are_raster_only"] is False


@real_dxf
def test_a_drawing_export_reports_a_sheet_extent_not_a_blank():
    """THE TRAP THAT BEAT AN EARLIER ATTEMPT OF MINE. Measuring vector extents on a GA
    returns the drawing BORDER — 10975_REV_B comes out 1680.00 x 1074.49, which is no part
    at all. A previous prototype of mine failed exactly here: it measured the frame on every
    page and returned one identical aspect ratio for six different parts.

    The tell is what a flat does NOT have: no dimension entities, no title-block text, no
    leaders or block inserts.
    """
    from dxf_probe import probe_dxf
    probe = probe_dxf(GA)
    assert probe["looks_like_flat_export"] is False
    assert probe["blank_length_mm"] is None, "a drawing must not offer a blank"
    assert probe["extent_length_mm"] == pytest.approx(1680.0, abs=0.05)
    assert "drawing export" in probe["extent_is"]
    assert probe["dimension_entities"] == 20


@real_dxf
def test_the_audit_puts_the_file_beside_the_engine_and_names_what_is_missing():
    """available in the file -> extracted -> assigned to a part -> used in costing.

    The other sheets can only report what the pipeline recorded, which blinds them to the
    failure that matters most: a fact that was in the file and reached nothing.
    """
    from source_drawing_data import build_tables
    summary = {"estimate_summary": {"part_estimates": [{
        "part_number": "117620202M",
        "blank_length_mm": 1009.49, "blank_width_mm": 363.91,
        "geometry_rollup": {"hole_count": 2},
    }]}}
    rows = build_tables(summary, [FLAT])["DXF file vs engine"]
    by_fact = {r["fact"]: r for r in rows}

    assert by_fact["blank length mm"]["agrees"] == "yes"
    assert by_fact["hole count"]["agrees"] == "yes"
    assert by_fact["blank length mm"]["part"] == "117620202M", "matched to its own part"

    # measurable in the file, nothing on the record — the row the audit exists to produce
    assert by_fact["cut length mm"]["agrees"] == "NOT EXTRACTED"
    assert by_fact["cut length mm"]["in_the_file"] > 0


@real_dxf
def test_a_disagreement_is_shown_rather_than_judged():
    """A mismatch is not automatically an engine defect — a part legitimately sized from a
    model can differ from its flat. The audit guarantees the difference is VISIBLE; it does
    not decide who is right."""
    from source_drawing_data import build_tables
    summary = {"estimate_summary": {"part_estimates": [{
        "part_number": "117620202M",
        "manufacturing_features": {"bend_count": 4},      # file says 5 bend lines
    }]}}
    rows = {r["fact"]: r for r in build_tables(summary, [FLAT])["DXF file vs engine"]}
    assert rows["bend lines"]["in_the_file"] == 5
    assert rows["bend lines"]["engine_has"] == 4
    assert rows["bend lines"]["agrees"] == "NO"


def test_a_raster_only_dxf_is_not_reported_as_a_reader_failure(tmp_path: Path):
    """A DXF can legitimately hold nothing but an image, and no API will reveal geometry
    that is not there. "We could not read it" and "there is nothing to read" must not look
    the same, or the fix gets aimed at the wrong thing."""
    from dxf_probe import probe_dxf
    path = tmp_path / "scan.dxf"
    path.write_text("0\nSECTION\n2\nENTITIES\n0\nIMAGE\n8\n0\n0\nENDSEC\n0\nEOF\n",
                    encoding="latin-1")
    probe = probe_dxf(path)
    assert probe["readable"] is True
    assert probe["entities_are_raster_only"] is True
    assert probe["blank_length_mm"] is None

    from source_drawing_data import build_tables
    rows = build_tables({}, [path])["DXF file vs engine"]
    assert rows and "raster image only" in rows[0]["in_the_file"]
    assert "no geometry in this file" in rows[0]["note"]


def test_the_probe_never_raises_on_rubbish(tmp_path: Path):
    from dxf_probe import probe_dxf, probe_many
    bad = tmp_path / "not.dxf"
    bad.write_bytes(b"\x00\x01\x02 not a dxf at all")
    assert probe_dxf(bad)["blank_length_mm"] is None
    assert probe_dxf(tmp_path / "missing.dxf")["readable"] is False
    assert len(probe_many([bad, tmp_path / "missing.dxf"])) == 2


def test_the_run_opens_the_job_folders_dxfs_itself():
    """Independence is the point: a reader cannot be checked against its own output."""
    source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "dxf_paths=_sdd_dxfs" in source
    assert '.dxf' in source


def test_a_synthetic_flat_is_measured_the_same_way(tmp_path: Path):
    """The corpus DXFs are not in the repo, so the assertions above skip on a fresh checkout.
    This one builds a flat from scratch — a 100 x 50 rectangle, one Ø10 hole, one bend line —
    so the measuring itself is covered wherever the suite runs."""
    from dxf_probe import probe_dxf
    parts = ["0", "SECTION", "2", "ENTITIES"]
    for x1, y1, x2, y2 in ((0, 0, 100, 0), (100, 0, 100, 50),
                           (100, 50, 0, 50), (0, 50, 0, 0)):
        parts += ["0", "LINE", "8", "SLD-0",
                  "10", str(x1), "20", str(y1), "11", str(x2), "21", str(y2)]
    parts += ["0", "LINE", "8", "BENDLINES",
              "10", "50", "20", "0", "11", "50", "21", "50"]
    parts += ["0", "CIRCLE", "8", "SLD-0", "10", "25", "20", "25", "40", "5"]
    parts += ["0", "ENDSEC", "0", "EOF"]
    path = tmp_path / "synthetic_flat.dxf"
    path.write_text("\n".join(parts) + "\n", encoding="latin-1")

    probe = probe_dxf(path)
    assert probe["looks_like_flat_export"] is True
    assert probe["blank_length_mm"] == 100.0
    assert probe["blank_width_mm"] == 50.0
    assert probe["hole_diameters_mm"] == [10.0]
    assert probe["bend_line_count"] == 1, "the bend line must not be counted as profile"
    # perimeter 300 + the Ø10 circle
    assert probe["cut_length_mm"] == pytest.approx(300 + 3.14159 * 10, abs=0.1)
