r"""The merchant laminates the board. The shop must not be paid to do it again.

From the 11908-21 book of 17 September 2026, 15:50 — Estimate row 99:

    Glue   laminating   GLUE   11908-21-01J, 11908-21-02J, 11908-21-03J
           9 off   40/hr   0.725 h   set-up 30 min   £18.43 a unit

£18.43 of glue labour a tray, on a job whose whole material bill reads £3.78. And the
engine's own promotion says why it should not be there: "the laminating on the route is IN
the sheet price, not a shop operation". That sentence was written as a review flag and
enforced nowhere, so a promoted board was billed for its facing twice — once inside
whatever the sheet costs, and again at the glue bench.

It is the kind of double that survives a reading, because both lines are individually
correct. The board really is laminated. The drawing really does say so. Only the
CONCLUSION is wrong: the drawing's word is evidence about the MATERIAL, not an instruction
to the shop.

SCOPED TO THE PROMOTION, AND TO NOTHING ELSE. A panel the shop genuinely lays up itself
carries no promotion, keeps its operation and keeps its glue time. The control at the
bottom holds that half.

AND THE EVIDENCE STAYS ON THE PART. The tube-bend gate strips `textual_operations` when it
cancels an op; this one must not, because the promotion reads that list to decide the board
is faced at all. Strip it and a second costing pass un-promotes the part and puts it back
on raw-core money — the cancellation would delete its own justification.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator  # noqa: E402

_TRAY = {"part_number": "11908-21-01J", "normalized_material": "MDF",
         "normalized_thickness_mm": 9.0, "blank_length_mm": 390.0,
         "blank_width_mm": 390.0, "quantity": 2,
         "textual_operations": ["laminating", "cnc_routing"],
         "operations": ["laminating", "cnc_routing"],
         "dxf_source_file": "11908-21-01J_9mm MDF+ LAM_REV[A].DXF"}


def _tray(**over):
    out = dict(_TRAY, **over)
    out["textual_operations"] = list(out["textual_operations"])
    out["operations"] = list(out["operations"])
    return out


def _timed(part):
    return estimator.estimate_process_times(part, quantity=1)


def _ops_charged(process):
    keys = set(process.get("run_times_min_per_unit") or {})
    keys |= set(process.get("setup_times_min") or {})
    return {str(k).lower() for k in keys}


# ── the double charge ────────────────────────────────────────────────────────────────

def test_a_promoted_board_is_not_charged_for_its_own_facing():
    part = _tray(_laminate_in_board=True)
    assert "laminating" not in _ops_charged(_timed(part))


def test_the_cancellation_travels_by_the_name_the_route_readers_read():
    """wb_populate and route_compiler rebuild the operation list from the part and honour
    `operations_ruled_out`. A ruling recorded anywhere else is a ruling that did nothing —
    the fault that put a cancelled tube bend back on three consecutive books."""
    part = _tray(_laminate_in_board=True)
    _timed(part)
    assert "laminating" in (part.get("operations_ruled_out") or {})
    assert "sheet price" in part["operations_ruled_out"]["laminating"]


def test_it_says_so_where_a_person_reads_it():
    part = _tray(_laminate_in_board=True)
    _timed(part)
    assert "laminating" in (part.get("removed_operations") or [])
    assert any("bills the same facing twice" in str(f)
               for f in part.get("review_flags", []))


def test_the_evidence_that_the_board_is_faced_is_not_deleted():
    """The cancellation must not delete its own justification. `_faced_board_promotion`
    reads `textual_operations` — strip it and a second costing pass un-promotes the part
    and puts it back on raw-core money."""
    part = _tray(_laminate_in_board=True)
    _timed(part)
    assert "laminating" in part["textual_operations"]
    family, why = estimator._faced_board_promotion(part, "MDF")
    assert family == "MFMDF", (family, why)


# ── the controls ─────────────────────────────────────────────────────────────────────

def test_a_panel_the_shop_really_laminates_is_not_touched():
    """No promotion, so no sheet price has paid for the facing: the glue bench does the
    work and whatever the route says stands, exactly as before. The gate does not fire and
    cancels nothing."""
    part = _tray()
    _timed(part)
    assert not part.get("operations_ruled_out")
    assert not part.get("removed_operations")
    assert "laminating" in part["operations"]


def test_the_rest_of_the_route_is_untouched():
    part = _tray(_laminate_in_board=True)
    assert "cnc_routing" in _ops_charged(_timed(part))
