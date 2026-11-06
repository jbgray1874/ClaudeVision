"""0355255's tape line is the whole gap between our sheet and the estimator's.

    AI      £19.50 a unit at 10 off, £18.94 at 250, £18.84 at 1000
    Manual  £7.63              £4.65            £4.55

TAPE113C is supplied on a 10 METRE ROLL at £4.50. The drawing asks for three strips across
the base — about 600 mm, six hundredths of a roll, twenty-eight pence. The line was costed
3 x the ROLL price: £13.63. That single line is £13.35 of an £11.87 difference, and because a
per-each charge does not amortise it is also why our column barely moves between 10 off and
1000 off while the estimator's falls by a third.

THE GUARD FOR THIS ALREADY EXISTED AND COULD NOT FIRE, TWICE OVER. Powder, paint, adhesive and
sealant are withheld when their quantity is unknown, because a consumable sold by weight with
a defaulted quantity of 1 means one kilogramme — that is how a powder line reached £8.03 on a
£6.74 job. TAPE was not in the list. And the list only applies when the quantity is UNKNOWN,
where here it is perfectly well known: it is 3, and 3 is a count of PIECES CUT FROM the pack,
which is the one number that must never multiply a pack price.

So roll goods are withheld whether or not a count was read, and the line says the arithmetic
rather than asking for a calculation — the estimator already does this sum in his head; what
he cannot do is see that the sheet did a different one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator                                                        # noqa: E402


@pytest.fixture()
def udef(monkeypatch):
    """A catalogue that answers for any code, at the tape's own rate."""
    monkeypatch.setattr(estimator, "_lookup_udef_exact_code",
                        lambda code: {"description": f"{code} DESC",
                                      "unit_price_gbp": 4.37, "supplier": "Antalis"})


def _find(parts, code):
    return next((p for p in parts if str(p.get("part_number")) == code), None)


def _flags(part):
    return " ".join(str(f) for f in (part or {}).get("review_flags") or [])


# ── the tape line ────────────────────────────────────────────────────────────────────────

def test_vinyl_is_not_charged_four_times_the_roll(udef):
    """VINYL is a recognised SDI code AND is sold off a roll — the class this reader can
    actually reach, and 11650's REEDED VINYL is the open case in the same family."""
    rows = [{"part_number": "VINYL76", "description": "REEDED VINYL, BASE", "quantity": 4}]
    found = estimator._recognise_sdi_coded_bought_in("VINYL76", set(), rows)
    part = _find(found, "VINYL76")
    assert part is not None
    assert part.get("unit_cost_gbp") is None
    assert part.get("extended_total_cost_gbp") is None
    assert part.get("_price_explicitly_withheld") is True


def test_the_line_shows_the_sum_it_refused_to_do(udef):
    rows = [{"part_number": "VINYL76", "description": "REEDED VINYL", "quantity": 4}]
    part = _find(estimator._recognise_sdi_coded_bought_in("VINYL76", set(), rows), "VINYL76")
    f = _flags(part)
    assert "4 x £4.37" in f and "£17.48" in f
    assert "piece count must never multiply a pack price" in f
    assert "length used ÷ roll length" in f


def test_it_names_the_job_that_found_it(udef):
    rows = [{"part_number": "VINYL76", "description": "VINYL", "quantity": 4}]
    part = _find(estimator._recognise_sdi_coded_bought_in("VINYL76", set(), rows), "VINYL76")
    assert "600 mm of a 10 m roll" in _flags(part)


def test_the_catalogue_rate_is_kept_so_it_can_be_priced_later(udef):
    """We withheld because the UNIT was wrong, not because the rate is unknown."""
    rows = [{"part_number": "VINYL76", "description": "VINYL", "quantity": 4}]
    part = _find(estimator._recognise_sdi_coded_bought_in("VINYL76", set(), rows), "VINYL76")
    assert part.get("_catalogue_rate_gbp") == 4.37


def test_the_row_is_still_on_the_sheet(udef):
    """Withheld is not dropped. A line nobody can see is worse than one priced wrongly."""
    rows = [{"part_number": "VINYL76", "description": "VINYL", "quantity": 4}]
    found = estimator._recognise_sdi_coded_bought_in("VINYL76", set(), rows)
    assert _find(found, "VINYL76") is not None


# ── what this reader cannot reach, said out loud ─────────────────────────────────────────

def test_tape_does_not_travel_this_reader_at_all(udef):
    """AND THIS IS WHY THE FIX IS NOT FINISHED. _SDI_BOUGHT_IN_CODE_RE matches FIXING,
    VINYL, PRINT, SUBPLAS and POWDER. TAPE113C is none of them, so 0355255's tape line is
    minted somewhere else and a guard here can never see it. Pinned so the next person does
    not spend an evening fixing a call site the line does not travel."""
    rows = [{"part_number": "TAPE113C", "description": "DOUBLE SIDED TAPE", "quantity": 3}]
    assert estimator._recognise_sdi_coded_bought_in("TAPE113C", set(), rows) == []
    assert "TAPE" not in estimator._SDI_BOUGHT_IN_CODE_RE.pattern


def test_a_fixing_with_a_known_quantity_is_still_priced(udef):
    """THE RULE'S EDGE. A screw IS sold by the each, so a count of four is four of them —
    withholding that would be the same mistake in the other direction."""
    rows = [{"part_number": "FIXING125", "description": "M8 GLIDE", "quantity": 4}]
    part = _find(estimator._recognise_sdi_coded_bought_in("FIXING125", set(), rows), "FIXING125")
    assert part.get("unit_cost_gbp") == 4.37
    assert part.get("extended_total_cost_gbp") == round(4.37 * 4, 2)
    assert not part.get("_price_explicitly_withheld")


def test_powder_with_an_unknown_quantity_reads_as_it_always_did(udef):
    rows = []                                   # no structured qty -> unknown
    part = _find(estimator._recognise_sdi_coded_bought_in("POWDER9005", set(), rows),
                 "POWDER9005")
    assert part.get("_price_explicitly_withheld") is True
    assert "CONSUMABLE" in _flags(part) and "sold by weight/volume" in _flags(part)
