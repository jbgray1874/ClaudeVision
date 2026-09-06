"""The two 7332 defects that move money: a guessed section length, and a fabricated part
published as bought-in.

1. Section stock is priced PER METRE, so the length is the money. _infer_section_length_mm
   tries four real sources and then falls back to "the largest dimension on the part" — and
   nothing downstream could tell that guess from a cut-list reading, because it returned a bare
   float either way. On 7332-01-002 the fallback produced a 1.4 m leg for an A3 stand: £5.86
   each, 24% of the job's material, and 1.5 kg carried into the plating mass. Two independent
   figures agreed on the fiction (the price inverts to 0.773 kg/leg; the plate mass leaves
   0.761 kg/leg), which is exactly why it survived so long.

2. bought_in_policy already states the rule — "a part with its own measured flat is a
   fabricated leaf whatever a transcribed hierarchy says" — but it was only used to RAISE a
   conflict, never to decide the kind. So 7332-01-001 BASE, nested as 5 mm steel and charged
   £3.03 of laser, was published as "bought_in" on the Canonical BOM and provenance tab.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator as e  # noqa: E402
import route_compiler as rc  # noqa: E402


# ── 1. a length nobody stated is not a length ────────────────────────────────
def _leg(**over):
    part = {"part_number": "7332-01-002", "description": "LEG",
            "normalized_material": "MILD STEEL", "quantity": 2,
            "section_stock": {"a": 15.88, "b": 15.88, "t": 1.2}}
    part.update(over)
    return part


def test_the_length_search_records_which_source_it_used():
    part = _leg(section_stock={"a": 15.88, "b": 15.88, "t": 1.2, "length_mm": 420.0})
    assert e._infer_section_length_mm(part) == 420.0
    assert part["_section_length_source"] == "section_stock_cut_list"

    guessed = _leg(all_dimensions_mm=[1400.0, 15.88, 297.0])
    assert e._infer_section_length_mm(guessed) == 1400.0
    assert guessed["_section_length_source"] == "largest_dimension_guess"


def test_a_guessed_section_length_is_not_priced():
    """THE DEFECT. The largest dimension on a drawing is as likely to be the assembly's
    overall size as this part's cut length — priced per metre, that guess IS the money."""
    part = _leg(all_dimensions_mm=[1400.0, 15.88, 297.0])
    pe = e.estimate_part(part, job_quantity=6)
    assert (pe.get("material_estimate") or {}).get("unit_material_cost_gbp") is None
    assert any("NOT STATED" in f for f in (part.get("review_flags") or [])), \
        "the line must say why it carries no price"


def test_a_stated_cut_length_still_prices_exactly_as_before():
    """The guard must not cost a job its section material where a real length exists."""
    part = _leg(section_stock={"a": 15.88, "b": 15.88, "t": 1.2, "length_mm": 420.0})
    pe = e.estimate_part(part, job_quantity=6)
    assert (pe.get("material_estimate") or {}).get("unit_material_cost_gbp") > 0
    assert not any("NOT STATED" in f for f in (part.get("review_flags") or []))


# ── 2. measured geometry of its own outranks a transcribed role ──────────────
def test_a_part_with_its_own_measured_flat_is_not_published_as_bought_in():
    base = {"part_number": "7332-01-001", "description": "BASE",
            "normalized_material": "MILD STEEL",
            "page_roles": ["bought_in"],              # the transcribed role
            "blank_length_mm": 453.0, "blank_width_mm": 300.0,
            "flat_pattern_detected": True,
            "dxf_source_file": "7332-01-001_5mm MS_revK.DXF"}
    assert rc._bought_in_record(base) is False
    assert {n.part_number: n.kind for n in rc.build_part_graph([base], {})["nodes"]} == {
        "7332-01-001": "leaf"}


def test_a_genuine_bought_in_is_untouched():
    """Narrowness is the point — a castor has a role and no measured flat, and stays bought-in."""
    castor = {"part_number": "BI-CASTOR", "description": "CASTOR", "page_roles": ["bought_in"]}
    assert rc._bought_in_record(castor) is True
    assert {n.part_number: n.kind for n in rc.build_part_graph([castor], {})["nodes"]} == {
        "BI-CASTOR": "bought_in"}
