r"""
test_we_do_not_laser_something_we_buy.py

TWO GATES HELD AND THE ROUTE CAME IN THROUGH THE THIRD DOOR.

12552-01-01X is a 62012RS ball bearing, 12x32x10mm. On the 18:34 run:

  * the assembly-page guard would not let it take operations from the shared GA sheet
  * the borrow refusal would not give it 12552-01-01M's flat pattern — Blank L came out
    empty, which is what we had been chasing

and the workbook still billed:

    Laser (Metal) — 1.5mm MILD STEEL (12552-01-01X) | 8 | 269

The Canonical Route named the writer. Source `inference`, not `drawing_notes`:

    10 | laser_cutting | required | 12552-01-01X | part | 8 | inference |
         textual_operations on existing part record

That is the LLM inference pass — "2 part(s) had no material or size printed … added 2
route(s), all stamped 'inference'". It reads a drawing and sees a purchased component
sitting in the assembly it was bought for, and nothing in that picture says SDI cuts it.

apply_routes_to_parts already refuses a route a MEASUREMENT contradicts
(operations_ruled_out). This is the same argument from the part's identity rather than its
geometry, and it belongs beside it.

FABRICATION_OPS, NOT EVERY OPERATION. handling and assembly are deliberately absent from
that set — we do receive and fit bought-in parts, and that bench time is real work. Only
what a purchased component can never incur is refused.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from source_connectors.llm_full_job import apply_routes_to_parts  # noqa: E402


def _bearing() -> dict:
    """As the record stands when this pass runs: no bought_in role yet, only the number."""
    return {
        "part_number": "12552-01-01X",
        "description": "62012RS Ball Bearing 12x32x10mm",
        "page_roles": ["assembly"],
        "textual_operations": [],
    }


def _cross_member() -> dict:
    return {
        "part_number": "12552-01-01M",
        "description": "CROSS MEMBERS",
        "page_roles": ["detail"],
        "textual_operations": [],
    }


def _route(op: str, *part_numbers: str) -> dict:
    return {"operation": op, "part_numbers": list(part_numbers), "inferred": True}


def test_a_bought_in_is_not_given_a_laser():
    bearing, cross = _bearing(), _cross_member()
    apply_routes_to_parts([bearing, cross],
                          {"routes": [_route("laser_cutting", "12552-01-01X", "12552-01-01M")]})

    assert "laser_cutting" not in bearing["textual_operations"], (
        "The bearing took laser_cutting from the inference pass. It is bought from a "
        "catalogue; on the last run this was 269 seconds of laser on 8 bearings."
    )
    assert "laser_cutting" in cross["textual_operations"], (
        "The cross member lost its laser. The refusal must turn on what the part IS, not "
        "on the route line — both parts are named by the same route."
    )


def test_handling_still_reaches_a_bought_in():
    """We receive and fit purchased parts, and that bench time is real."""
    bearing = _bearing()
    apply_routes_to_parts([bearing], {"routes": [_route("handling", "12552-01-01X"),
                                                 _route("assembly", "12552-01-01X")]})
    assert "handling" in bearing["textual_operations"], (
        f"Handling was refused: {bearing['textual_operations']!r}. Stripping the bench time "
        f"from a bought-in undercharges the job — the point is to remove fabrication only."
    )


def test_the_refusal_is_on_the_record():
    """A declined route must be visible, or it looks like one that was never read."""
    bearing = _bearing()
    apply_routes_to_parts([bearing], {"routes": [_route("laser_cutting", "12552-01-01X")]})
    flags = " ".join(str(f) for f in (bearing.get("review_flags") or []))
    assert "12552-01-01X" in flags and "laser_cutting" in flags and "bought-in" in flags, (
        f"The flag must name the part, the operation and the reason: {flags!r}"
    )
    assert "part number or its page role is wrong" in flags, (
        "It must also say what to check if the classification itself is the error — "
        "otherwise a genuinely fabricated part silently loses its route."
    )


def test_every_fabrication_op_is_refused_not_just_the_laser():
    """The bug was found on a laser; the rule is about fabrication."""
    for op in ("laser_cutting", "folding", "punch", "welding", "powder_coating", "saw"):
        bearing = _bearing()
        apply_routes_to_parts([bearing], {"routes": [_route(op, "12552-01-01X")]})
        assert op not in bearing["textual_operations"], (
            f"'{op}' reached a purchased component. Fixing only the operation that happened "
            f"to be noticed leaves the next one to be found the same expensive way."
        )
