r"""A fold is charged from what must be bent, not from how somebody built the model.

James Gray, 18 September 2026, on 401912-02:

    "SolidWorks is not necessarily 'wrong'; its feature tree may correctly contain three CAD
     bend-related features. The defect is ours: we treated that model feature count as though
     it were the number of press-brake operations and gave it a higher generic source rank
     than the flat-pattern/DXF evidence. That is the wrong comparison... a flat pattern
     describes what must be bent; a CAD feature tree describes how somebody built the model."

THE DIVIDER HAS ONE FOLD AND THE SHEET CHARGED THREE. The flat DXF measured one bend axis --
`_extract_bend_data` counts DISTINCT AXES, so a bend line the exporter broke around a cut-out
is one fold and not three, and it was right. The SolidWorks cut list reported three bend
features and the connector wrote that into `geometry_rollup.estimated_bend_line_count` at rank
90, over the top of the measurement. Thirty minutes of brake set-up and three times the run
time, on a part with one bend in it.

AND THE LABEL FOLLOWED THE WRONG NUMBER: the review line read "3 fold(s) charged, counted by
dxf_bendlines_layer -- measured, not inferred". The flat pattern said one. A provenance label
attached to a figure it did not produce is worse than no label, because it tells a reader to
stop checking.

WHERE THE DASHED-LINE PROXY SITS. The brief ranks "a clear drawing fold note/dashed bend line"
above the model. A fold NOTE is a statement by the drawing office and is ranked there. A
DASHED-LINE COUNT is not a statement -- it is our own inference from vectors in a PDF view.
Ranking it above the model would undo the fix the override was built for: on 12552 the scan
read 26 and 28 lines against cut lists of 6 and 8, and the two largest fabricated lines on the
bay were folded about twenty times each for folds that are not there. So the proxy sits BELOW
the model. Both jobs come out right, and this file holds both.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from fold_count import press_brake_folds  # noqa: E402


def _part(**kw):
    rollup = {"confidence": {"geometry_reliability": 0.9}}
    if "dashed" in kw:
        rollup["dashed_long_axis_lines"] = kw.pop("dashed")
    return dict({"geometry_rollup": rollup}, **kw)


# ── the four controls the brief names ────────────────────────────────────────────────

def test_flat_says_one_model_says_three_charge_one_and_report_it():
    got = press_brake_folds(_part(bend_count_dxf=1, solidworks_bend_features=3))
    assert got["count"] == 1
    assert got["source"] == "flat_pattern_bend_lines"
    assert got["disagreement"] and "3" in got["disagreement"]


def test_no_flat_and_no_drawing_count_the_model_answers():
    got = press_brake_folds(_part(solidworks_bend_features=3))
    assert got["count"] == 3
    assert got["source"] == "solidworks_bend_features"


def test_the_drawing_states_one_and_there_is_no_flat():
    got = press_brake_folds(_part(fold_count_textual=1))
    assert got["count"] == 1
    assert got["source"] == "drawing_fold_note"


def test_a_drawing_statement_outranks_the_model():
    """A fold callout is the drawing office saying what the part is; a feature tree is not."""
    got = press_brake_folds(_part(fold_count_textual=1, solidworks_bend_features=3))
    assert got["count"] == 1
    assert got["disagreement"]


# ── 12552, which the model override was built for, is untouched ─────────────────────

def test_the_dashed_line_scan_still_loses_to_the_model():
    """26 dashed lines against a cut list of 6. This is the failure the override exists for,
    and the fix for 401912-02 must not reopen it."""
    got = press_brake_folds(_part(solidworks_bend_features=6, dashed=26))
    assert got["count"] == 6
    assert got["source"] == "solidworks_bend_features"
    assert "26" in got["disagreement"]


def test_the_model_still_wins_when_it_reads_higher_than_the_scan():
    """The other direction: 5 in the cut list, 1 dashed line. Fixing an over-count must not
    create an under-count."""
    assert press_brake_folds(_part(solidworks_bend_features=5, dashed=1))["count"] == 5


def test_the_dashed_proxy_answers_when_it_is_all_there_is():
    got = press_brake_folds(_part(dashed=2))
    assert got["count"] == 2
    assert got["source"] == "inferred_dashed_lines"
    assert got["measured"] is False


# ── what the resolver says about itself ──────────────────────────────────────────────

def test_a_measured_zero_is_a_value_not_an_absence():
    """A flat pattern that measured no bend lines has ANSWERED. It must not fall through to
    a model or a proxy — that is how a cut-only part gets folded."""
    got = press_brake_folds(_part(bend_count_dxf=0, solidworks_bend_features=3))
    assert got["count"] == 0
    assert got["source"] == "flat_pattern_bend_lines"


def test_nothing_at_all_says_nothing_at_all():
    got = press_brake_folds(_part())
    assert got["count"] == 0
    assert got["source"] == "no_bend_evidence"
    assert got["disagreement"] is None


def test_agreement_is_not_a_disagreement():
    """A sentence on every folded part is a sentence nobody reads."""
    assert press_brake_folds(_part(bend_count_dxf=2, solidworks_bend_features=2))["disagreement"] is None


def test_the_model_figure_is_kept_whatever_happens_to_it():
    got = press_brake_folds(_part(bend_count_dxf=1, solidworks_bend_features=3))
    assert got["model_features"] == 3


def test_only_a_measurement_claims_to_be_one():
    assert press_brake_folds(_part(bend_count_dxf=1))["measured"] is True
    assert press_brake_folds(_part(solidworks_bend_features=3))["measured"] is True
    assert press_brake_folds(_part(fold_count_textual=1))["measured"] is False
    assert press_brake_folds(_part(dashed=1))["measured"] is False


def test_rubbish_in_does_not_crash_the_resolver():
    for junk in (None, [], "", 0, {"bend_count_dxf": "banana"}):
        assert press_brake_folds(junk)["count"] == 0 if not isinstance(junk, dict) \
            else press_brake_folds(junk)["count"] == 0


# ── and every consumer asks the one resolver ────────────────────────────────────────

def test_the_connector_records_evidence_and_does_not_charge_it():
    """The count goes on the record as CAD evidence. It no longer writes the field the fold
    row is billed from."""
    import inspect
    from source_connectors import solidworks
    src = inspect.getsource(solidworks)
    at = src.index('part["solidworks_bend_features"] = _bends')
    after = src[at:at + 900]
    assert "estimated_bend_line_count" not in after, \
        "the connector is still writing the field the fold is charged from"


def test_the_process_time_asks_the_resolver():
    import inspect
    import estimator
    src = inspect.getsource(estimator.estimate_process_times)
    assert "press_brake_folds" in src


def test_the_synthesis_asks_the_resolver():
    import inspect
    import feature_synthesis
    src = inspect.getsource(feature_synthesis.synthesize_manufacturing_features)
    assert "press_brake_folds" in src
