"""Price from the drawing when the overalls are clear, and mark it for check.

The sizing policy, in priority order:

  1. A measured flat (SolidWorks / DXF)          use it
  2. The detail's printed overall + thickness    infer, and say it was inferred
  3. A page vector sum or a scraped dimension    never
  4. Nothing usable                              estimator input

12392's back panel is the case. It is ours — laser, fold, weld, dress, coat — and the
model gives no flat because it is a weldment. It was priced at GBP 0.01 from a 16 x 3.7
blank nobody could account for, judged against a 6,679 mm "cut path" that is the PDF
reader's sum of every vector on the sheet.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import blank_credibility as bc  # noqa: E402
import estimator  # noqa: E402
import source_precedence  # noqa: E402


# ---------------------------------------------------------------------------
# 3. What is never blank evidence
# ---------------------------------------------------------------------------
def test_a_page_summed_vector_total_is_not_a_cut_path():
    """estimated_cut_length_mm sums borders, views, dimension lines and the title block
    at 72 points to the inch, with no drawing scale applied."""
    assert bc.cut_path_is_measured(None) is False
    assert bc.cut_path_is_measured("page_vector_sum") is False
    assert bc.cut_path_is_measured("llm_extract") is False


def test_a_measured_cut_path_is_evidence():
    assert bc.cut_path_is_measured("solidworks_api") is True
    assert bc.cut_path_is_measured("dxf_flat_pattern") is True


def test_an_unstamped_blank_is_not_treated_as_measured():
    """16 x 3.7 carried no source at all, which is what made it impossible to argue
    with. Absence of provenance is not provenance."""
    part = {"part_number": "X", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "blank_length_mm": 16, "blank_width_mm": 3.7,
            "estimated_cut_length_mm": 6678.66}
    assert estimator._blank_that_could_have_been_cut(part, 16, 3.7) == (None, None)


# ---------------------------------------------------------------------------
# 2. Inferring from the drawing, with the guardrails
# ---------------------------------------------------------------------------
def test_a_flat_part_is_sized_from_its_printed_overall():
    got = bc.blank_from_drawing_overalls(1435, 130, 1.5)
    assert got["usable"] is True
    assert (got["blank_length_mm"], got["blank_width_mm"]) == (1435.0, 130.0)
    assert got["source"] == "pdf_overall_dims"
    assert "confirm before a firm quote" in got["reason"]


def test_one_dimension_is_not_a_blank():
    assert bc.blank_from_drawing_overalls(1435, None, 1.5)["usable"] is False


def test_no_thickness_means_no_blank():
    """A sheet part with no thickness cannot be costed anyway, and demanding it rejects
    text scraped off a page that was never about this part."""
    assert bc.blank_from_drawing_overalls(1435, 130, None)["usable"] is False


def test_a_hole_pitch_is_not_an_overall_size():
    """The exact failure being replaced: small plausible numbers taken off the sheet."""
    got = bc.blank_from_drawing_overalls(16, 3.7, 1.5)
    assert got["usable"] is False
    assert "feature dimension" in got["reason"]


def test_an_absurdly_large_dimension_is_refused():
    assert bc.blank_from_drawing_overalls(9000, 130, 1.5)["usable"] is False


def test_a_folded_part_is_not_sized_from_its_overall():
    """A folded part unfolds longer than its finished extent. Sizing it from the overall
    quotes it short."""
    got = bc.blank_from_drawing_overalls(1435, 130, 1.5, is_folded=True)
    assert got["usable"] is False
    assert "needs a flat/DXF" in got["reason"]


def test_a_folded_part_with_a_stated_developed_length_is_sized_from_it():
    got = bc.blank_from_drawing_overalls(1435, 130, 1.5, is_folded=True,
                                         developed_length_mm=1520)
    assert got["usable"] is True
    assert got["blank_length_mm"] == 1520.0


def test_an_envelope_as_deep_as_the_material_has_no_fold_out_of_plane():
    """12392-02-01M's route names folding and its model envelope is 1.5mm deep — the
    material. Nothing leaves the plane, whatever the route says, so the overall IS the
    blank. Geometry outranks a read operation here."""
    got = bc.blank_from_drawing_overalls(1435, 130, 1.5, is_folded=True,
                                         bbox_mm=[130, 1435, 1.5])
    assert got["usable"] is True
    assert got["blank_length_mm"] == 1435.0
    assert "nothing leaves the plane" in got["reason"]


def test_a_genuinely_folded_part_is_still_refused_by_its_envelope():
    """Mutation guard on the rule above: a 40mm-deep box is a folded part and must not
    be sized from its overall."""
    got = bc.blank_from_drawing_overalls(1435, 130, 1.5, is_folded=True,
                                         bbox_mm=[130, 1435, 40])
    assert got["usable"] is False


# ---------------------------------------------------------------------------
# The whole policy, on the part that caused it
# ---------------------------------------------------------------------------
def _back_panel():
    return {"part_number": "12392-02-01M", "description": "BACK PANEL",
            "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 1.5,
            "quantity": 1, "blank_length_mm": 16, "blank_width_mm": 3.7,
            "overall_length_mm": 1435, "overall_width_mm": 130,
            "estimated_cut_length_mm": 6678.66,
            "textual_operations": ["folding", "welding", "laser_cutting"],
            "bbox_mm": [130.0, 1435.0, 1.5]}


def test_the_back_panel_prices_from_the_model_when_there_is_one():
    """With the SolidWorks pack present, the model's measured envelope outranks a number
    read off the drawing — and the stamp says which was used."""
    part = _back_panel()
    out = estimator.estimate_material(part)
    assert (out["blank_length_mm"], out["blank_width_mm"]) == (1435.0, 130.0)
    assert part["blank_length_mm_source"] == "bounding_box_floor"
    assert (out.get("cost_per_part_gbp") or 0) > 1.0, "a 1435x130x1.5 panel is not pennies"


def test_a_flat_part_prices_from_the_drawing_when_there_is_no_model():
    """The PDF-only case, which is the whole point of priority 2: no model, no flat, but
    the detail prints an overall — so it is priced and marked inferred rather than left
    as a material gap on a part we cut ourselves."""
    part = _back_panel()
    part.pop("bbox_mm")
    part["textual_operations"] = ["laser_cutting"]
    out = estimator.estimate_material(part)
    assert (out["blank_length_mm"], out["blank_width_mm"]) == (1435.0, 130.0)
    assert part["blank_length_mm_source"] == "pdf_overall_dims"
    assert part["blank_is_inferred"] is True
    assert "blank_inferred_from_drawing_overalls" in part["review_flags"]
    assert "confirm before a firm quote" in part["blank_inferred_reason"]
    assert (out.get("cost_per_part_gbp") or 0) > 1.0, "a 1435x130x1.5 panel is not pennies"


def test_the_back_panel_no_longer_blocks_the_job():
    import invariants

    part = _back_panel()
    estimator.estimate_material(part)
    assert invariants.check_a_blank_and_its_cut_path_can_both_be_true({"parts": [part]}) == []


def test_a_folded_part_with_no_model_says_it_needs_a_flat():
    """The guardrail, on the real part. With the model we can see its envelope is 1.5mm
    deep and nothing leaves the plane. Without it, the route says folding and a folded
    part's overall is not its blank — so this needs a flat pattern, and says so rather
    than quoting the part short."""
    part = _back_panel()
    part.pop("bbox_mm")
    out = estimator.estimate_material(part)
    assert out.get("blank_length_mm") is None
    assert "needs a flat/DXF" in part["blank_needs_sizing_reason"]


def test_a_measured_flat_is_never_second_guessed():
    """Mutation guard on the whole policy. If this fails, the gate is eating good
    geometry and the cure is worse than the disease."""
    part = {"part_number": "12392-02-02M", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "quantity": 1,
            "blank_length_mm": 1405, "blank_width_mm": 143.04, "cut_length_mm": 4226.7,
            "geometry_source": "solidworks_api",
            "blank_length_mm_source": "solidworks_api"}
    out = estimator.estimate_material(part)
    assert (out["blank_length_mm"], out["blank_width_mm"]) == (1405.0, 143.04)
    assert not part.get("review_flags")
    assert not part.get("blank_is_inferred")


def test_nothing_usable_leaves_the_part_for_the_estimator():
    part = {"part_number": "Z", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "quantity": 1,
            "blank_length_mm": 16, "blank_width_mm": 3.7}
    out = estimator.estimate_material(part)
    assert out.get("blank_length_mm") is None
    assert "blank_impossible_no_replacement" in part["review_flags"]


# ---------------------------------------------------------------------------
# Inferred must never outrank measured
# ---------------------------------------------------------------------------
def test_an_inferred_blank_ranks_below_every_measurement():
    assert source_precedence.rank("pdf_overall_dims") < source_precedence.rank("dxf")
    assert source_precedence.rank("pdf_overall_dims") < source_precedence.rank("solidworks_api")
    assert source_precedence.rank("pdf_overall_dims") > source_precedence.rank("llm_extract")
    assert source_precedence.rank("pdf_overall_dims") > source_precedence.rank("geometry_inference")
