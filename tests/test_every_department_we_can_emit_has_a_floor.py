"""A department with no throughput is a #DIV/0! waiting for a pack to find it.

WHAT HAPPENED, AND IT WAS MINE. Moving acrylic routing off the joinery router onto CNC sent
the operation to a department `_THROUGHPUT_DEFAULTS` had never heard of. The sheet writes
`Total Hours` as `60/throughput`, so an empty throughput cell is a division by nothing; one
such row poisons `=SUM(M96:M167)`, which poisons the unit cost, and the covering email came
back "not readable from the sheet" and "Labour is 0 sheet rows" on a pack whose quantities
were finally correct.

The engine had already said so — "labour op '…' has no batch_hours and no default throughput
— WB hours/cost will be #DIV/0! for this row" — and the sheet shipped anyway. The note above
that table warns about the same thing in almost the same words, about joinery.

THE RULE THIS PINS: any department the operation maps can produce must have a floor. Adding a
department without adding its throughput is the mistake, and it is invisible until a pack
happens to use it.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import wb_populate                                                      # noqa: E402


def _throughput_defaults() -> dict:
    """Read the table out of the function that owns it.

    IT IS A DATA AUDIT, NOT AN ASSERTION ABOUT SPELLING. The table is a literal inside the
    populate routine, so there is no import to reach it by; what is checked is its CONTENT
    against the maps, and the test fails loudly if the table can no longer be located rather
    than passing vacuously."""
    src = inspect.getsource(wb_populate)
    m = re.search(r"_THROUGHPUT_DEFAULTS = \{(.*?)\n    \}", src, re.S)
    assert m, "the throughput table could not be found — this guard has gone blind"
    out = {k: float(v) for k, v in re.findall(r'"([^"]+)":\s*([\d.]+)', m.group(1))}
    assert len(out) > 15, f"only {len(out)} departments parsed — the guard has gone blind"
    return out


# Departments whose rate is written as a live formula instead of a number, so the cell is
# never empty and the table is not where their floor lives.
_FORMULA_RATED = {"Laser (Metal)"}


def test_every_department_the_maps_can_emit_has_a_throughput():
    """The maps are what turn an engine operation into a rate-card row. Anything they can
    produce can reach the sheet, so anything they can produce needs a floor."""
    defaults = _throughput_defaults()
    emitted = set()
    for _map in (wb_populate.OP_NAME_MAP, wb_populate.OP_NAME_MAP_ACRYLIC,
                 wb_populate.OP_NAME_MAP_JOINERY, wb_populate._TUBE_OP_REMAP):
        emitted |= {v for v in _map.values() if v}
    missing = sorted(d for d in emitted if d not in defaults and d not in _FORMULA_RATED)
    assert not missing, (
        "these departments can be written to a labour row and have no throughput floor, so "
        f"Total Hours will be 60/blank = #DIV/0! and the labour total with it: {missing}")


def test_the_acrylic_router_specifically_has_one():
    """The regression that took a whole sheet's money out."""
    assert "CNC" in _throughput_defaults()


def test_both_routers_are_covered_and_neither_borrows_silently():
    """Acrylic and board are different machines. They may share a figure while nothing
    measured separates them, but both must be present in their own right."""
    d = _throughput_defaults()
    assert "CNC" in d and "CNC Joinery" in d


def test_the_table_covers_the_departments_this_rate_card_can_charge():
    """A softer check over the rate card itself, reported rather than enforced: a department
    that can be charged and has no floor is a latent version of the same defect, and naming
    them is how the next one gets closed before a pack finds it."""
    from sheet_steel_costing import RATE_CARD
    d = _throughput_defaults()
    uncovered = sorted(t for t in RATE_CARD if t not in d and t not in _FORMULA_RATED)
    # Known and accepted today: none of these is reachable from the operation maps above,
    # which is what the enforced test covers. If one becomes reachable, that test fails first.
    assert set(uncovered) <= {"Edge Banding", "Machines Joinery", "Oven"}, (
        f"a rate-card department lost its throughput floor: {uncovered}")
