"""AN EMPTY BEND LAYER DOES NOT UNFOLD A Z-BAR (reviewer, 12 Nov 2026).

"Retain required operations: a missing DXF bend layer must not silently erase stronger
drawing/model evidence of folding." A WALL FIXED Z-BAR was ruled "DXF flat pattern measured 0
bend lines — the part does not fold" and charged no folding; the UNIT FIXED Z-BAR beside it,
whose bend text was read, was folded.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config  # noqa: E402
import drawing_job_merge as M  # noqa: E402
import estimator as E  # noqa: E402


def _zbar(**over):
    p = {"part_number": "10000-02-01-12M", "description": "WALL FIXED Z-BAR",
         "normalized_material": "MILD_STEEL", "material": "MILD STEEL",
         "normalized_thickness_mm": 2.0, "thickness_mm": 2.0,
         "manufacturing_features": {"bend_count": 0, "bend_count_source": "dxf_bendlines"}}
    p.update(over)
    return p


def test_a_z_bar_is_a_formed_shape_of_two_folds():
    assert config.FORMED_SHEET_SHAPE_FOLDS["Z-BAR"] == 2 and config.FORMED_SHEET_SHAPE_FOLDS["Z BAR"] == 2
    assert M.shape_that_cannot_be_flat(_zbar()) == "Z-BAR"
    assert M.shape_that_cannot_be_flat(_zbar(description="UNIT FIXED Z BAR")) == "Z BAR"


def test_a_zero_from_the_export_is_not_a_measured_zero_for_a_named_shape():
    assert E._model_measured_zero_bends(_zbar()) is False
    plain = _zbar(description="COVER PLATE")
    plain["manufacturing_features"]["bend_count_source"] = sorted(E._MEASURED_BEND_SOURCES)[0]
    assert E._model_measured_zero_bends(plain) is True, "a plate that measured no bends still does not fold"


def test_a_solid_the_model_measured_flat_is_flat_whatever_it_is_called():
    flat = _zbar(native_flat_solid=True)
    assert M.shape_that_cannot_be_flat(flat) is None
    assert E._model_measured_zero_bends(flat) is True


def test_a_shape_word_names_no_fold_on_a_board_or_a_bought_section():
    assert M.shape_that_cannot_be_flat(_zbar(normalized_material="MDF")) is None
    assert M.shape_that_cannot_be_flat(_zbar(description="Z-BAR 25X25X3", )) is None
    assert M.shape_that_cannot_be_flat(_zbar(normalized_thickness_mm=None, thickness_mm=None)) is None


def test_the_ruling_is_withheld_and_said_where_the_shape_is_named():
    src = (ROOT / "src" / "drawing_job_merge.py").read_text(encoding="utf-8")
    at = src.index("_shape_named = shape_that_cannot_be_flat(part) if _can_rule_out else None")
    block = src[at:at + 700]
    assert "_can_rule_out = False" in block and "cannot be flat: folding is kept" in block
    assert at < src.index('"DXF flat pattern measured 0 bend lines — the part does not fold")')
