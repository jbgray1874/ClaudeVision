"""A sentence naming a source must name the one that finally supplied the value.

The write-up's observations are composed at file_scan.py:1912. The SolidWorks connector
applies the model's material at 2352. So the sentence was a snapshot of an arbitration
that had not finished, and job 12392's deliverable said

    12392-02-01M: material MILD STEEL (from drawing_deterministic)

about a record whose own provenance trail says solidworks_api. The value was right and
the attribution named a source that had lost — which sends an estimator to a title block
that does not hold the answer, to check a number that came from the model.

This is not the dual-record problem. There is one record; the sentence describing it was
simply written too early.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from document_builder import (material_observation,                 # noqa: E402
                              restate_material_observations)
from source_precedence import apply_field                           # noqa: E402


def _summary_mid_arbitration():
    """A write-up as it stands when the observations are composed: the title block has
    spoken, the model has not."""
    part = {"part_number": "12392-02-01M", "materials": ["Card"],
            "normalized_material": "MILD_STEEL",
            "material_source": "drawing_deterministic"}
    return {
        "manufacturing_writeup": {
            "parts": [part],
            "manufacturing_observations": [
                "12392-02-01M: finish detected (RAW).",
                material_observation("12392-02-01M", part),
                "12392-02-01M: process notes detected (FLAT SHEET TAPPING).",
            ],
        }
    }, part


def test_the_sentence_follows_the_record_when_a_stronger_source_arrives():
    summary, part = _summary_mid_arbitration()
    assert "drawing_deterministic" in summary["manufacturing_writeup"][
        "manufacturing_observations"][1]

    # The model speaks, through the resolver, exactly as the connector does.
    apply_field(part, "normalized_material", "MILD_STEEL", "solidworks_api")

    changed = restate_material_observations(summary)

    line = summary["manufacturing_writeup"]["manufacturing_observations"][1]
    assert changed == 1
    assert "solidworks_api" in line, \
        "the observation still credits the source that lost the arbitration"
    assert "drawing_deterministic" not in line


def test_the_other_observations_are_left_alone():
    summary, part = _summary_mid_arbitration()
    apply_field(part, "normalized_material", "MILD_STEEL", "solidworks_api")
    restate_material_observations(summary)

    obs = summary["manufacturing_writeup"]["manufacturing_observations"]
    assert obs[0] == "12392-02-01M: finish detected (RAW)."
    assert obs[2] == "12392-02-01M: process notes detected (FLAT SHEET TAPPING)."


def test_a_sentence_that_is_already_right_is_not_rewritten():
    """A restatement that changes nothing must report nothing. A count that always reads
    non-zero cannot distinguish a run that had work to do from one that did not."""
    summary, _part = _summary_mid_arbitration()
    assert restate_material_observations(summary) == 0


def test_the_conclusion_still_comes_before_the_reading():
    """The rule this sentence was written for, which must survive being made a function:
    what we COSTED first, and only then what the drawing text said."""
    part = {"part_number": "X", "materials": ["Card"],
            "normalized_material": "MILD_STEEL", "material_source": "solidworks_api"}
    line = material_observation("X", part)
    assert line.index("MILD_STEEL") < line.index("Card"), \
        "a report that shows the loser of an arbitration first is worse than one that " \
        "shows nothing"
    assert "was not used" in line


def test_an_agreeing_material_reads_plainly():
    part = {"part_number": "X", "materials": ["MILD STEEL"],
            "normalized_material": "MILD_STEEL", "material_source": "solidworks_api"}
    assert material_observation("X", part) == "X: material detected (MILD STEEL)."


def test_the_sentence_has_one_definition():
    """Two spellings of it would drift, and only the one composed early would ever be
    read — which is how the stale attribution survived in the first place."""
    src = (Path(__file__).resolve().parents[1] / "src" / "document_builder.py").read_text(
        encoding="utf-8")
    assert src.count("the drawing text read as") == 1, \
        "the material sentence is written out more than once in document_builder"


def test_the_restatement_is_wired_into_the_run():
    """Built is not wired. The function existing changes no deliverable; being called
    after every applier is the whole fix."""
    import re as _re

    src = (Path(__file__).resolve().parents[1] / "src" / "file_scan.py").read_text(
        encoding="utf-8")
    # WORD BOUNDARY. A plain substring test passes against
    # `restate_material_observations_MUTANT`, which is exactly the edit this guard exists
    # to catch — the first version of this test did, and reported the wiring intact.
    hit = _re.search(r"\brestate_material_observations\b", src)
    assert hit, "the restatement is not called from the run"
    assert hit.start() > src.index("apply_native_to_pre_estimate"), \
        "the restatement must run AFTER the connector that supplies the material"


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
