r"""
test_a_quorum_defends_as_well_as_overrules.py

THE RULE WAS ASKED ONLY ON THE BRANCH WHERE IT COULD NOT HELP.

source_precedence has carried a quorum rule for a while: several independent readings
agreeing outweigh a single stronger one, because that is the question an estimator asks in
front of the drawing. Its docstrings name the jobs it was written for.

apply_field asked it in exactly one place -- after `may_overwrite` had REFUSED. That is the
branch a WEAKER or equal source takes. So the quorum could defend a value against sources
that could not have taken it anyway, and had nothing to say when a stronger one arrived.

Every job the module cites is the stronger-source shape:

  * 11650-04's door: title block, an options list and six DXF exports say PETG; one
    SolidWorks property says ABS, outranks them 90 to 70, and the part goes from GBP 35.28
    to GBP 0.00 because ABS has a sheet size and a density in config and no rate.
  * 12349-02-69-04M: the DXF is named `1.2MM_MS`, the title block reads "1.2 THK", the
    model's cut list says 6mm. Two readings against one, and the one wins on rank -- a
    1.2mm bracket costed as 6mm plate.

In both the losing evidence was recorded and countable. Nothing ever counted it.

What must NOT change: a stronger source correcting a value only ONE source holds. That is
precedence doing its job, and it is most of what the resolver is for.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

sp = pytest.importorskip("source_precedence", reason="the resolver under test")


def _gauge_read_twice_off_the_drawing():
    """04M as the pack presents it: the export filename, then the title block agreeing."""
    part = {}
    sp.apply_field(part, "normalized_thickness_mm", 1.2, "dxf_filename")
    sp.apply_field(part, "normalized_thickness_mm", 1.2, "title_block")
    return part


# ── the case that was broken ───────────────────────────────────────────────────

def test_two_drawing_sources_hold_a_gauge_against_the_model():
    part = _gauge_read_twice_off_the_drawing()
    wrote = sp.apply_field(part, "normalized_thickness_mm", 6.0, "solidworks_api")
    assert wrote is False
    assert part["normalized_thickness_mm"] == 1.2, (
        "a 1.2mm bracket costed as 6mm plate is the whole of this test")
    assert sp.source_of(part, "normalized_thickness_mm") == "dxf_filename"


def test_the_model_reading_is_kept_on_the_record_it_lost():
    """Refused is not discarded. Someone has to be able to see the model said 6."""
    part = _gauge_read_twice_off_the_drawing()
    sp.apply_field(part, "normalized_thickness_mm", 6.0, "solidworks_api")
    said = {(e["source"], e["value"]) for e in sp.displaced_values(part, "normalized_thickness_mm")}
    assert ("solidworks_api", 6.0) in said


def test_the_conflict_is_flagged_for_a_person_to_settle():
    part = _gauge_read_twice_off_the_drawing()
    sp.apply_field(part, "normalized_thickness_mm", 6.0, "solidworks_api")
    blob = " ".join(part.get("review_flags") or [])
    assert "solidworks_api" in blob and "confirm which is right" in blob
    ev = part["_corroboration"]["normalized_thickness_mm"]
    assert ev["value"] == 1.2
    assert sorted(ev["sources"]) == ["dxf_filename", "title_block"]
    assert ev["refused_value"] == 6.0


def test_11650s_door_keeps_the_material_four_readings_agree_on():
    part = {}
    sp.apply_field(part, "normalized_material", "PETG", "title_block")
    sp.apply_field(part, "normalized_material", "PETG", "dxf_filename")
    sp.apply_field(part, "normalized_material", "ABS", "solidworks_api")
    assert part["normalized_material"] == "PETG"


# ── precedence, still working ──────────────────────────────────────────────────

def test_a_stronger_source_still_corrects_a_value_only_one_source_holds():
    """The common case, and the one the resolver mostly exists for."""
    part = {}
    sp.apply_field(part, "normalized_thickness_mm", 1.2, "dxf_filename")
    assert sp.apply_field(part, "normalized_thickness_mm", 2.0, "solidworks_api") is True
    assert part["normalized_thickness_mm"] == 2.0


def test_one_source_saying_it_twice_is_not_a_quorum():
    """Two passes of one reader agreeing with itself is one observation seen twice."""
    part = {}
    sp.apply_field(part, "normalized_thickness_mm", 1.2, "dxf_filename")
    sp.apply_field(part, "normalized_thickness_mm", 1.2, "dxf_filename")
    assert sp.apply_field(part, "normalized_thickness_mm", 6.0, "solidworks_api") is True
    assert part["normalized_thickness_mm"] == 6.0


def test_anything_may_still_fill_an_empty_field():
    part = {}
    assert sp.apply_field(part, "normalized_thickness_mm", 6.0, "solidworks_api") is True
    assert part["normalized_thickness_mm"] == 6.0


def test_a_quorum_defends_only_while_it_is_the_larger_side():
    """Two against two is not a quorum against a singleton any more, and rank decides it —
    which is the resolver's ordinary job. The defence is for the LOPSIDED case: several
    readings against one. It must not turn into a permanent veto that no amount of
    contrary evidence can shift."""
    part = {}
    sp.apply_field(part, "normalized_material", "PETG", "title_block")
    sp.apply_field(part, "normalized_material", "PETG", "dxf_filename")
    assert sp.apply_field(part, "normalized_material", "ABS", "solidworks_api") is False
    assert sp.apply_field(part, "normalized_material", "ABS", "solidworks_flat_pattern") is True
    assert part["normalized_material"] == "ABS", (
        "two model readings against two drawing readings is settled on rank, not on count")


def test_an_estimator_is_never_outvoted_by_readers():
    """A person deciding is not a reading. This is the one source the quorum may not stop."""
    part = _gauge_read_twice_off_the_drawing()
    assert sp.apply_field(part, "normalized_thickness_mm", 3.0, "estimator_confirmed") is True
    assert part["normalized_thickness_mm"] == 3.0


def test_a_confirming_source_does_not_count_as_an_attacker():
    """Agreement is handled before any of this and must stay a provenance question."""
    part = _gauge_read_twice_off_the_drawing()
    assert sp.apply_field(part, "normalized_thickness_mm", 1.2, "solidworks_api") is False
    assert part["normalized_thickness_mm"] == 1.2
    assert sp.source_of(part, "normalized_thickness_mm") == "solidworks_api", (
        "agreement from a stronger source should still upgrade the provenance")


# ── the rule the other way round, unchanged ────────────────────────────────────

def test_a_quorum_still_overrules_a_stronger_incumbent_that_wrote_first():
    """corroboration_overrules, the half that already worked: the model gets there first
    and two drawing sources arrive after it."""
    part = {}
    sp.apply_field(part, "normalized_material", "ABS", "solidworks_api")
    sp.apply_field(part, "normalized_material", "PETG", "title_block")
    sp.apply_field(part, "normalized_material", "PETG", "dxf_filename")
    assert part["normalized_material"] == "PETG"
