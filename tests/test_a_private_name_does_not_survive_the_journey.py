"""Forty minutes of brushing became forty-six seconds, and the only difference was one
underscore.

7332-01's 11:29 book, row 104:

    Manual labour (Metal) — 1.2mm MILD STEEL (7332-01-101)   MANM   79/hr

79 pieces an hour is 46 seconds. Howard Thurley stated FORTY MINUTES, and the run before
this one put it on the sheet correctly at 1.50/hr. It was not lost to a costing rule. It was
lost to a name.

THE THREE MARKERS THAT LANDED AND THE ONE THAT DID NOT:

    weld_time_is_an_allowance     landed
    weld_time_is_per_joint        landed
    plater_pack_applied           landed
    _brush_before_plate_applied   did not

record_merge.mergeable_keys and route_compiler's member fold both skip any key starting with
an underscore — deliberately, because a leading underscore in this codebase means "working
state, private to the module that set it", and working state must not be copied between two
records being merged into one. That convention is right. The marker was simply on the wrong
side of it: it is not working state, it is a FACT about the part that has to reach the
workbook three stages later.

So the sheet asked "does 7332-01-101 carry a stated shop time for manual_labour_metal?",
the flag had been dropped in a fold, the answer came back no, and the row took the
department's median of every MANM job in the corpus.

IT WAS ALSO THE ONE I ADDED. The other three were written by someone following the
convention; this one was written in the same commit that scoped claims to operations, whose
whole purpose was to stop brushing being timed by accident off the weld claim. It stopped
being timed by accident and was not timed on purpose either.

A convention that is only in people's heads gets broken by the next person, so this is the
test rather than the rename: no marker may be named in a way the record merge will throw
away, and the next one added is checked the same way.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import wb_populate as wb                                                # noqa: E402
import record_merge                                                     # noqa: E402


def test_no_stated_time_marker_is_dropped_by_a_record_merge():
    """THE RULE, ASKED OF EVERY MARKER — the three that work and the next one written."""
    for marker, ops, why in wb._STATED_SHOP_TIME_MARKERS:
        assert not marker.startswith("_"), (
            f"{marker} starts with an underscore, so record_merge and route_compiler drop "
            f"it when two records for one part are folded together. The workbook then asks "
            f"whether this part carries a stated shop time, gets no for an answer, and "
            f"prints a corpus median over a figure a department gave us.")


def test_the_brushing_marker_is_the_one_this_caught():
    names = [m for m, _ops, _why in wb._STATED_SHOP_TIME_MARKERS]
    assert "brush_before_plate_applied" in names
    assert "_brush_before_plate_applied" not in names


def test_the_estimator_stamps_the_name_the_workbook_reads():
    """Two spellings of one fact is the defect this session keeps finding. Renaming the
    marker in one file and not the other would have been that defect again, with the
    brushing still missing and the test still green."""
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert 'part["brush_before_plate_applied"] = True' in src
    assert '"_brush_before_plate_applied"' not in src


def test_the_merge_really_does_drop_private_keys():
    """The premise, asserted rather than assumed — if this convention ever changed, the
    test above would be guarding nothing and should be the thing that tells us."""
    keys = record_merge._mergeable_fields(
        {"part_number": "X", "brush_before_plate_applied": True,
         "_brush_before_plate_applied": True}, skip=())
    assert "brush_before_plate_applied" in keys
    assert "_brush_before_plate_applied" not in keys


def test_route_compiler_folds_on_the_same_rule():
    """The other place a part's record is merged into a survivor."""
    src = (ROOT / "src" / "route_compiler.py").read_text(encoding="utf-8")
    assert 'str(key).startswith("_")' in src
