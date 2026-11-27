"""Labour the block had no room for is not free (D-340).

12173, 29 Sep 2026: thirty false Robomac rows filled the Estimate's Labour block. The emit
loop stopped at the last row with a `break` and one line in the flags, so Wet Spray (required
on the MDF base and plate) and Assemble/pack never reached the sheet — and the unit cost, the
PROVISIONAL banner and the report all read as if the job were complete without them.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf  # noqa: E402

_DROPPED = {"labour_not_on_sheet": [
    {"operation": "Wet Spray", "parts": ["12173-03-01J", "12173-03-02J"], "batch_hours": 0.1},
    {"operation": "Assemble/pack (Metal)", "parts": ["12173-02-GA"], "batch_hours": 0.2}]}


def test_each_dropped_operation_is_a_blocking_item_by_name():
    o = cf.outstanding_summary(_DROPPED)
    assert o["labour_not_on_sheet"] == 2 and o["blocking"] >= 2
    assert "2 operations not on the sheet (Labour block full)" in o["phrase"]


def test_a_book_missing_timed_work_is_provisional():
    rel = cf.costed_job(_DROPPED)["release"]
    assert rel["status"] == "provisional"
    assert any("Labour block was full" in r for r in rel["reasons"])


def test_the_writer_records_rather_than_breaks():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    i = src.index('if row > lb["last_row"]:')
    block = src[i:i + 1200]
    assert "labour_not_on_sheet" in block and "continue" in block
    assert "break\n" not in block.split("wb_op = g[")[0]
