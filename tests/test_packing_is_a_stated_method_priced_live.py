"""£0.00 for packing on every estimate, while the method sat in Howard's email.

    "put it into config and start to build it in. if we're working it out and it's
     scaleable and using more sensible calculations and numbers they will be accepted.
     Better than 0 or crazy numbers."                       — James Gray, 15 Sep 2026

    "Individually Bagged (PACK13 12 x 18 x 100G) Then Bulk Packed in Large Stock Boxes
     (BOX481) 1 Box Suits 10 or 50 Components, 3 Boxes to Suit 250 Components 9 Boxes
     Suit 1000 Components."               — Howard Thurley, 0355255 packing note, 9 Sep

THE TAPE SPLIT, APPLIED TO PACKING. How an order packs is a stated fact and lives in
config with Howard's name on (PACKING_METHOD); what a bag and a box COST is money and is
asked of SDI's own priced sources at run time. Nothing typed, nothing stale invisibly.

ALL OR NOTHING. A half-priced method — bag found, box missing — would put a number on the
sheet that is confidently short, and nothing about it says "short". The zero stays until
every consumable prices, and the line names the one code that would not, so the fix is a
catalogue row and not a diagnosis.

AND THE STEPS ARE STEPS. 1 box for 10 or 50, 3 for 250, 9 for 1000 — you cannot buy 1.4
boxes, and beyond 1000 nothing Howard said tells us how it packs, so beyond 1000 nothing
is invented (the board-price rule, applied to cartons).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import commercial_lines as CL                                        # noqa: E402
import config                                                        # noqa: E402


def _prices(table):
    """Stand in for SDI's priced sources: the test states what UDEF answers."""
    def _px(code):
        v = table.get(code)
        return {"gbp": v, "source": "udef_sqlserver"} if v else None
    return _px


def _parts():
    return [{"part_number": "10975-02-A01", "description": "L-STAND", "quantity": 1,
             "blank_length_mm": 760.25, "blank_width_mm": 210.0,
             "normalized_thickness_mm": 2.0, "normalized_material": "ACRYLIC"}]


def test_the_steps_are_used_exactly_as_stated():
    steps = {10: 1, 50: 1, 250: 3, 1000: 9}
    assert CL._boxes_for(steps, 10) == 1
    assert CL._boxes_for(steps, 50) == 1
    assert CL._boxes_for(steps, 250) == 3
    assert CL._boxes_for(steps, 1000) == 9
    assert CL._boxes_for(steps, 3) == 1, "an order below the first step still needs a box"
    assert CL._boxes_for(steps, 100) == 3, "between steps, the next stated point covers it"


def test_beyond_the_last_stated_point_nothing_is_invented():
    assert CL._boxes_for({10: 1, 50: 1, 250: 3, 1000: 9}, 2000) is None


def test_a_fully_priced_method_puts_real_money_on_the_line(monkeypatch):
    monkeypatch.setattr(CL, "_consumable_price",
                        _prices({"PACK13": 0.06, "BOX481": 1.89}))
    line = CL.packaging_line(_parts(), 50)
    # 50 bags at 0.06 + 1 box at 1.89
    assert line["order_gbp"] == 4.89
    assert line["unit_gbp"] == round(4.89 / 50, 2)
    assert line["estimator_input_required"] is False
    assert line["price_source"]["source_class"] == "packing_method"
    assert line["price_source"]["indicative"] is True, \
        "priced and honest about being a method, not a quote"
    assert "PACK13" in line["packing_working"] and "BOX481" in line["packing_working"]
    assert "0355255" in line["method_source"] and "Howard Thurley" in line["method_source"]


def test_the_breaks_carry_the_step_not_a_slope(monkeypatch):
    """At £1.89 a box Howard's own sheet reads 0.189 / 0.0378 / 0.02268 / 0.01701 a unit
    across the four breaks — the one line on his estimate that moves. Dividing one
    order's cost by other quantities would smear that step into a slope."""
    monkeypatch.setattr(CL, "_consumable_price",
                        _prices({"PACK13": 0.06, "BOX481": 1.89}))
    line = CL.packaging_line(_parts(), 50)
    at = line["order_gbp_at_breaks"]
    assert at[10] == round(10 * 0.06 + 1 * 1.89, 2)
    assert at[250] == round(250 * 0.06 + 3 * 1.89, 2)
    assert at[1000] == round(1000 * 0.06 + 9 * 1.89, 2)
    # and the break table prices from those exact order costs
    from material_price_break import _price_at
    rec = {"order_gbp": line["order_gbp"], "order_gbp_at": at}
    assert _price_at(rec, 250) == round(at[250] / 250, 5)


def test_one_missing_consumable_keeps_the_honest_zero_and_names_itself(monkeypatch):
    monkeypatch.setattr(CL, "_consumable_price", _prices({"PACK13": 0.06}))  # no BOX481
    line = CL.packaging_line(_parts(), 50)
    assert line.get("order_gbp") is None, "a half-priced method is confidently short"
    assert line["estimator_input_required"] is True
    assert "BOX481" in line["note"], "the fix is one catalogue row, not a diagnosis"


def test_an_order_beyond_the_stated_steps_is_not_priced_by_extrapolation(monkeypatch):
    monkeypatch.setattr(CL, "_consumable_price",
                        _prices({"PACK13": 0.06, "BOX481": 1.89}))
    line = CL.packaging_line(_parts(), 2000)
    assert line.get("order_gbp") is None
    assert "beyond the last stated point" in line["note"]


def test_an_estimators_house_rate_still_beats_the_method(monkeypatch):
    """The explicit figure a person typed outranks the derived one, always."""
    monkeypatch.setattr(CL, "_consumable_price",
                        _prices({"PACK13": 0.06, "BOX481": 1.89}))
    monkeypatch.setattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER", {"PACKAGING": 12.0},
                        raising=False)
    line = CL.packaging_line(_parts(), 50)
    assert line["order_gbp"] == 12.0
    assert line["price_source"]["source_class"] == "config_house_rate"


def test_the_method_carries_its_own_provenance_in_config():
    m = config.PACKING_METHOD
    assert m["stated_by"].startswith("Howard Thurley")
    assert m["source_job"] == "0355255"
    codes = [c["code"] for c in m["consumables"]]
    assert codes == ["PACK13", "BOX481"]
    assert not any("gbp" in str(k).lower() or "price" in str(k).lower()
                   for c in m["consumables"] for k in c), \
        "the method holds NO money — prices come from the system at run time"


def test_delivery_is_untouched_by_the_packing_method(monkeypatch):
    monkeypatch.setattr(CL, "_consumable_price",
                        _prices({"PACK13": 0.06, "BOX481": 1.89}))
    line = CL.delivery_line(_parts(), 50)
    assert line.get("order_gbp") is None, \
        "no stated method exists for haulage yet — the honest zero stands there"
