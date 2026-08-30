"""A mirror fills what a hand is missing. It must not overwrite what the hand read of itself.

11650-04 SURVIVED BY LUCK. Its base carried a title-block PETG, so when the mirror overwrote
the hand's own export the pair-level quorum still had a second independent voice — the base's
title block — to count PETG back into the answer. A pack WITHOUT that second voice does not get
so lucky.

    base   ABS, from a lone SolidWorks model (rank 90)
    hand   PETG, from its OWN export "…_2MM PETG_…" (dxf_filename, rank 70)

The mirror copies the base's material onto the hand at mirror_of_measured (75), which beats the
export's 70. Both hands now say ABS, settle_handed_pairs finds them agreeing, and the whole
pair is lost to one model property — on a job where the machine that cuts the part is fed the
file that says PETG. The hand's own measured reading is destroyed one function before the rule
that would have defended it ever runs.

THE FIX IS NARROW ON PURPOSE. A mirror is not an independent observation of this hand; it is
the other hand's reading wearing a different source name. So it must not displace a reading
this part made OF ITSELF — and the one such reading ranked below the mirror is the export
filename, which names the exact part it is cut from.

IT IS ALSO DELIBERATELY NOT BROADER. Assembly-page text (drawing_deterministic on an
assembly-only hand) is NOT protected: an assembly page lists many parts, and text scraped near
one hand may name the material of another, so the existing rule that a mirror overwrites that
stands. This protects the hand's own cut file, and nothing that could belong to a neighbour on
a shared sheet.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import drawing_job_merge as djm  # noqa: E402
import source_precedence as sp  # noqa: E402

MAT, GAUGE = "normalized_material", "normalized_thickness_mm"


def _base(material="ABS", gauge=2.2):
    return {"part_number": "77A", "normalized_material": material, "material_source": "solidworks_api",
            "normalized_thickness_mm": gauge, "thickness_source": "solidworks_api",
            "normalized_geometry": {"geometry_source": "dxf", "bounding_box_flat_mm": [1250.0, 525.0],
                                    "blank_length_mm": 1250.0, "blank_width_mm": 525.0}}


def _hand_with(source, material="PETG", gauge=2.0):
    h = {"part_number": "77A-HANDED", "normalized_geometry": {}}
    if material:
        sp.apply_field(h, MAT, material, source)
    if gauge:
        sp.apply_field(h, GAUGE, gauge, "dxf")
    return h


# ── the defect, stated as the test ───────────────────────────────────────────────────

def test_the_hands_own_export_reading_is_not_overwritten_by_the_mirror():
    """THE WHOLE POINT. dxf_filename names this exact part; the mirror copies the other hand."""
    base, hand = _base(), _hand_with("dxf_filename")
    assert hand[MAT] == "PETG"
    djm.apply_mirror_geometry([base, hand])
    assert hand[MAT] == "PETG", "the mirror clobbered the hand's own export reading"
    assert sp.source_of(hand, MAT) == "dxf_filename"


def test_the_disagreement_is_recorded_rather_than_silently_kept():
    """A hand that keeps a material different from its base is a thing a person may need to
    see. The refusal is flagged with both readings, and the base's value is logged as a
    displaced observation so the pair-level quorum can still count it."""
    base, hand = _base(), _hand_with("dxf_filename")
    djm.apply_mirror_geometry([base, hand])
    said = {str(e.get("value")) for e in sp.displaced_values(hand, MAT)}
    assert "ABS" in said, "the base's reading was not recorded for the pair quorum to weigh"
    assert any("mirror copies the other hand" in f for f in hand.get("review_flags", []))


def test_the_pair_then_settles_to_the_export_not_the_lone_model():
    """The reason the narrow fix matters: with the export preserved, the pair-level rules can
    do their job. Base model (ABS) is one voice; the hand's export (PETG) is another. On this
    one-for-one split the cut file the CNC is driven from breaks the tie, so BOTH hands price
    as PETG — one stock key from the export — and neither silently becomes ABS on the strength
    of one model property."""
    base, hand = _base(), _hand_with("dxf_filename")
    djm.apply_mirror_geometry([base, hand])
    djm.settle_handed_pairs([base, hand])
    assert hand[MAT] == "PETG"
    assert base[MAT] == "PETG", "the pair did not unify to the cut-file material"


def test_an_export_that_agrees_with_the_base_is_corroborated_not_flagged():
    """The refusal is ONLY for a disagreement. When the hand's own export reads the SAME
    material as the base, there is nothing to settle: the mirror corroborates it, no
    displaced observation is logged, and no 'a person must look' flag is raised. Without the
    agreement guard, an identical reading would be recorded as a conflict against itself."""
    base, hand = _base(material="PETG", gauge=2.0), _hand_with("dxf_filename", material="PETG", gauge=2.0)
    djm.apply_mirror_geometry([base, hand])
    assert hand[MAT] == "PETG"
    assert not sp.displaced_values(hand, MAT), "an agreeing reading was logged as displaced"
    assert not any("mirror copies the other hand" in f for f in hand.get("review_flags", [])), \
        "an agreeing reading was flagged as a disagreement"


# ── what it must still do ────────────────────────────────────────────────────────────

def test_a_hand_missing_the_material_is_still_filled():
    """Fill what is missing — the mirror's actual job. A hand with no material of its own gets
    the base's."""
    base = _base()
    hand = {"part_number": "77A-HANDED", "normalized_geometry": {}}
    djm.apply_mirror_geometry([base, hand])
    assert hand[MAT] == "ABS"
    assert sp.source_of(hand, MAT) == "mirror_of_measured"


def test_a_hand_carrying_only_an_inference_is_still_overwritten():
    """An inference is the engine reasoning, not a reading. The mirror — a measured opposite
    hand — is better evidence and replaces it."""
    base, hand = _base(), _hand_with("inference", material="MDF")
    djm.apply_mirror_geometry([base, hand])
    assert hand[MAT] == "ABS"


def test_assembly_page_text_on_a_hand_is_still_overwritten():
    """DELIBERATELY OUT OF SCOPE. Assembly-page text can name a neighbour's material; the
    existing rule that a mirror overrules it is preserved, and this fix does not touch it."""
    base, hand = _base(), _hand_with("drawing_deterministic")
    djm.apply_mirror_geometry([base, hand])
    assert hand[MAT] == "ABS", "the narrow fix wrongly protected shared-page text"


def test_only_the_export_filename_is_protected_not_everything_rank_70():
    """The line between the two is 'does this source name THIS specific part', not rank.
    dxf_filename and drawing_deterministic are both rank 70; only the first survives."""
    assert "dxf_filename" in djm._A_READING_OF_THIS_SPECIFIC_PART
    assert "drawing_deterministic" not in djm._A_READING_OF_THIS_SPECIFIC_PART
    assert "title_block" not in djm._A_READING_OF_THIS_SPECIFIC_PART


def test_a_measured_hand_still_wins_as_it_always_did():
    """Unchanged: a hand measured by its own DXF (80) or model (90) already beats the mirror
    on rank, so the protection here is not what defends it — but it must still hold."""
    base, hand = _base(), _hand_with("dxf", material="POLYCARBONATE", gauge=3.0)
    djm.apply_mirror_geometry([base, hand])
    assert hand[MAT] == "POLYCARBONATE"
