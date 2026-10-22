"""An arrangement drawing's notes describe its members — its glue is their glue.

WHAT THE ESTIMATOR SAW. 12349-02's labour sheet carried "Glue — 6mm TIMBER (12349-02-69)":
a bonding charge against the general-arrangement record itself, minted from the word GLUE
in the arrangement drawing's own notes. His comment was a question — "A glue op included on
12349-02-69 for timber. (What op is this for?)" — and it has no answer, because the gluing
that note calls up is performed on the MEMBERS and is already charged there: the acrylic
route books the UV bond on the bonded assembly, the timber allowance books glue on the
timber leaves.

THE PREDICATE, AND WHY IT IS NOT "THE ROOT". A weldment that tops its own job — 7332-01-101
STAND WELD ASSY over leaf plates — is a root and genuinely performs its joining; the bonded
acrylic assembly 12349-02-69-01A keeps its UV glue for the same reason. Both have only
LEAVES below them. What marks a node as paper rather than a bench is having another
ASSEMBLY below it: 12349-02-69's members include 01A, so its notes are about its members.
That is `is_arrangement_parent`, stamped in drawing_job_merge where the whole population is
visible, and read at the one point glue minutes are booked.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from drawing_job_merge import _stamp_assembly_parents                   # noqa: E402
from estimator import estimate_process_times                            # noqa: E402


def _job_like_12349():
    """The shape of the golden pack: an arrangement over a bonded sub-assembly and leaves."""
    return [
        {"part_number": "12349-02-69", "description": "RETAILER UNIT GA",
         "textual_operations": ["glue"]},
        {"part_number": "12349-02-69-01A", "description": "ACRYLIC ASSEMBLY",
         "textual_operations": ["glue"]},
        {"part_number": "12349-02-69-01A-01", "description": "FRONT 2MM",
         "geometry_source": "dxf"},
        {"part_number": "12349-02-69-01A-02", "description": "SIDE 3MM",
         "geometry_source": "dxf"},
        {"part_number": "12349-02-69-03M-01", "description": "BRACKET",
         "geometry_source": "dxf"},
        {"part_number": "12349-02-69-04M", "description": "MDF PACKER"},
    ]


def _by_pn(parts):
    return {p["part_number"]: p for p in parts}


def test_the_arrangement_is_stamped_and_the_bonded_assembly_is_not():
    parts = _job_like_12349()
    _stamp_assembly_parents(parts)
    rec = _by_pn(parts)
    assert rec["12349-02-69"].get("is_arrangement_parent"), \
        "the GA node holds another assembly (01A) — it is an arrangement"
    assert not rec["12349-02-69-01A"].get("is_arrangement_parent"), \
        "01A has only leaves below it — its UV bond is its own bench work"


def test_a_weldment_over_leaf_plates_is_not_an_arrangement():
    """7332-01-101's shape: the top of its job, and every child a plate it welds."""
    parts = [
        {"part_number": "7332-01-101", "description": "STAND WELD ASSY",
         "textual_operations": ["welding"]},
        {"part_number": "7332-01-101-01", "description": "PLATE", "geometry_source": "dxf"},
        {"part_number": "7332-01-101-02", "description": "PLATE", "geometry_source": "dxf"},
    ]
    _stamp_assembly_parents(parts)
    assert not parts[0].get("is_arrangement_parent"), \
        "a weldment performs its own joining — being the top of the job does not make it paper"


def test_no_glue_minutes_on_the_arrangement():
    """The exact defect: the GA record with a note-minted glue op books no glue time."""
    parts = _job_like_12349()
    _stamp_assembly_parents(parts)
    ga = _by_pn(parts)["12349-02-69"]
    times = estimate_process_times(ga)
    assert "glue" not in (times.get("run_times_min_per_unit") or {})
    assert "glue" not in (times.get("setup_times_min") or {})
    assert any("not charged here" in str(f).lower() for f in ga.get("review_flags") or []), \
        "the suppression must be stated on the record, not silent"
    # And the record itself no longer claims the op, so the route-decision report cannot
    # print "glue required" beside a sheet with no glue row.
    assert "glue" not in (ga.get("textual_operations") or [])
    assert "glue" in (ga.get("removed_operations") or [])


def test_a_glue_op_that_arrives_after_the_stamp_still_books_nothing():
    """Belt and braces: ops can land on a record after the merge pass. The charge point
    itself refuses glue on a stamped arrangement."""
    ga = {"part_number": "12349-02-69", "description": "RETAILER UNIT GA",
          "is_arrangement_parent": True, "textual_operations": ["glue"]}
    times = estimate_process_times(ga)
    assert "glue" not in (times.get("run_times_min_per_unit") or {})


def test_the_bonded_sub_assembly_keeps_its_glue():
    """01A stays: same word on the drawing, but the bench work is its own."""
    parts = _job_like_12349()
    _stamp_assembly_parents(parts)
    sub = _by_pn(parts)["12349-02-69-01A"]
    times = estimate_process_times(sub)
    assert (times.get("run_times_min_per_unit") or {}).get("glue") == 1.0


def test_a_leaf_with_a_glue_note_is_untouched():
    """The gate is about arrangements, not about glue."""
    leaf = {"part_number": "X-01", "description": "BONDED LENS",
            "textual_operations": ["glue"]}
    times = estimate_process_times(leaf)
    assert (times.get("run_times_min_per_unit") or {}).get("glue") == 1.0


def test_a_described_assembly_child_also_marks_an_arrangement():
    """The hierarchy is not always in the numbers: a parent whose recorded
    assembly_children include another parent is an arrangement by the same rule."""
    parts = [
        {"part_number": "9000-100", "description": "DISPLAY WITH STAND ASSY",
         "is_assembly_parent": True, "assembly_children": ["9000-200"],
         "textual_operations": ["glue"]},
        {"part_number": "9000-200", "description": "STAND ASSY", "is_assembly_parent": True},
        {"part_number": "9000-201", "description": "LEG", "geometry_source": "dxf"},
    ]
    _stamp_assembly_parents(parts)
    assert parts[0].get("is_arrangement_parent")
