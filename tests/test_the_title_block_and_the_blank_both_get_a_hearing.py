r"""Two numbers for the mass of one part, and the sheet named neither.

James Gray, 17 September 2026, on 401912-02 (Tesco, Metal Divider — Tall):

    "1.7 kg is the drawing figure. Title block on both sheets: WEIGHT 1.7 kg. Use that as
     the stated mass — do not replace it with a STEP/volume guess... If the engine prints a
     different steel mass, flag it against 1.7 kg — do not silently overwrite the title
     block."

401912-02 is the case the existing gate cannot see. Its blank is 460 x 356.6 of 2 mm CR4,
which is 2.575 kg of steel; the title block says 1.7 kg. The plausibility gate fires only
outside half-to-three-times, and 0.66 is comfortably inside, so nothing was said and the
material was costed from the lighter figure without a word.

BOTH NUMBERS ARE USUALLY RIGHT, AND THEY ARE NOT THE SAME QUANTITY.

    STATED WEIGHT     the FINISHED part, after the window is cut out of it
    BLANK             what is BOUGHT, before anything is cut out of it

On this divider the difference is the triangular window: 0.88 kg of steel that is paid for
and thrown away. Costing the net weight under-buys the material by exactly the size of the
hole. On a part with no cut-outs the two should agree, and a gap means one of them is
wrong. Either way it is a question for a person and it takes five seconds — once somebody
is told it exists.

NOTHING IS OVERWRITTEN AND NO PRICE MOVES. The engine says which figure it costed from,
what the other one was, and what the difference means. A silent choice between two
defensible numbers is the one outcome nobody can check.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator  # noqa: E402

# The divider, as the pack presents it: the developed blank off sheet 2, the gauge both the
# title block and the DXF agree on, and the printed mass.
_DIVIDER = {"part_number": "401912-02-01M", "description": "METAL DIVIDER - TALL",
            "normalized_material": "MILD STEEL", "normalized_thickness_mm": 2.0,
            "blank_length_mm": 460.0, "blank_width_mm": 356.6, "quantity": 1,
            "dxf_weight_kg": 1.7, "geometry_source": "dxf_flat_pattern"}


def _divider(**over):
    return dict(_DIVIDER, **over)


def test_the_disagreement_is_reported_at_all():
    """0.66 of the blank — inside the plausibility band, so the old gate said nothing."""
    part = _divider()
    estimator.estimate_material(part)
    assert any("MASS:" in str(f) for f in part.get("review_flags", [])), \
        part.get("review_flags")


def test_it_names_both_numbers():
    part = _divider()
    estimator.estimate_material(part)
    said = " ".join(str(f) for f in part.get("review_flags", []))
    assert "1.7 kg" in said
    assert "2.58 kg" in said, said


def test_the_measured_blank_buys_the_steel():
    """"Steel cost from nested blank area, with 1.7 kg only a sanity check." That is the
    transaction: a laser part is nested on a sheet and you pay for its share of that sheet,
    cut-out and all. Costing the finished weight is buying back the hole."""
    part = _divider()
    out = estimator.estimate_material(part)
    said = " ".join(str(f) for f in part.get("review_flags", []))
    assert "costed from the MEASURED BLANK" in said
    assert part["stated_weight_vs_blank"]["costed_from"] == "blank"
    assert "stated_weight" not in str(out.get("cost_method") or "")


def test_without_a_measured_flat_the_printed_weight_still_wins():
    """The control on the other half, and the reason this is scoped. A blank read off a
    drawing image is the weaker of the two facts, and that behaviour is unchanged."""
    part = _divider(geometry_source="pdf_vision")
    estimator.estimate_material(part)
    said = " ".join(str(f) for f in part.get("review_flags", []))
    assert "costed from the STATED" in said
    assert part["stated_weight_vs_blank"]["costed_from"] == "stated_weight"


def test_it_says_what_the_difference_means_and_how_big_it_is():
    """"They differ" is a fact. "The window is 0.88 kg of steel you buy and scrap" is the
    thing an estimator can act on."""
    part = _divider()
    estimator.estimate_material(part)
    said = " ".join(str(f) for f in part.get("review_flags", []))
    assert "0.88 kg" in said, said
    assert "scrap that was paid for" in said


def test_the_record_carries_both_for_the_report_to_read():
    part = _divider()
    estimator.estimate_material(part)
    rec = part["stated_weight_vs_blank"]
    assert rec["stated_weight_kg"] == 1.7
    assert rec["blank_implied_kg"] == 2.575
    assert rec["blank_length_mm"] == 460.0


def test_the_title_block_is_not_overwritten():
    """His instruction, exactly. The engine reports; it does not decide for him."""
    part = _divider()
    estimator.estimate_material(part)
    assert part["dxf_weight_kg"] == 1.7
    said = " ".join(str(f) for f in part.get("review_flags", []))
    assert "not overwritten" in said


def test_a_stated_weight_heavier_than_its_blank_is_called_out_differently():
    """A flat part cannot weigh more than the rectangle it was cut from — that is not a
    cut-out, it is an error in one of the two figures."""
    part = _divider(dxf_weight_kg=4.0)
    estimator.estimate_material(part)
    said = " ".join(str(f) for f in part.get("review_flags", []))
    assert "HEAVIER than the blank" in said


# ── the controls ─────────────────────────────────────────────────────────────────────

def test_a_part_whose_weight_matches_its_blank_says_nothing():
    """A flag that fires on every part is read on none of them. 2.57 kg against a 2.58 kg
    blank is agreement, and agreement is not news."""
    part = _divider(dxf_weight_kg=2.57)
    estimator.estimate_material(part)
    assert not any("MASS:" in str(f) for f in part.get("review_flags", []))
    assert "stated_weight_vs_blank" not in part


def test_a_part_with_no_stated_weight_says_nothing():
    part = _divider()
    part.pop("dxf_weight_kg")
    estimator.estimate_material(part)
    assert not any("MASS:" in str(f) for f in part.get("review_flags", []))


def test_a_part_with_no_blank_to_check_against_says_nothing():
    """Nothing to compare is not a disagreement."""
    part = _divider(blank_length_mm=None, blank_width_mm=None)
    estimator.estimate_material(part)
    assert not any("MASS:" in str(f) for f in part.get("review_flags", []))


def test_a_part_whose_figures_agree_is_costed_exactly_as_before():
    """The change is scoped to a DISAGREEMENT. Where the weight and the blank say the same
    thing there is nothing to arbitrate and nothing moves."""
    part = _divider(dxf_weight_kg=2.57)
    out = estimator.estimate_material(part)
    assert "stated_weight_vs_blank" not in part
    assert out.get("unit_material_cost_gbp") is not None or out.get(
        "cost_per_part_gbp") is not None
