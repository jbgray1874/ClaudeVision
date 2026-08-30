"""The Decision Report and AI Provenance answered the same question differently.

FOUND ON A REAL WORKBOOK — 10575-02 V2 Upright Display, the run of 30/08 12:31. For part
10575-01-001 the two tabs of the SAME file said:

    Decision Report   Material Source — WHY :  "⚡ AI inference from drawing context"
    AI Provenance     Mat. Source           :  "drawing_deterministic"  ·  REPORTED

Provenance was right. The material was read off the title block by the deterministic drawing
reader — rank 70, a MEASURED source, no model involved. The Decision Report said a language
model guessed it, on every mild steel part in the pack, which is most of any pack we quote.

WHY IT HAPPENED, BECAUSE IT IS NOT A TYPO. _mat_source_explanation ignored the recorded
`material_source` entirely and re-derived an explanation from the DXF filename, the part-number
suffix and the material string. Its mild steel branch is guarded by `"pdf" in geo` — and:

    estimation_report.py:265   geo = str(part.get("geometry_source") or "pdf")
    job_decision_report.py:271 geo = str(part.get("geometry_source") or "")

On a PDF-only part `geometry_source` is unset, so the guard was TRUE in one file and FALSE in
the other, and the Decision Report fell through every branch to its AI catch-all.

THE RULE THIS ENCODES. A document whose purpose is provenance must READ the provenance, not
infer it. Two readers that each guess will eventually disagree, and the disagreement lands in
front of an estimator deciding whether to trust a number.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import job_decision_report as dr                                       # noqa: E402
import source_precedence as sp                                         # noqa: E402


def _part(**kw):
    p = {"part_number": "10575-01-001", "description": "V1 - BACK - REAR TRAY",
         "normalized_material": "MILD STEEL", "quantity": 1}
    p.update(kw)
    return p


# ── the recorded source is what gets printed ─────────────────────────────────

@pytest.mark.parametrize("source,expect", [
    ("drawing_deterministic", "the drawing"),
    ("solidworks_api", "the SolidWorks model"),
    ("knowledge_base", "SDI's knowledge base"),
    ("estimator_confirmed", "an estimator"),
    ("llm_full_extract", "Grok (xAI)"),
    ("inference", "engine inference"),
    ("title_block", "the title block"),
])
def test_it_names_the_source_the_waterfall_recorded(source, expect):
    """Named by source_precedence, so a source the waterfall knows about cannot render as an
    internal key — or, worse, as a different source entirely."""
    got = dr._mat_source_explanation(_part(material_source=source))
    assert expect in got, f"{source!r} rendered as {got!r}"


def test_a_deterministic_read_is_never_called_ai():
    """THE EXACT CONTRADICTION. This is the string that was on the sheet."""
    got = dr._mat_source_explanation(_part(material_source="drawing_deterministic"))
    assert "AI inference" not in got, got
    assert "Grok" not in got, got


def test_it_does_not_depend_on_geometry_source_being_set():
    """The whole cause. A PDF-only part has no geometry_source, and the two files defaulted it
    differently — so the answer must not turn on it at all."""
    with_geo = dr._mat_source_explanation(_part(material_source="drawing_deterministic",
                                                geometry_source="pdf"))
    without = dr._mat_source_explanation(_part(material_source="drawing_deterministic"))
    assert with_geo == without, (
        "the explanation still changes with geometry_source: %r vs %r" % (with_geo, without))


# ── measured and reasoned are marked differently ─────────────────────────────

def test_a_measured_source_is_ticked_and_a_reasoned_one_is_not():
    """The distinction the waterfall exists to make: a number off a model can be held against
    the model, a number off a language model cannot. The marks must not be decoration."""
    measured = dr._mat_source_explanation(_part(material_source="solidworks_api"))
    reasoned = dr._mat_source_explanation(_part(material_source="llm_full_extract"))
    assert measured.startswith("✅"), measured
    assert reasoned.startswith("⚡"), reasoned


def test_the_marks_follow_the_ranking_module_not_a_list_kept_here():
    """A private copy of "which sources counted as measured" is how the two tabs drifted apart
    in the first place. Checked against source_precedence itself, so adding a source there is
    enough."""
    for source in sorted(sp.MEASURED_SOURCES):
        if source in ("solidworks_applied_material",):   # deliberately not a material spec
            continue
        got = dr._mat_source_explanation(_part(material_source=source))
        assert got.startswith("✅"), f"{source} is a MEASURED source but renders {got!r}"


# ── nothing recorded is still answered ───────────────────────────────────────

def test_a_part_with_no_recorded_source_still_gets_an_explanation():
    """A guess stated as a guess beats a blank cell. The heuristics stay for this case."""
    got = dr._mat_source_explanation(_part())
    assert got and got.strip() not in ("", "—")


def test_unknown_is_not_treated_as_a_source():
    """`unknown` renders as "an unrecorded source", which said after "Read from" is worse than
    falling through to the heuristics that may still recognise the part."""
    got = dr._mat_source_explanation(_part(material_source="unknown",
                                           dxf_source_file="10575-01-001_MS_1.2mm_Rev D.DXF"))
    assert "unrecorded source" not in got, got
    assert "Mild Steel" in got or "MS" in got, got


def test_a_bought_in_part_is_still_answered_as_bought_in():
    """Bought-in has no fabrication material, and running it through the material heuristics
    misreads the part-number suffix. That guard runs BEFORE any of this and must stay first."""
    got = dr._mat_source_explanation({"part_number": "BI-BOLT", "is_bought_in": True,
                                      "description": "M6x10mm C/SUNK BOLT; BLACK"})
    assert "Bought-in" in got, got
