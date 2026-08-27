"""There are four pages that answer "when", and a workstream has to be on all of them.

WHAT WENT WRONG, reported by James in one line: *"http://localhost:8072/#roadmap — for this, I
can't see creative design elements"*. He was right and the file was not stale.

The portal has two separate pages that both look like a roadmap and are not the same view:

    #programme   the AI Programme page — workstream cards, phase-by-phase, with date chips
    #roadmap     the AI Roadmap page   — Phase 1..6 cards across the whole AI & Robotics plan

Their markup sits in the same region of the file and both contain the words "Workstream" and
"Phase". Editing by searching for a heading landed the whole SDI Creative Design Intelligence
section in `#programme` — where it looked right, and passed every check I had — while `#roadmap`
carried no trace of it. Three pages showed a workstream and the fourth did not, which does not
read as an omission. It reads as three different things.

WHY A TEST AND NOT MORE CARE. The two views are 200,000 characters apart in one HTML file, and
the only thing distinguishing them is which `<section class="view" id="...">` an edit fell
inside. Nothing about the surrounding markup tells you which one you are in. That is precisely
the situation a test is for: it can compute the answer, and a person reading a diff cannot.

WHAT THIS PINS. For each live workstream, every page that carries dates must name it. Not the
dates themselves — those change, and the delivery tracker owns them — but the presence of the
workstream on each surface, so a fourth page cannot silently fall behind again.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PORTAL = (_ROOT / "sdi-intelligence-backend" / "sdi-intelligence-portal.html").read_text(
    encoding="utf-8")


def _views() -> dict:
    """Each `<section class="view" id="...">` and the markup inside it.

    Sections do not nest, so the next section's start is this one's end. The last runs to the
    script block, which is where the page stops being markup.
    """
    starts = [(m.start(), m.group(1)) for m in
              re.finditer(r'<section class="view[^"]*" id="([a-z0-9-]+)"', _PORTAL)]
    assert len(starts) >= 8, f"only {len(starts)} views found — has the page structure changed?"
    end_of_markup = _PORTAL.index("<script>", starts[-1][0])
    out = {}
    for i, (at, name) in enumerate(starts):
        stop = starts[i + 1][0] if i + 1 < len(starts) else end_of_markup
        out[name] = _PORTAL[at:stop]
    return out


_VIEWS = _views()

# The pages a person opens to find out when something happens. The dashboard is the front
# door, the two roadmaps are the plan, and each has to be complete on its own.
_DATED_PAGES = ("dashboard", "programme", "roadmap")

# Live workstreams and the name each page must call them by.
_WORKSTREAMS = (
    "SDI Estimating Intelligence",
    "SDI Technical Design Intelligence",
    "SDI Creative Design Intelligence",
)


def test_the_three_dated_pages_are_all_present_and_distinct():
    """If two of these ever resolved to the same markup the assertions below would pass
    twice over on one page and prove nothing."""
    for name in _DATED_PAGES:
        assert name in _VIEWS, f"no view with id={name!r}"
    bodies = [_VIEWS[n] for n in _DATED_PAGES]
    assert len({len(b) for b in bodies}) == len(bodies), "two dated views look identical"


@pytest.mark.parametrize("page", _DATED_PAGES)
@pytest.mark.parametrize("workstream", _WORKSTREAMS)
def test_every_dated_page_names_every_live_workstream(page, workstream):
    """THE ASSERTION. #roadmap had no mention of the creative workstream at all while the
    other two carried it in full."""
    assert workstream in _VIEWS[page], (
        f"the {page} page does not mention {workstream}. A workstream on three of the four "
        f"surfaces and missing from the fourth reads as a different thing, not as an omission.")


@pytest.mark.parametrize("page", _DATED_PAGES)
def test_the_creative_workstream_carries_its_two_projects_by_name(page):
    """Naming the workstream and not its deliverables would satisfy the test above while
    still leaving somebody unable to find out when Drawing Search ships."""
    for project in ("SDI Drawing Search Intelligence", "SDI Client Briefing Intelligence"):
        assert project in _VIEWS[page], f"{page} does not name {project}"


@pytest.mark.parametrize("page", _DATED_PAGES)
def test_the_first_go_live_in_the_programme_is_stated_on_each(page):
    """25 Sep 2026 is the earliest go-live anywhere in the programme — earlier than the
    estimating engine's, which every one of these pages leads with. A page that omits it
    gives a reader the wrong idea of what lands first."""
    assert re.search(r"25 Sep(?:tember)? (?:20)?26", _VIEWS[page]), (
        f"{page} does not carry the 25 Sep 26 go-live")


# ── the sidebar and the detail pages ───────────────────────────────────────────

def test_the_two_new_services_carry_their_dates_on_their_own_detail_page():
    """A service page reached from the sidebar has to answer "when" without sending somebody
    to a different page to find out. Both were published with prose and no schedule."""
    script = _PORTAL[_PORTAL.index("const SERVICES=["):]
    for sid in ("drawing-search", "client-briefing"):
        at = script.index("{id:'" + sid + "'")
        entry = script[at:script.index("\n\n", at)]
        assert "Delivery plan" in entry, f"{sid} has no delivery-plan section"
        assert entry.count("<tr") >= 6, f"{sid}'s phase table has too few rows to be the plan"
        assert "Sep 26" in entry, f"{sid} names no dates"


def test_the_tracker_names_are_kept_beside_the_service_names():
    """The delivery tracker calls these "Fixture Library" and "Client Briefing". Somebody
    holding that document has to be able to tell it is the same two projects, or the rename
    turns one set of work into two."""
    for tracker_name in ("Fixture Library", "Client Briefing"):
        assert tracker_name in _PORTAL, tracker_name
