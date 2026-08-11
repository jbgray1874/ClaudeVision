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
