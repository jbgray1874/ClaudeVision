r"""
test_a_finish_we_have_never_heard_of_is_not_a_finish_thats_free.py

THE CHECK WAS A WHITELIST, SO ITS OWN GAPS WERE INVISIBLE.

check_a_stated_finish_is_costed asks whether a stated finish reached the sheet. It answered
by matching _FINISH_PROCESS_WORDS -- VINYL, PAINT, LAMINATE, ANODIS, and so on. That is a
list of finishes somebody already knew this engine cannot cost. A finish matching NONE of
them produced no cost AND no flag: silent, because the vocabulary had never met it.

11650-01-05A DOOR states UV HARDCOAT ALL SIDES. Not powder, not vinyl, not a sheen. It went
through this check, the route and the sheet without one word.

The new bucket names it without deciding what it is, and that restraint is the point. An
unrecognised finish is one of two things and the engine cannot tell which:

  A SHOP PROCESS nobody has a rate for -- the work is being supplied free.
  A PROPERTY OF THE SHEET WE BUY -- UV hardcoat arrives on polycarbonate from the mill
  (Makrolon UV, Lexan Margard), so it belongs in the GBP/m2 and not in the route. Adding a
  labour line for that kind would invent work SDI does not do, and double-count against a
  material rate that should simply be dearer.

An estimator settles that in seconds. The engine's job is to ask, not to guess -- and the
same restraint the uncostable bucket already shows: "this check does not guess what the
finish costs; inventing a rate would be worse than the gap".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import invariants as inv                       # noqa: E402
from invariants import WARNING, UNVERIFIED     # noqa: E402


def _job(*finishes, priced_ops=("P.Coat",)):
    return {"manufacturing_writeup": {"parts": [
                {"part_number": f"P{i}", "normalized_finish": f}
                for i, f in enumerate(finishes)]},
            "estimate_summary": {"final_estimate": {
                "labour_rows": [{"operation": op} for op in priced_ops]}}}


def _codes(job):
    return sorted(v.get("code") or v.get("name") or "" for v in
                  inv.check_a_stated_finish_is_costed(job))


@pytest.mark.parametrize("finish,expected,why", [
    ("UV HARDCOAT ALL SIDES", ["stated_finish_not_recognised"],
     "the live case: no vocabulary for it, so it was silently free"),
    ("1/2 INCH REEDED VINYL", ["stated_finish_not_costed"],
     "a known-uncostable process keeps its own, more specific finding"),
    ("POWDER COATED - MATT - EPOXY BASED POWDER", [],
     "powder is costable and costed; flagging it is the cry-wolf failure"),
    ("SEE ASSEMBLY DRAWING", [],
     "a pointer names no work; whether it was followed is another check's question"),
    ("RAW", [], "states there is NO finish"),
    ("SELF COLOUR", [], "states there is NO finish"),
    ("MILL FINISH", [], "states there is NO finish"),
    ("MATT", [], "a sheen qualifies a finish and is never the finish"),
    ("", [], "an empty field is an absence, owned by a different check"),
])
def test_each_kind_of_finish_gets_its_own_answer(finish, expected, why):
    assert _codes(_job(finish)) == expected, why


def test_the_unrecognised_message_does_not_decide_what_the_finish_is():
    """Naming it a process would invent work; naming it a material property would move money
    into a rate on a guess. It says both possibilities and hands it over."""
    found = inv.check_a_stated_finish_is_costed(_job("UV HARDCOAT ALL SIDES"))
    assert [v["severity"] for v in found] == [WARNING]
    msg = found[0]["message"]
    assert "SHOP PROCESS" in msg and "PROPERTY OF THE SHEET WE BUY" in msg
    assert "invent work that is not done" in msg
    assert "UV HARDCOAT ALL SIDES" in msg, "name the finish or nobody can act on it"


def test_both_kinds_can_fire_on_one_job():
    """A vinyl panel and a hardcoated door are different gaps with different answers, and
    collapsing them into one finding would lose the one that needs a rate."""
    assert _codes(_job("1/2 INCH REEDED VINYL", "UV HARDCOAT ALL SIDES")) == [
        "stated_finish_not_costed", "stated_finish_not_recognised"]


def test_a_costed_powder_job_stays_silent():
    """11650's cabinet fired the old check on ten powder-coated steel parts whose P.Coat row
    was on the same sheet. The new bucket must not reintroduce that by another door."""
    assert _codes(_job(*["POWDER COATED - MATT"] * 10)) == []


def test_an_unreadable_summary_is_unverified_not_a_pass():
    out = inv.check_a_stated_finish_is_costed(None)
    assert out and out[0]["severity"] == UNVERIFIED


def test_the_no_finish_list_earns_its_place():
    """A previous _NO_FINISH_WORDS list was deleted because a mutation proved it never fired:
    requiring a process word already excluded RAW and SELF COLOUR. The unrecognised bucket
    has no such requirement by design, so the list is load-bearing again -- and this is the
    test that proves it, rather than a comment claiming it."""
    assert "RAW" in inv._NO_FINISH_WORDS
    assert _codes(_job("RAW")) == []


def test_the_vocabularies_do_not_overlap():
    """Asserted at import too. A word meaning both 'no finish' and 'an uncostable process'
    would make one finish two different findings depending on which loop reached it."""
    assert not (set(inv._NO_FINISH_WORDS) & set(inv._FINISH_PROCESS_WORDS))
    assert not any(w in inv._FINISH_PROCESS_WORDS
                   for w in ("POWDER", "DIAMOND", "POLISH", "PEEL"))


def test_no_finish_is_matched_on_whole_words():
    """RAW IS INSIDE DRAWING. A substring test made "SEE ASSEMBLY DRAWING" -- on ten parts of
    this job -- state that it has no finish, which is the right verdict reached for a
    completely wrong reason. A mutation deleting the pointer rule that SHOULD have caught
    them changed nothing, because the accident was doing the work. An accidental match is
    worse than a miss: it hides the miss."""
    assert inv._states_no_finish("RAW") is True
    assert inv._states_no_finish("SEE ASSEMBLY DRAWING") is False
    assert inv._states_no_finish("PAINTED, NOT RAW") is True
    assert inv._states_no_finish("BRUSHED") is False, "BRUSHED must not match BARE or PLAIN"


def test_a_pointer_is_skipped_because_it_is_a_pointer():
    """Now that DRAWING no longer matches RAW, this is carried by the rule that means it."""
    assert _codes(_job("SEE ASSEMBLY DRAWING")) == []
    assert _codes(_job("AS PER DRAWING")) == []
    assert _codes(_job("REFER TO GA")) == []


def test_a_costable_finish_with_no_sheen_is_still_skipped():
    """DIAMOND POLISH names a process this engine CAN cost and carries no sheen word, so it
    reaches the unrecognised bucket and must be let through there. The earlier tests all
    happened to carry a sheen, so the skip that does this was never exercised."""
    assert _codes(_job("DIAMOND POLISH")) == []
    assert _codes(_job("POWDER COATED")) == []


def test_unfinished_states_no_finish():
    assert _codes(_job("UNFINISHED")) == []
