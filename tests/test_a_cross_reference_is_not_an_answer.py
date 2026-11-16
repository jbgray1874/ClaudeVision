"""A drawing that says "look on another sheet" has not told us the material or the finish.

THE FAULT, on 10575-02, and it is the reason powder came to £0.00.

The GA writes this in both its MATERIAL and its FINISH field:

    REFER TO INDIVIDUAL COMPONENT DRAWINGS

The engine stored it as the value of each. As a material it cannot be priced, so the part costed
£0.00. As a finish it never routed a powder operation, so a powder-coated job carried £0.00 of
powder and £0.00 of P.Coat labour:

    "powder_material_gbp": 0.0
    "powder_labour_gbp":   0.0
    "powder_total_gbp":    0.0

Nothing failed. No exception, no error, no red line. The job was simply costed as though the parts
were made of nothing and finished with nothing — and the manual estimate for the same job charged
for powder.

WHY IT SLIPPED THROUGH A GUARD THAT ALREADY EXISTED. `_MATERIAL_REF_NOTE_RE` has caught these
since the title-block reader was written. But this value did not come from the title block; it
came from `llm_full_extract`, a different path with no such check. One guard on one of two doors.
So the predicate is now exported — `is_cross_reference_note` — and used at the points every
material and every finish passes through, rather than at the one that happened to be written
first.

THE DISTINCTION THAT MATTERS MORE THAN THE NUMBER. "This part needs no finish" and "the drawing
sent us to a sheet that is not in this pack" produced identical output: no finish, no operation,
no cost, nothing said. One of those is correct and the other is an under-charge on every coated
job. `finish_deferred` separates them, because a silence that means two things is not a silence
anybody can act on.

WHAT THIS DOES NOT DO, said plainly: it does not invent a material or a finish. It removes a
non-answer and records that the question is open. Pricing a part the drawing never described
would be a worse fault than the one being fixed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from extractor_patterns import is_cross_reference_note  # noqa: E402
from feature_synthesis import synthesize_manufacturing_features  # noqa: E402


# ── the predicate ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "REFER TO INDIVIDUAL COMPONENT DRAWINGS",
    "Refer to individual component drawings",
    "SEE INDIVIDUAL DRAWINGS",
    "SEE ASSEMBLY",
    "AS PER DRAWING",
    "SEE ABOVE",
    "VARIOUS",
    "TBC",
    "N/A",
])
def test_an_instruction_is_recognised_as_one(value):
    assert is_cross_reference_note(value)


@pytest.mark.parametrize("value", [
    "MILD STEEL", "MDF", "ALUMINIUM", "3mm ACRYLIC", "MELAMINE FACED CHIPBOARD",
    "POWDER COATED RAL 9005", "WET SPRAY SATIN BLACK", "ANODISED", "DIBOND",
])
def test_a_real_answer_is_left_alone(value):
    """The cost of being wrong here is a part that cannot be priced, so the net is deliberately
    narrow. Every one of these is a material or finish the engine must keep."""
    assert not is_cross_reference_note(value)


def test_nothing_is_not_an_instruction():
    assert not is_cross_reference_note("")
    assert not is_cross_reference_note(None)


# ── the finish gate, which is what cost the powder ─────────────────────────────

def _features(**part):
    part.setdefault("geometry_rollup", {"confidence": {}})
    part.setdefault("textual_operations", [])
    return synthesize_manufacturing_features(part)


def test_a_stated_finish_still_requires_a_finish():
    f = _features(normalized_finish="POWDER COATED RAL 9005")
    assert f["finish_required"] is True
    assert f["finish_deferred"] is False


def test_a_deferred_finish_does_not_count_as_a_finish():
    """It is not a finish. Counting it as one would route powder against a string nobody can
    price, which is the opposite error and just as wrong."""
    f = _features(normalized_finish="REFER TO INDIVIDUAL COMPONENT DRAWINGS")
    assert f["finish_required"] is False


def test_a_deferred_finish_is_not_silence():
    """THE ASSERTION THAT MATTERS. Without this, "we were not told" and "nothing to do" are the
    same output, and one of them is an under-charge on every coated job."""
    f = _features(normalized_finish="REFER TO INDIVIDUAL COMPONENT DRAWINGS")
    assert f["finish_deferred"] is True


def test_a_part_with_no_finish_at_all_is_not_marked_deferred():
    """A part that genuinely needs no finish must not raise a question. Flagging everything is
    the same as flagging nothing."""
    f = _features()
    assert f["finish_required"] is False
    assert f["finish_deferred"] is False


def test_a_real_finish_beside_a_cross_reference_still_wins():
    """A sheet can carry both. One real answer is enough — it is not deferred, it is answered."""
    f = _features(normalized_finish="POWDER COATED RAL 9005",
                  surface_finishes=["REFER TO INDIVIDUAL COMPONENT DRAWINGS"])
    assert f["finish_required"] is True
    assert f["finish_deferred"] is False


def test_the_flag_travels_with_the_features():
    """It has to reach the JSON, or nothing downstream can act on it."""
    assert "finish_deferred" in _features(normalized_finish="SEE ASSEMBLY")


# ── the material side ──────────────────────────────────────────────────────────

def test_the_material_guard_is_wired_at_the_choke_point():
    """estimate_material is where every material passes through — the title-block reader had its
    own guard and llm_full_extract had none, which is how this got in."""
    src = (_ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    at = src.index("def estimate_material(")
    body = src[at:at + 2200]
    assert "is_cross_reference_note" in body
    assert 'part["normalized_material"] = None' in body


def test_clearing_the_material_is_declared_to_the_arbitration():
    """The codebase requires a direct write to an arbitrated fact to say why. A cross-reference is
    not a competing material — submitting it as a reading would give it a rank and let it beat a
    real one."""
    src = (_ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    at = src.index('part["normalized_material"] = None')
    assert "precedence: direct-write ok" in src[at:at + 400]


def test_the_estimator_is_told_rather_than_left_with_a_zero():
    """A part costed at £0.00 with no explanation reads as a cheap part."""
    src = (_ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    at = src.index("def estimate_material(")
    body = src[at:at + 2200]
    assert "review_flags" in body
    assert "An estimator must supply it" in body
