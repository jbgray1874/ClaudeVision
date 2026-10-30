"""A tube read from the weldment cut list reaches the estimate as a costable section.

The frame's tube sizes live in the SolidWorks weldment cut list — the analyser reads the member
Description and LENGTH into the property set it already enumerates, but never turned them into a
section, so the Wire block came through empty. Now:
  * the analyser extracts a section from the cut-list properties it already holds
    (weldment_section_from_cutlist — no new SolidWorks call), and
  * the connector adopts it onto the part's section_stock, which the existing tube-costing path
    and the workbook's section block already price.

The COM enumeration that fills the property set needs a SolidWorks seat and is exercised on the
box; the extraction and the hand-off — the parts that were actually missing — are pure and proven
here. A part that already carries a drawing-stated section is never overwritten.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "solidworks"))

import sw_native_analyse as swa  # noqa: E402
from source_connectors import solidworks as sw  # noqa: E402


# ── the analyser extracts a section from cut-list properties it already has ───────────────
def test_a_square_tube_member_yields_a_full_section():
    props = {"Description": "TUBE, SQUARE 30 X 30 X 2.6", "LENGTH": "1125.00",
             "MATERIAL": "Mild Steel", "QUANTITY": "4"}
    sec = swa.weldment_section_from_cutlist(props)
    assert sec["a"] == 30.0 and sec["b"] == 30.0 and sec["t"] == 2.6
    assert sec["profile_form"] == "SHS"
    assert sec["length_mm"] == 1125.0
    assert sec["review_section_profile"] is True


def test_a_member_with_a_profile_but_no_length_still_reads():
    """The connector fills the length from the model bounding box, so a profile alone is useful."""
    sec = swa.weldment_section_from_cutlist({"Description": "RHS 60 X 40 X 3"})
    assert sec["profile_form"] == "RHS" and "length_mm" not in sec


def test_a_non_section_member_is_not_read_as_a_tube():
    assert swa.weldment_section_from_cutlist({"Description": "GUSSET PLATE 100 X 100 X 3"}) is None
    assert swa.weldment_section_from_cutlist({}) is None


# ── the connector adopts the section onto the part ───────────────────────────────────────
def _job_with_section(section):
    rec = [{"title": "8352-FRAME-01", "doctype": 1,
            "route_signals": {"material": "Mild Steel", "has_weldment": True,
                              "section_profile": section}}]
    return sw.normalize_native_extract(rec)


def test_the_connector_carries_the_section_onto_the_native_part():
    job = _job_with_section({"a": 30.0, "b": 30.0, "t": 2.6, "profile_form": "SHS",
                             "length_mm": 1125.0})
    assert job.part_signals["8352-FRAME-01"].section_profile["profile_form"] == "SHS"


def test_the_apply_step_sets_section_stock_so_the_tube_is_costed():
    """THE PAYOFF. A frame part with no section gets one from the weldment cut list, plus a
    'section' role so the workbook routes it to the section/BOM block, not a blank."""
    job = _job_with_section({"a": 30.0, "b": 30.0, "t": 2.6, "profile_form": "SHS",
                             "length_mm": 1125.0})
    part = {"part_number": "8352-FRAME-01", "normalized_material": "MILD STEEL"}
    sw.apply_native_to_pre_estimate([part], job)
    assert part.get("section_stock", {}).get("length_mm") == 1125.0
    assert "section" in [str(r).lower() for r in (part.get("page_roles") or [])]


def test_a_drawing_stated_section_is_never_overwritten():
    """A section the drawing already stated stands — the model's read fills a gap, never
    replaces a printed figure."""
    job = _job_with_section({"a": 30.0, "b": 30.0, "t": 2.6, "profile_form": "SHS",
                             "length_mm": 1125.0})
    part = {"part_number": "8352-FRAME-01",
            "section_stock": {"a": 40, "b": 40, "t": 3, "length_mm": 500,
                              "detection_path": "drawing"}}
    sw.apply_native_to_pre_estimate([part], job)
    assert part["section_stock"]["detection_path"] == "drawing"


def test_a_part_with_no_weldment_section_is_unaffected():
    job = _job_with_section(None)
    part = {"part_number": "8352-FRAME-01"}
    sw.apply_native_to_pre_estimate([part], job)
    assert part.get("section_stock") is None
