r"""
test_a_dashed_line_is_not_a_bend.py

THE MODEL COUNTED THE BENDS. THE FOLD ROW WAS BILLED FROM DASHED LINES ON A PDF.

Two fields hold one fact. The SolidWorks connector wrote manufacturing_features.bend_count;
the estimator folds by geometry_rollup.estimated_bend_line_count, which the PDF vector scan
fills from dashed_long_axis_lines. Nothing carried the model's number into the field that
costs, so the two never met:

    estimator.py:4290
        _bends = _safe_int(part.get("bend_count_dxf")) \
                 or _safe_int(_geom.get("estimated_bend_line_count")) or 0

On 12552 every part's estimated_bend_line_count equalled its dashed_long_axis_lines exactly,
model or no model:

    02-06M  LARGE TRAY BODY     26 dashed lines      6 bends in the cut list
    02-07M  SMALL TRAY BODY     28 dashed lines      8 bends in the cut list
    02-04M  LATCH MECHANISM      1 dashed line       5 bends in the cut list

The first two are the largest fabricated lines on that bay, each folded about twenty times
for folds that do not exist. Where the two happened to agree — 01-04M at 5, 01-05M at 4 —
that was coincidence, and it is why the run's own "bends+7" summary looked like the model
had been applied when it had reached seven records out of nineteen.

RAISE-ONLY WOULD NOT FIX IT. The existing guard only lifts bend_count when the model reads
HIGHER. Here the model reads LOWER than the drawing scan, which is the entire complaint: a
dashed line is not a bend. Under-counting by the feature tree is a real hazard and has its
own answer already — formed_but_no_bend_features — which fires before a zero is believed.

Applied through source_precedence at rank 90, like the cut length and pierce count beside
it, so an estimator's own figure still wins and a disagreement is recorded on the part
rather than silently overwritten.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from source_connectors.solidworks import (  # noqa: E402
    apply_native_to_pre_estimate, normalize_native_extract,
)


def _extract(part_number: str, bends: int, thickness: float = 1.5) -> dict:
    """One record in the shape the SOLIDWORKS sidecar actually writes."""
    return {
        "title": part_number,
        "doctype": 1,
        "path": rf"K:\Live Enquiry\{part_number}.SLDPRT",
        "route_signals": {
            "part_number": part_number,
            "material": "Mild Steel [CR4]",
            "material_source": "applied_library",
            "thickness_mm": thickness,
            "is_sheet_metal": True,
            "bend_count": bends,
            "bend_count_cutlist": bends,
            "bend_radius_mm": 1.5,
            "flat_length_mm": 1486.53,
            "flat_width_mm": 701.53,
            "flat_pattern_present": True,
            "cut_length_mm": 12222.55,
            "cut_out_count": 49,
        },
    }


def _part(part_number: str, dashed: int) -> dict:
    """The pre-estimate record, carrying the PDF scan's dashed-line count."""
    return {
        "part_number": part_number,
        "description": "SMALL TRAY BODY",
        "normalized_material": "MILD STEEL",
        "page_roles": ["detail"],
        "geometry_rollup": {
            "estimated_bend_line_count": dashed,
            "dashed_long_axis_lines": dashed,
            "confidence": {"geometry_reliability": 1.0},
        },
    }


def _bend_line_count(part: dict):
    return (part.get("geometry_rollup") or {}).get("estimated_bend_line_count")


def test_the_cut_list_beats_the_dashed_lines():
    """02-07M: the model says 8, the drawing scan said 28. Fold hours follow the model."""
    part = _part("12552-02-07M", dashed=28)
    job = normalize_native_extract([_extract("12552-02-07M", bends=8)])
    apply_native_to_pre_estimate([part], job)

    assert _bend_line_count(part) == 8, (
        f"The fold row is still costed on {_bend_line_count(part)} bends. The SolidWorks cut "
        f"list says 8; 28 is the number of dashed lines on the PDF, and a dashed line is not "
        f"a bend. This is the field the estimator folds by."
    )
    assert (part.get("manufacturing_features") or {}).get("bend_count") == 8, (
        "The two fields must not disagree once the model has spoken — that split is the "
        "defect this test exists for."
    )


def test_the_disagreement_is_recorded_not_swallowed():
    """Twenty folds leaving a part is a change somebody should be able to see."""
    part = _part("12552-02-07M", dashed=28)
    job = normalize_native_extract([_extract("12552-02-07M", bends=8)])
    apply_native_to_pre_estimate([part], job)

    flags = " ".join(str(f) for f in (part.get("review_flags") or []))
    assert "28" in flags and "8" in flags, (
        f"Both figures must be on the record so a human can check which is right: {flags!r}"
    )


def test_the_model_still_raises_an_undercount():
    """The pre-existing direction must keep working: model higher than the scan wins too."""
    part = _part("12552-02-04M", dashed=1)
    job = normalize_native_extract([_extract("12552-02-04M", bends=5)])
    apply_native_to_pre_estimate([part], job)
    assert _bend_line_count(part) == 5, (
        f"The latch mechanism has 5 bends in the cut list and 1 dashed line on the sheet; "
        f"got {_bend_line_count(part)}. Fixing the over-count must not break the under-count."
    )


def test_agreement_leaves_the_number_alone():
    """01-04M: model 5, scan 5. Nothing to change, and nothing to flag."""
    part = _part("12552-01-04M", dashed=5)
    job = normalize_native_extract([_extract("12552-01-04M", bends=5)])
    apply_native_to_pre_estimate([part], job)
    assert _bend_line_count(part) == 5
    flags = " ".join(str(f) for f in (part.get("review_flags") or []))
    assert "bend count:" not in flags, (
        f"A value that did not change is not a disagreement worth a flag: {flags!r}"
    )
