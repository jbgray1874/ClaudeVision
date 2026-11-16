r"""
test_a_bought_in_prefix_is_not_the_whole_identity.py

FIVE LINES, ONE IDENTITY.

normalize_part_code strips a trailing all-letter segment so description bleed does not become
part of a code: "11650-04-01A-WALL" is the part 11650-04-01A with the word WALL stuck to it,
and the rule that removes WALL is right.

It was written for codes that begin with a job number, and it was applied to every code. So
it also removed the only meaningful half of any code whose FIRST segment is letters:

    BI-HEADBOLT      -> BI
    BI-DOMERIVET     -> BI
    BI-HEXNUT        -> BI
    BI-SCREW         -> BI
    BI-LEDDOWNLIGHTS -> BI
    SA-BRACKET       -> SA
    M4-NUT           -> M4

The first five are all on 12552's bill of materials. Callers key dictionaries on this
(drawing_job_merge and file_scan both build `{normalize_part_code(c): row}`), so five lines
collide on one slot and four of them are unreachable through it; other callers compare two
normalised codes for equality, where two different bought-ins now test equal.

The fix is not a longer regex. It is to ask, before trimming, whether what would be LEFT is
still a drawing number — using the shape test part_code_conventions already publishes, so
this asks the same question as everything else that asks it instead of adding another
spelling of it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from part_identity import normalize_part_code as n                  # noqa: E402


# ── the codes that were collapsing ─────────────────────────────────────────────

@pytest.mark.parametrize("code", [
    "BI-HEADBOLT", "BI-DOMERIVET", "BI-HEXNUT", "BI-SCREW", "BI-LEDDOWNLIGHTS",
    "SA-BRACKET", "M4-NUT",
])
def test_a_letter_prefixed_code_keeps_the_half_that_identifies_it(code):
    assert n(code) == code, "the descriptive half IS the identity on these"


def test_five_bought_ins_off_one_job_stay_five_identities():
    """They were on 12552 together. One slot in a dict is four lines lost."""
    codes = ["BI-HEADBOLT", "BI-DOMERIVET", "BI-HEXNUT", "BI-SCREW", "BI-LEDDOWNLIGHTS"]
    assert len({n(c) for c in codes}) == len(codes)


def test_two_different_bought_ins_do_not_test_equal():
    """Some callers compare normalised codes rather than keying on them, and there the
    collision is a wrong match rather than a lost one."""
    assert n("BI-SCREW") != n("BI-HEXNUT")


# ── what the rule was for, still working ───────────────────────────────────────

@pytest.mark.parametrize("code,expected", [
    ("11650-04-01A-WALL", "11650-04-01A"),
    ("1450-GA-PANEL", "1450-GA"),
    ("9233-12-GA-UKM", "9233-12-GA"),
])
def test_description_bleed_is_still_stripped_from_a_drawing_number(code, expected):
    assert n(code) == expected


@pytest.mark.parametrize("code,expected", [
    ("12349-02-69-01A", "12349-02-69-01A"),
    ("12552-01-01X", "12552-01-01X"),
    ("1455-C GA", "1455-C-GA"),
    ("1450-CGA", "1450-CGA"),
    ("FIXING908", "FIXING908"),
])
def test_every_other_shape_is_unchanged_by_the_guard(code, expected):
    assert n(code) == expected
