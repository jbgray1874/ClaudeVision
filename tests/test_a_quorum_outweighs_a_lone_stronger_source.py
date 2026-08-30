"""Several independent readings agreeing outweigh one stronger reading on its own.

11650-04 IS THE CASE, AND IT IS NOT MARGINAL. The pack says PETG four separate ways:

    title block          MATERIAL: PETG
    options list         PETG + REEDED VINYL... / PC + REEDED VINYL...   (no ABS anywhere)
    six DXF exports      11650-04-01A_2MM PETG_REVG (and REVF, REVE, REVD, REVC)
    parts catalogue      37 rows of plain PETG sheet stock at 2mm

Against that: ONE SolidWorks model property saying ABS, which outranks all of them at 90.
Result on the sheet — ABS, a material the engine holds no rate for, four panels priced by an
LLM at GBP 175.01, 244.97 and 114.98 for the same nominal material, and two BLOCKING
invariants. The same shape had already cost 11650's door GBP 35.28 -> GBP 0.00.

A MODEL'S MATERIAL PROPERTY IS THE LEAST RELIABLE THING A MODEL CARRIES. It is whatever was
assigned in CAD, often a library default nobody revisited; the title block is what was ISSUED
and what the shop buys to. Rank is right about geometry and wrong about this, and the fix is
not to re-rank sources per field — it is to notice when the lone strong source stands alone.

WHAT THE RULE IS NOT. It is not a tie-break: two against two changes nothing, because then
order would decide. It is not a vote of readings: two passes of one reader agreeing with
itself is one observation. And it is never silent — the record says what outvoted what, and
the displaced value stays readable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import source_precedence as sp  # noqa: E402
from source_precedence import apply_field, source_of, value_of  # noqa: E402

FIELD = "normalized_material"


def _side_panel():
    """11650-04-01A, in the order the readers run."""
    part = {}
    apply_field(part, FIELD, "PETG", "title_block")
    apply_field(part, FIELD, "ABS", "solidworks_api")
    return part


def test_one_drawing_source_does_not_overturn_the_model():
    """A single weaker reading is a disagreement, not evidence. This is the behaviour that
    must not change — otherwise every stale filename in a job folder rewrites the material."""
    part = _side_panel()
    assert value_of(part, FIELD) == "ABS"
    assert source_of(part, FIELD) == "solidworks_api"


def test_two_independent_drawing_sources_do():
    part = _side_panel()
    apply_field(part, FIELD, "PETG", "drawing_deterministic")
    assert value_of(part, FIELD) == "PETG"


def test_the_reversal_is_written_down_in_words_an_estimator_can_act_on():
    """A precedence rule that silently reverses an earlier decision is worse than the one it
    replaces — the sheet would change and nothing would say why."""
    part = _side_panel()
    apply_field(part, FIELD, "PETG", "drawing_deterministic")
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "OUTVOTED" in flags
    assert "solidworks_api" in flags and "title_block" in flags
    assert "confirm which is right" in flags


def test_the_evidence_is_on_the_record_not_only_in_prose():
    part = _side_panel()
    apply_field(part, FIELD, "PETG", "drawing_deterministic")
    corr = part["_corroboration"][FIELD]
    assert corr["value"] == "PETG"
    assert corr["displaced_value"] == "ABS"
    assert corr["displaced_sources"] == ["solidworks_api"]
    assert sorted(corr["sources"]) == ["drawing_deterministic", "title_block"]


def test_the_source_recorded_is_the_one_that_carried_the_vote():
    """Not solidworks_api, which lost, and not an invented "corroboration" source that no
    reader is called — every consumer of material_source resolves a real source name."""
    part = _side_panel()
    apply_field(part, FIELD, "PETG", "drawing_deterministic")
    assert source_of(part, FIELD) == "drawing_deterministic"
    assert sp.rank(source_of(part, FIELD)) > 0


def test_what_was_overruled_stays_readable():
    part = _side_panel()
    apply_field(part, FIELD, "PETG", "drawing_deterministic")
    displaced = [e["value"] for e in sp.displaced_values(part, FIELD)]
    assert "ABS" in displaced, "the model's reading must not vanish because it lost"


# ── what the rule refuses to do ──────────────────────────────────────────────────────

def test_one_reader_repeating_itself_is_one_observation():
    """THE FAILURE THIS WOULD OTHERWISE INVITE. Six DXF exports of one part are six files and
    one source; counting them as six would let a single stale filename outvote anything."""
    part = _side_panel()
    for _ in range(5):
        apply_field(part, FIELD, "PETG", "title_block")
    assert value_of(part, FIELD) == "ABS", (
        "the title block was already counted once — repeating it is not corroboration")


def test_a_source_confirming_the_same_value_repeatedly_is_recorded_once():
    """The record says WHICH sources confirmed a value, not how many times each of them did.
    Unbounded it grows on every pass and travels into the job JSON, and a reader counting
    entries instead of sources would find support that is not there — the same trap the
    displaced log is deduplicated against."""
    part = {}
    apply_field(part, FIELD, "ABS", "solidworks_api")
    for _ in range(4):
        apply_field(part, FIELD, "ABS", "solidworks_flat_pattern")
    agreed = part["_agreed"][FIELD]
    assert len(agreed) == 1
    assert sp.support_for(part, FIELD, "ABS") == ["solidworks_api", "solidworks_flat_pattern"]


def test_two_against_two_is_left_for_a_person():
    """Not a tie-break. With equal support on both sides nothing distinguishes them, and
    letting the newcomer win would make the answer depend on the order pages were read."""
    part = {}
    apply_field(part, FIELD, "ABS", "solidworks_api")
    apply_field(part, FIELD, "ABS", "solidworks_flat_pattern")   # a second source agrees
    apply_field(part, FIELD, "PETG", "title_block")
    apply_field(part, FIELD, "PETG", "drawing_deterministic")
    assert value_of(part, FIELD) == "ABS"
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "OUTVOTED" not in flags


def test_a_quorum_agreeing_with_the_value_already_held_changes_nothing():
    part = _side_panel()
    apply_field(part, FIELD, "ABS", "drawing_deterministic")
    assert value_of(part, FIELD) == "ABS"
    assert "_corroboration" not in part


def test_an_empty_field_is_still_just_filled():
    part = {}
    assert apply_field(part, FIELD, "PETG", "llm_extract") is True
    assert "_corroboration" not in part


# ── it is the same rule for every arbitrated field ───────────────────────────────────

@pytest.mark.parametrize("field,strong,weak", [
    ("normalized_material", "ABS", "PETG"),
    ("normalized_thickness_mm", 2.2, 2.0),
    ("quantity", 1, 4),
])
def test_the_rule_is_not_written_for_material(field, strong, weak):
    """11650-04 splits on GAUGE as well as material — six DXFs named 2MM and a catalogue
    stocking 2.0 against one model property saying 2.2. A rule that named material would fix
    half the defect and leave the pair priced at two rates."""
    part = {}
    apply_field(part, field, weak, "title_block")
    apply_field(part, field, strong, "solidworks_api")
    assert value_of(part, field) == strong
    apply_field(part, field, weak, "drawing_deterministic")
    assert value_of(part, field) == weak, f"{field} did not follow the same rule"


def test_it_works_on_a_nested_field():
    """The fields that drive cost mostly do not live at the top of a part."""
    part = {}
    apply_field(part, "normalized_geometry.cut_length_mm", 3802.9, "title_block")
    apply_field(part, "normalized_geometry.cut_length_mm", 7582.17, "solidworks_api")
    apply_field(part, "normalized_geometry.cut_length_mm", 3802.9, "drawing_deterministic")
    assert value_of(part, "normalized_geometry.cut_length_mm") == 3802.9


def test_the_quorum_is_a_named_constant_and_it_is_two():
    """Two is the smallest number that is not one source seen twice. Three would refuse the
    case this exists for — a drawing and its DXF export against a model."""
    assert sp.CORROBORATION_QUORUM == 2
