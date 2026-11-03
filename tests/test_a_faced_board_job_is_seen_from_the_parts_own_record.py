"""A faced-board job is seen from the part's own record too (D-664).

12203-66-GA, 3 Nov 2026 19:48: a tray of three 13.8 mm laminated MDF panels, bought faced. Every
CNC row was labelled "13.8mm MFMDF", read from the costed record OR the part's own record. The
switch that puts the joinery shop's stated rates on a faced-board job read the costed record
alone; the market rescue had replaced the panels' costed material record without the faced
family. So Bench Work ran at 10/hr and Packing at 75/hr against the stated 2/hr and 20/hr for
faced board, and nothing on the sheet said the scope had been missed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import wb_populate as W  # noqa: E402


def _rescued(pn):
    """The costed record after the market rescue: a per-piece figure, no faced family."""
    return {"part_number": pn, "normalized_material": "MDF",
            "material_estimate": {"material": "MDF", "sheet_price_gbp": 4.5,
                                  "cost_method": "last_resort_market_indication"}}


def _summary(*own):
    return {"manufacturing_writeup": {"parts": list(own)}}


def _own(pn, family="MFMDF"):
    return {"part_number": pn, "normalized_material": "MDF",
            "material_estimate": {"costing_material_family": family,
                                  "cost_method": "faced_board_unpriced"}}


def test_the_19_48_shape_reads_as_faced_board_from_the_parts_own_record():
    lines = [_rescued("12203-66-01J"), _rescued("12203-66-03J")]
    assert W.is_faced_board_job(_summary(_own("12203-66-01J"), _own("12203-66-03J")), lines)


def test_without_the_parts_own_record_the_switch_missed_it():
    """What the 19:48 sheet did: the costed records alone say plain MDF."""
    lines = [_rescued("12203-66-01J"), _rescued("12203-66-03J")]
    assert not W.is_faced_board_job(_summary(), lines)


def test_a_plain_mdf_job_stays_outside_the_joinery_pilot():
    lines = [_rescued("X-01J")]
    assert not W.is_faced_board_job(_summary(_own("X-01J", family="MDF")), lines)


def test_a_costed_record_that_says_faced_board_is_still_enough():
    lines = [{"part_number": "Y-01J", "material_estimate": {"costing_material_family": "MFC"}}]
    assert W.is_faced_board_job({}, lines)


def test_the_populate_step_asks_this_one_question():
    import inspect
    src = inspect.getsource(W.populate_workbook)
    assert "is_faced_board_job(summary," in src
