"""Four commits of "raised so a person can rule on it" reached nobody at all.

Grepped across 7332-01's 20:26 workbook and its report, every sheet and every cell:

    brushing before the platers        0 hits
    "1.0 mm in lieu" substitution      0 hits
    tube bend charged on a word alone  0 hits
    the double plater pack             0 hits

All four are written. `part["review_flags"]` is where this engine puts every ruling it wants
a person to make, and part review flags reach neither deliverable. The workbook's OUTSTANDING
ESTIMATOR INPUTS block is fed by three things only — unpriced BOM rows, an unset margin, and
the powder coverage assumption — so a question about a part that IS priced has nowhere to go.

Which means the honest third option we kept choosing was not honest. "Not costed, because
nobody drew it — named instead so an estimator decides" is only true if the estimator can
see it. Otherwise it is just not costed, and from Howard Thurley's side the sheet looked as
though his email had been read and ignored.

A DECISION COSTS NOTHING TO WRITE AND EVERYTHING TO LOSE. The flags that ASK something now
join the other outstanding inputs, so one list on the sheet is the whole of what is
unresolved — priced or not.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SRC = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")


def test_part_review_flags_now_feed_the_outstanding_list():
    assert "THE QUESTIONS THE ENGINE RAISED, WHICH REACHED NOBODY" in SRC
    assert "_inputs.append" in SRC.split(
        "THE QUESTIONS THE ENGINE RAISED, WHICH REACHED NOBODY")[1].split(
        "_write_estimator_inputs")[0]


def test_only_the_flags_that_ask_something_are_promoted():
    """A provenance note is not a question. Promoting every flag would bury the ones that
    need an answer under the ones that do not, which is how a checklist stops being read."""
    block = SRC.split("THE QUESTIONS THE ENGINE RAISED")[1][:2500]
    for word in ("confirm", "tbc", "your call", "estimator"):
        assert word in block


def test_the_same_question_is_not_listed_twice():
    """A flag raised on a part that appears in more than one record source would otherwise
    appear two or three times, which reads as three problems."""
    block = SRC.split("THE QUESTIONS THE ENGINE RAISED")[1][:2500]
    assert "_seen_asks" in block


def test_it_reads_the_records_the_costing_stage_actually_stamped():
    """The flags are written onto the estimator's own part dicts, which reach the workbook
    through the summary — not through any local list. Reading the wrong one is how this
    would silently find nothing and pass."""
    block = SRC.split("THE QUESTIONS THE ENGINE RAISED")[1][:2500]
    assert "estimate_summary" in block and "part_estimates" in block


# ── the four questions themselves, still asked at source ─────────────────────────────────

from estimator import estimate_process_times                             # noqa: E402


def _flags(part):
    return " ".join(str(f) for f in part.get("review_flags") or [])


def test_the_brushing_question_is_raised_on_a_plated_part():
    part = {"part_number": "7332-01-101", "description": "FRAME WELDMENT",
            "normalized_material": "MILD_STEEL", "normalized_finish": "PLATED",
            "textual_operations": ["welding", "assembly"], "quantity": 1}
    estimate_process_times(part, 6)
    text = _flags(part)
    assert "brushes material before it goes to the platers" in text
    assert "40 minutes" in text
    assert "Add it if" in text                       # it ASKS — so it gets promoted


def test_the_gauge_substitution_question_is_raised_at_zero_nine():
    part = {"part_number": "7332-01-008", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 0.9, "textual_operations": ["laser_cutting"]}
    estimate_process_times(part, 6)
    text = _flags(part)
    assert "1.0 mm in lieu" in text and "confirm" in text.lower()


def test_the_tube_bend_question_is_raised_when_only_a_word_states_it():
    part = {"part_number": "7332-01-002", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.2, "fold_count_textual": 2,
            "textual_operations": ["tube_bending"],
            "material_estimate": {"stock_form": "tube"}}
    estimate_process_times(part, 6)
    text = _flags(part)
    assert "CHARGED on the drawing's word alone" in text
    assert "Confirm the leg actually bends" in text


def test_a_job_with_none_of_these_raises_none_of_them():
    """12349-02 is powder coated, has no tube and no thin-gauge steel. A checklist that grows
    on every job is a checklist nobody reads."""
    part = {"part_number": "12349-02-69-04M", "description": "LID",
            "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 1.5,
            "normalized_finish": "POWDER COATED RAL9005",
            "textual_operations": ["laser_cutting", "folding"], "quantity": 1}
    estimate_process_times(part, 6)
    text = _flags(part).lower()
    assert "brushes material" not in text
    assert "in lieu" not in text
    assert "word alone" not in text
