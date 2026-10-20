r"""
test_a_bought_in_does_not_wear_another_parts_blank.py

A 62012RS BALL BEARING, 12x32x10mm, WAS COSTED ON A 650.7 x 178.7 x 1.5mm STEEL BLANK.

That blank belongs to 12552-01-01M, CROSS MEMBERS. The two are not the same article and
nothing merged them — geometry_inference GAVE the bearing the cross member's flat, by a rule
that was working exactly as written:

    _material_family("MILD_STEEL")                       -> "metal"
    _family_of("62012RS Ball Bearing 12x32x10mm")        -> None
    _sibling_dims(bearing, [cross_member])
        -> {'ref': '12552-01-01M', 'length': 650.7, 'width': 178.7,
            'score': 1, 'same_family': False}

`score: 1` is the "same material" tier. With no family to match on, EVERY steel part in the
job is a valid donor, and the first one wins. The bearing's material was itself only the
SolidWorks library appearance ("Steel"), which the provenance tab already labels "appearance,
not a spec" — so an appearance on a purchased component reached out and took a measured flat
off a fabricated one.

WHAT IT COST. The blank made the bearing look like sheet metal to the estimator, which gave
it laser_cutting and 269 seconds of laser labour, and it was billed at GBP 2.02 x 8 = 16.16.
None of it was a misread: the material was real and the blank was real, and they belonged to
two different parts.

WHY THE EARLIER GUARD COULD NOT SAVE IT. 43c70ac keeps a shared assembly page's text off an
unmeasured bought-in, and it is gated on `geo_reliability == 0.0`. The borrow writes a blank
at reliability 0.4 — so by the time the ops are inferred the bearing is no longer unmeasured
and the guard correctly does not fire. Stolen geometry walks straight past it. That is why
identity has to be settled before routes: a guard cannot un-see a blank the engine believes.

THE RULE. This function answers "we make this and nobody measured it — roughly how big is
it?" A bought-in has no answer, because we do not make it; its size is whatever the supplier
ships. So the question is not asked. It is refused through bought_in_policy, the predicate
the rest of the codebase already uses, rather than a local re-implementation free to drift.

The fabricated parts must keep the borrow — that is what the rule is FOR. 12552-01-01A, a
nylon washer SDI makes, is not bought-in and stays eligible.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import geometry_inference as gi  # noqa: E402
from bought_in_policy import is_bought_in  # noqa: E402


# 12552-01-01M's real SolidWorks flat, off the extract this job ran on.
CROSS_MEMBER_FLAT = (650.7, 178.7)


def _cross_member() -> dict:
    return {
        "part_number": "12552-01-01M",
        "description": "CROSS MEMBERS",
        "normalized_material": "MILD STEEL",
        "page_roles": ["detail"],
        "normalized_geometry": {
            "blank_length_mm": CROSS_MEMBER_FLAT[0],
            "blank_width_mm": CROSS_MEMBER_FLAT[1],
            "confidence": {"geometry_reliability": 1.0},
        },
    }


def _bearing() -> dict:
    """The purchased part. Same job, same steel, no geometry of its own.

    Its material is the SolidWorks library appearance, which is how a bearing comes to read
    as MILD_STEEL at all — the record is reproduced as the engine actually held it.
    """
    return {
        "part_number": "12552-01-01X",
        "description": "62012RS Ball Bearing 12x32x10mm",
        "normalized_material": "MILD_STEEL",
        "page_roles": ["assembly", "bought_in"],
        "normalized_geometry": {},
    }


def _summary(parts: list) -> dict:
    return {"manufacturing_writeup": {"parts": parts}}


def _blank(part: dict):
    ng = part.get("normalized_geometry") or {}
    return ng.get("blank_length_mm"), ng.get("blank_width_mm")


def test_the_bearing_does_not_take_the_cross_members_flat():
    """The failing case, by part number and by millimetre."""
    bearing, cross = _bearing(), _cross_member()
    report = gi.infer_missing_geometry(_summary([cross, bearing]))

    length, width = _blank(bearing)
    assert length is None and width is None, (
        f"12552-01-01X came out carrying a {length} x {width}mm blank. A 12x32x10mm ball "
        f"bearing has no flat pattern; {CROSS_MEMBER_FLAT[0]} x {CROSS_MEMBER_FLAT[1]} is "
        f"12552-01-01M's, and a blank is what makes the estimator laser-cut it."
    )
    assert not bearing.get("geometry_inferred"), (
        "The bearing was tagged with inferred geometry. We do not make it, so there is "
        "nothing to infer."
    )
    assert [r["part"] for r in report.get("refused_bought_in", [])] == ["12552-01-01X"], (
        f"The refusal must be on the record, not silent: {report.get('refused_bought_in')!r}. "
        f"Unreported, a bought-in denied a blank looks exactly like one the rule never saw."
    )


def test_the_donor_is_untouched():
    """Refusing the borrow must not disturb the part that was going to be borrowed FROM."""
    bearing, cross = _bearing(), _cross_member()
    gi.infer_missing_geometry(_summary([cross, bearing]))
    assert _blank(cross) == CROSS_MEMBER_FLAT


def test_a_fabricated_part_still_borrows():
    """The rule exists for parts SDI makes, and they must keep it.

    12552-01-01A is a nylon washer on its own detail sheet — not bought-in, no geometry.
    Nothing here narrows what it is entitled to.
    """
    washer = {
        "part_number": "12552-01-01A",
        "description": "PLASTIC WASHER",
        "normalized_material": "NYLON",
        "page_roles": ["detail"],
        "normalized_geometry": {},
    }
    assert not is_bought_in(washer), (
        "This fixture is only meaningful while the washer reads as a made part; if the "
        "bought-in predicate now claims it, this test is asserting nothing."
    )
    acrylic_sibling = {
        "part_number": "12552-09-99A",
        "description": "PLASTIC WASHER",
        "normalized_material": "NYLON",
        "page_roles": ["detail"],
        "normalized_geometry": {"blank_length_mm": 60.0, "blank_width_mm": 60.0,
                                "confidence": {"geometry_reliability": 1.0}},
    }
    gi.infer_missing_geometry(_summary([acrylic_sibling, washer]))
    assert _blank(washer) == (60.0, 60.0), (
        f"A fabricated part lost its sibling borrow: {_blank(washer)}. The bought-in "
        f"refusal was meant to except purchased articles, not switch the rule off."
    )


def test_the_bearing_is_refused_even_with_no_donor_in_the_job():
    """The refusal is about what the part IS, not about what happened to be borrowable.

    Pinned because a rule that only bites when a donor exists would pass this suite on a job
    with no steel in it and fail silently on the next one that has some.
    """
    bearing = _bearing()
    report = gi.infer_missing_geometry(_summary([bearing]))
    assert _blank(bearing) == (None, None)
    assert [r["part"] for r in report.get("refused_bought_in", [])] == ["12552-01-01X"]
    assert "12552-01-01X" not in (report.get("still_missing") or []), (
        "A bought-in priced per piece from a catalogue is not an unpriced hole. Reporting "
        "it as missing geometry invites someone to fix it by loosening the refusal."
    )
