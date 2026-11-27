"""The workbook listed every part twice, on two tabs, and the two disagreed.

WHAT WAS IN THE 10575-02 WORKBOOK: nine sheets, of which the Decision Report and AI Provenance
each carried one row per part with its material, its gauge, and where each of those came from.
Twenty-five rows duplicated. James, reading them side by side:

    "we don't want overlapping data between the two sheets decision and ai governance. they need
     to have their own identities."

and then, having looked again:

    "let's get rid of one and just keep the other one then. we don't want clutter."

THE DUPLICATION WAS NOT MERELY REDUNDANT, IT WAS WRONG. The two tabs derived the same facts
independently instead of reading one recorded datum, and where a derivation differs from another
derivation the reader is handed a contradiction with no way to resolve it:

    AI Material Detail   Geom source = pdf                    for 10575-01-001
    AI Provenance        DXF flat pattern (exact)             for the same part

Both were reading `geometry_source`. One did an exact dict lookup over two keys with "pdf" as
the default, so `dxf_cut_length_only` and `dxf_matched_no_geometry` — both DXF-derived — printed
"pdf". The other did a substring test for "dxf", so `dxf_matched_no_geometry` (which means the
DXF was found and carried no geometry) printed "DXF flat pattern (exact)". One underclaimed, one
overclaimed, and the record itself, written in three grades by drawing_job_merge, was better
than both. That is what two independent derivations of one fact buy you.

TRIMMING THE DUPLICATE TABLE WAS TRIED FIRST AND IS NOT AVAILABLE.
test_every_deliverable_describes_the_same_part_list requires every deliverable to describe the
same parts, so neither tab can be narrowed to a subset of rows. Deletion is the only way to
remove the duplication — which makes James's instruction the correct answer rather than merely
the one he gave.

WHAT WAS UNIQUE HAD TO MOVE FIRST. Four blocks existed on the Decision Report and nowhere else,
and this file exists mostly to make sure they never quietly leave with it:

    who decided powder, and at what rank
    the material breakdown that adds back to the sheet's own material total
    the operations where two equally-ranked sources disagreed
    the DATA contests — what the part is made of, and how thick

The last is the expensive one. Material decides the rate and whether the part has a rate at all;
gauge decides the rate AND steps the cut time, so a part costed on the wrong gauge is wrong
twice. Deleting the tab without carrying these across would have removed the only place in the
workbook where either appears.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

openpyxl = pytest.importorskip("openpyxl")

import estimation_report as er                                          # noqa: E402
import job_decision_report as jdr                                       # noqa: E402


def _summary():
    """A job with something contested on both axes, and a material total the parts undershoot."""
    return {
        "estimate_summary": {
            "part_estimates": [
                {"part_number": "10575-01-001", "description": "bracket",
                 "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 1.5,
                 "extended_total_cost_gbp": 40.0,
                 "material_estimate": {"extended_material_cost_gbp": 40.0}},
                {"part_number": "BI-BOLT", "description": "M6 bolt",
                 "normalized_material": "BOUGHT_IN", "extended_total_cost_gbp": 30.27,
                 "material_estimate": {"extended_material_cost_gbp": 30.27}},
            ],
            "canonical_route_shadow": {"decisions": [
                {"target_id": "10575-01-001", "operation": "powder_coating",
                 "status": "required", "source": "llm_full_extract",
                 "decided_by": "Grok (xAI)", "source_rank": 40, "contested": True,
                 "losing_statuses": ["not_applicable"], "settled_by_key": "confidence"},
            ]},
        },
        "invariants": {"violations": [
            {"code": "two_sources_disagree_about_the_gauge",
             "detail": {"parts": [{"part_number": "10575-01-001", "costed_as": "1.5",
                                   "costed_from": "the drawing", "other": "3.0",
                                   "other_from": "Grok (xAI)", "ratio": 2.0}]}},
        ]},
        "final_estimate": {"totals": {"unit_gbp": 593.07, "material_gbp": 144.40,
                                      "labour_gbp": 300.0}},
        "manufacturing_writeup": {"parts": []},
    }


def _provenance_text(summary) -> str:
    wb = openpyxl.Workbook()
    er.add_provenance_sheet(wb, summary, {"job_number": "10575"})
    ws = wb["AI Provenance"]
    return "\n".join(
        " | ".join("" if c.value is None else str(c.value) for c in row)
        for row in ws.iter_rows())


# ── the tab is gone from the delivered workbook ──────────────────────────────

def test_the_engine_no_longer_writes_a_decision_report_tab():
    """James asked for one tab, not two. Stated against main.py's source because the failure
    mode is somebody restoring the call while merging, and a workbook grown back to nine
    sheets looks exactly like one that was always nine."""
    import main as _main
    src = inspect.getsource(_main)
    code = re.sub(r"#[^\n]*", " ", src)
    assert "add_decision_report_sheet(" not in code, (
        "the Decision Report tab is being written into the workbook again")
    assert "add_provenance_sheet(_wb" in code, "AI Provenance is no longer written at all"


def test_the_writer_is_kept_but_says_it_is_not_wired_in():
    """Kept deliberately: the blocks' tests exercise it here, and the tab can be restored in
    one line if the estimators miss it. A function nobody calls and nothing explains is the
    kind of thing that gets re-wired by accident six months later."""
    doc = (jdr.add_decision_report_sheet.__doc__ or "")
    assert "NO LONGER WRITTEN" in doc, (
        "nothing on the function says the workbook does not use it")


# ── and everything it knew alone came with it ────────────────────────────────

def test_powder_authority_moved_across():
    """Powder has twice produced a figure on a sheet that no reader could trace to a decision.
    The sentence naming who decided it is the check that makes that visible, and the Decision
    Report was the only place it appeared."""
    assert "Powder:" in _provenance_text(_summary())


def test_the_material_breakdown_adds_back_to_the_sheets_own_total():
    """THE RESIDUAL IS THE POINT. Parts summing to £70.27 against a sheet total of £144.40 is a
    breakdown that accounts for half the money, and a reader concludes the engine lost the
    other half. It is the powder consumable and the per-line scrap uplift, which belong to no
    single part."""
    rows = jdr.material_breakdown(_summary())
    assert rows, "no breakdown at all"
    assert jdr.POWDER_SCRAP_LABEL in dict(rows), (
        "the difference between the parts and the sheet is not named as its own row")
    assert abs(sum(v for _k, v in rows) - 144.40) < 0.01, (
        "the breakdown does not add back to the workbook's material total")


def test_the_residual_is_spelled_the_same_way_the_reconciliation_names_it():
    """Two vocabularies for one number is the defect this whole consolidation is removing. The
    reader has to be able to join the sentence to the row."""
    src = (ROOT / "src" / "estimation_report.py").read_text(encoding="utf-8")
    assert jdr.POWDER_SCRAP_LABEL.upper() in src.upper(), (
        "AI Provenance's reconciliation sentence and the breakdown row no longer match")


def test_the_operation_contests_moved_across():
    assert "DECISIONS THAT REQUIRED RESOLUTION" in _provenance_text(_summary())


def test_the_datum_contests_moved_across():
    """THE EXPENSIVE ONE. Material decides the rate and whether the part has a rate at all;
    gauge decides the rate AND steps the cut time. Nowhere else in the workbook says two
    sources disagreed about either."""
    txt = _provenance_text(_summary())
    assert "WHERE TWO SOURCES DISAGREED" in txt
    assert "10575-01-001" in txt
    assert "2x" in txt, "the gauge contest no longer says how far apart the two readings were"


def test_a_clean_job_says_nothing_was_contested_rather_than_going_quiet():
    """An absent block reads as a tab that forgot to render. "Nothing was contested" is a
    finding, and it comes with the caveat that matters: where only one reader looked, there was
    nothing to disagree with it."""
    s = _summary()
    s["estimate_summary"]["canonical_route_shadow"] = {"decisions": []}
    s["invariants"] = {"violations": []}
    txt = _provenance_text(s)
    assert "NOTHING WAS CONTESTED" in txt
    assert "nothing to disagree with it" in txt


def test_a_failure_to_build_the_blocks_is_printed_not_swallowed():
    """These are now the ONLY place the contests appear. A silent exception would render a tab
    that reads exactly like a job where nothing was contested."""
    src = inspect.getsource(er.add_provenance_sheet)
    at = src.index("append_decision_blocks")
    window = src[at:at + 1200]
    assert "except" in window, "the call is unguarded"
    assert "not a job with nothing contested" in window, (
        "a failed render is not distinguished from a clean job")


# ── and the two tabs stop deriving the same fact separately ──────────────────

@pytest.mark.parametrize("recorded,expected_word", [
    ("dxf_flat_pattern", "measured flat pattern"),
    ("dxf_cut_length_only", "cut length only"),
    ("dxf_matched_no_geometry", "carried no geometry"),
    ("mirror_of_measured", "opposite hand"),
    ("solidworks_flat_pattern", "SolidWorks"),
])
def test_every_grade_of_geometry_source_is_reported_as_itself(recorded, expected_word):
    """THE DEFAULT WAS ANSWERING FOR THE RECORD.

        {"dxf_flat_pattern": "dxf", "solidworks_flat_pattern": "solidworks"}.get(src, "pdf")

    Two keys, a "pdf" fallback, over a field that takes at least six values. Three DXF-derived
    states — cut-length-only, matched-no-geometry, mirrored — all printed "pdf", so a miss and
    a genuine PDF read produced the same word. That is exactly what the source waterfall exists
    to prevent, reintroduced in the sheet whose job is to report it."""
    from wb_populate import _geom_source_words
    assert expected_word.lower() in _geom_source_words(recorded).lower()


def test_nothing_recorded_is_not_reported_as_a_pdf_read():
    """A part nobody stamped has not been read off a PDF. Those are different facts about the
    estimate and the old default resolved them the same way."""
    from wb_populate import _geom_source_words
    assert _geom_source_words(None) == "not recorded"
    assert _geom_source_words("") == "not recorded"


def test_a_dxf_that_carried_no_geometry_is_not_called_an_exact_flat_pattern():
    """THE DISAGREEMENT JAMES WOULD HAVE HIT NEXT. AI Provenance tested `"dxf" in geo`, so
    `dxf_matched_no_geometry` — the DXF was found and carried NO geometry — printed "DXF flat
    pattern (exact)". Meanwhile AI Material Detail's exact lookup missed it and printed "pdf".
    One tab overclaimed, one underclaimed, about one part, off one recorded field."""
    src = (ROOT / "src" / "estimation_report.py").read_text(encoding="utf-8")
    code = re.sub(r"#[^\n]*", " ", re.sub(r'"""(?:.|\n)*?"""', " ", src))
    assert '"DXF flat pattern (exact)" if "dxf" in geo' not in code, (
        "the substring test is back, and it calls an empty DXF an exact flat pattern")
    from wb_populate import _geom_source_words
    assert "exact" not in _geom_source_words("dxf_matched_no_geometry").lower()
