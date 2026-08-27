"""When a fact changes, it has to change on every page that asserts it — not on the one you
happened to be editing.

WHAT PROMPTED THIS, asked in one line: *"are the #roadmap and the #programme up to date with all
the latest information also?"* I had said yes about the workstream sections. The honest answer
was no, and I only found that out by grepping rather than by remembering.

A permanent SolidWorks seat was installed on the estimating laptop. That single fact was
asserted, in the negative, in FIVE places:

    #dashboard   AI Programme panel — "Blocked on a licence, not on code"
    #roadmap     Technical Design card — "Proven, but held by a licence"
    #programme   Technical Design resource box — "Open dependency … subject to licence"
    service      SDI Technical Design Intelligence detail — same claim again
    service      …and its `next:` field — "Resolve a SolidWorks seat"

I updated the dashboard, because that was the panel I was already editing, and left the other
four saying the opposite. Which is worse than not having updated any of them: a reader who opens
two pages gets two answers and has no way to tell which is current.

WHY THIS IS STRUCTURAL AND NOT CARELESSNESS. This is one 430,000-character HTML file holding
thirteen views plus a service array. The same fact is deliberately restated at different lengths
for different audiences — a chip on the dashboard, a paragraph on the roadmap, a full box on the
service page — so there is no single string to change and no way to see, from the place you are
editing, where else the claim lives.

WHAT THIS FILE DOES. For each fact that has changed, it lists the wording that would mean the
OLD state and requires that wording to be gone everywhere. It deliberately does not require any
particular new wording: the pages should say it in their own voice and at their own length. It
requires only that no page still says the thing that stopped being true.

ADDING TO THIS FILE IS THE POINT. When the next fact changes — the server password lands, the
bought-in catalogue is repointed — add its stale phrasing here in the same shape, and the suite
will tell you which pages you missed instead of a reader telling you.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PORTAL = (_ROOT / "sdi-intelligence-backend" / "sdi-intelligence-portal.html").read_text(
    encoding="utf-8")


def _where(pattern: str) -> list:
    """Every place a phrase appears, named by the view it falls in, so a failure says which
    page to open rather than which character offset to look at."""
    starts = [(m.start(), m.group(1)) for m in
              re.finditer(r'<section class="view[^"]*" id="([a-z0-9-]+)"', _PORTAL)]
    script_at = _PORTAL.index("const SERVICES=[")
    out = []
    for m in re.finditer(pattern, _PORTAL, re.I):
        if m.start() >= script_at:
            out.append("the SERVICES array (a service detail page)")
        else:
            prior = [n for at, n in starts if at <= m.start()]
            out.append(f"#{prior[-1]}" if prior else "the page header")
    return out


# Each entry: what changed, and the wording that asserts the state it changed FROM.
#
# Phrases are chosen to be specific enough not to fire on prose that describes the history
# correctly. "was blocked on a licence" and "the licence WAS the blocker" are both fine and
# should stay readable; "is blocked" and "subject to SolidWorks licence" as a live condition
# are not.
_SUPERSEDED = [
    pytest.param(
        "A permanent SolidWorks seat is installed on the estimating laptop",
        r"(?:Proven, but held by a licence"
        r"|<b[^>]*>Blocked on a licence"
        r"|Nothing ships until a seat is resolved"
        r"|Open dependency:</b> C1"
        r"|it is the single constraint holding C1"
        r"|the constraint is a seat, not development effort)",
        id="solidworks-seat",
    ),
    pytest.param(
        "The SDILive password is rotated and no longer a literal in the source tree",
        r"AIAgentPW2026(?!['\"]?\s*(?:was|had|is the OLD))",
        id="sdilive-password",
    ),
    pytest.param(
        "Workstream 3 exists and is named",
        r"Two workstreams are live and running <b>in parallel</b>, not in sequence\.",
        id="two-workstreams",
    ),
]


@pytest.mark.parametrize("fact,stale", _SUPERSEDED)
def test_no_page_still_asserts_the_superseded_state(fact, stale):
    """THE ASSERTION. Not "the new fact is stated somewhere" — that was already true, on one
    page, while four others said the opposite."""
    places = _where(stale)
    assert not places, (
        f"{fact}.\n"
        f"But {len(places)} place(s) still say otherwise: {', '.join(sorted(set(places)))}.\n"
        f"Update every one, in each page's own voice — the point is that no page contradicts "
        f"another, not that they use identical words.")


# ── the pages that carry the same claim at different lengths ──────────────────

def test_the_licence_change_is_stated_wherever_the_tools_are_described():
    """The counterpart to the test above, and the reason that one is not enough on its own:
    deleting the stale sentence everywhere would also pass it. Anywhere the four COM tools are
    described has to say where they stand, because "C1 generates DXF flat patterns" with no
    mention of the seat reads as though it has always been available."""
    for at in (m.start() for m in re.finditer(r"C1[^<]{0,40}(?:multi-format|export)", _PORTAL, re.I)):
        window = _PORTAL[max(0, at - 900):at + 1400]
        assert re.search(r"seat is now installed|permanent seat is now|now installed on the "
                         r"estimating laptop|the seat is now installed", window, re.I), (
            "a description of the COM tools does not say the seat is installed — "
            f"near: ...{_PORTAL[at:at + 90]}...")


def test_the_remaining_question_is_stated_as_a_decision_not_a_blocker():
    """Seats for the rest of the department are a licensing decision. Left described as a
    constraint it reads as something engineering is waiting on, which is the wrong owner."""
    assert re.search(r"which (?:other )?machines get a seat|machines beyond the estimating laptop "
                     r"get a SolidWorks seat|seats on the other machines", _PORTAL, re.I), (
        "nothing states what is actually still open about the licence")
