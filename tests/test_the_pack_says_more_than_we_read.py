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


# ── the file itself, read with ezdxf, independently of the production readers ──────────
#
# The first version of the probe counted group codes by hand and review found four generic
# cases where it was simply wrong. An audit that reports an engine defect when the PROBE is
# wrong is worse than no audit: it sends people to fix things that are not broken. Each of
# those four is a test here, with the wrong answer recorded beside the right one.

import ezdxf                                                             # noqa: E402
from dxf_probe import probe_dxf                                          # noqa: E402

MM, INCH, UNITLESS = 4, 1, 0


def _dxf(tmp_path: Path, name: str, build, insunits: int = MM) -> Path:
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = insunits
    build(doc.modelspace())
    path = tmp_path / name
    doc.saveas(path)
    return path


def test_a_closed_polyline_includes_its_closing_segment(tmp_path: Path):
    """A 10 x 10 closed square is 40 mm round, not 30. The handwritten version walked the
    vertices and never joined the last back to the first."""
    path = _dxf(tmp_path, "square.dxf",
                lambda m: m.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True))
    assert probe_dxf(path)["outline_length"] == pytest.approx(40.0, abs=0.01)


def test_an_arc_covers_its_own_sweep_not_the_whole_circle(tmp_path: Path):
    """A radius-10 arc from 0 to 90 degrees spans 10 x 10. The handwritten version used the
    full circle's bounds and made it 20 x 20 — doubling a blank in both directions."""
    path = _dxf(tmp_path, "arc.dxf", lambda m: m.add_arc((0, 0), 10, 0, 90))
    probe = probe_dxf(path)
    assert probe["extent_length"] == pytest.approx(10.0, abs=0.01)
    assert probe["extent_width"] == pytest.approx(10.0, abs=0.01)


def test_a_circle_is_reported_as_a_circle_and_never_as_a_hole(tmp_path: Path):
    """A Ø24 disc has ONE circular outline and NO hole. Calling every circle a hole is a
    manufacturing interpretation, and on a disc it is simply false. Which circles are holes
    needs the part's role and the drawing's instructions — the estimator's job, not this."""
    path = _dxf(tmp_path, "disc.dxf", lambda m: m.add_circle((0, 0), 12))
    probe = probe_dxf(path)
    assert probe["circle_count"] == 1
    assert probe["circle_diameters"] == [24.0]
    assert "hole_count" not in probe, "the probe must not publish an interpretation"


def test_geometry_inside_an_inserted_block_is_seen(tmp_path: Path):
    """A file whose profile lives in a block looked EMPTY, and one holding an image beside
    such a block was called raster-only — sending the fix in exactly the wrong direction."""
    def build(msp):
        block = msp.doc.blocks.new("PROFILE")
        block.add_lwpolyline([(0, 0), (50, 0), (50, 30), (0, 30)], close=True)
        msp.add_blockref("PROFILE", (0, 0))
    probe = probe_dxf(_dxf(tmp_path, "block.dxf", build))
    assert probe["entities_are_raster_only"] is False
    assert probe["extent_length"] == pytest.approx(50.0, abs=0.01)
    assert probe["extent_width"] == pytest.approx(30.0, abs=0.01)


def test_an_inch_drawing_is_converted_and_says_so(tmp_path: Path):
    """The probe labelled everything mm without reading $INSUNITS, so an inch drawing
    produced comparisons that looked like defects and were arithmetic. 10 in is 254 mm."""
    path = _dxf(tmp_path, "inch.dxf",
                lambda m: m.add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True),
                insunits=INCH)
    probe = probe_dxf(path)
    assert probe["units"] == "in" and probe["units_known"] is True
    assert probe["blank_length_mm"] == pytest.approx(254.0, abs=0.01)
    assert probe["blank_width_mm"] == pytest.approx(127.0, abs=0.01)


def test_a_file_that_declares_no_units_publishes_no_blank(tmp_path: Path):
    """A drawing that states nothing is not thereby millimetres."""
    path = _dxf(tmp_path, "unitless.dxf",
                lambda m: m.add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True),
                insunits=UNITLESS)
    probe = probe_dxf(path)
    assert probe["units_known"] is False
    assert probe["blank_length_mm"] is None
    assert "declares no units" in probe["extent_is"]


def test_a_bulged_polyline_is_measured_along_its_curve(tmp_path: Path):
    """The curve maths is ezdxf's. A bulge between two points 10 apart is longer than 10, and
    a straight-line sum would quietly under-report every rolled edge in the corpus."""
    path = _dxf(tmp_path, "bulge.dxf",
                lambda m: m.add_lwpolyline([(0, 0, 0.5), (10, 0, 0)], format="xyb"))
    probe = probe_dxf(path)
    assert probe["outline_length"] > 10.0
    assert probe["outline_length_partial"] is False


def test_duplicate_geometry_is_counted_twice_and_not_silently_merged(tmp_path: Path):
    """Two identical circles are two entities. The probe reports what is there; deciding that
    a duplicate is a drafting error is not its call."""
    def build(msp):
        msp.add_circle((0, 0), 5)
        msp.add_circle((0, 0), 5)
    assert probe_dxf(_dxf(tmp_path, "dupe.dxf", build))["circle_count"] == 2


def test_a_genuinely_raster_only_file_is_still_identified(tmp_path: Path):
    """The case that must survive the block fix: no geometry anywhere, only an image."""
    from dxf_probe import probe_dxf as probe
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = MM
    msp = doc.modelspace()
    image_def = doc.add_image_def(filename="scan.png", size_in_pixel=(100, 100))
    msp.add_image(image_def=image_def, insert=(0, 0), size_in_units=(10, 10))
    path = tmp_path / "raster.dxf"
    doc.saveas(path)
    result = probe(path)
    assert result["entities_are_raster_only"] is True
    assert result["blank_length_mm"] is None


def test_an_unreadable_file_reports_its_error_rather_than_a_measurement(tmp_path: Path):
    bad = tmp_path / "not.dxf"
    bad.write_bytes(b"\x00\x01\x02 not a dxf")
    probe = probe_dxf(bad)
    assert probe["readable"] is False and probe["error"]
    assert probe["blank_length_mm"] is None


# ── what the audit is allowed to claim ────────────────────────────────────────────────

def test_a_circle_count_is_never_scored_against_a_hole_count(tmp_path: Path):
    """An audit that manufactures disagreements is noise. A circle is not a hole and a line
    on a bend layer is not a bend, so both are shown side by side and marked NOT COMPARABLE
    rather than being called a mismatch."""
    from source_drawing_data import build_tables
    path = _dxf(tmp_path, "117620202M.dxf", lambda m: (
        m.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True),
        m.add_circle((20, 20), 2.5)))
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "117620202M", "geometry_rollup": {"hole_count": 1},
         "manufacturing_features": {"bend_count": 3}}]}}
    rows = {r["fact"]: r for r in build_tables(summary, [path])["DXF file vs engine"]}
    assert rows["circles in the file"]["agrees"] == "NOT COMPARABLE"
    assert "not necessarily a hole" in rows["circles in the file"]["note"]


def test_a_missing_field_is_not_claimed_as_never_extracted(tmp_path: Path):
    """This audit inspects a handful of fields. Their absence is NOT proof the engine never
    read or used the value, and the earlier wording said exactly that."""
    from source_drawing_data import build_tables
    path = _dxf(tmp_path, "117620202M.dxf",
                lambda m: m.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True))
    summary = {"estimate_summary": {"part_estimates": [{"part_number": "117620202M"}]}}
    rows = {r["fact"]: r for r in build_tables(summary, [path])["DXF file vs engine"]}
    assert rows["outline length"]["agrees"] == "not in the fields checked"


def test_an_ambiguous_file_to_part_match_is_reported_not_resolved(tmp_path: Path):
    """Attribution IS the audit. A fact credited to the wrong part is worse than one nobody
    credited, because it reads as evidence — so two candidates are declared, not ranked."""
    from source_drawing_data import _match_part
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "1176202"}, {"part_number": "117620202M"}]}}
    part, how, ambiguous = _match_part(summary, "117620202M_0.9mm_MS_revA.DXF")
    assert ambiguous is True and part is None and "ambiguous" in how


def test_the_pipelines_own_association_is_preferred_over_the_filename(tmp_path: Path):
    from source_drawing_data import _match_part
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "OTHER", "dxf_file": "C:/jobs/117620202M_0.9mm_MS_revA.DXF"}]}}
    part, how, ambiguous = _match_part(summary, "117620202M_0.9mm_MS_revA.DXF")
    assert part["part_number"] == "OTHER"
    assert "pipeline's own" in how and ambiguous is False


# ── the same tables, as a page ────────────────────────────────────────────────────────

def test_the_html_is_built_from_the_same_tables_as_the_workbook(tmp_path: Path):
    """Estimating works from the spreadsheet, management reads the page. If they were built
    from separate passes they could disagree about what the pack contained, which is exactly
    the class of problem this whole deliverable exists to expose."""
    from source_drawing_data import (SHEETS, build_tables, write_source_drawing_html)
    summary = _summary()
    page = write_source_drawing_html(summary, tmp_path, job="0359342")
    assert page is not None and page.name == "0359342_source_drawing_data.html"
    html = page.read_text(encoding="utf-8")

    for name in SHEETS:
        assert f"<h2>{name}" in html, f"{name} must appear as a section"
    # every BOM row in the tables reaches the page
    for row in build_tables(summary)["BOM rows"]:
        assert str(row["part_number"]) in html
        assert row["material_as_printed"] in html


def test_the_page_is_self_contained_and_well_formed(tmp_path: Path):
    """It has to render in the portal and survive being e-mailed. No external CSS, no fonts
    to fetch, no scripts."""
    import html.parser
    from source_drawing_data import write_source_drawing_html
    text = write_source_drawing_html(_summary(), tmp_path, job="j").read_text(encoding="utf-8")
    assert "<script" not in text.lower()
    assert "http://" not in text and "https://" not in text
    assert "<style>" in text

    class Check(html.parser.HTMLParser):
        VOID = {"meta", "br", "img", "input", "link", "hr"}

        def __init__(self):
            super().__init__()
            self.stack, self.bad = [], []

        def handle_starttag(self, tag, attrs):
            if tag not in self.VOID:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()
            else:
                self.bad.append(tag)

    check = Check()
    check.feed(text)
    assert not check.bad and not check.stack, f"unbalanced: {check.bad or check.stack}"


def test_a_file_nothing_read_is_visible_on_the_page(tmp_path: Path):
    """The row management should see first."""
    from source_drawing_data import write_source_drawing_html
    text = write_source_drawing_html(_summary(), tmp_path, job="j").read_text(encoding="utf-8")
    assert "not read" in text
    assert "Not read</div>" in text, "and it is counted in the summary cards"


def test_content_is_escaped_not_injected(tmp_path: Path):
    """Drawing text is arbitrary — a note containing angle brackets must not become markup."""
    from source_drawing_data import write_source_drawing_html
    summary = {"document_analysis": {"bom_rows": [
        {"part_number": "<script>alert(1)</script>", "description": "A & B <b>bold</b>",
         "quantity": 1}]}}
    text = write_source_drawing_html(summary, tmp_path, job="x").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text and "A &amp; B" in text


def test_the_run_writes_the_page_beside_the_workbook():
    source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "write_source_drawing_html(" in source
    assert "source_drawing_data_html" in source
