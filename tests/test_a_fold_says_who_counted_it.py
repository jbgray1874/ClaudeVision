r"""A fold says who counted it, and the layers we read are not the drawing's business.

James Gray, 18 September 2026, on 401912-02:

    "Ensure the correct flat DXF supplies the fold evidence/count. why are we getting this
     incorrect ever ? ... anything fundamental around bends needs to be resolved."

TWO FAULTS, ONE SYMPTOM. 401912-02's book carried a Fold row at half an hour of set-up and,
a few lines away, "layers not provided so bend vs cut assignment unknown". Read together
they say the engine charged a fold it could not see. Neither half was true.

    1. `manufacturing_features.bend_count_source` was READ in two places -- the measured-zero
       gate and the fold's own review line -- and WRITTEN in exactly one, by the SOLIDWORKS
       connector. `infer_bend_count` knows which rung answered at the moment it chooses, and
       threw that away to return a bare integer. So every fold in the shop read as unverified,
       including the ones measured off a BENDLINES layer, and the flag that was supposed to
       separate the two fired on all of them alike.

    2. "layers not provided" was a fact about OUR HAND-OFF, not about the file.
       `drawing_job_merge` passes the interpreter `raw.get("layers")`, and the reader's dict
       has never had a `layers` key -- nor `entity_counts`, nor `text_entities`, asked for on
       the same line. The model was asked which layer is the cut profile with no layers, no
       entity census and no text, and its guess was then quoted back as evidence.

The second is the worse of the two: a gap in our own plumbing was being published as a
limitation of the customer's drawing, and it said so on every job ever run, whatever the file.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from feature_synthesis import synthesize_manufacturing_features  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_FLAT_WITH_BENDS = _FIXTURES / "1097502A01_2mm_ACRY_Rev_B.DXF"


def _part(**over):
    part = {"geometry_rollup": {"confidence": {"geometry_reliability": 0.9}}}
    part.update(over)
    return part


def _dxf_flat(**over):
    return _part(flat_pattern_detected=True, geometry_source="dxf_flat_pattern", **over)


# ── which rung answered ──────────────────────────────────────────────────────────────

def test_a_bendlines_count_says_it_was_measured():
    """The press brake bends off this layer. Nothing in the run should have to guess that
    the count behind a 30-minute set-up came from it."""
    mf = synthesize_manufacturing_features(_dxf_flat(bend_count_dxf=1))
    assert mf["bend_count"] == 1
    assert mf["bend_count_source"] == "dxf_bendlines_layer"


def test_a_flat_pattern_with_no_bend_layer_is_still_a_measurement():
    """A cut-only export sets no bend layer, and its zero is a measured zero -- the
    distinction `_model_measured_zero_bends` exists to draw."""
    mf = synthesize_manufacturing_features(
        _dxf_flat(geometry_rollup={"confidence": {"geometry_reliability": 0.9},
                                   "estimated_bend_line_count": 0}))
    assert mf["bend_count"] == 0
    assert mf["bend_count_source"] == "dxf_flat_pattern"


def test_a_count_read_off_a_drawing_note_admits_it():
    """A 90 on the page is a perfectly good reason to fold. It is not a measurement, and the
    sheet has to be able to say which of the two it charged."""
    mf = synthesize_manufacturing_features(_part(angles_deg=[90.0]))
    assert mf["bend_count"] == 1
    assert mf["bend_count_source"] == "drawing_text"


def test_a_dashed_line_is_named_as_the_proxy_it_is():
    mf = synthesize_manufacturing_features(
        _part(geometry_rollup={"confidence": {"geometry_reliability": 0.9},
                               "dashed_long_axis_lines": 1}))
    assert mf["bend_count_source"] == "inferred_dashed_lines"


def test_no_evidence_at_all_is_not_dressed_up_as_a_measured_zero():
    """This zero and a DXF's zero mean opposite things and must not share a word."""
    mf = synthesize_manufacturing_features(_part())
    assert mf["bend_count"] == 0
    assert mf["bend_count_source"] == "no_bend_evidence"


# ── precedence, and not destroying evidence on the way past ─────────────────────────

def test_the_models_own_word_survives_this_function():
    """The SOLIDWORKS plate gate stamps a measured zero on `manufacturing_features`, and
    this function REPLACES that dict wholesale. Overwriting the stamp with our own
    'nobody counted' would discard the one reading that actually saw the solid."""
    part = _part(manufacturing_features={"bend_count": 0,
                                         "bend_count_source": "solidworks_api"})
    assert synthesize_manufacturing_features(part)["bend_count_source"] == "solidworks_api"


def test_a_dxf_reading_still_outranks_the_model():
    """On 11762-02-02M the BENDLINES layer carried 5 folds and the model said 4. The count
    already follows the DXF; the source has to follow it too or they name different things."""
    part = _dxf_flat(bend_count_dxf=2,
                     manufacturing_features={"bend_count": 0,
                                             "bend_count_source": "solidworks_api"})
    mf = synthesize_manufacturing_features(part)
    assert mf["bend_count"] == 2
    assert mf["bend_count_source"] == "dxf_bendlines_layer"


def test_running_twice_does_not_change_the_answer():
    """`_interpret_part` is not guaranteed to run once. A stamp that degrades on a second
    pass is how a measured fold quietly becomes an inferred one."""
    part = _part(manufacturing_features={"bend_count": 0,
                                         "bend_count_source": "solidworks_api"})
    first = synthesize_manufacturing_features(part)["bend_count_source"]
    part["manufacturing_features"] = first and {"bend_count": 0, "bend_count_source": first}
    assert synthesize_manufacturing_features(part)["bend_count_source"] == first


def test_the_part_and_the_features_do_not_disagree():
    """The two-names fault, pre-empted: one fact, recorded under two keys, is how every
    other hand-off defect this month began."""
    part = _dxf_flat(bend_count_dxf=1)
    mf = synthesize_manufacturing_features(part)
    assert part["bend_count_source"] == mf["bend_count_source"]


def test_the_estimator_recognises_a_measured_source():
    """A word only this module uses is a word the gate reading it will not honour."""
    import estimator
    assert "dxf_bendlines_layer" in estimator._MEASURED_BEND_SOURCES
    assert "dxf_flat_pattern" in estimator._MEASURED_BEND_SOURCES
    for inferred in ("drawing_text", "inferred_dashed_lines", "no_bend_evidence",
                     "inferred_mirrored_return_flange", "geometry_rollup"):
        assert inferred not in estimator._MEASURED_BEND_SOURCES


# ── and the layers are ours to report, not the drawing's to be blamed for ───────────

def _reader():
    """The reader's filename is not importable (`dxf_reader.py.py`)."""
    path = Path(__file__).resolve().parent.parent / "src" / "dxf_reader.py.py"
    spec = importlib.util.spec_from_file_location("_dxf_reader_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_reader_publishes_the_layers_it_read():
    """This fixture has a BENDLINES layer. The interpreter was told `null` for it, and then
    reported that absence as the drawing's shortcoming."""
    raw = _reader().extract_dxf_geometry(_FLAT_WITH_BENDS)
    assert "BENDLINES" in raw["layers"]
    assert raw["layer_entity_counts"]["BENDLINES"] > 0


def test_the_entity_census_and_the_text_go_with_it():
    """Asked for on the same line as the layers, and absent for the same reason."""
    raw = _reader().extract_dxf_geometry(_FLAT_WITH_BENDS)
    assert raw["entity_counts"].get("LINE", 0) > 0
    assert isinstance(raw["text_entities"], list)


def test_a_drawing_with_text_hands_its_text_over():
    other = _FIXTURES / "0355255 - A4 Table Top Graphic Holder - 10975_REV B.DXF"
    raw = _reader().extract_dxf_geometry(other)
    assert raw["text_entities"], "31 MTEXT entities on this sheet and none reached the model"
    assert all(isinstance(t, str) for t in raw["text_entities"])


def test_the_hand_off_carries_them_to_the_part():
    """The layers have to survive the merge, not just exist in the reader. The fold's review
    line checks the part before it accuses an export of having no bend lines, and the
    interpreter is handed the same reading a line later."""
    import drawing_job_merge
    part = drawing_job_merge.apply_dxf_geometry_to_part({}, _FLAT_WITH_BENDS)
    assert "BENDLINES" in (part.get("dxf_layers") or [])


def test_the_fold_on_a_measured_part_is_not_accused_of_being_a_guess():
    """The whole point, end to end: a part whose folds came off the BENDLINES layer must
    read as measured on the sheet, and must not collect the 'nothing that can see the part
    counted them' sentence that used to land on every folded part in the shop."""
    import drawing_job_merge
    import estimator
    part = drawing_job_merge.apply_dxf_geometry_to_part({}, _FLAT_WITH_BENDS)
    part["manufacturing_features"] = synthesize_manufacturing_features(part)
    assert part["manufacturing_features"]["bend_count"] > 0, "fixture has a BENDLINES layer"
    # The engine's own test for "did anything actually look", applied to what the merge and
    # the synthesis between them produced -- not to a dict this test wrote by hand.
    assert (part["manufacturing_features"]["bend_count_source"]
            in estimator._MEASURED_BEND_SOURCES)
