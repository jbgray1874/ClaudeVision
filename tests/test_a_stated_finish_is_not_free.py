"""Powder is the only finish this engine can cost, and that is a gap, not a rule.

The two halves look correct separately, which is why it was invisible: the shared physical
rule correctly refuses to powder-coat a plastic, and the route correctly contains no powder
operation -- so nothing is flagged, and a stated finish is silently free.

11650-05 is the live case. Its PETG side panels state "1/2 INCH REEDED VINYL + UV OR CLEAR
VINYL". The engine read that, printed it as a manufacturing observation, and costed Laser,
Manual labour and Assemble/pack. There is no vinyl operation in the vocabulary, no rate for
one, and no line on the sheet. The vinyl is free.

THIS MATTERS MOST FOR BOARD AND PLASTIC, AND IT IS ABOUT TO MATTER MORE. Powder coating is
an oven process, metals only. Paint, vinyl, laminate, print and foil go onto wood, MDF,
acrylic and PETG every day -- SDI paints wood. Ruling powder out on a non-metal is right;
leaving nothing in its place is an under-charge that grows with every non-metal job.

THE CHECK DOES NOT INVENT A RATE. There is no measured rate for these finishes, and
guessing one would be worse than the gap. It says the work was named and not charged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import invariants                                                   # noqa: E402
from invariants import (WARNING,                                    # noqa: E402
                        check_a_stated_finish_is_costed as check)
from stock_form_rules import is_impossible_operation as impossible  # noqa: E402


def _job(finish, ops=("Laser (Acrylic)",), pn="11650-04-01A"):
    return {"manufacturing_writeup": {"parts": [
                {"part_number": pn, "normalized_finish": finish}]},
            "estimate_summary": {"workbook_route_rows": [
                {"operation": o} for o in ops]}}


# ── the live failure ────────────────────────────────────────────────────────────────
def test_a_vinyl_finish_with_no_finish_operation_is_flagged():
    out = check(_job("1/2 INCH REEDED VINYL + UV OR CLEAR VINYL"))
    assert len(out) == 1 and out[0]["severity"] == WARNING
    assert "11650-04-01A" in out[0]["message"]
    assert "supplied free" in out[0]["message"]


@pytest.mark.parametrize("finish", [
    "VINYL WRAP", "SPRAY PAINT RAL 9005", "2 PACK PAINT", "LACQUERED",
    "LAMINATED BOTH FACES", "OAK VENEER", "FOIL BLOCKED", "DIGITALLY PRINTED",
    "ANODISED CLEAR", "CHROME PLATED", "SATIN FILM",
])
def test_every_finish_process_the_engine_cannot_cost_is_flagged(finish):
    assert check(_job(finish)), f"{finish} is being supplied free and nothing says so"


# ── what must NOT be flagged ────────────────────────────────────────────────────────
def test_a_powder_job_that_costs_powder_is_silent():
    assert check(_job("POWDER COATED - FINE TEXTURE", ops=("P.Coat", "Laser (Metal)"))) == []


@pytest.mark.parametrize("finish", ["RAW", "SELF COLOUR", "NONE", "MILL FINISH",
                                    "AS ROLLED", "UNFINISHED"])
def test_a_finish_field_that_states_there_is_no_finish_is_silent(finish):
    """A warning on every bare-metal job is how estimators learn to scroll past all of them.

    This is carried by the PROCESS-WORD requirement alone. An explicit no-finish word list
    existed alongside it and a mutation proved it never fired -- none of those strings
    contains a process word, so it could only ever agree with the rule above it. It was
    removed; these cases now prove the remaining rule does the work."""
    assert check(_job(finish)) == []


def test_a_part_with_no_finish_field_is_silent():
    assert check(_job("")) == []
    assert check({"manufacturing_writeup": {"parts": [{"part_number": "A"}]},
                  "estimate_summary": {}}) == []


def test_an_acrylic_job_costing_diamond_polish_is_silent():
    """Diamond polish IS a finish this engine can cost, and acrylic's correct one."""
    assert check(_job("DIAMOND POLISHED EDGES", ops=("Diamond Polish",))) == []


def test_an_unreadable_summary_is_unevaluated_not_clean():
    out = check("not a job")
    assert len(out) == 1 and out[0]["severity"] == "unverified"


def test_the_check_is_registered():
    """Built is not wired."""
    assert check in invariants.CHECKS


# ── the rule stays finish-type aware ────────────────────────────────────────────────
# THE OVER-GENERALISATION THAT WOULD COST REAL MONEY. "Non-metal" rules out the POWDER OVEN
# and nothing else. SDI paints wood; vinyl goes on PETG; MDF is laminated and veneered.
# A future edit that widened the non-metal rule from powder to "finishing" would delete
# every one of those from every non-metal job at once, silently.
@pytest.mark.parametrize("material", ["MDF", "PLYWOOD", "OAK", "PETG", "ACRYLIC", "HIPS"])
@pytest.mark.parametrize("operation", ["paint", "spray_paint", "wet_paint", "lacquer",
                                       "vinyl", "vinyl_wrap", "laminate", "veneer",
                                       "print", "foil", "diamond_polish"])
def test_a_non_metal_may_still_take_every_finish_that_is_not_powder(material, operation):
    assert not impossible(operation, "sheet", material), (
        f"{operation} has been ruled out on {material} -- the non-metal rule has been "
        f"widened beyond the powder oven, and every painted wood job just lost its finish")


@pytest.mark.parametrize("material", ["MDF", "PLYWOOD", "OAK", "PETG", "ACRYLIC", "HIPS"])
def test_powder_specifically_is_still_ruled_out(material):
    """The other direction: widening must not be prevented by weakening."""
    assert impossible("powder_coating", "sheet", material)


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
