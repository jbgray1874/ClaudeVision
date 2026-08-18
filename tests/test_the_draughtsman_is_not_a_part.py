"""A person named in the title block is not costed as a component.

Dyson 10575-02 is drawn by "P.Andrew", and the engine costed a part called ANDREW-14: a
1200 x 1000 x 18mm MDF panel at GBP 28.21 plus CNC joinery labour — on a job whose bill of
materials contains no MDF at all. The dimensions were the pallet's and the name was the
draughtsman's, and nothing on the sheet said either.

It passed the existing boilerplate guard because that guard requires a digit before it will
believe a string is a part number, and the "-14" beside the name supplied one. So a person
became a part on the strength of a revision number typed next to them.

The rule here is deliberately narrow: the part number's letters, stripped of every digit and
separator, must be EXACTLY an author's name. Deleting a real part costs more than carrying a
phantom, so anything that merely contains a name survives.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from file_scan import is_a_person_not_a_part, title_block_author_tokens  # noqa: E402


def _summary(drawn_by="P.Andrew", modified_by="-"):
    return {"pages": [{"page_analysis": {"title_block": {
        "drawn_by": drawn_by, "modified_by": modified_by}}}]}


# ── reading the names off the title block ────────────────────────────────────────────
def test_the_draughtsman_is_read_from_the_title_block():
    assert title_block_author_tokens(_summary("P.Andrew")) == {"ANDREW"}


def test_both_drawn_by_and_modified_by_are_read():
    toks = title_block_author_tokens(_summary("P.Andrew", "J.Gray"))
    assert {"ANDREW", "GRAY"} <= toks


def test_a_list_of_candidates_is_accepted():
    assert "ANDREW" in title_block_author_tokens(_summary(["P.Andrew", "P. ANDREW"]))


def test_initials_are_too_short_to_match_on():
    """Two-letter fragments appear inside real codes constantly; a guard that fired on them
    would delete genuine parts, which is the worse failure by a distance."""
    assert title_block_author_tokens(_summary("PA")) == set()


def test_a_summary_with_no_pages_is_safe():
    assert title_block_author_tokens({}) == set()
    assert title_block_author_tokens(None) == set()


# ── deciding whether a part number is really a person ────────────────────────────────
def test_the_dyson_phantom_is_caught():
    assert is_a_person_not_a_part("ANDREW-14", {"ANDREW"}) is True
    assert is_a_person_not_a_part("Andrew-14", {"ANDREW"}) is True     # case-insensitive
    assert is_a_person_not_a_part("ANDREW", {"ANDREW"}) is True        # bare name


def test_real_part_numbers_survive():
    authors = {"ANDREW"}
    for code in ("8352-01-02", "10575-02-009", "BI-FOOTPLATE", "FIXING2104",
                 "PALLET1", "VINYL-42X76"):
        assert is_a_person_not_a_part(code, authors) is False, code


def test_a_code_that_merely_contains_the_name_survives():
    """Narrow on purpose — only an identity that is NOTHING BUT the name is refused."""
    assert is_a_person_not_a_part("ANDREWS-14", {"ANDREW"}) is False
    assert is_a_person_not_a_part("ANDREW-BRACKET-14", {"ANDREW"}) is False


def test_without_a_named_author_nothing_is_dropped():
    """The guard can only fire on a name the drawing actually gave us."""
    assert is_a_person_not_a_part("ANDREW-14", set()) is False
    assert is_a_person_not_a_part(None, {"ANDREW"}) is False
