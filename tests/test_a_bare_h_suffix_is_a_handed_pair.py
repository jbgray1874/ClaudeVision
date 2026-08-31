"""12552's handed pair would have been priced as two separate parts.

THE PACK. 12552 Infinity Drawer, Rev C. The folder holds `12552-01-03M.SLDPRT` and
`12552-01-03M-H.SLDPRT`; the GA lists `12552-01-03M` at quantity 2 and details it on one
sheet. James, reading it before the run: "Folder has 12552-01-03M-H.SLDPRT — handed pair, not
a second identical panel. PDF has one 03M sheet."

WHAT THE ENGINE WOULD HAVE DONE. mirror_base knew MIR, MIRROR, MIRRORED and HANDED, and
nothing else. A bare "-H" is then an unrelated part number, with three consequences that all
look like different bugs:

  IT INHERITS NO GEOMETRY. The mirror-fill pass copies a measured blank onto the hand that has
  none. 11350's right arm is the case on record: no DXF of its own, so no blank, so it fell
  through to a web lookup and then to an LLM market estimate — £79.04 one run, £86.04 the next,
  97% of the material total — while its left hand sat measured at 258.35 x 84.8 x 2.0 the whole
  time.

  IT IS COUNTED AS A MISSING DRAWING. The pack-completeness check exempts a mirror because a
  hand has no sheet of its own. Unrecognised, "-H" becomes a drawing nobody supplied, on a pack
  that is complete.

  IT IS PRICED AS A SECOND PURCHASE. settle_handed_pairs exists because a handed pair is ONE
  purchase and takes one stock key. Two codes that never pair get two.

"-H" IS NOT "-RH", AND THE ORIGINAL EXCLUSION WAS RIGHT. The rule deliberately refused HAND,
"-LH" and "-RH", because those name the two hands of a symmetric pair and NEITHER is the base:
collapsing them merges two real parts. "-H" names one hand OF a base that is separately drawn
and separately numbered — the same shape as MIR and HANDED. That distinction is the whole of
this change, and it is why LH/RH stay out.

AND THE CALLERS GUARD IT. handed_pairs, the mirror-fill pass and the completeness check all
require the BASE to be present in the same job before doing anything, so a part legitimately
ending in "-H" is untouched unless the job also holds the identical code without it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from part_code_conventions import mirror_base                          # noqa: E402


# ── the pair 12552 actually holds ────────────────────────────────────────────

def test_the_12552_hand_finds_its_base():
    assert mirror_base("12552-01-03M-H") == "12552-01-03M"


def test_the_base_is_not_a_mirror_of_anything():
    assert mirror_base("12552-01-03M") == ""


@pytest.mark.parametrize("code,base", [
    ("11350-01-02 MIR", "11350-01-02"),
    ("11350-01-02MIR", "11350-01-02"),
    ("Mirror7712-04-03A", "7712-04-03A"),
    ("11650-04-01A-HANDED", "11650-04-01A"),
])
def test_the_spellings_that_already_worked_still_do(code, base):
    assert mirror_base(code) == base


# ── and the exclusions the original rule was protecting ──────────────────────

@pytest.mark.parametrize("code", ["12552-01-03M-LH", "12552-01-03M-RH"])
def test_two_hands_of_a_symmetric_pair_are_still_two_parts(code):
    """NEITHER IS THE BASE. Pairing these would merge two real parts, each with its own
    drawing and its own line on the BOM — the exact failure the original exclusion was
    written to prevent, and the reason "-H" had to be admitted on its own rather than by
    relaxing the rule to "any H"."""
    assert mirror_base(code) == ""


@pytest.mark.parametrize("code", ["SOMETHING-HIGH", "PART-HEX", "BRACKET-HANDLE"])
def test_a_word_beginning_with_h_is_not_a_hand(code):
    """The marker has to END the code. Otherwise every part whose name happens to contain an
    H-word becomes somebody's opposite hand."""
    assert mirror_base(code) == ""


def test_a_digit_run_ending_in_h_is_not_a_hand():
    """MIR and HANDED are accepted directly after a digit because normalize_part_code strips
    the separator — "11350-01-02 MIR" becomes "11350-01-02MIR" before most readers see it. A
    single letter cannot take that liberty: "1234H" is a part code, not a hand."""
    assert mirror_base("1234H") == ""


# ── the guard that makes it safe ─────────────────────────────────────────────

def test_nothing_pairs_unless_the_base_is_in_the_same_job():
    """A part legitimately ending in "-H" is untouched unless the job ALSO holds the identical
    code without it. That is what keeps a one-letter suffix from being reckless: the evidence
    is not the name alone, it is two codes that differ by exactly the marker."""
    import drawing_job_merge as djm
    lone = [{"part_number": "BRACKET-H", "description": "a part that just ends in H"}]
    assert list(djm.handed_pairs(lone)) == []

    both = [{"part_number": "12552-01-03M", "description": "concrete support"},
            {"part_number": "12552-01-03M-H", "description": "concrete support, other hand"}]
    pairs = list(djm.handed_pairs(both))
    assert len(pairs) == 1
    hand, base = pairs[0]
    assert hand["part_number"] == "12552-01-03M-H"
    assert base["part_number"] == "12552-01-03M"
