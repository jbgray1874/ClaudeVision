"""A rolled part is charged by the Roll row, and an unknown is never "0 min" (D-603).

THE HPP 15:47 BOOK SAID TWO THINGS ABOUT ONE ROW. Estimate row 166, "Roll", charged 45 min and
£23.74 on the halo skin and the guard rail ring. The report said, of the same work, "R1.op.rolling
HALO RING SKIN: rolling (the read names it and no calculated row charges it)", and listed
"Engine allowance not confirmed for this job: roll, 0 min a unit".

Two vocabulary defects, both generic:

  * the read says ROLLING and the sheet's row is ROLL, and the read ledger had no entry joining
    them, so no sheet anywhere could ever satisfy a rolled part;

  * the allowance check takes its minutes from the part's own run times, and where none is
    recorded it summed nothing to "0 min" beside a row that charges money.

Neither changes a charge. They change what the book says about the charge, which is what an
estimator reads before deciding whether to add one.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("SDI_OFFLINE", "1")

import accepted_construction  # noqa: E402
import concept_scan  # noqa: E402
import config  # noqa: E402
import invariants  # noqa: E402
import read_charge_contract as rcc  # noqa: E402
from test_what_the_read_returned_is_charged_covered_excluded_or_held import (  # noqa: E402
    B, U, _answer, _book, _lab)


@pytest.fixture(autouse=True)
def _breaks(monkeypatch):
    monkeypatch.setenv("SDI_QUANTITY_BREAKS", "1000")


def _state(result, item_id):
    return next(e for e in result["items"] if e["id"] == item_id)["state"]


def _with_row(s, row, ops, pn, hours, value, title, qty=1):
    group, line = _lab(row, ops, pn, hours, value, title, qty)
    s["workbook_labour"]["rows"].append(group)
    s["final_estimate"]["labour_rows"].append(line)
    return s


# ── the vocabulary contract ──────────────────────────────────────────────────────────────────

def test_every_operation_the_read_can_return_has_a_sheet_row_that_can_charge_it():
    """The read's words and the costing's words are kept in two places. A charged row carries
    the engine operations it prices, and every one the engine can charge has a rate. Any read
    operation whose family names no rated operation can never be shown charged, on any job."""
    read_ops = set(concept_scan.SIGHTABLE_OPERATIONS) | set(accepted_construction.OPERATIONS)
    sheet_ops = set((getattr(config, "HOURLY_RATES_GBP", {}) or {}).keys())
    # Plating is a subcontract line, never a labour row (READ_OPERATION_CHARGED_BY says so).
    orphans = sorted(op for op in read_ops - {"plating"}
                     if not set(rcc._families(op)) & sheet_ops)
    assert orphans == [], f"read operations no sheet row can charge: {orphans}"


def test_rolling_is_charged_by_the_roll_row():
    assert "roll" in rcc._families("rolling")


# ── the read ledger on a calculated book ───────────────────────────────────────────────────

def _rolled_bracket():
    answer = _answer()
    answer["parts"][1]["operations"] = ["laser_cutting", "rolling", "deburring"]
    return answer


def test_a_rolled_part_with_a_roll_row_is_charged():
    s = _with_row(_book(answer=_rolled_bracket()), 161, ["roll"], B, .77, 23.74, "Roll", 2)
    assert _state(rcc.audit(s), "R2.op.rolling") == rcc.CHARGED


def test_a_rolled_part_with_no_roll_row_is_still_unresolved():
    """The fix joins two words; it does not invent a charge."""
    assert _state(rcc.audit(_book(answer=_rolled_bracket())), "R2.op.rolling") == rcc.UNRESOLVED


# ── an unknown is not zero ───────────────────────────────────────────────────────────────

def test_an_allowance_with_no_recorded_minutes_names_its_row_and_charge():
    s = _with_row(_book(), 162, ["roll"], U, .77, 23.74, "Roll")
    s["read_charge_result"] = rcc.audit(s)
    viol = [v for v in invariants.check_what_the_read_returned_is_accounted_for(s)
            if v["code"] == "engine_allowance_unconfirmed" and v["detail"]["operation"] == "roll"]
    assert viol, "an unexplained Roll row is an engine allowance, listed apart"
    msg = viol[0]["message"]
    assert "0 min" not in msg
    assert "roll, run minutes not recorded on the part on" in msg
    assert "the sheet's Roll row (Estimate!M162) charges £23.74" in msg


def test_an_allowance_with_recorded_minutes_still_says_them():
    s = _book()
    s["read_charge_result"] = rcc.audit(s)
    brush = next(v for v in invariants.check_what_the_read_returned_is_accounted_for(s)
                 if v["code"] == "engine_allowance_unconfirmed"
                 and v["detail"]["operation"] == "brush_before_plate")
    assert "40 min a unit" in brush["message"]
