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

NOTHING HERE CHANGES AN OUTCOME. Rank still decides, exactly as before. This is the record any
rule about corroboration would have to read, and it did not exist.
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
        {"value": "POLYCARBONATE", "source": "dxf", "displaced_by": "solidworks_api"}]


def test_a_weaker_source_that_never_landed_leaves_no_displacement():
    """Only a value that was actually HELD can be displaced. A refusal is already flagged
    elsewhere with both sides, and recording it here too would count one disagreement twice."""
    part = _door()
    apply_field(part, "normalized_material", "MILD_STEEL", "pdf_overall_dims")
    assert len(displaced_values(part, "normalized_material")) == 1


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
