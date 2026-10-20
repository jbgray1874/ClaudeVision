"""A short run is charged a fraction of a sheet, and a short run buys a whole one.

Both sheet paths cost a part as sheet_price / parts_per_sheet:

    steel        cost_per_part = ((GBP/tonne x kg_per_sheet) / 1000) / parts_per_sheet
    other sheet  cost_per_part = (sheet_price / parts_per_sheet) x (1 + scrap)

Over 180 off that is exactly right -- the sheets are used up and the arithmetic is the
invoice. Over ONE off it is not: a panel that nests 6-up is charged a sixth of a sheet and the
other five sixths are bought, paid for and standing in the rack.

THE WORKBOOK DOES THE SAME THING. This is not the engine disagreeing with the sheet and not a
defect against the template. It is a commercial assumption that is invisible at batch
quantities and dominant at short ones -- and the next jobs in are one and two off.

Which is why it is a WARNING that states the assumption, not a silent uplift. Whether the
offcut is chargeable is a real question with two real answers (it goes into the next job, or
it is a bespoke colour nobody will use again) and it belongs to the estimator.

THE FACT IS STAMPED BY THE CALCULATION THAT DIVIDED THE SHEET, not worked out by the checker.
A checker deriving it would need a list of the cost methods that divide a sheet, and a list of
spellings is what goes stale -- it is how one nesting rule came to be applied to every
material and how _is_board came to exist twice.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator  # noqa: E402
import invariants  # noqa: E402

CHECK = invariants.check_a_short_run_is_charged_for_the_sheet_it_uses


def _part(pn, material="PETG", thickness=2.0, fraction=1 / 6, quantity=1):
    return {"part_number": pn, "quantity": quantity,
            "material_estimate": {"material": material, "thickness_mm": thickness,
                                  "sheet_fraction_per_part": fraction}}


def _codes(findings):
    return [f["code"] for f in findings]


# ── the fact is recorded where the sheet was divided ─────────────────────────────────

def _material(material, length, width, thickness):
    return estimator.estimate_material({
        "part_number": "T-1", "normalized_material": material,
        "normalized_thickness_mm": thickness, "quantity": 1,
        "blank_length_mm": length, "blank_width_mm": width,
        "material_estimate": {}, "manufacturing_interpretation": {},
    })


def test_a_nested_plastic_part_records_how_much_of_a_sheet_it_is():
    me = _material("ACRYLIC", 1202.0, 689.0, 3.0)
    assert me["parts_per_sheet"] == 4
    assert me["sheet_fraction_per_part"] == pytest.approx(0.25)


def test_a_nested_steel_part_records_it_too():
    me = _material("MILD STEEL", 1250.0, 525.0, 2.0)
    assert me["cost_method"] == "workbook_sheet_steel_formula"
    assert me["sheet_fraction_per_part"] == pytest.approx(
        1.0 / me["stock_estimate"]["parts_per_sheet"])


def test_a_part_priced_by_mass_claims_no_sheet_fraction():
    """The mass path charges kg at a rate and never divides a sheet. Claiming a fraction for
    it would be an invented fact -- and the reason this is stamped by the calculation rather
    than inferred by a reader is that a reader cannot tell those two apart from the record."""
    me = _material("MILD STEEL", 1250.0, 525.0, 2.0)
    if me.get("cost_method") != "workbook_sheet_steel_formula":
        pytest.skip("this configuration does not reach the sheet-steel formula")
    mass = _material("INCONEL 625", 100.0, 100.0, 2.0)
    assert mass.get("cost_method") != "workbook_sheet_steel_formula"
    assert "sheet_fraction_per_part" not in mass


# ── what the check says ──────────────────────────────────────────────────────────────

def test_a_one_off_that_nests_six_up_is_flagged():
    found = CHECK({"quantity": 1, "part_estimates": [_part("10575-01-01")]})
    assert _codes(found) == ["short_run_pays_for_sheet_it_does_not_use"]
    assert found[0]["severity"] == invariants.WARNING
    assert found[0]["detail"]["sheets_bought"] == 1
    assert found[0]["detail"]["sheets_charged"] == pytest.approx(0.167, abs=0.001)


def test_a_batch_that_uses_its_sheets_up_is_not_flagged():
    """The whole point of the quantity. 180 panels at 6-up is 30 sheets exactly, and a warning
    here would fire on every real production job in the system."""
    assert CHECK({"quantity": 180, "part_estimates": [_part("10575-01-01")]}) == []


def test_parts_that_share_a_sheet_are_counted_together():
    """Six different parts of the same stock filling one sheet waste nothing. Flagging them
    one at a time would cry wolf on exactly the jobs where the nesting is efficient."""
    parts = [_part(f"P{i}") for i in range(6)]
    assert CHECK({"quantity": 1, "part_estimates": parts}) == []


def test_a_different_gauge_is_a_different_sheet():
    """2mm and 3mm PETG do not nest together. Pooling them would hide a whole sheet of waste
    behind another material's efficiency."""
    found = CHECK({"quantity": 1, "part_estimates": [
        _part("A", thickness=2.0, fraction=0.5),
        _part("B", thickness=3.0, fraction=0.5)]})
    assert len(found) == 2


def test_a_different_material_is_a_different_sheet():
    found = CHECK({"quantity": 1, "part_estimates": [
        _part("A", material="PETG", fraction=0.5),
        _part("B", material="ABS", fraction=0.5)]})
    assert len(found) == 2


def test_the_part_quantity_per_unit_is_counted():
    """Four of one panel per display, one display: four panels, not one. A check that read the
    order quantity and ignored the BOM quantity would under-count every multi-off part."""
    one = CHECK({"quantity": 1, "part_estimates": [_part("A", quantity=1)]})
    six = CHECK({"quantity": 1, "part_estimates": [_part("A", quantity=6)]})
    assert one and not six, "six of a 6-up part fill the sheet"


def test_a_small_offcut_is_not_worth_a_warning():
    """Below a quarter of a sheet the remnant is ordinary stock-keeping. Every job in the
    system would carry this flag, which is how a real warning gets ignored."""
    assert CHECK({"quantity": 1, "part_estimates": [_part("A", fraction=0.9)]}) == []
    assert CHECK({"quantity": 1, "part_estimates": [_part("A", fraction=0.7)]})


def test_a_job_with_no_stated_quantity_is_left_to_the_check_that_owns_that():
    """Without a quantity there is no way to know how many sheets are bought, and
    check_the_quantity_costed_is_the_quantity_ordered already reports a job that states none.
    Two checks shouting the same thing is noise."""
    assert CHECK({"part_estimates": [_part("A")]}) == []


def test_a_part_that_never_divided_a_sheet_is_not_counted():
    """A bought-in fitting or a mass-priced bar has no sheet fraction, and inventing one for it
    would put every hardware line into a materials warning.

    Asserted at quantity 1 as well as 4: a default fraction substituted for the missing one
    can land on a whole number of sheets and disappear, so a single quantity proves nothing.
    """
    screws = {"part_number": "BI-SCREW", "quantity": 4, "material_estimate": {}}
    bar = {"part_number": "BAR-01", "quantity": 1,
           "material_estimate": {"material": "MILD STEEL", "cost_method": "mass_times_price_per_kg"}}
    assert CHECK({"quantity": 1, "part_estimates": [screws, bar]}) == []
    assert CHECK({"quantity": 2, "part_estimates": [screws, bar]}) == []


def test_a_hardware_line_never_appears_in_a_sheet_warning():
    """Beside a real sheet part, a fitting with no fraction must not be swept into the group
    it happens to share a material name with — the flag names parts for someone to act on, and
    a screw in that list is a screw somebody goes looking for."""
    found = CHECK({"quantity": 1, "part_estimates": [
        _part("10575-01-01"),
        {"part_number": "BI-SCREW", "quantity": 4,
         "material_estimate": {"material": "PETG", "thickness_mm": 2.0}}]})
    assert len(found) == 1
    assert found[0]["detail"]["parts"] == ["10575-01-01"]


def test_the_finding_names_the_parts_so_it_can_be_acted_on():
    found = CHECK({"quantity": 1, "part_estimates": [_part("10575-01-01")]})
    assert "10575-01-01" in found[0]["message"]
    assert "1 off" in found[0]["message"]
    assert "goes to stock" in found[0]["message"], (
        "the estimator has to be told what the decision IS, not just that there is one")


def test_it_does_not_claim_the_engine_disagrees_with_the_workbook():
    """It does not. Saying so is what stops this being read as a bug and chased as one."""
    found = CHECK({"quantity": 1, "part_estimates": [_part("10575-01-01")]})
    assert "the workbook divides a sheet price by parts-per-sheet the same way" \
        in found[0]["message"].lower()


def test_the_check_is_registered():
    """A check that is not in CHECKS runs on no job. Built is not wired."""
    assert CHECK in invariants.CHECKS
