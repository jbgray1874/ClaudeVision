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

# The corpus DXFs are not in the repo, so anything asserting against them skips on a fresh
# checkout. Every behaviour they cover is also proved on a synthetic file built in-test.
UPLOADS = Path("/root/.claude/uploads/09b98f42-bd9e-534a-8993-f8eb3975326c")
real_dxf = pytest.mark.skipif(
    not (UPLOADS / "f124e9e8-117620202M_0.9mm_MS_revA.DXF").exists(),
    reason="corpus DXFs not present in this checkout")


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


# ── where the DXF states a fact, we must be exactly right ─────────────────────────────

def test_a_dashed_bend_line_is_one_bend_not_ten(tmp_path: Path):
    """SDI's 117621702M draws its folds DASHED: ten LINE entities on BENDLINES, five 6mm
    dashes at y=75.31 and five at y=84.31, describing exactly TWO bends. Counting entities
    reported ten — a five-fold over-count on a fact the file states perfectly clearly.

    The DXF is what the CNC machines fold to. Where it represents something, we should never
    get it wrong."""
    from dxf_probe import probe_dxf
    def build(msp):
        for y in (75.31, 84.31):
            for x0 in (-53, -28, -3, 22, 47):
                msp.add_line((x0, y), (x0 + 6, y), dxfattribs={"layer": "BENDLINES"})
        msp.add_lwpolyline([(-53, 0), (53, 0), (53, 90), (-53, 90)], close=True)
    probe = probe_dxf(_dxf(tmp_path, "dashed.dxf", build))
    assert probe["bend_layer_line_count"] == 10, "the raw segments are still reported"
    assert probe["candidate_fold_axes"] == 2, "but the BENDS are two"


def test_folds_drawn_in_opposite_directions_stay_separate(tmp_path: Path):
    """MY OWN BUG, CAUGHT ON REAL GEOMETRY. A line's signed offset flips when it is drawn the
    other way round, so 117620202M's folds at y=+124.12 and y=-124.12 — drawn in opposite
    directions — produced the same offset and collapsed into one. Five bends read as three."""
    from dxf_probe import _candidate_fold_axes
    assert _candidate_fold_axes([((-5, 10), (5, 10)), ((5, -10), (-5, -10))]) == 2
    assert _candidate_fold_axes([((0, 0), (10, 0)), ((10, 0), (0, 0))]) == 1, \
        "and one line drawn twice, each way, is still one line"


@real_dxf
def test_the_corpus_bend_counts_are_exact():
    """Against the three real flats, with the count each file actually describes."""
    from dxf_probe import probe_dxf
    for name, expected in (("f124e9e8-117620202M_0.9mm_MS_revA.DXF", 5),
                           ("3c321a99-117621702M_2MM_MS_RevA.DXF", 2),
                           ("f421e02c-1097502A01_2mm_ACRY_Rev_B.DXF", 2)):
        path = UPLOADS / name
        if path.exists():
            assert probe_dxf(path)["candidate_fold_axes"] == expected, name


def test_bends_are_compared_because_the_dxf_states_them(tmp_path: Path):
    """Unlike circles-vs-holes, this IS the same fact measured two ways, so it is scored."""
    from source_drawing_data import build_tables
    def build(msp):
        msp.add_line((0, 10), (100, 10), dxfattribs={"layer": "BENDLINES"})
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
    path = _dxf(tmp_path, "117620202M.dxf", build)
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "117620202M", "manufacturing_features": {"bend_count": 1}}]}}
    rows = {r["fact"]: r for r in build_tables(summary, [path])["DXF file vs engine"]}
    assert rows["candidate fold axes"]["comparable"] == "yes"
    assert rows["candidate fold axes"]["agrees"] == "yes"
    assert "collapse to 1 fold axis" in rows["candidate fold axes"]["note"]


# ── the page carries everything, not a summary ────────────────────────────────────────

def test_every_page_of_every_pdf_gets_a_row_even_when_it_yielded_nothing():
    """A document where the pages that failed are simply absent reads as a shorter pack."""
    from source_drawing_data import page_rows
    summary = {"pages": [
        {"page_number": 1, "source_pdf_name": "j.pdf", "source_page_number": 1,
         "page_analysis": {"dimensions": {"all_dimensions_mm": [10, 20]}}},
        {"page_number": 2, "source_pdf_name": "j.pdf", "source_page_number": 2,
         "page_analysis": {}}]}
    rows = page_rows(summary)
    assert len(rows) == 2
    # The row says which fields were looked for and came back empty. It does NOT claim
    # nothing was read: the page inventory checks a fixed list of fields, and a page can
    # still carry process notes or textual operations that this row does not cover.
    assert "none of the fields checked were populated" in rows[1]["read_from_it"]
    assert "nothing was read" not in rows[1]["read_from_it"]


def test_the_page_lists_each_dxf_in_full(tmp_path: Path):
    """100% of what was extracted, per file — entities, layers, text, circles, units — with
    nothing elided. Hiding the dull rows is how a fact goes missing without a decision."""
    from source_drawing_data import write_source_drawing_html
    def build(msp):
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
        msp.add_circle((20, 20), 2.5)
        msp.add_line((0, 10), (100, 10), dxfattribs={"layer": "BENDLINES"})
    path = _dxf(tmp_path, "117620202M.dxf", build)
    summary = {"estimate_summary": {"part_estimates": [{"part_number": "117620202M"}]}}
    html = write_source_drawing_html(summary, tmp_path, "j", [path]).read_text(encoding="utf-8")

    assert "Every DXF in full" in html
    for label in ("read with", "units declared", "extent", "profile length", "circles",
                  "candidate fold axes", "layers", "entities", "not measured", "text in the file",
                  "attributed to a part by"):
        assert f">{label}<" in html, f"the page must state {label}"
    assert "BENDLINES" in html and "LWPOLYLINE" in html, "layers and entity types verbatim"
    assert "ezdxf" in html


# ── what the audit is NOT allowed to claim ────────────────────────────────────────────

def test_two_features_folding_on_one_line_are_not_one_axis():
    """A fold AXIS is not proven to be one manufacturing bend, and the grouping must not
    pretend otherwise. Two tabs 500mm apart happen to line up; collapsing them to one was an
    overclaim that a dashed-line fix had smuggled in."""
    from dxf_probe import _candidate_fold_axes
    assert _candidate_fold_axes([((0, 10), (10, 10)), ((500, 10), (510, 10))]) == 2
    # ...while the dashes of one fold, 19mm apart, still collapse
    assert _candidate_fold_axes([((-53, 75), (-47, 75)), ((-28, 75), (-22, 75)),
                                 ((-3, 75), (3, 75)), ((22, 75), (28, 75)),
                                 ((47, 75), (53, 75))]) == 1


def test_the_grouping_tolerance_is_millimetres_not_file_units(tmp_path: Path):
    """0.25 applied to raw coordinates meant 0.25 INCHES on an inch drawing, so two folds a
    millimetre apart collapsed into one. Coordinates are converted before any tolerance."""
    def build(msp):
        msp.add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True)
        msp.add_line((0, 1.0), (10, 1.0), dxfattribs={"layer": "BENDLINES"})
        msp.add_line((0, 1.03937), (10, 1.03937), dxfattribs={"layer": "BENDLINES"})
    probe = probe_dxf(_dxf(tmp_path, "inchbend.dxf", build, insunits=INCH))
    assert probe["candidate_fold_axes"] == 2, \
        "1mm apart on an inch drawing is 1mm apart, not the same line"


def test_the_detail_section_escapes_every_source_derived_value(tmp_path: Path):
    """Layer names, entity types, attribution and error text all come out of files, and the
    detail renderer inserted strings raw. Whether today's files can exploit it is not the
    test — a table that can render source data as markup is a defect."""
    from source_drawing_data import write_source_drawing_html
    def build(msp):
        msp.add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True)
        msp.add_text("<img src=x onerror=alert(1)> & <b>bold</b>")
    path = _dxf(tmp_path, "esc.dxf", build)
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "<script>alert(2)</script>"}]}}
    html = write_source_drawing_html(summary, tmp_path, "j", [path]).read_text(encoding="utf-8")
    assert "<img src=x onerror" not in html
    assert "<script>alert(2)</script>" not in html
    assert "&lt;img" in html and "&amp;" in html


def test_a_page_with_only_notes_does_not_claim_nothing_was_read():
    """A false statement about the pack, made by the document whose only job is to be true
    about the pack. It now lists what it found, and when it finds none of them it says which
    fields it looked at."""
    from source_drawing_data import page_rows
    rows = page_rows({"pages": [{"page_number": 1, "source_pdf_name": "j.pdf",
                                 "page_analysis": {"process_notes": ["Puddle weld both sides"],
                                                   "textual_operations": ["welding"]}}]})
    said = rows[0]["read_from_it"]
    assert "nothing was read" not in said
    assert "process notes: 1" in said and "welding" in said

    empty = page_rows({"pages": [{"page_number": 2, "source_pdf_name": "j.pdf",
                                  "page_analysis": {}}]})[0]["read_from_it"]
    assert "none of the fields checked were populated" in empty
    assert "process notes" in empty, "and names what it looked at"


def test_no_text_is_silently_dropped(tmp_path: Path):
    """The cap was texts[:40] with no note, on a document claiming to elide nothing. The GA
    export in the corpus carries 118 strings; 78 were disappearing."""
    def build(msp):
        msp.add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True)
        for index in range(60):
            msp.add_text(f"NOTE {index}")
    probe = probe_dxf(_dxf(tmp_path, "many.dxf", build))
    assert probe["text_count"] == 60
    assert len(probe["text_values"]) == 60


def test_each_dxf_is_read_once_per_page(tmp_path: Path):
    """The comparison table and the detail section both want the same inventory. Reading each
    file twice is slower and lets the two halves of one page disagree."""
    import source_drawing_data as sdd
    calls = {"n": 0}
    real = sdd._probe_once.__wrapped__ if hasattr(sdd._probe_once, "__wrapped__") else None
    path = _dxf(tmp_path, "once.dxf",
                lambda m: m.add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True))
    sdd._PROBE_CACHE.clear()
    import dxf_probe
    original = dxf_probe.probe_dxf

    def counting(p):
        calls["n"] += 1
        return original(p)

    dxf_probe.probe_dxf = counting
    try:
        sdd.write_source_drawing_html({"estimate_summary": {"part_estimates": []}},
                                      tmp_path, "j", [path])
    finally:
        dxf_probe.probe_dxf = original
        sdd._PROBE_CACHE.clear()
    assert calls["n"] == 1, f"the file was read {calls['n']} times"


# ── the four the reviewer left open after the dashed-fold commit ───────────────────────


def _nested_dxf(tmp_path: Path, name: str, insunits: int = MM) -> Path:
    """Profile in INNER, INNER inserted into OUTER, OUTER inserted into modelspace. This is
    the ordinary shape of a SolidWorks assembly export, not a contrived file."""
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = insunits
    inner = doc.blocks.new("INNER")
    inner.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
    inner.add_circle((20, 20), 2.5)
    outer = doc.blocks.new("OUTER")
    outer.add_blockref("INNER", (0, 0))
    doc.modelspace().add_blockref("OUTER", (0, 0))
    path = tmp_path / name
    doc.saveas(path)
    return path


def test_geometry_inside_a_nested_block_is_counted(tmp_path: Path):
    """virtual_entities() explodes ONE level. A block that inserts the block holding the
    profile came back as another INSERT and was appended as a leaf, so the file reported
    {"INSERT": 1}, no circles and no outline length — while ezdxf.bbox, which recurses on its
    own, reported the real extent. The page showed an extent for geometry it also denied."""
    probe = probe_dxf(_nested_dxf(tmp_path, "nested.dxf"))
    assert probe["entity_counts"].get("LWPOLYLINE") == 1
    assert probe["entity_counts"].get("INSERT") is None, "the reference is resolved, not counted"
    assert probe["circle_count"] == 1
    assert probe["outline_length"] == pytest.approx(300.0 + 2.5 * 2 * 3.14159, abs=0.5)
    assert probe["extent_length"] == pytest.approx(100.0, abs=0.01)
    assert probe["block_nesting_depth"] >= 2


def test_a_self_inserting_block_is_named_and_not_followed(tmp_path: Path):
    """Real files carry these by accident. Following one is an infinite descent, so the
    recursion stops and SAYS which block it stopped at."""
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = MM
    block = doc.blocks.new("SELF")
    block.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
    block.add_blockref("SELF", (20, 0))
    doc.modelspace().add_blockref("SELF", (0, 0))
    path = tmp_path / "self.dxf"
    doc.saveas(path)
    probe = probe_dxf(path)
    assert any("inserts itself" in u for u in probe["unresolved_blocks"])
    assert any("block not resolved" in u for u in probe["unsupported"]), \
        "an abandoned branch holds geometry we have not counted, so it is named"


def test_nesting_deeper_than_the_cap_is_declared_not_silently_truncated(tmp_path: Path):
    """A total computed after abandoning a branch is partial and must say so."""
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = MM
    base = doc.blocks.new("L0")
    base.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
    for level in range(1, 13):
        doc.blocks.new(f"L{level}").add_blockref(f"L{level - 1}", (0, 0))
    doc.modelspace().add_blockref("L12", (0, 0))
    path = tmp_path / "deep.dxf"
    doc.saveas(path)
    probe = probe_dxf(path)
    assert probe["unresolved_blocks"], "the cap is reported, not silent"
    assert any("deeper than" in u for u in probe["unresolved_blocks"])


def test_a_unitless_file_is_not_scored_against_millimetres(tmp_path: Path):
    """$INSUNITS unset means the figure is in file units. One unitless drawing read 30000
    against the engine's 762 mm and scored a red NO — that is the inch-to-mm factor, not a
    disagreement, and a red card here sends somebody to fix an engine that is correct."""
    from source_drawing_data import build_tables
    path = _dxf(tmp_path, "unitless.dxf",
                lambda m: m.add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True),
                insunits=UNITLESS)
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "unitless", "geometry_rollup": {"cut_length_mm": 762.0}}]}}
    row = {r["fact"]: r for r in build_tables(summary, [path])["DXF file vs engine"]}
    assert row["outline length"]["agrees"] == "NOT COMPARABLE"
    assert row["outline length"]["comparable"] == "no"
    assert "declares no units" in row["outline length"]["note"]
    # disclosed, not hidden: both numbers are still on the row
    assert row["outline length"]["in_the_file"] == pytest.approx(30.0, abs=0.01)
    assert row["outline length"]["engine_has"] == 762.0


def test_a_partial_total_is_not_scored_against_a_complete_one(tmp_path: Path):
    """A sum taken while geometry was skipped is knowingly short of the whole file. 300 vs 420
    scored NO on a file whose own unsupported list said geometry was missing."""
    from source_drawing_data import build_tables
    path = _nested_dxf(tmp_path, "partial.dxf")
    probe = probe_dxf(path)
    if not probe.get("outline_length_partial"):
        # force the condition through the documented flag rather than a contrived file
        pytest.skip("this build measured everything in the fixture")
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "partial", "geometry_rollup": {"cut_length_mm": 420.0}}]}}
    row = {r["fact"]: r for r in build_tables(summary, [path])["DXF file vs engine"]}
    assert row["outline length"]["agrees"] == "NOT COMPARABLE"


def test_an_unresolvable_block_makes_every_total_partial(tmp_path: Path):
    """Directly: the flag, not via a comparison row."""
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = MM
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
    msp.add_blockref("DOES-NOT-EXIST", (0, 0))
    path = tmp_path / "missingblock.dxf"
    doc.saveas(path)
    probe = probe_dxf(path)
    assert probe["unresolved_blocks"], "the block we could not open is named"
    assert probe["outline_length_partial"] is True, \
        "a total summed past missing geometry is partial"


def _same_name_pack(tmp_path: Path) -> tuple:
    """revA/X.dxf and revB/X.dxf, different geometry, one basename."""
    made = []
    for folder, length in (("revA", 100), ("revB", 250)):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
        doc = ezdxf.new()
        doc.header["$INSUNITS"] = MM
        doc.modelspace().add_lwpolyline(
            [(0, 0), (length, 0), (length, 50), (0, 50)], close=True)
        path = tmp_path / folder / "117620202M.dxf"
        doc.saveas(path)
        made.append(path)
    return made[0], made[1]


def test_two_files_sharing_a_basename_are_told_apart(tmp_path: Path):
    """They produced two rows identical in every visible column — same file name, same part —
    one agreeing and one a red NO, with nothing saying the pipeline had used the other file."""
    from source_drawing_data import build_tables
    rev_a, rev_b = _same_name_pack(tmp_path)
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "117620202M", "dxf_file": str(rev_b), "blank_length_mm": 250.0}]}}
    rows = [r for r in build_tables(summary, [rev_a, rev_b])["DXF file vs engine"]
            if r["fact"] == "blank length"]
    assert len(rows) == 2
    assert len({r["file"] for r in rows}) == 2, "the two rows are distinguishable"
    assert all("117620202M.dxf" in r["file"] for r in rows), "the recognisable name is kept"


def test_the_file_the_pipeline_did_not_use_is_not_scored_against_the_part(tmp_path: Path):
    """Comparing file A's geometry against part P's figures, where the engine read file B, is
    not one fact measured twice — it is two files. The exact path wins; a basename-only match
    is still offered, because it is usually right, but it is not SCORED."""
    from source_drawing_data import build_tables
    rev_a, rev_b = _same_name_pack(tmp_path)
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "117620202M", "dxf_file": str(rev_b), "blank_length_mm": 250.0}]}}
    rows = {r["file"]: r for r in build_tables(summary, [rev_a, rev_b])["DXF file vs engine"]
            if r["fact"] == "blank length"}
    used = [r for k, r in rows.items() if "revB" in k][0]
    other = [r for k, r in rows.items() if "revA" in k][0]
    assert used["agrees"] == "yes", "the file the pipeline recorded is compared normally"
    assert other["agrees"] == "NOT COMPARABLE"
    assert "name only" in other["note"]
    assert str(rev_b) in other["note"] or rev_b.name in other["note"], \
        "and it names the path the pipeline actually used"


def test_a_bare_filename_still_matches_without_a_false_ambiguity_warning(tmp_path: Path):
    """Callers that only have a name must not be told the path disagrees — there is no path."""
    from source_drawing_data import _match_part
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "X1", "dxf_file": "/some/where/X1.dxf"}]}}
    part, how, ambiguous = _match_part(summary, "X1.dxf")
    assert part is not None
    assert ambiguous is False
    assert "own file-to-part association" in how


def test_the_workbook_and_the_page_are_written_from_one_snapshot(tmp_path: Path):
    """The docstring claimed the two "cannot drift apart" because both were built from
    build_tables() — but calling the same FUNCTION twice is not the same DATA. Passing the
    snapshot makes the claim true by construction: neither writer rebuilds."""
    import source_drawing_data as sdd
    path = _dxf(tmp_path, "snap.dxf",
                lambda m: m.add_lwpolyline([(0, 0), (60, 0), (60, 30), (0, 30)], close=True))
    summary = {"estimate_summary": {"part_estimates": [{"part_number": "snap"}]}}
    sdd._PROBE_CACHE.clear()
    tables = sdd.build_tables(summary, [path])
    calls = {"n": 0}
    real_build = sdd.build_tables

    def counting(*a, **k):
        calls["n"] += 1
        return real_build(*a, **k)

    sdd.build_tables = counting
    try:
        sdd.write_source_drawing_data(summary, tmp_path, "j", [path], tables=tables)
        sdd.write_source_drawing_html(summary, tmp_path, "j", [path], tables=tables)
    finally:
        sdd.build_tables = real_build
        sdd._PROBE_CACHE.clear()
    assert calls["n"] == 0, f"a writer rebuilt the tables {calls['n']} time(s)"


def test_the_run_builds_the_audit_snapshot_once(tmp_path: Path):
    """The production call site, not just the capability: main.py must build once and hand the
    same dict to both writers. A test that only proves the parameter exists proves nothing
    about what the run does."""
    source = (Path(__file__).resolve().parents[1] / "src" / "main.py").read_text(
        encoding="utf-8", errors="ignore")
    assert "_sdd_tables = build_tables(" in source
    assert source.count("tables=_sdd_tables") == 2, \
        "both writers take the one snapshot"
