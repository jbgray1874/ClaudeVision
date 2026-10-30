"""What a stronger source replaced, kept.

A REFUSAL WAS ALWAYS RECORDED AND A SUCCESSFUL REPLACEMENT WAS NOT. When an incoming value
lost, apply_field flagged the disagreement with both values and both sources. When it WON,
whatever it replaced was overwritten and nothing recorded that anything had been -- so a datum
three sources argued over looked identical to one nobody contradicted.

11650's door is what that costs. The model gave 11650-01-05A as ABS; a DXF filename said
POLYCARBONATE and so did the drawing text. The model outranked both, the part went from
GBP 35.28 to GBP 0.00 because ABS has a sheet size and a density in config and no rate -- and
asking afterwards whether independent sources had agreed against the winner was impossible.
The answer had been discarded at the moment it became worth having.

THAT RECORD NOW HAS A RULE READING IT. When this file was written it ended "nothing here
changes an outcome; rank still decides" — true then, and no longer true, so it is corrected
rather than left standing. corroboration_overrules lets a QUORUM of independent sources
outweigh a SINGLE stronger one, and the record below is what it counts.

The half that was still missing is also fixed: a REFUSED reading was written into review_flags
as English prose and into the record not at all, so the evidence base held only the readings
that had won and later lost. On 11650-04 every PETG reading after the first was refused — the
title block, the options list, six DXF exports — and nothing could count any of them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from source_precedence import (apply_field, displaced_values,          # noqa: E402
                               corroboration_against, value_of, source_of)


def _door():
    """The live sequence, in the order the readers run."""
    part = {}
    apply_field(part, "normalized_material", "POLYCARBONATE", "dxf")
    apply_field(part, "normalized_material", "ABS", "solidworks_api")
    return part


def test_rank_still_decides_and_nothing_moved():
    part = _door()
    assert value_of(part, "normalized_material") == "ABS"
    assert source_of(part, "normalized_material") == "solidworks_api"


def test_what_the_winner_replaced_is_still_readable():
    assert displaced_values(_door(), "normalized_material") == [
        {"value": "POLYCARBONATE", "source": "dxf", "applied": True,
         "displaced_by": "solidworks_api"}]


def test_a_reading_that_was_refused_is_evidence_too():
    """THIS FILE USED TO ASSERT THE OPPOSITE, on the reasoning that a refusal is flagged
    elsewhere and recording it here would count one disagreement twice.

    That reasoning was wrong, and 11650-04 is the proof. The title block says PETG, the
    options list says PETG or PC, six DXF exports are named 2MM PETG, and the parts catalogue
    stocks PETG — against ONE SolidWorks property saying ABS. Every one of those readings
    after the first was refused, so the record held one PETG observation and the honest count
    was four. A rule asking "did independent sources agree against the winner" cannot be built
    on a log that keeps only the winners.

    Counted once per source, so the same reader saying the same thing twice is still one.
    """
    part = _door()
    apply_field(part, "normalized_material", "MILD_STEEL", "pdf_overall_dims")
    log = displaced_values(part, "normalized_material")
    assert [(e["value"], e["applied"]) for e in log] == [
        ("POLYCARBONATE", True), ("MILD_STEEL", False)]
    apply_field(part, "normalized_material", "MILD_STEEL", "pdf_overall_dims")
    assert len(displaced_values(part, "normalized_material")) == 2


def test_agreement_is_not_a_displacement():
    part = {}
    apply_field(part, "normalized_material", "POLYCARBONATE", "dxf")
    apply_field(part, "normalized_material", "POLYCARBONATE", "solidworks_api")
    assert displaced_values(part, "normalized_material") == []


def test_the_same_value_written_twice_records_nothing():
    part = {}
    apply_field(part, "blank_length_mm", 1202, "dxf")
    apply_field(part, "blank_length_mm", 1202, "solidworks_api")
    assert displaced_values(part, "blank_length_mm") == []


def test_who_disagreed_with_what_is_now_answerable():
    got = corroboration_against(_door(), "normalized_material")
    assert got["value"] == "POLYCARBONATE" and got["sources"] == ["dxf"]


def test_two_readers_agreeing_with_themselves_are_one_observation():
    """Distinct SOURCES, not distinct readings. Two passes of one reader agreeing with itself
    is one observation seen twice, and counting it twice is how a single stale filename would
    come to outvote a model."""
    # BUILT DIRECTLY, because apply_field cannot reach this state: with real rank rules a
    # given source displaces a given value at most once, so driving it through the arbiter
    # left one entry and the assertion passed without the dedup ever running. Green for a
    # reason unrelated to the claim. This is a unit test of corroboration_against, and the
    # record it reads is what a future reader with looser ordering would produce.
    part = {"normalized_material": "ABS", "normalized_material_source": "solidworks_api",
            "_displaced": {"normalized_material": [
                {"value": "POLYCARBONATE", "source": "dxf"},
                {"value": "POLYCARBONATE", "source": "dxf"},
            ]}}
    assert corroboration_against(part, "normalized_material")["count"] == 1


def test_two_different_sources_disagreeing_with_the_winner_count_as_two():
    """The case the whole record exists for: a drawing and a DXF both saying POLYCARBONATE
    against a model saying ABS is a different fact from one stale filename, and until now
    neither could be told from the other."""
    part = {"normalized_material": "ABS", "normalized_material_source": "solidworks_api",
            "_displaced": {"normalized_material": [
                {"value": "POLYCARBONATE", "source": "dxf"},
                {"value": "POLYCARBONATE", "source": "drawing_deterministic"},
            ]}}
    got = corroboration_against(part, "normalized_material")
    assert got["count"] == 2
    assert got["sources"] == ["drawing_deterministic", "dxf"]


def test_an_uncontested_datum_reports_no_disagreement():
    part = {}
    apply_field(part, "normalized_material", "MILD_STEEL", "solidworks_api")
    assert corroboration_against(part, "normalized_material") == {
        "count": 0, "value": None, "sources": []}


def test_a_non_part_is_survivable():
    assert displaced_values(None, "x") == [] and displaced_values("", "x") == []


if __name__ == "__main__":                                              # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
