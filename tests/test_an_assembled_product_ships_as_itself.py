"""An assembled product ships as itself (D-530).

James, 14 Oct 2026, on the 0356456 tote trolley: "we should be using the boxing calculation now?
Delivery looks ok until we get the correct calculator; the cartons no. is clearly wrong." The
shipment planner packed every product as loose parts by weight into standard 25 kg cartons —
right for a flat-pack display, wrong for a welded trolley, which cannot be taken apart to pack:
one trolley came out as two cartons, 1,000 as 1,414. A welded unit with a known overall size is
now one carton per unit, sized around the product, and the pallets are how many of those a
pallet footprint takes. Anything else packs by its parts exactly as before.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import commercial_lines as cl  # noqa: E402
import concept_scan as cs  # noqa: E402
import palletising  # noqa: E402


def _unit(welded=True, envelope=(630, 480, 1035)):
    u = {"part_number": "J-CPT00", "description": "TROLLEY — unit assembly",
         "is_assembly_parent": True, "quantity": 1,
         "inferred_operations": ["welding", "assembly"] if welded else ["assembly"]}
    if envelope:
        u["product_envelope_mm"] = dict(zip(("length", "width", "height"), envelope),
                                         source="the read's overall size")
    return u


def _parts(welded=True):
    ops = ["welding"] if welded else ["saw"]
    return [
        {"part_number": "J-CPT01", "description": "SIDE", "blank_length_mm": 830,
         "blank_width_mm": 620, "normalized_thickness_mm": 1.5, "quantity": 2,
         "normalized_material": "MILD STEEL", "inferred_operations": ops},
        {"part_number": "J-CPT02", "description": "FRAME POST", "blank_length_mm": 880,
         "blank_width_mm": 25, "normalized_thickness_mm": 1.5, "quantity": 4,
         "normalized_material": "MILD STEEL", "inferred_operations": ops,
         "material_estimate": {"stock_form": "tube", "unit_material_mass_kg": 0.974}},
    ]


def test_a_welded_unit_is_one_carton_per_unit_sized_around_itself():
    for q in (1, 25, 1000):
        o = cl.describe_order([_unit()] + _parts(), q)
        sh = o["shipment"]
        assert sh["ships_assembled"] and sh["carton_count"] == q
        assert sh["carton_internal_mm"] == [630.0, 480.0, 1035.0]
        assert sh["units_per_pallet"] == 2, "630 x 480 sits two to a 1200 x 1000 pallet"
        assert sh["pallet_count"] == -(-q // 2)


def test_the_box_line_prices_one_carton_around_the_product():
    o = cl.describe_order([_unit()] + _parts(), 25)
    b = cl._box_method_price(o)
    assert b and b["source_class"] == "box_calculator"
    assert "one per unit" in b["working"] and "630 x 480 x 1035" in b["working"]
    import box_costing
    each = box_costing.price_box(630, 480, 1035, 25)["sheet_total_gbp"]
    assert abs(b["order_gbp"] - round(each * 25, 2)) < 0.01
    assert b["order_gbp_at_breaks"][1] > b["order_gbp_at_breaks"][100] / 100, (
        "the set-up is spread over the order's cartons at each break")


def test_an_unwelded_product_still_packs_by_its_parts():
    o = cl.describe_order([_unit(welded=False)] + _parts(welded=False), 1)
    assert not o["shipment"].get("ships_assembled") and "assembled_unit" not in o


def test_a_product_with_no_overall_size_packs_by_its_parts():
    o = cl.describe_order([_unit(envelope=None)] + _parts(), 1)
    assert not o["shipment"].get("ships_assembled")


def test_a_unit_larger_than_the_pallet_is_one_per_pallet_and_flagged():
    plan = palletising.plan_shipment([{"_assembled_unit": True,
                                       "envelope_mm": [2400, 1100, 900],
                                       "unit_weight_kg": 80}], 3)
    assert plan["pallet_count"] == 3 and "unit_exceeds_pallet" in plan["flags"]


def test_a_section_is_weighed_by_its_costed_mass_in_the_shipment_description():
    o = cl.describe_order(_parts(), 1)
    post = next(p for p in o["counted_parts"] if p["part_number"] == "J-CPT02")
    assert post["kg_each"] == 0.974, "a box section's weight is not length x width x wall"


def test_the_unit_record_carries_the_products_overall_size():
    ans = {"product": {"name": "TROLLEY",
                       "assumed_overall_mm": {"height": 1035, "width": 480, "depth": 630}},
           "parts": [{"name": "SIDE", "kind": "fabricated", "material_guess": "MILD STEEL",
                      "assumed_blank_mm": {"length": 830, "width": 620, "thickness": 1.5},
                      "quantity": 2, "operations": ["laser_cutting", "welding"]},
                     {"name": "POST", "kind": "fabricated", "material_guess": "MILD STEEL",
                      "assumed_blank_mm": {"length": 880, "width": 25, "thickness": 1.5},
                      "quantity": 4, "operations": ["saw", "welding"]}]}
    recs = cs.parts_from_concept(ans, "J")
    unit = cs.unit_assembly_part(recs, ans, "J")
    env = unit["product_envelope_mm"]
    assert (env["length"], env["width"], env["height"]) == (630.0, 480.0, 1035.0)
    ans["sheet_facts"] = {"body_mm": {"height": 1030, "width": 470, "depth": 620}}
    env = cs.unit_assembly_part(recs, ans, "J")["product_envelope_mm"]
    assert env["height"] == 1030.0 and "drawing" in env["source"], "the drawn body comes first"
