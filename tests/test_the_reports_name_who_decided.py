"""All three reports must name where a decision was taken, and show contested ones.

"Where did this come from" is the first question asked of any estimate this engine
produces, and until now the answer depended on which document you happened to open:

  * The Decision Report named the source for THICKNESS only, through a private eight-entry
    table that omitted mirror_of_measured, pdf_overall_dims and override_rule -- so those
    rendered as bare internal keys in the one document written to explain the costing.
  * The HTML job report carried route detail ONLY when a manual workbook was passed with
    --parity-workbook. On an ordinary run it could not say what decided a single operation.
  * The provenance tool printed the raw key alone: "solidworks_flat_pattern". Correct, and
    not an answer anybody outside this codebase can read.

One table of names, owned by the module that owns the ranks, so a name and a rank can never
disagree about what a source is.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import source_precedence as sp                                      # noqa: E402
import job_report_html as jrh                                       # noqa: E402


def _summary(decisions):
    return {"estimate_summary": {"canonical_route_shadow": {"decisions": decisions}}}


def _d(**kw):
    base = {"decision_id": "d1", "operation": "powder_coating", "status": "required",
            "target_id": "11650-02-01A", "source": "dxf", "source_rank": 80,
            "decided_by": "the DXF", "contested": False, "losing_statuses": [],
            "evidence": "", "participants": []}
    base.update(kw)
    return base


# ── the HTML report ─────────────────────────────────────────────────────────────────
def test_the_html_report_names_who_decided_each_operation():
    html = jrh._route_decisions_section(_summary([_d()]))
    assert "the DXF" in html
    assert "powder coating" in html
    assert "11650-02-01A" in html


def test_the_html_section_renders_without_a_parity_workbook():
    """The defect. Route detail used to appear only when --parity-workbook was passed, so
    an ordinary run produced a report that could not explain one operation."""
    html = jrh._route_decisions_section(_summary([_d()]))
    assert "<table" in html and "How each operation was decided" in html


def test_a_contested_decision_is_shown_and_listed_first():
    """A decision taken over an objection is the one worth reading. Buried among fifty
    unanimous rows, it is hidden."""
    rows = [_d(target_id="AAA-1", contested=False),
            _d(target_id="ZZZ-9", contested=True, losing_statuses=["ruled_out"])]
    html = jrh._route_decisions_section(_summary(rows))
    assert "resolved over" in html and "ruled_out" in html
    assert html.index("ZZZ-9") < html.index("AAA-1"), \
        "the contested decision must come before the unanimous ones"
    assert "1 decision(s) were contested" in html


def test_an_uncontested_job_says_so_rather_than_staying_silent():
    html = jrh._route_decisions_section(_summary([_d()]))
    assert "No decision was contested" in html


def test_a_job_with_no_compiled_route_says_so_loudly():
    """Silence is not a clean bill. A missing section reads as 'nothing to report', when
    it means no operation was arbitrated at all."""
    for empty in ({}, _summary([]), {"estimate_summary": {}}):
        html = jrh._route_decisions_section(empty)
        assert "No compiled route" in html and "warn" in html


def test_a_decision_with_no_drawing_quote_says_so():
    """Empty evidence is a fact about the decision, not a blank to be tidied away: it
    means the decision cannot be held against the sheet."""
    assert "nothing quoted" in jrh._route_decisions_section(_summary([_d()]))
    quoted = jrh._route_decisions_section(
        _summary([_d(evidence="SURFACE FINISH: POWDER COATED")]))
    assert "SURFACE FINISH" in quoted


def test_a_decision_missing_its_display_name_still_names_something():
    """A blank in this column reads as 'nobody decided', which it never means."""
    html = jrh._route_decisions_section(_summary([_d(decided_by="", source="dxf")]))
    assert "dxf" in html
    html2 = jrh._route_decisions_section(_summary([_d(decided_by="", source="")]))
    assert "not recorded" in html2


def test_the_section_survives_a_malformed_decision():
    """A report that raises produces no document at all, and the run that needed
    explaining is the one that gets none."""
    html = jrh._route_decisions_section(_summary(["not a dict", _d()]))
    assert "11650-02-01A" in html


# ── the provenance tool ─────────────────────────────────────────────────────────────
_PROV = (ROOT / "tools" / "where_did_this_come_from.py").read_text(encoding="utf-8")


def test_the_provenance_report_names_the_source_readably():
    assert "_display(src)" in _PROV, \
        "the provenance report still prints the raw internal key alone"
    assert "rank {_rank(src)}" in _PROV, "the rank must stay visible beside the name"


def test_the_provenance_report_marks_measured_against_reasoned():
    """The whole point of the waterfall: a number off a model can be held against the
    model, and a number off a language model cannot."""
    assert "_was_measured(src)" in _PROV
    assert "measured" in _PROV and "reasoned" in _PROV


# ── one table of names ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mod", ["src/job_decision_report.py",
                                 "src/job_report_html.py",
                                 "src/route_compiler.py",
                                 "tools/where_did_this_come_from.py"])
def test_no_report_keeps_a_private_source_name_table(mod):
    text = (ROOT / mod).read_text(encoding="utf-8")
    assert '"the SolidWorks flat pattern"' not in text, \
        f"{mod} has grown its own copy of the source-name table"


def test_all_three_reports_read_the_shared_names():
    for mod in ("src/job_decision_report.py", "tools/where_did_this_come_from.py"):
        text = (ROOT / mod).read_text(encoding="utf-8")
        assert "display_name" in text, f"{mod} does not use the shared source names"
    assert sp.display_name("solidworks_flat_pattern") == "the SolidWorks flat pattern"


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── the BOM half of the same question ───────────────────────────────────────────────
# Section 9 explains the ROUTE; this explains the BILL OF MATERIALS. An estimator asks both
# at once: was the material, thickness and quantity behind this line measured off a model,
# read off a DXF, or produced by a language model? The report named none of them, so a
# figure from a SolidWorks model and one from Grok looked identical on the page.
def _part(pn="11650-04-01A", **stamps):
    p = {"part_number": pn, "normalized_material": "PETG",
         "normalized_thickness_mm": 3.0, "quantity": 2}
    p.update(stamps)
    return p


def _psummary(parts):
    return {"estimate_summary": {"part_estimates": list(parts)}, "parts": list(parts)}


def test_the_bom_section_names_where_each_datum_came_from():
    html = jrh._bom_provenance_section(_psummary([
        _part(material_source="solidworks_api", thickness_source="dxf_flat_pattern")]))
    assert "the SolidWorks model" in html and "the DXF flat pattern" in html
    assert "11650-04-01A" in html


def test_a_reasoned_datum_is_marked_and_a_measured_one_is_not():
    """The distinction the whole waterfall exists for. A reasoned value can be right and
    still cannot be held against the drawing."""
    html = jrh._bom_provenance_section(_psummary([
        _part(material_source="llm_full_extract", thickness_source="solidworks_api")]))
    assert "Grok (xAI)" in html
    assert "rest on at least one reasoned value" in html
    # IN THE CELL, NOT MERELY ON THE PAGE. The first version asserted the marker appeared
    # anywhere in the HTML and passed with the cell marker deleted -- the legend explaining
    # the symbol contains the symbol, so the note masked its absence from every row. A
    # mutation showed it. Assert it sits immediately before the reasoned source's name and
    # NOT before the measured one.
    assert "&#9889; Grok (xAI)" in html, \
        "the reasoned datum's own cell is not marked"
    assert "&#9889; the SolidWorks model" not in html, \
        "a measured datum has been marked as reasoned"


def test_an_unstamped_field_says_so_rather_than_reading_as_measured():
    """A blank in a provenance column reads as 'fine'. It means nobody recorded who
    decided, which is not the same fact at all."""
    html = jrh._bom_provenance_section(_psummary([_part()]))
    assert "not stamped" in html


def test_the_weakest_provenance_is_listed_first():
    strong = _part("AAA-1", material_source="solidworks_api",
                   thickness_source="solidworks_api", quantity_source="solidworks_api")
    weak = _part("ZZZ-9", material_source="llm_full_extract",
                 thickness_source="llm_full_extract", quantity_source="llm_full_extract")
    html = jrh._bom_provenance_section(_psummary([strong, weak]))
    assert html.index("ZZZ-9") < html.index("AAA-1"), \
        "the line most in need of a person must not be buried below the safe ones"


def test_a_fully_measured_job_says_so_positively():
    html = jrh._bom_provenance_section(_psummary([
        _part(material_source="solidworks_api", thickness_source="solidworks_api",
              quantity_source="solidworks_api", blank_length_mm=400.0,
              blank_length_mm_source="dxf_flat_pattern")]))
    assert "Every costing datum" in html


def test_the_bom_section_reads_the_recorded_stamp_not_a_second_opinion():
    """Deriving provenance from filenames or geometry hints -- which other parts of this
    codebase used to do -- produces a report that can disagree with the record it reports
    on, which is worse than no report."""
    src = Path(jrh.__file__).read_text(encoding="utf-8")
    block = src[src.index("def _bom_provenance_section"):src.index("def _route_decisions_section")]
    assert "source_of(" in block, "provenance is not read from where it is stamped"
    assert "dxf_source_file" not in block, "the report is re-deriving provenance from a filename"


def test_both_provenance_sections_render_on_a_job_with_no_parity_workbook():
    """The whole ask: the report must explain itself with or without a spreadsheet to run
    parity against."""
    s = _psummary([_part(material_source="dxf")])
    s["estimate_summary"]["canonical_route_shadow"] = {"decisions": [_d()]}
    assert "<table" in jrh._bom_provenance_section(s)
    assert "<table" in jrh._route_decisions_section(s)


# The section-number guard lives once, at the end of this file, against the CURRENT
# layout. Two copies asserting different numberings is how a renumbering passes half the
# suite and fails the other half with no way to tell which one is right.


# ── the four-line trust strip ───────────────────────────────────────────────────────
# What a reviewer needs before the long tables: whether to trust the number at all.
def _full(decisions=None, parts=None, truth="populated_xlsx_excel_com"):
    s = {"estimate_summary": {"part_estimates": list(parts or []),
                              "canonical_route_shadow": {"decisions": list(decisions or [])}},
         "parts": list(parts or []),
         }
    s["estimate_summary"]["workbook_equivalent_pricing"] = {"source_of_truth": truth}
    return s


def test_the_strip_says_where_the_totals_came_from():
    """A reader cannot otherwise tell a figure the workbook calculated from one this report
    worked out for itself, and only the first can be checked by opening the sheet."""
    html = jrh._provenance_strip(_full([_d()]))
    assert "workbook's own calculated cells" in html and "not re-computed here" in html


def test_an_unrecorded_source_of_truth_is_called_out_not_assumed():
    html = jrh._provenance_strip(_full([_d()], truth=""))
    assert "not recorded" in html and "unverified" in html


def test_the_strip_names_the_best_source_that_contributed():
    html = jrh._provenance_strip(_full([
        _d(source="llm_full_extract", source_rank=40),
        _d(source="solidworks_api", source_rank=90)]))
    assert "the SolidWorks model" in html and "rank 90" in html


def test_the_strip_counts_contested_decisions_and_names_the_key():
    html = jrh._provenance_strip(_full([
        _d(contested=True, losing_statuses=["ruled_out"],
           settled_by_key="quotes the drawing")]))
    assert "1" in html and "quotes the drawing" in html


def test_the_strip_names_the_powder_authority():
    """Powder is on this strip because it is the one figure that has twice been produced by
    a mechanism nobody could name from the sheet."""
    coated = jrh._provenance_strip(_full([_d(operation="powder_coating", status="required")]))
    assert "route compiler" in coated and "1 part(s) decided coated" in coated

    none = jrh._provenance_strip(_full([_d(operation="powder_coating", status="ruled_out")]))
    assert "nothing coated on this job" in none

    silent = jrh._provenance_strip(_full([_d(operation="welding")]))
    assert "no powder decision" in silent and "geometry" in silent

    legacy = jrh._provenance_strip(_full([]))
    assert "legacy finish gate" in legacy


# ── cross-links and the secondary-key marker ────────────────────────────────────────
def test_a_part_links_between_the_two_provenance_sections():
    """An estimator reading a material line wants that part's operations, and vice versa."""
    bom = jrh._bom_provenance_section(_psummary([_part("11650-04-01A", material_source="dxf")]))
    route = jrh._route_decisions_section(_summary([_d(target_id="11650-04-01A")]))
    assert 'id="bom-11650-04-01A"' in bom and 'href="#route-11650-04-01A"' in bom
    assert 'id="route-11650-04-01A"' in route and 'href="#bom-11650-04-01A"' in route


def test_the_route_table_names_which_key_settled_a_contest():
    """'Resolved' alone does not say whether the drawing's own words decided it or a
    reproducibility backstop did, and those deserve different amounts of trust."""
    html = jrh._route_decisions_section(_summary([
        _d(contested=True, losing_statuses=["ruled_out"],
           settled_by_key="claim id (reproducibility backstop)")]))
    assert "by claim id (reproducibility backstop)" in html


def test_a_job_with_no_costed_parts_says_so_loudly():
    """Section 10 already knows silence is not a clean bill; section 9 does now too."""
    html = jrh._bom_provenance_section(_psummary([]))
    assert "No costed parts" in html and "warn" in html


def test_the_section_numbers_are_still_unique_and_ordered():
    """Section 10 was inserted for the purchased-part lookup keys and the two below it moved
    up. This guard is what noticed -- which is the whole reason it enumerates titles against
    numbers rather than merely counting headings."""
    src = Path(jrh.__file__).read_text(encoding="utf-8")
    for n, title in ((8, "How far to trust this number"),
                     (9, "Where the bill of materials came from"),
                     (10, "What each purchased part was looked up by"),
                     (11, "Why these lines carry no price"),
                     (12, "How each operation was decided"),
                     (13, "Consistency checks")):
        assert f"<h2>{n} &nbsp;{title}</h2>" in src, f"section {n} ({title}) is misnumbered"


def test_no_two_sections_claim_the_same_number():
    """The check above would pass a report with TWO section 10s, because it only asks whether
    each expected heading is present. Inserting a section is exactly when a duplicate appears,
    so the question has to be asked from the other side as well."""
    src = Path(jrh.__file__).read_text(encoding="utf-8")
    seen = {}
    for m in re.finditer(r"<h2>(\d+[a-z]?) &nbsp;([^<]+)</h2>", src):
        seen.setdefault(m.group(1), set()).add(m.group(2))
    dupes = {n: t for n, t in seen.items() if len(t) > 1}
    assert not dupes, f"section number(s) used for more than one heading: {dupes}"
