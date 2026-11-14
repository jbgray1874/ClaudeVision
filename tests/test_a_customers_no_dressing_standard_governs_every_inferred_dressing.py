"""A customer's no-dressing standard governs every inferred dressing, whoever inferred it.

11896-08-02-GA and 11896-01-00-GA, 14 Nov 2026. "TTI none (no weld dressing)" (Howard
Thurley, SDI estimating, 15 Sep 2026) stopped the engine adding Dress Welds itself, and the
top assembly's line said so. The welded sub-assemblies under it were still charged dressing,
Estimate rows 177 to 180, £68.93 a unit on 11896-08-02-GA: theirs arrived from the pack
read as an inference ("Dress is not printed. One dressing per upright") and the standard was
never asked about it.

The customer and codes here are this test's own.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator as E  # noqa: E402
import route_compiler as rc  # noqa: E402

NONE = {"dress_visible_welds": False, "customer": "ACME", "statement": "ACME none (no weld dressing)",
        "stated_by": "an estimator", "stated_on": "2026-09-15"}
ALL = {"dress_visible_welds": True, "customer": "BRAVO", "statement": "BRAVO dress all seen welds",
       "stated_by": "an estimator", "stated_on": "2026-09-15"}


def _weldment(dress_source="inference", standard=NONE):
    part = {"part_number": "T-08-101", "description": "UPRIGHT - WELDED ASSEMBLY", "quantity": 1,
            "normalized_material": "MILD_STEEL", "is_assembly_parent": True,
            "assembly_children": ["T-08-01M", "T-08-11M"],
            "textual_operations": ["welding", "dress_welds", "handling"],
            "operation_sources": {"welding": "drawing_deterministic", "dress_welds": dress_source,
                                  "handling": "inference"}}
    if standard:
        part["_customer_finish_standard"] = dict(standard)
    return part


def _times(part):
    return E.estimate_process_times(part, 1).get("unit_times_min") or {}


def test_an_inferred_dressing_is_ruled_out_where_the_customers_standard_is_none():
    part = _weldment()
    times = _times(part)
    assert "dress_welds" not in times and "welding" in times, times
    why = part["operations_ruled_out"]["dress_welds"]
    assert "ACME none (no weld dressing)" in why and "inferred, not stated" in why
    assert any("weld dressing NOT charged" in f for f in part["review_flags"])


def test_the_ruling_stands_above_an_inference_and_below_what_a_drawing_states():
    part = _weldment()
    _times(part)
    src = part["operation_ruling_sources"]["dress_welds"]
    import source_precedence as sp
    assert sp.rank("inference") < sp.rank(src) < sp.rank("drawing_deterministic")
    assert rc._ruling_source(part, "dress_welds", part["operations_ruled_out"]["dress_welds"]) == src


def test_a_dressing_the_drawing_states_is_still_charged():
    part = _weldment(dress_source="drawing_deterministic")
    assert "dress_welds" in _times(part)
    assert "dress_welds" not in (part.get("operations_ruled_out") or {})


def test_a_customer_whose_standard_is_to_dress_keeps_the_inferred_dressing():
    part = _weldment(standard=ALL)
    assert "dress_welds" in _times(part)
    assert "dress_welds" not in (part.get("operations_ruled_out") or {})


def test_a_customer_with_no_stated_standard_keeps_the_inferred_dressing():
    part = _weldment(standard=None)
    assert "dress_welds" in _times(part)


def test_a_dressing_with_no_recorded_source_is_kept_because_it_may_be_the_drawings():
    part = _weldment(dress_source="")
    assert "dress_welds" in _times(part)
    assert "dress_welds" not in (part.get("operations_ruled_out") or {})
