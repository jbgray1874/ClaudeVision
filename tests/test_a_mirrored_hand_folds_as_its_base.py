"""12173-02 Card Spinner, 17:34 book (D-380): 12173-04-02M was charged 1 fold (one angle read
as the fold note) and its mirrored hand 02M-H 4 (the model's bend features, copied without the
note). Same flat, opposite hand. Its sheet prints two bend callouts; the model has four
features, which confirms them.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import drawing_job_merge as djm                                       # noqa: E402
import fold_count as fc                                               # noqa: E402


def _pair():
    base = {"part_number": "12173-04-02M", "pages": [1], "fold_count_textual": 0,
            "angles_deg": [90], "solidworks_bend_features": 4, "drawing_bend_callouts": 2,
            "geometry_rollup": {"dashed_long_axis_lines": 2},
            "normalized_geometry": {"blank_length_mm": 280.97, "blank_width_mm": 159.24,
                                    "geometry_source": "dxf_flat_pattern"}}
    hand = {"part_number": "12173-04-02M-H", "pages": [15], "fold_count_textual": 0,
            "solidworks_bend_features": 4,
            "normalized_geometry": {"blank_length_mm": 280.97, "blank_width_mm": 159.24,
                                    "mirrored_from": "12173-04-02M"}}
    return base, hand


def test_callouts_the_model_confirms_beat_a_note_that_counts_fewer():
    base, _ = _pair()
    got = fc.press_brake_folds(base)
    assert (got["count"], got["source"]) == (2, fc.CALLOUTS_AND_MODEL)


def test_a_note_alone_still_stands_against_the_model_alone():
    part = {"angles_deg": [90], "solidworks_bend_features": 4}
    assert fc.press_brake_folds(part)["count"] == 1


def test_the_hand_is_charged_what_its_base_is_charged():
    base, hand = _pair()
    assert fc.press_brake_folds(hand)["count"] == 4          # today's fault, reproduced
    assert djm.settle_mirrored_folds([base, hand]) == 1
    b, h = fc.press_brake_folds(base), fc.press_brake_folds(hand)
    assert h["count"] == b["count"] == 2
    assert h["source"] == b["source"]
    assert h["mirrored_from"] == "12173-04-02M"
    assert "the hand this part mirrors" in h["source_label"]


def test_a_hand_with_its_own_sheet_callouts_keeps_its_reading():
    base, hand = _pair()
    hand["drawing_bend_callouts"] = 3
    hand["drawing_bend_callouts_source"] = "drawing_deterministic"
    assert djm.settle_mirrored_folds([base, hand]) == 0
    assert "mirrored_fold_evidence" not in hand


def test_a_hand_with_its_own_flat_is_not_settled():
    base, hand = _pair()
    hand["normalized_geometry"].pop("mirrored_from")
    assert djm.settle_mirrored_folds([base, hand]) == 0


def test_the_portal_path_settles_after_every_reading_is_in():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    i = src.index("stamp_drawing_bend_callouts(summary[\"manufacturing_writeup\"][\"parts\"]")
    assert i < src.index(
        "settle_mirrored_folds(summary[\"manufacturing_writeup\"][\"parts\"], summary)")
