"""A revision note saying a panel was removed must not set the part's material.

The second half of the ANDREW-14 fault on 10575-02. Having invented a part from the draughtsman's
name, the engine gave it the material MDF — read from a revision note that says:

    MDF PANEL REMOVED

The note is a record of something taken OFF the drawing. The keyword scan saw the letters M-D-F
and set the family, and from there the part was priced as board.

This is the same shape as a bug already fixed here once. `_strip_material_boilerplate` exists
because the spec-legend header "TIMBER PRODUCTS:" was setting TIMBER on steel detail sheets — a
material word in a non-part context. A negated revision note is the same kind of context and was
simply not on the list.

WHAT IS DELIBERATELY NARROW. Only the material token is blanked, not the clause around it, and
only when a removal verb follows it closely with no other material word in between. A drawing
that reads "MATERIAL: MDF" and separately carries "REV C ALUMINIUM PANEL REMOVED" must keep MDF
and drop ALUMINIUM — blanking whole clauses would have taken both.

WHAT WAS REJECTED: treating any material word near the word "REV" as suspect. Revision blocks are
where material CHANGES are recorded, and a note reading "REV D MATERIAL NOW 18MM MDF" is the most
authoritative statement of material on the sheet. Negation is the signal, not proximity to a
revision marker.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from extractor_patterns import extract_title_block_fields  # noqa: E402


def _materials(text: str):
    return extract_title_block_fields(text).get("materials") or []


# ── The 10575-02 fault ─────────────────────────────────────────────────────────

def test_a_removed_panel_does_not_set_the_material():
    assert _materials("REV C  MDF PANEL REMOVED") == []


@pytest.mark.parametrize("verb", [
    "REMOVED", "DELETED", "OMITTED", "SUPERSEDED", "CANCELLED",
    "NOT USED", "NOT REQUIRED", "NO LONGER USED", "NO LONGER REQUIRED",
])
def test_every_removal_word_is_understood(verb):
    assert _materials(f"REV B  ALUMINIUM BRACKET {verb}") == [], (
        f"a material {verb.lower()} was still read as the part's material")


# ── What must survive ──────────────────────────────────────────────────────────

def test_a_labelled_material_is_untouched():
    assert _materials("MATERIAL: MDF") == ["MDF"]


def test_a_labelled_material_survives_a_removal_note_elsewhere():
    """The narrow case that rules out blanking whole clauses."""
    got = _materials("MATERIAL: MDF    REV C  ALUMINIUM PANEL REMOVED")
    assert "MDF" in got, "the labelled material was lost to a note about a different material"
    assert "ALUMINIUM" not in got, "the removed material was still read"


def test_a_revision_that_changes_the_material_is_still_authoritative():
    """Revision blocks are where material changes are recorded. Proximity to REV is not the
    signal — negation is. This is the case that would break if it were."""
    assert "MDF" in _materials("REV D  MATERIAL NOW 18MM MDF")


def test_a_plain_material_callout_near_other_words_still_reads():
    assert "ALUMINIUM" in _materials("ALUMINIUM BRACKET TO SUIT")


def test_a_removal_verb_far_away_does_not_reach_back():
    """The window is short on purpose. A verb at the other end of the sheet is not about this
    callout, and letting it reach would lose genuine materials."""
    text = "MDF" + " FILLER WORDS AND MORE FILLER WORDS AND YET MORE PADDING HERE " * 2 + "REMOVED"
    assert "MDF" in _materials(text)
