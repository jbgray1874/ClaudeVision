"""A size nothing printed is never called a printed overall (D-598z).

The HPP column was read as one 1884 x 1580 x 18 board panel: 1884 is pi x 600, worked out by the
vision read. In MDF that blank fits no stocked sheet (the largest is 3050 x 1525), so the gate questioned it, and with no overall
printed the rescue was handed the same figure and returned it as "the detail's printed overall",
source pdf_overall_dims, which ranks 65 where the read's own figure ranks 20. The figure is now
kept under its own source, with the reason it was questioned and a request to confirm.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import estimator  # noqa: E402
import source_precedence  # noqa: E402


def _column(source):
    return {"part_number": "CPT09", "normalized_material": "MDF",
            "normalized_thickness_mm": 18.0, "blank_length_mm": 1884.0, "blank_width_mm": 1580.0,
            "blank_length_mm_source": source, "blank_width_mm_source": source,
            "geometry_source": source}


def _gate(part):
    return estimator._blank_that_could_have_been_cut(part, part["blank_length_mm"],
                                                     part["blank_width_mm"])


def test_a_sighted_blank_keeps_its_own_source_and_says_no_drawing_prints_it(capsys):
    part = _column("vision_concept")
    got = _gate(part)
    out = capsys.readouterr().out
    assert got == (1884.0, 1580.0), "the figure is still priced, as before"
    assert part["blank_length_mm_source"] == "vision_concept"
    assert part["geometry_source"] == "vision_concept"
    assert "printed overall" not in part["blank_inferred_reason"]
    assert "no drawing prints this size" in part["blank_inferred_reason"]
    assert "blank_kept_from_an_unprinted_size" in part["review_flags"]
    assert "blank_inferred_from_drawing_overalls" not in part["review_flags"]
    assert "printed overall" not in out
    assert source_precedence.rank("vision_concept") < source_precedence.rank("pdf_overall_dims")


def test_a_size_the_brief_stated_keeps_the_brief_as_its_source():
    part = _column("enquiry_brief")
    assert _gate(part) == (1884.0, 1580.0)
    assert part["blank_length_mm_source"] == "enquiry_brief"
    assert "the enquiry brief" in part["blank_inferred_reason"]


def test_a_printed_overall_is_still_called_one():
    part = dict(_column("llm_extract"), overall_length_mm=1884.0, overall_width_mm=1580.0)
    assert _gate(part) == (1884.0, 1580.0)
    assert part["blank_length_mm_source"] == "pdf_overall_dims"
    assert "printed overall" in part["blank_inferred_reason"]
    assert "blank_inferred_from_drawing_overalls" in part["review_flags"]
