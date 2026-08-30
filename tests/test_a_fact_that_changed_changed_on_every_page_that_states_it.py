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


# ── the pattern list is the weak point, and it proved it ──────────────────────
#
# The SolidWorks entry above was written after finding the claim in four places. It missed a
# FIFTH — the Architecture page, which said "Needs a licensed seat — none active since 19 Aug".
# The fact was the same; the WORDING was not, so a pattern list built from four examples did
# not match the one it had not seen.
#
# That is the honest limit of this file: it catches a stale fact only where somebody thought to
# describe how it might be phrased. It is still worth having — it caught four — but it must not
# be read as proof that a fact is current everywhere. The check below is the cheap general
# backstop: no page may state a DATE-STAMPED status about the seat, however phrased, because
# every such sentence was written before the seat arrived.

def test_no_page_dates_the_absence_of_a_solidworks_seat():
    """A sentence of the form "no seat since <date>" cannot be true now, whatever words it
    uses around it. Broader than the pattern list, and it is what would have caught the fifth."""
    hits = [m.group(0) for m in re.finditer(
        r"(?:no(?:ne)?|without|awaiting|lacking)[^.<]{0,40}seat[^.<]{0,40}"
        r"(?:since|from)\s+\d{1,2}\s+\w{3}", _PORTAL, re.I)]
    assert not hits, (
        "a page still dates the absence of a SolidWorks seat: " + "; ".join(hits))


def test_the_architecture_page_states_the_seat_is_installed():
    """The specific page that was missed, named so the miss is recorded rather than merely
    fixed."""
    at = _PORTAL.index('id="architecture"')
    page = _PORTAL[at:_PORTAL.index('id="rnd"')]
    assert re.search(r"seat is installed|permanent seat", page, re.I), (
        "the architecture page does not say the SolidWorks seat is installed")


# ── claims about mechanisms that do not exist ─────────────────────────────────
#
# The architecture page stated "Fixings capped at £10 from RAG to stop implausible matches".
# There is no such rule anywhere in the pricing path. A documented safeguard that is not in the
# code is worse than no safeguard, because it is relied on — and it is the same shape as the
# parity report's comment pointing at sheet_steel_costing.powder_total_cost, which had no
# callers and sent the next reader chasing dead code.

def test_no_page_claims_a_pricing_cap_the_code_does_not_have():
    """If a cap is ever added, this test should be updated to require the page to describe
    it — the point is that the page and the code agree, not that neither mentions one."""
    claim = re.search(r"[Ff]ixings? capped at £\s*\d+", _PORTAL)
    assert not claim, (
        f"the portal claims {claim.group(0)!r}. Searching src/ for a fixings price cap in the "
        f"historical path finds nothing — the guard that actually exists is the 0.45 minimum "
        f"token overlap. Either implement the cap or do not promise it.")


def test_the_engine_reads_the_repo_root_env_and_the_page_says_so():
    """The layering table listed sdi-intelligence-backend/.env as layer 1 and said earlier
    layers win. For the ENGINE that is not what happens: src/config.py tries the repo root,
    then src/.env, and RETURNS ON THE FIRST HIT — it never opens the backend file. An engine
    setting placed in layer 1 is silently ignored, and this has already cost time once."""
    cfg = (_ROOT / "src" / "config.py").read_text(encoding="utf-8")
    order = re.search(r"\(BASE_DIR / \"\.env\",\s*Path\(__file__\)\.resolve\(\)\.parent / \"\.env\"\)", cfg)
    assert order, "src/config.py no longer looks in the repo root before src/ — update the page"
    at = _PORTAL.index('id="architecture"')
    page = _PORTAL[at:_PORTAL.index('id="rnd"')]
    assert "never opens" in page and "sdi-intelligence-backend/.env" in page, (
        "the architecture page does not warn that the engine never reads the backend .env")
