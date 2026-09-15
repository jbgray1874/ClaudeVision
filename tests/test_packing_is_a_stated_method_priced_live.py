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
    # BETWEEN STATED POINTS IS AN INFERENCE AND SAYS SO. Howard supplied 10/50/250/1000
    # and nothing else; 100 taking the 250 step's three boxes is our reading of his rule.
    # Priced — a labelled inference beats a zero — and labelled, pending his answer on
    # job-fixed counts versus a capacity rule.
    assert CL._boxes_for_with_basis(steps, 100) == (3, True)
    assert CL._boxes_for_with_basis(steps, 250) == (3, False)
    assert CL._boxes_for_with_basis(steps, 3) == (1, True)


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


# ── the catalogue sells packs and the method counts eaches ───────────────────────────────
#
# James ran the UDEF query, 15 Sep 2026:
#
#   BOX481   H266266 - 610 x 455 x 455mm (Large stock box) ...   COMPLETE PACKAGING   1.89
#   PACK13   POLY BAG 18 x 24 x 100G (PACK OF 1000)   The Packaging Company   29.68
#
# £29.68 is a THOUSAND bags. Read per-bag, a 50-off order carries £1,484 of poly bags —
# the crazy number, wearing a real supplier's name.

def _udef(code):
    rows = {"PACK13": {"gbp": 29.68, "source": "udef_sqlserver",
                       "description": "POLY BAG 18 x 24 x 100G (PACK OF 1000)"},
            "BOX481": {"gbp": 1.89, "source": "udef_sqlserver",
                       "description": "H266266 - 610 x 455 x 455mm (Large stock box)"}}
    return rows.get(code)


def test_a_pack_of_1000_is_divided_to_the_price_of_one(monkeypatch):
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    px = CL._consumable_price("PACK13")
    assert px["gbp"] == round(29.68 / 1000, 5)
    assert px["pack_of"] == 1000 and px["pack_gbp"] == 29.68


def test_a_dimension_is_never_read_as_a_pack_size(monkeypatch):
    """"18 x 24 x 100G" contains numbers and none of them is a quantity. Only the
    catalogue's own "PACK OF N" wording converts."""
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    px = CL._consumable_price("BOX481")
    assert px["gbp"] == 1.89
    assert "pack_of" not in px


def test_the_real_catalogue_rows_price_howards_break_line(monkeypatch):
    """End to end on the actual UDEF rows: the box step at £1.89 reproduces Howard's own
    sheet — 0.189 / 0.0378 / 0.02268 / 0.01701 a unit across the four breaks — plus a
    bag at just under 3p each."""
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    line = CL.packaging_line(_parts(), 50)
    _bag = round(29.68 / 1000, 5)
    assert line["order_gbp"] == round(50 * _bag + 1 * 1.89, 2)     # £3.37, not £1,485.89
    at = line["order_gbp_at_breaks"]
    for q, boxes in ((10, 1), (50, 1), (250, 3), (1000, 9)):
        assert at[q] == round(q * _bag + boxes * 1.89, 2)
        # the box component per unit is exactly Howard's figure at every break
        assert round((boxes * 1.89) / q, 5) == round({10: .189, 50: .0378, 250: .02268,
                                                      1000: .01701}[q], 5)
    assert "pack of 1000" in line["packing_working"]


def test_an_in_between_quantity_is_priced_and_labelled_inferred(monkeypatch):
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    line = CL.packaging_line(_parts(), 100)
    assert line["order_gbp"] == round(100 * round(29.68 / 1000, 5) + 3 * 1.89, 2)
    assert line.get("inferred_step") is True
    assert "INFERRED" in line["packing_working"]
    line50 = CL.packaging_line(_parts(), 50)
    assert not line50.get("inferred_step"), "a stated point carries no inference label"


# ── the method knows which jobs it was stated for ────────────────────────────────────────
#
# "Every PACKAGING line invokes _method_price() without checking product type, dimensions,
#  material or source job... Add an applicability predicate and a negative test proving
#  that a steel, joinery or large display job does not inherit PACK13/BOX481."
#                                                        — James Gray review, 15 Sep 2026

def _steel_parts():
    return [{"part_number": "7332-01-101", "description": "BACK PANEL", "quantity": 1,
             "blank_length_mm": 400.0, "blank_width_mm": 300.0,
             "normalized_thickness_mm": 2.0, "normalized_material": "MILD STEEL"}]


def _joinery_parts():
    return [{"part_number": "12422-24-01J", "description": "PANEL", "quantity": 1,
             "blank_length_mm": 1200.0, "blank_width_mm": 600.0,
             "normalized_thickness_mm": 18.0, "normalized_material": "MFC"}]


def _large_acrylic_parts():
    # all-acrylic and ~19 kg a unit: right family, plainly not a bagged table-top item
    return [{"part_number": "BIG-01", "description": "COUNTER FRONT", "quantity": 2,
             "blank_length_mm": 2000.0, "blank_width_mm": 2000.0,
             "normalized_thickness_mm": 2.0, "normalized_material": "ACRYLIC"}]


def test_a_steel_job_does_not_inherit_howards_bags(monkeypatch):
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    line = CL.packaging_line(_steel_parts(), 50)
    assert line.get("order_gbp") is None
    assert "MILD STEEL" in line["note"] and "not applied" in line["note"]


def test_a_joinery_job_does_not_inherit_them_either(monkeypatch):
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    line = CL.packaging_line(_joinery_parts(), 50)
    assert line.get("order_gbp") is None
    assert "not applied" in line["note"]


def test_a_large_display_fails_the_declared_small_goods_ceiling(monkeypatch):
    """Right material family, wrong scale. The ceiling is OURS — declared in config as an
    SDI Intelligence assumption, and the line says so when it bites."""
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    line = CL.packaging_line(_large_acrylic_parts(), 50)
    assert line.get("order_gbp") is None
    assert "ceiling" in line["note"] and "assumption" in line["note"]


def test_a_job_with_nothing_measured_is_not_priced_by_a_method_nobody_can_check(monkeypatch):
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    line = CL.packaging_line([{"part_number": "X", "description": "?"}], 50)
    assert line.get("order_gbp") is None


def test_the_source_job_itself_still_prices(monkeypatch):
    """The gate must not exclude the job the method was stated for — the 0355255 L-stand's
    BLANK is 760 mm, which is exactly why blank dimensions are not gated (a line-bent part
    packs far smaller than its flat blank)."""
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    line = CL.packaging_line(_parts(), 50)
    assert line["order_gbp"] == 3.37


def test_the_sheet_row_says_what_the_number_is_made_of(monkeypatch):
    """"when we explain the packaging and delivery on s/sheet we need to try to provide as
    much clarity as possible on the number" — James, 15 Sep. The ROW names the method and
    the codes; the full arithmetic is the review flag one click away; the Supplier column
    names both facts in one label."""
    import price_provenance as P
    assert P.source_system_label("stated_method_system_priced") == "Stated method + SDI Live"
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "estimator.py"),
               encoding="utf-8").read()
    assert "bagged (PACK13) + boxed (BOX481)" in src, "the row's own description"
    assert "PACKED BY THE STATED METHOD" in src, "and the working in the flag"


def test_the_method_stamp_is_visible_to_the_walker(monkeypatch):
    """The roll-goods lesson: a stamp without `applied` is invisible to iter_price_stamps,
    and the supplier column labels the line from whatever else is lying around."""
    import stated_prices, price_provenance
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    line = CL.packaging_line(_parts(), 50)
    stamps = list(price_provenance.iter_price_stamps({"commercial_line": line}))
    assert any(b.get("source_name") == "stated_method_system_priced" for _p, b in stamps)


# ── partial evidence cannot bypass the gate ──────────────────────────────────────────────
#
# "A job containing one measured acrylic part and another unmeasured non-plastic leaf could
#  still receive Howard's packing method. The gate should reject unassessed fabricated
#  leaves while continuing to ignore legitimate assembly parents." — James review, 15 Sep

def test_an_unmeasured_fabricated_leaf_blocks_the_method(monkeypatch):
    """One measured acrylic part used to carry the whole job through the gate on the
    strength of the half that happened to have a blank."""
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    parts = _parts() + [{"part_number": "10975-02-B01", "description": "BRACKET",
                         "normalized_material": "MILD STEEL", "quantity": 1,
                         "flat_pattern_detected": True}]        # fabricated, no blank dims
    line = CL.packaging_line(parts, 50)
    assert line.get("order_gbp") is None
    assert "10975-02-B01" in line["note"]


def test_an_unmeasured_fabricated_leaf_with_no_material_blocks_it_too(monkeypatch):
    """Unknown is not plastic. A leaf nobody measured and nobody materialed leaves the
    stated basis unproven, and unproven does not price."""
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    parts = _parts() + [{"part_number": "10975-02-C01", "description": "STIFFENER",
                         "quantity": 1, "flat_pattern_detected": True}]
    line = CL.packaging_line(parts, 50)
    assert line.get("order_gbp") is None
    assert "could not be assessed" in line["note"]


def test_an_unmeasured_bought_in_rides_along(monkeypatch):
    """The source job's own shape: the tape and the graphic have no blanks and never will —
    they are bought items that go in the same bag. A gate that rejected them would exclude
    0355255 itself, which is the false alarm that gets a gate switched off."""
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    parts = _parts() + [
        {"part_number": "10975", "description": "EPDM TAPE 25X1MM - TAPE 113C",
         "quantity": 3, "page_roles": ["bought_in"], "source": "bom_table"},
    ]
    # only count it as riding along if the policy actually calls it bought-in
    from bought_in_policy import is_bought_in
    assert is_bought_in(parts[-1]), "fixture must be a real bought-in by the one predicate"
    line = CL.packaging_line(parts, 50)
    assert line["order_gbp"] == 3.37


def test_an_assembly_parent_is_still_ignored(monkeypatch):
    import stated_prices
    monkeypatch.setattr(stated_prices, "system_price", lambda c, d=None: _udef(c))
    parts = _parts() + [{"part_number": "10975-02-GA", "description": "ASSEMBLY",
                         "is_assembly_parent": True, "quantity": 1}]
    line = CL.packaging_line(parts, 50)
    assert line["order_gbp"] == 3.37, "counted through its children, exactly as the weight is"
