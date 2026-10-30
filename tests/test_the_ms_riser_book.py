"""12527-22-GA, TSE Footwear Hero Riser (M&S, 72 off), book of 30 Sep 2026 (D-370).

Two folded 1 mm panels spot-welded into a riser, powder coated RAL 9005, four bump-ons, and a
ticket the customer supplies. The bill and the route were right; two lines of money were not.

1. P.Coat charged £19.01 of a £36.19 unit for 0.17 m2. The weldment has no blank of its own
   and is welded, so the costing stage gave it the 3-minute WIRE floor; the sheet then read
   the assembly's own figure as a stated shop time (20/hr) and skipped the size band. A coat's
   time follows its area — the same fault, the other way round, charged the M&S steel unit
   about £1 for 9.36 m2.
2. 12527-22-03X "TICKET-SUPPLIED BY OTHERS" went out at £0.08 on a researched price. The line
   names its own supplier; its SDI-style code and model geometry read as "ours".
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import wb_populate as wb                                   # noqa: E402
from third_party_supply import own_supply_party, mark_third_party_supplied  # noqa: E402

EST_SRC = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
WB_SRC = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")

RULE = {"throughput_m2_per_hour": 180.0}


def _weldment(area):
    return {"part_number": "12527-22-101", "quantity": 1,
            "process_estimate": {"powder_coating_detail": {"coated_m2": area}}}


# ── powder follows area ───────────────────────────────────────────────────────────────

def test_a_small_coat_runs_fast():
    rate, working = wb.powder_area_throughput([_weldment(0.1663)], RULE)
    assert round(rate) == 1082
    assert "12527-22-101 0.166 m2" in working


def test_a_large_coat_runs_slow():
    rate, _ = wb.powder_area_throughput([_weldment(9.36)], RULE)
    assert 19 < rate < 20


def test_the_members_area_is_read_when_the_detail_is_absent():
    rate, _ = wb.powder_area_throughput(
        [{"part_number": "A", "_powder_members_coated_m2": 0.5}], RULE)
    assert round(rate) == 360


def test_several_parts_combine_as_the_true_rate_not_an_average():
    parts = [_weldment(1.0), {**_weldment(0.2), "part_number": "B", "quantity": 3}]
    rate, _ = wb.powder_area_throughput(parts, RULE)
    assert abs(rate - 180.0 * 4 / (1.0 + 0.6)) < 1e-9


def test_one_unmeasured_piece_leaves_the_band_in_charge():
    assert wb.powder_area_throughput([_weldment(0.2), {"part_number": "X"}], RULE) is None
    assert wb.powder_area_throughput([_weldment(0.2)], {}) is None


def test_the_row_takes_the_slower_of_line_and_area():
    block = WB_SRC.split("AND THE COAT'S TIME FOLLOWS ITS AREA")[1][:1400]
    assert "powder_area_throughput(_row_parts_ph)" in block
    assert "_by_area[0] < float(default_tp)" in block
    assert 'g["time_from_area"] = True' in block


def test_a_time_from_area_is_not_a_stated_time():
    assert wb._group_carries_a_stated_shop_time(
        {"assembly_own_time": True, "time_from_area": True, "parts": ["12527-22-101"]},
        {}) is False
    # the 7332-01 weld claim is untouched
    assert wb._group_carries_a_stated_shop_time(
        {"assembly_own_time": True, "parts": ["7332-01-101"]}, {}) is True


def test_a_sheet_weldment_does_not_take_the_wire_floor():
    assert '_coats_as_sheet = _has_flat_blank or bool(part.get("_powder_members_coated_m2"))' \
        in EST_SRC
    assert "_wire_pc_floor if (_is_wire_op_part and not _coats_as_sheet)" in EST_SRC


# ── a line that names its own supplier ────────────────────────────────────────────────

def test_the_ticket_names_its_supplier():
    assert own_supply_party("TICKET-SUPPLIED BY OTHERS") == "OTHERS"
    assert own_supply_party("GRAPHIC - FREE ISSUE BY CUSTOMER") == "CUSTOMER"
    assert own_supply_party("LCD SUPPLIED AND FITTED BY PIXEL (SEE NOTE)") == "PIXEL"


def test_sdi_and_ordinary_lines_are_not_third_party():
    assert own_supply_party("BRACKET SUPPLIED BY SDI") == ""
    assert own_supply_party("RISER") == ""
    assert own_supply_party("OVERSUPPLIED BY X") == ""


def test_the_line_is_marked_whatever_its_code_says():
    parts = [{"part_number": "12527-22-03X", "description": "TICKET-SUPPLIED BY OTHERS"},
             {"part_number": "12527-22-02M", "description": "RISER"}]
    marked = mark_third_party_supplied(parts, {"pages": []})
    assert [m["part_number"] for m in marked] == ["12527-22-03X"]
    assert parts[0]["supplied_by_third_party"] == "OTHERS"
    assert "customer_supplied_zero_cost" in parts[0]["risk_flags"]
    assert "supplied_by_third_party" not in parts[1]


def test_a_note_still_cannot_zero_a_part_we_make():
    parts = [{"part_number": "1-02M", "description": "DISPLAY BRACKET"}]
    pages = {"pages": [{"pdfplumber_text": "DISPLAY SUPPLIED BY PIXEL INSPIRATION UK."}]}
    assert mark_third_party_supplied(parts, pages) == []
