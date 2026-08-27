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


# ── the milestone strip ────────────────────────────────────────────────────────
#
# The AI Programme page opens with a PROGRAMME TIMELINE strip — five nodes on a rule, which is
# the first thing on the page and the only part most readers will look at. It had two faults
# and only one was reported.
#
#   1. Creative Design was absent. Its first go-live, 25 Sep 26, is the EARLIEST fixed date in
#      the whole programme — so the one element whose job is to say what lands when omitted
#      the thing that lands first.
#
#   2. The nodes were not in date order: Sept/Oct 26, Sep 26 – Jan 27, Q3–Q4 2026, 4 Jan 27.
#      A quarter in 2026 sat to the RIGHT of a span ending in 2027. A timeline that is not
#      chronological is worse than no timeline, because it is read as one without being
#      checked — nobody audits the left-to-right order of a graphic that looks finished.

def _timeline_nodes():
    """(date text, name) for each node on the strip, in the order they are drawn."""
    strip = _VIEWS["programme"]
    at = strip.index("Programme timeline")
    block = strip[at:strip.index("<!-- WORKSTREAM 1", at)]
    return re.findall(
        r'font-weight:700">([^<]+)</div>\s*<div[^>]*font-weight:600">(.*?)</div>',
        block, re.S)


def test_the_strip_still_has_nodes_this_test_can_read():
    """A markup change that this regex stopped matching would make every assertion below
    pass on an empty list — the failure mode where a pinning test quietly stops pinning."""
    nodes = _timeline_nodes()
    assert len(nodes) >= 5, f"only {len(nodes)} timeline nodes parsed"


def test_every_live_workstream_is_on_the_milestone_strip():
    """THE ASSERTION. It is the first thing on the page and it named two of three."""
    text = " ".join(f"{d} {n}" for d, n in _timeline_nodes()).replace("<br>", " ")
    for ws in ("Technical Design", "Creative Design", "Estimating"):
        assert ws in text, f"the programme timeline does not mention {ws}"


def test_the_earliest_date_in_the_programme_is_the_first_node():
    """25 Sep is not just present, it is FIRST — and Drawing Search at 25 Sep is preceded only
    by Technical Design's P1 on 15 Sep. A strip that leads with the estimating engine tells a
    reader the wrong thing about what lands first."""
    dates = [d for d, _ in _timeline_nodes()]
    assert "15 SEP 2026" in dates[0], f"the strip opens on {dates[0]!r}"
    assert "25 SEP 2026" in dates[1], f"the second node is {dates[1]!r}"


def test_the_nodes_run_in_date_order():
    """The fault nobody would have reported, because a finished-looking graphic is not
    audited left to right. Each node is keyed on its FIRST delivery — the only ordering a
    reader can check against the sections below."""
    import datetime as _dt
    # First date of each node, as the strip states it. A node that stops being parseable here
    # is a node whose date somebody has written in a new format, which is worth failing on.
    known = {
        "15 SEP 2026": _dt.date(2026, 9, 15),
        "25 SEP 2026": _dt.date(2026, 9, 25),
        "SEPT / OCT 2026": _dt.date(2026, 9, 30),   # the target window opens end-Sept
        "~NOV 2026": _dt.date(2026, 11, 1),
        "4 JAN 2027": _dt.date(2027, 1, 4),
    }
    dates = [d.strip() for d, _ in _timeline_nodes()]
    unknown = [d for d in dates if d not in known]
    assert not unknown, (
        f"timeline node(s) with a date this test cannot order: {unknown}. Add them to `known` "
        f"with the date they represent, so the ordering below still means something.")
    ordered = [known[d] for d in dates]
    assert ordered == sorted(ordered), (
        "the programme timeline is not in date order: "
        + " → ".join(dates))


def test_the_page_says_how_many_dates_the_strip_carries():
    """The lede said "four active workstreams, three fixed milestones" above a strip of four
    nodes. Three numbers, none of which agreed with each other or with the page."""
    strip_count = len(_timeline_nodes())
    lede = re.search(r"([A-Za-z]+) fixed dates", _VIEWS["programme"])
    assert lede, "the lede no longer states how many fixed dates there are"
    words = {"three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
    assert words.get(lede.group(1).lower()) == strip_count, (
        f"the lede says {lede.group(1)} fixed dates and the strip draws {strip_count}")


# ── the dashboard has to hold three of them ───────────────────────────────────
#
# The AI Programme panel sat in the NARROW half of a 1.5fr/1fr grid, with its workstreams
# stacked vertically. With two that was merely tight. With three it measured 1,383px against a
# left-hand panel carrying about 250px of content — and CSS grid stretches siblings to match,
# so roughly 1,100px of the dashboard was empty white space beside a column too long to read
# without scrolling.
#
# That is a layout consequence of a CONTENT change, which is the kind nobody plans for: adding
# the third workstream was correct everywhere and broke the page in one place.

def _dashboard() -> str:
    at = _PORTAL.index('id="dashboard"')
    return _PORTAL[at:_PORTAL.index('<section class="view" id="aisvc"')]


def test_the_programme_panel_is_full_width_not_a_grid_column():
    """THE FIX, pinned. Inside a grid2 it is half a page wide; the three workstreams need the
    whole width to sit side by side.

    Walks the dashboard keeping a stack of the elements still open, so the question asked is
    the real one — "is a grid2 open at the point the panel starts?" — rather than a count of
    tags before it, which the first version of this test got wrong.
    """
    dash = _dashboard()
    prog_at = dash.index("<h3>AI Programme</h3>")
    stack = []
    for m in re.finditer(r"<(/?)div\b([^>]*?)(/?)>", dash[:prog_at]):
        if m.group(3) == "/":                       # self-closing
            continue
        if m.group(1):                              # closing tag
            if stack:
                stack.pop()
        else:
            stack.append("grid2" in m.group(2))
    assert not any(stack), (
        "the AI Programme panel is inside a grid2 column — it renders at half width and grid "
        "stretches its sibling to match its height, which is how 1,100px of the dashboard "
        "became empty space beside an unreadably long column")


def test_the_check_can_tell_a_grid_column_from_a_full_width_panel():
    """A guard on the guard: the walk above must actually detect nesting, or it would pass on
    any markup at all. The end-to-end panel IS a grid column, so it must come out true."""
    dash = _dashboard()
    at = dash.index("<h3>We are uniquely end-to-end</h3>")
    stack = []
    for m in re.finditer(r"<(/?)div\b([^>]*?)(/?)>", dash[:at]):
        if m.group(3) == "/":
            continue
        if m.group(1):
            if stack:
                stack.pop()
        else:
            stack.append("grid2" in m.group(2))
    assert any(stack), "the walk cannot see that this panel sits inside a grid2"


def test_the_three_workstreams_are_columns_not_a_stack():
    """Side by side they read as peers. Stacked, the third is a footnote to the first two —
    which is the opposite of what the programme is."""
    dash = _dashboard()
    prog = dash[dash.index("<h3>AI Programme</h3>"):]
    grid = re.search(r'<div style="display:grid;grid-template-columns:repeat\(auto-fit,'
                     r'minmax\((\d+)px,1fr\)\)[^"]*"', prog)
    assert grid, "the workstreams are not laid out in a multi-column grid"
    assert int(grid.group(1)) <= 320, (
        f"the columns need {grid.group(1)}px each to appear — too wide to fit three, so they "
        f"would wrap back into a stack on any normal screen")


def test_each_workstream_column_carries_its_own_colour():
    """Green live, amber in build, violet creative — the same coding as the roadmap strip and
    the status report. Three identical boxes would lose the one thing the colour says."""
    dash = _dashboard()
    prog = dash[dash.index("<h3>AI Programme</h3>"):]
    for colour in ("var(--ok)", "var(--accent)", "var(--violet)"):
        assert f"border-top:3px solid {colour}" in prog, (
            f"no workstream column is marked {colour}")
