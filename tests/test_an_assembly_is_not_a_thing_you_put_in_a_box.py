r"""
test_an_assembly_is_not_a_thing_you_put_in_a_box.py

THE TWO LARGEST BOUGHT-IN LINES ON THE JOB WERE PRICED AGAINST A PART THAT DOES NOT EXIST.

12349-02's packaging and delivery were asked for as:

    "Protective packaging and a pallet for 7 flat-packed display assemblies,
     largest panel 2026 x 1144mm, about 446 kg total, flat-packed on 1 pallet(s)"

Seven gravity feeders whose drawings mass about 28 kg each is roughly 196 kg, not 446. And
2026 mm is the install width off the general arrangement — not a panel anybody wraps.

describe_order is careful about parts with no blank and counts nothing it cannot measure. It
was not careful about WHAT it was measuring: it walked every part including the assembly
parents, whose material is already counted on their children (so the same steel is weighed
twice) and whose "blank" is not a blank at all but the envelope the finished unit occupies.

Both indications were asked against that. Packaging and delivery are the largest bought-in
lines on this job and nobody checks a haulage description, so it is the quieter of the two
places a phantom blank does damage — the other being the price of the part itself, which
blank_credibility already refuses. The same test now applies here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

commercial_lines = pytest.importorskip("commercial_lines")
from commercial_lines import describe_order                        # noqa: E402


GA = {"part_number": "12349-02-69", "is_assembly_parent": True,
      "blank_length_mm": 2026, "blank_width_mm": 1144,
      "normalized_thickness_mm": 6, "normalized_material": "MDF", "quantity": 1}
REAL = [
    {"part_number": "12349-02-69-01A", "blank_length_mm": 770, "blank_width_mm": 135,
     "normalized_thickness_mm": 5, "normalized_material": "ACRYLIC", "quantity": 3},
    {"part_number": "12349-02-69-03M", "blank_length_mm": 1144.53, "blank_width_mm": 357.9,
     "normalized_thickness_mm": 1.5, "normalized_material": "MILD_STEEL", "quantity": 3},
    {"part_number": "12349-02-69-08J", "blank_length_mm": 775, "blank_width_mm": 125,
     "normalized_thickness_mm": 6, "normalized_material": "MDF", "quantity": 3},
]


# ── the case that was broken ───────────────────────────────────────────────────

def test_the_assemblys_envelope_is_not_the_largest_panel():
    order = describe_order([GA] + REAL, 7)
    assert order["largest_part_mm"] == [1144.53, 357.9], (
        "2026mm is the install width off the GA, not a panel anybody wraps")


def test_the_assembly_is_not_weighed_on_top_of_its_own_children():
    with_ga = describe_order([GA] + REAL, 7)["order_weight_kg"]
    without = describe_order(REAL, 7)["order_weight_kg"]
    assert with_ga == without, "the same material is being counted twice"


@pytest.mark.parametrize("marker", [
    {"is_assembly_parent": True},
    {"route_context": {"is_assembly_parent": True}},
    {"is_sub_assembly": True},
])
def test_every_way_a_record_says_it_is_an_assembly_is_honoured(marker):
    part = dict(GA)
    part.pop("is_assembly_parent")
    part.update(marker)
    assert describe_order([part] + REAL, 7)["largest_part_mm"] == [1144.53, 357.9]


# ── and a blank that fits no sheet ─────────────────────────────────────────────

def test_a_blank_that_fits_no_stock_sheet_is_not_shipped_either():
    """The test that stops such a figure being PRICED should stop it being SHIPPED. A
    2120 x 2120 acrylic panel fits neither 2050x1520 nor 3050x2050 in either rotation."""
    phantom = {"part_number": "01A", "blank_length_mm": 2120, "blank_width_mm": 2120,
               "normalized_thickness_mm": 5, "normalized_material": "HIGH IMPACT ACRYLIC",
               "quantity": 3}
    order = describe_order([phantom] + REAL, 7)
    assert order["largest_part_mm"] == [1144.53, 357.9]
    assert order["parts_with_an_impossible_blank"] == 1, (
        "counted apart from an ordinary miss: this is a defect upstream, not a gap in the "
        "drawings")


# ── what must still work ───────────────────────────────────────────────────────

def test_real_parts_are_still_measured_and_counted():
    order = describe_order(REAL, 7)
    assert order["parts_measured"] == 3
    assert order["order_weight_kg"] and order["order_weight_kg"] > 0


def test_the_weight_still_scales_with_the_order():
    one = describe_order(REAL, 1)["order_weight_kg"]
    ten = describe_order(REAL, 10)["order_weight_kg"]
    # Each call rounds to the penny before returning, so ten times a rounded
    # figure is not the rounded figure of ten. The point is that it scales.
    assert ten == pytest.approx(one * 10, abs=0.5)


def test_a_part_with_no_blank_still_contributes_nothing_rather_than_a_guess():
    order = describe_order(REAL + [{"part_number": "X"}], 7)
    assert order["parts_measured"] == 3 and order["parts_without_a_blank"] == 1


def test_the_pallet_plan_is_built_from_the_same_parts_as_the_weight():
    """Handing plan_shipment the unfiltered list left the carton and pallet count resting on
    the envelope the weight had just been cleared of — half a fix, and the half nobody
    reads."""
    with_ga = describe_order([GA] + REAL, 7).get("shipment")
    without = describe_order(REAL, 7).get("shipment")
    assert with_ga == without


def test_a_job_of_nothing_but_assemblies_reports_no_shipment_rather_than_a_phantom():
    order = describe_order([GA], 7)
    assert order["largest_part_mm"] is None
    assert order["order_weight_kg"] is None
