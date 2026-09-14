"""Three of the estimator's 7332-01 points: one op that should not be there, two the drawing
never mentions.

    "Line 103 - Tube Bending Op. – Not Required."
    "Line 67 / Line 100 – 0.9mm Steel Production use 1mm in Lieu – TBC"
    "Line 85 – Drawing doesn't annotate – material is brushed prior to sending to platers,
     op. for Manual Labour (Metal) 40 Minutes – Grey area as drawing only nominates a finish
     as Harrods01"

THE TUBE BEND COMES OFF, because nothing says it bends. tube_bending is not inferred from
geometry the way folding is — it arrives from the drawing READ, so a mention near a tube is
enough to charge the tube-bender, its rate and its 45-minute set-up. 7332-01-002 booked two
bends on a straight leg. The gate is the standard the fold rule already applies: any bend
evidence keeps the op, none of it takes the op off, out loud.

THE OTHER TWO ARE FLAGS AND NOT REWRITES. Each is something a person told us about one job,
neither is on the drawing, and acting on either silently would be this engine inventing a
spec — a substituted gauge nobody bought, or forty minutes of labour nobody asked for. Both
are raised where a person can rule, and the figures stay exactly as drawn.

None of this can reach a job with no tube, no thin-gauge steel and no plating.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from estimator import estimate_process_times                            # noqa: E402


def _tube(**over):
    part = {"part_number": "7332-01-002", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.2, "textual_operations": ["tube_bending", "handling"],
            "material_estimate": {"stock_form": "tube"}}
    part.update(over)
    return part


def _flags(part):
    return " ".join(str(f) for f in part.get("review_flags") or [])


# ── the tube bend that was not required ──────────────────────────────────────────────────

def test_a_straight_tube_is_not_charged_a_bend():
    part = _tube()
    out = estimate_process_times(part)
    assert "tube_bending" not in out["run_times_min_per_unit"]
    assert "tube_bending" not in (part.get("textual_operations") or [])
    assert "tube_bending" in (part.get("removed_operations") or [])


def test_it_says_why_and_what_would_bring_it_back():
    part = _tube()
    estimate_process_times(part)
    assert "nothing on this part states a bend" in _flags(part)
    assert "the drawing needs to say so" in _flags(part)


def test_any_evidence_of_a_bend_keeps_the_op():
    for ev in ({"manufacturing_features": {"bend_count": 2}},
               {"bend_count_dxf": 1},
               {"angles_deg": [90]},
               {"fold_count_textual": 3}):
        part = _tube(**ev)
        estimate_process_times(part)
        assert "tube_bending" in (part.get("textual_operations") or []), ev


# ── kept on a word alone, and still worth asking about ───────────────────────────────────
#
# "Line 103 - Tube Bending Op. – Not Required." The gate above only removes the op where
# NOTHING states a bend, and 7332-01-002 is the other case: the drawing text states one and
# no measurement backs it — no bend line in a DXF, no angle callout. The op stays, because
# the drawing did say something and deleting charged work on one estimator's disagreement
# with one drawing is how a rule stops describing anything. But the tube-bender is £32.84 an
# hour with a 45-minute set-up, and a word is weaker evidence than a measurement, so the
# weak case costs a sentence.

def test_a_bend_stated_in_words_only_is_charged_and_raised():
    part = _tube(fold_count_textual=2)
    estimate_process_times(part)
    assert "tube_bending" in (part.get("textual_operations") or [])   # still charged
    assert "CHARGED on the drawing's word alone" in _flags(part)
    assert "Confirm the leg actually bends" in _flags(part)


def test_a_measured_bend_is_not_second_guessed():
    """A DXF bend line or an angle callout IS the measurement. Flagging those would put a
    question on every bent tube in the shop, which is noise, not review."""
    for ev in ({"bend_count_dxf": 1}, {"angles_deg": [90]},
               {"bend_count_dxf": 2, "angles_deg": [45, 45]}):
        part = _tube(**ev)
        estimate_process_times(part)
        assert "tube_bending" in (part.get("textual_operations") or []), ev
        assert "word alone" not in _flags(part), ev


def test_a_removed_bend_is_not_also_queried():
    """The two states are exclusive: it either came off with its reason, or it stayed with
    its question. Both on one part would be the sheet arguing with itself."""
    part = _tube()
    estimate_process_times(part)
    assert "tube bending removed" in _flags(part)
    assert "word alone" not in _flags(part)


def test_a_part_with_no_tube_bend_op_is_untouched():
    part = {"part_number": "X", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "textual_operations": ["laser_cutting"]}
    estimate_process_times(part)
    assert not part.get("removed_operations")


# ── 0.9 mm: flagged, and costed as drawn ─────────────────────────────────────────────────

def test_a_zero_nine_gauge_raises_the_substitution_without_making_it():
    part = {"part_number": "7332-01-008", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 0.9, "textual_operations": ["laser_cutting"]}
    estimate_process_times(part)
    assert "1.0 mm in lieu" in _flags(part)
    assert "Costed AS DRAWN" in _flags(part)
    assert part["normalized_thickness_mm"] == 0.9, "the gauge must not be rewritten"


def test_a_normal_gauge_says_nothing():
    for g in (0.7, 1.2, 1.5, 2.5):
        part = {"part_number": "X", "normalized_material": "MILD_STEEL",
                "normalized_thickness_mm": g, "textual_operations": ["laser_cutting"]}
        estimate_process_times(part)
        assert "in lieu" not in _flags(part), g


# ── brushing before the platers: named, not added ────────────────────────────────────────

def test_a_plated_part_raises_the_brushing_nobody_drew():
    part = {"part_number": "7332-01-101", "normalized_material": "MILD_STEEL",
            "normalized_finish": "Harrods01", "textual_operations": ["handling"]}
    out = estimate_process_times(part)
    assert "brushes material before it goes to the platers" in _flags(part)
    assert "NOT costed here" in _flags(part)
    assert "manual_labour" not in out["run_times_min_per_unit"], "flagged, never added"


def test_an_unplated_part_raises_nothing():
    part = {"part_number": "12349-02-69-04M", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.2, "normalized_finish": "powder coated",
            "textual_operations": ["handling"]}
    estimate_process_times(part)
    assert not (part.get("review_flags") or []), "a powder-coated part goes to no plater"


def test_the_whole_feeder_job_is_untouched_by_all_three():
    """12349-02 has no tube, no 0.9 mm steel and no plating. None of this can reach it."""
    for g, fin in ((1.2, "powder coated"), (1.5, "powder coated"), (5.0, "")):
        part = {"part_number": "12349-02-69-03M", "normalized_material": "MILD_STEEL",
                "normalized_thickness_mm": g, "normalized_finish": fin,
                "textual_operations": ["laser_cutting", "handling"]}
        estimate_process_times(part)
        assert not (part.get("review_flags") or []), (g, fin)
        assert not part.get("removed_operations"), (g, fin)
