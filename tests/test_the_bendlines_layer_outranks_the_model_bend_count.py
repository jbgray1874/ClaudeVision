r"""
test_the_bendlines_layer_outranks_the_model_bend_count.py

THE PRESS BRAKE BENDS FROM THE FLAT, NOT THE MODEL.

Two sources count folds: the DXF BENDLINES layer (bend_count_dxf) and the SOLIDWORKS API
(which can overwrite geometry_rollup.estimated_bend_line_count). On 11762-02-02M the DXF
BENDLINES layer carried 5 folds and the SW value was 4, so the Fold op was booked one bend
light -- about GBP 0.60.

The rule matches the one the fold rule-out already uses: the DXF BENDLINES count is ground
truth and WINS where both exist; SW fills the gap only where the DXF measured no bend layer;
and a disagreement is flagged, never taken silently.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feature_synthesis import infer_bend_count                    # noqa: E402
from drawing_job_merge import bend_count_disagreement             # noqa: E402


def _dxf_flat(bend_count_dxf=None, rollup_bends=0):
    """A part the merge marks as a genuine flat-pattern DXF."""
    part = {"flat_pattern_detected": True, "geometry_source": "dxf_flat_pattern",
            "geometry_rollup": {"estimated_bend_line_count": rollup_bends}}
    if bend_count_dxf is not None:
        part["bend_count_dxf"] = bend_count_dxf
    return part


# ── the count that feeds Fold labour ────────────────────────────────────────────────
def test_the_bendlines_layer_wins_over_an_sw_rollup_that_disagrees():
    """11762-02-02M exactly: BENDLINES 5, SW-filled rollup 4 -> 5 folds, not 4."""
    part = _dxf_flat(bend_count_dxf=5, rollup_bends=4)
    assert infer_bend_count(part, 1.0) == 5


def test_sw_fills_the_gap_when_the_dxf_has_no_bend_layer():
    """bend_count_dxf is absent when the BENDLINES layer measured zero (a cut-only export sets
    none). The rollup's authoritative value still decides, so a 0-fold part stays 0."""
    assert infer_bend_count(_dxf_flat(bend_count_dxf=None, rollup_bends=0), 1.0) == 0
    assert infer_bend_count(_dxf_flat(bend_count_dxf=None, rollup_bends=3), 1.0) == 3


def test_a_measured_zero_on_the_bendlines_layer_is_honoured_not_overridden():
    """If the layer is present and measured 0, bend_count_dxf is not set (>0 gate upstream), so
    we do NOT force a phantom fold; the rollup's measured zero stands."""
    assert infer_bend_count(_dxf_flat(bend_count_dxf=None, rollup_bends=0), 1.0) == 0


def test_the_two_counts_agreeing_is_unremarkable():
    """When BENDLINES and the rollup agree, the answer is that number and nothing is flagged."""
    assert infer_bend_count(_dxf_flat(bend_count_dxf=3, rollup_bends=3), 1.0) == 3


def test_a_non_dxf_flat_part_is_untouched_by_this_rule():
    """The BENDLINES preference lives in the DXF-flat branch only; a text-only part still runs
    the proxy logic and is not reached by bend_count_dxf."""
    text_part = {"flat_pattern_detected": False, "geometry_source": "drawing_text",
                 "geometry_rollup": {"estimated_bend_line_count": 0},
                 "angles_deg": [90, 90], "fold_values_mm": [], "fold_count_textual": 0}
    # two text angles -> the proxy path returns a text signal, not anything from bend_count_dxf
    assert infer_bend_count(text_part, 0.0) == 2


# ── the disagreement is spoken, only when it is real ────────────────────────────────
def test_a_disagreement_is_flagged_and_names_both_counts():
    msg = bend_count_disagreement(5, 4)
    assert msg is not None
    assert "DXF BENDLINES layer shows 5" in msg
    assert "SOLIDWORKS bend count shows 4" in msg
    assert "so 5 is used" in msg


def test_agreement_says_nothing():
    assert bend_count_disagreement(4, 4) is None
    assert bend_count_disagreement(0, 0) is None


def test_an_absent_source_is_a_gap_not_a_disagreement():
    """One source missing is the other filling a gap -- not a conflict to flag."""
    assert bend_count_disagreement(None, 4) is None
    assert bend_count_disagreement(5, None) is None
    assert bend_count_disagreement(None, None) is None


def test_the_flag_direction_always_prefers_the_dxf():
    """Whichever is larger, the message states the DXF count is the one used."""
    assert "so 4 is used" in bend_count_disagreement(4, 5)
    assert "so 5 is used" in bend_count_disagreement(5, 4)
