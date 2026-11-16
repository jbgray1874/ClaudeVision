"""A bounding box that proves the part is flat is a MEASUREMENT, not a floor under one.

`bounding_box_floor` ranks zero — fills gaps, displaces nothing. That is right for a
folded part, whose box under-reads the blank it unfolds from. It is wrong for a part the
model proves never leaves the plane: there the envelope IS the blank, and stamping it at
rank zero left 12392's 1435 x 130 panel — off the model — open to replacement by a rank-20
inference, silently, on the two numbers that drive the laser and the material cost.

The same evidence carried the gauge. 12392-02-01M's thickness read 1.5 mm stamped
llm_full_extract (rank 40) on a part whose SolidWorks envelope is 130 x 1435 x 1.5. The
number was right and its provenance was three ranks weaker than the evidence sitting on
the same record.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import blank_credibility as bc                                      # noqa: E402
import estimator                                                    # noqa: E402


def _rejected_blank_part(**extra):
    """12392's back panel as it actually arrives: a blank of 16 x 3.7 that nothing
    measured and that could not hold the cut path, so the sizing gate rejects it and
    looks for something better."""
    part = {"part_number": "12392-02-01M", "description": "BACK PANEL",
            "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 1.5,
            "quantity": 1, "blank_length_mm": 16, "blank_width_mm": 3.7}
    part.update(extra)
    return part


# ── the rule itself ─────────────────────────────────────────────────────────────────
def test_a_box_whose_smallest_side_is_the_gauge_is_flat():
    assert bc.envelope_proves_it_never_leaves_the_plane([130.0, 1435.0, 1.5], 1.5)


def test_a_box_deeper_than_the_gauge_is_not_flat():
    assert not bc.envelope_proves_it_never_leaves_the_plane([130.0, 1435.0, 60.0], 1.5)


def test_without_a_thickness_the_envelope_proves_nothing():
    """The smallest side of a machined block is not a gauge, and nothing here can tell a
    sheet part from one. Refusing to guess is the whole guard."""
    assert not bc.envelope_proves_it_never_leaves_the_plane([130.0, 1435.0, 1.5], None)


def test_a_two_sided_box_is_not_an_envelope():
    assert not bc.envelope_proves_it_never_leaves_the_plane([130.0, 1435.0], 1.5)


def test_the_rule_has_one_definition():
    """The overall-size path and the bounding-box path asked the same question with the
    same arithmetic written out twice. A rule with two spellings is a rule that will one
    day be corrected in one of them."""
    src = (Path(__file__).resolve().parents[1] / "src" / "blank_credibility.py").read_text(
        encoding="utf-8")
    assert src.count("thickness * 0.25") == 1, \
        "the flatness tolerance is spelled more than once in blank_credibility"


# ── what it changes at the blank ────────────────────────────────────────────────────
def test_a_measured_envelope_on_a_flat_part_is_the_blank_not_a_floor():
    part = _rejected_blank_part(bbox_mm=[130.0, 1435.0, 1.5],
                                bbox_mm_source="solidworks_api")

    assert estimator._blank_that_could_have_been_cut(part, 16, 3.7) == (1435.0, 130.0)

    assert part["blank_length_mm_source"] == "solidworks_api", \
        "a 1435mm blank off the model must not sit at rank 0 where inference can take it"
    assert part["blank_width_mm_source"] == "solidworks_api"
    assert "blank_replaced_by_measured_envelope" in part["review_flags"]
    assert "blank_replaced_by_bounding_box_floor" not in part["review_flags"], \
        "this part is not folded out of plane, so nothing here under-states"


def test_a_folded_part_keeps_the_floor_even_with_a_measured_envelope():
    """The envelope of a part that DOES leave the plane under-reads the blank it unfolds
    from. Measured or not, that is a floor and must stay one."""
    part = _rejected_blank_part(normalized_thickness_mm=1.5,
                                bbox_mm=[130.0, 1435.0, 60.0],
                                bbox_mm_source="solidworks_api")

    assert estimator._blank_that_could_have_been_cut(part, 16, 3.7) == (1435.0, 130.0)

    assert part["blank_length_mm_source"] == "bounding_box_floor"
    assert "blank_replaced_by_bounding_box_floor" in part["review_flags"]


def test_an_unstamped_envelope_is_not_a_measurement():
    """Strip the source off the bbox and this must fall straight back to a floor. A
    derived datum inherits the rank of the measurement it rests on, and no more —
    inheriting rank 90 from a box nobody attributed would invent evidence."""
    part = _rejected_blank_part(bbox_mm=[130.0, 1435.0, 1.5])

    estimator._blank_that_could_have_been_cut(part, 16, 3.7)

    assert part["blank_length_mm_source"] == "bounding_box_floor"


def test_a_weakly_sourced_envelope_does_not_become_a_measurement():
    """llm_extract is a reading, not a measurement. Only the measuring source classes
    promote a bounding box out of floor status."""
    part = _rejected_blank_part(bbox_mm=[130.0, 1435.0, 1.5],
                                bbox_mm_source="llm_extract")

    estimator._blank_that_could_have_been_cut(part, 16, 3.7)

    assert part["blank_length_mm_source"] == "bounding_box_floor"


def test_a_dxf_measured_envelope_promotes_too():
    """Keyed on the source CLASS, not on SolidWorks. A measured envelope is a measured
    envelope whichever tool measured it."""
    part = _rejected_blank_part(bbox_mm=[130.0, 1435.0, 1.5],
                                bbox_mm_source="dxf_flat_pattern")

    estimator._blank_that_could_have_been_cut(part, 16, 3.7)

    assert part["blank_length_mm_source"] == "dxf_flat_pattern"


def test_the_promoted_blank_survives_a_later_inference():
    """The point of the rank, not merely a label on it. At rank 0 a rank-20 guess could
    replace 1435mm and nothing would object."""
    from source_precedence import apply_field, source_of

    part = _rejected_blank_part(bbox_mm=[130.0, 1435.0, 1.5],
                                bbox_mm_source="solidworks_api")
    estimator._blank_that_could_have_been_cut(part, 16, 3.7)

    apply_field(part, "blank_length_mm", 300.0, "inference")

    assert part["blank_length_mm"] == 1435.0
    assert source_of(part, "blank_length_mm") == "solidworks_api"


# ── what it changes at the gauge ────────────────────────────────────────────────────
def _native_job(**part_kw):
    """A one-part extract, through the connector's real public entry point.

    Built from the connector's own dataclasses rather than a hand-made dict, because a
    fixture that invents the wrong shape produces a test that exercises nothing — this
    suite has been fooled by exactly that before.
    """
    from source_connectors import solidworks as sw
    nat = sw.NativePart(part_number="12392-02-01M", **part_kw)
    return sw.NativeJob(part_signals={"12392-02-01M": nat}, found=True,
                        meta={"extract_path": "test"})


def test_the_envelope_upgrades_a_thickness_it_agrees_with():
    from source_connectors import solidworks as sw
    from source_precedence import source_of

    part = {"part_number": "12392-02-01M", "normalized_thickness_mm": 1.5,
            "normalized_thickness_mm_source": "llm_full_extract"}

    sw.apply_native_to_pre_estimate([part], _native_job(bbox_mm=[130.0, 1435.0, 1.5]))

    assert part["normalized_thickness_mm"] == 1.5, "the value must not move"
    assert source_of(part, "normalized_thickness_mm") == "solidworks_api", \
        "the gauge sat on the model's own envelope and was credited to a text reading"


def test_the_envelope_never_invents_a_thickness():
    """A part with no recorded thickness is left alone. The smallest side of a machined
    block is not a gauge, and this cannot tell a sheet part from one."""
    from source_connectors import solidworks as sw

    part = {"part_number": "12392-02-01M"}
    sw.apply_native_to_pre_estimate([part], _native_job(bbox_mm=[130.0, 1435.0, 25.0]))

    assert not part.get("normalized_thickness_mm"), \
        "25mm is the depth of a block, not the gauge of a sheet"


def test_the_envelope_does_not_overwrite_a_gauge_it_disagrees_with():
    """Disagreement here is not the envelope knowing better — it is evidence the part is
    not flat, which is exactly when the envelope means nothing about thickness."""
    from source_connectors import solidworks as sw

    part = {"part_number": "12392-02-01M", "normalized_thickness_mm": 3.0,
            "normalized_thickness_mm_source": "llm_full_extract"}
    sw.apply_native_to_pre_estimate([part], _native_job(bbox_mm=[130.0, 1435.0, 60.0]))

    assert part["normalized_thickness_mm"] == 3.0


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
