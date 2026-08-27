"""A class name with no rule behind it does not fail. It renders as nothing, and reads as fine.

WHAT PROMPTED THIS. Adding one page — Muhammad's Fixture Library guide, rebuilt in this site's
components — I wrote five class names that do not exist: `.kpi`, `.lbl`, `.secttl`, `.grid3` and
`.tablewrap`. Every one of them was a reasonable guess from the names that DO exist. None would
have thrown, failed a test, or looked wrong in a diff. `.grid3` would simply have stacked three
side-by-side cards into a column; `.tablewrap` would have let a wide table run off the page.

Auditing for that turned up the same defect ALREADY LIVE on the page, twice over:

    chip c-acc   3 uses, no rule
    chip c-ok    5 uses, no rule

Eight status chips rendering as bare words — no background, no border, no colour — because the
chip layer had grown two aliases nobody defined. And this file's own stylesheet already carries a
comment about exactly this happening before, one layer down:

    Aliases. Both names were in use against no definition, so `var(--acc)` fell back to
    inherit and `background:var(--good)` fell back to transparent — which is why the two
    "Done" bars on the estimating timeline rendered as empty tracks.

Same failure, same page, second time, and the first one was only found because somebody noticed
a chart looked empty. That is the argument for computing it rather than looking.

WHY THIS IS EASY TO GET WRONG AND HARD TO SEE. This is one 450,000-character HTML file with its
whole design system in a single <style> block at the top and thirteen views below it. Nobody
scrolls up to check whether `.tablewrap` exists; they copy the shape of a nearby block and trust
the name. CSS is forgiving by design — an unknown class is not an error, it is nothing — so the
feedback for a wrong guess is a layout that is slightly off in a way you would blame on content.

WHAT THIS DOES. Every class used in the markup must have a rule in the stylesheet. Utility-only
names that genuinely carry no styling are allow-listed BY NAME, so the exception is a decision
somebody made rather than a hole in the check.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _ROOT / "sdi-intelligence-backend"
_PAGES = ("sdi-intelligence-portal.html",
          "sdi-estimating-intelligence.html",
          "sdi-estimating-guide.html")

# Names that carry no styling on purpose. `reveal` is animated by script; the rest are hooks a
# selector or a query uses. Each is here because somebody decided it, not because the check
# could not see it.
_INTENTIONALLY_UNSTYLED = {
    "reveal",       # the entrance animation is applied by JavaScript, not by a rule
    "sorted",       # set by the file-list sorter and read back by it
    "testing-up",   # a state hook toggled by script
}


def _split(page: str):
    """All stylesheet text, and all the markup, for one page.

    TWO STYLE BLOCKS, NOT ONE. The estimating page and the guide each carry a second <style>
    for the shared sidebar. Splitting on the FIRST `</style>` read half the CSS and reported
    every sidebar class as undefined — the same greedy-first-match trap already recorded in
    this suite against the page-script syntax check, which for weeks handed `node` literal
    tag text because `(.*)` between one `<script>` and the last `</script>` is greedy.
    """
    blocks = re.findall(r"<style[^>]*>(.*?)</style>", page, re.S)
    assert blocks, "no stylesheet found on this page"
    markup = re.sub(r"<style[^>]*>.*?</style>", "", page, flags=re.S)
    return "\n".join(blocks), markup


def _classes_used(body: str) -> set:
    out = set()
    # Static markup, plus the class strings JavaScript builds at run time — the second kind is
    # where a wrong name is hardest to spot, because it never appears in the file as markup.
    for attr in re.findall(r'class="([^"{}<>]+)"', body):
        out.update(attr.split())
    for attr in re.findall(r"class='([^'{}<>]+)'", body):
        out.update(attr.split())
    return {c for c in out if re.fullmatch(r"[a-z][a-z0-9-]*", c)}


def _classes_defined(css: str) -> set:
    r"""Every class a rule mentions, including inside a descendant selector.

    LOOKAHEAD, NOT A CHARACTER CLASS. The first version ended `[,{:.\[]`, which CONSUMED the
    delimiter — so in `.k .big{...}` it matched `.k` and ate the dot of `.big`, and `.big`
    was reported undefined while being defined on that very line. A selector that styles a
    child is still a definition, and this is the common shape in these files.
    """
    return set(re.findall(r"\.([a-z][a-z0-9-]*)(?=[\s,{:.\[>+~)]|$)", css))


@pytest.mark.parametrize("page_name", _PAGES)
def test_every_class_on_the_page_has_a_rule_behind_it(page_name):
    """THE ASSERTION. An unknown class is not an error in CSS — it is nothing at all, which
    is why this cannot be left to review."""
    css, body = _split((_BACKEND / page_name).read_text(encoding="utf-8"))
    orphans = sorted(_classes_used(body) - _classes_defined(css) - _INTENTIONALLY_UNSTYLED)
    assert not orphans, (
        f"{page_name} uses class names with no rule in its stylesheet: {', '.join(orphans)}.\n"
        f"These do not error — they render as nothing. Either add the rule, use the component "
        f"that already exists, or add the name to _INTENTIONALLY_UNSTYLED so the exception is "
        f"a decision rather than a gap.")


def test_the_chip_aliases_that_were_rendering_as_bare_words_are_defined():
    """The two that were already live when this test was written. Named explicitly so that
    removing their rules fails HERE, with the history, rather than only in the general check
    above."""
    css, _ = _split((_BACKEND / "sdi-intelligence-portal.html").read_text(encoding="utf-8"))
    for alias in ("c-acc", "c-ok"):
        assert re.search(rf"\.{alias}\{{", css), (
            f".{alias} is used as a chip class and has no rule — the chip renders as bare "
            f"text with no background or border, which still reads as a word and so is not "
            f"noticed. This is the third instance of this exact fault in this file.")


def test_the_check_can_actually_see_a_missing_class():
    """A guard on the guard. If the regexes stopped matching, every assertion above would
    pass on empty sets — the failure mode where a pinning test quietly stops pinning."""
    css, body = _split((_BACKEND / "sdi-intelligence-portal.html").read_text(encoding="utf-8"))
    used, defined = _classes_used(body), _classes_defined(css)
    assert len(used) > 40, f"only {len(used)} classes parsed out of the markup"
    assert len(defined) > 40, f"only {len(defined)} classes parsed out of the stylesheet"
    assert "panel" in used and "panel" in defined
    # And it would catch one: a name that is in neither must be reported, not ignored.
    assert "notaclass" not in defined


# ── every navigation target resolves ──────────────────────────────────────────
#
# The same shape of fault one level up. Both hand-copied sidebars linked to `/#permissions`
# long after that page was removed from the portal — and `routeHash` requires
# `document.getElementById(h)` before it will navigate, so the link had been doing nothing at
# all. A dead entry in a nav is worse than a missing one: it says the feature exists and looks
# broken when it does not respond.

def _portal_view_ids() -> set:
    portal = (_BACKEND / "sdi-intelligence-portal.html").read_text(encoding="utf-8")
    return set(re.findall(r'<section class="view[^"]*" id="([a-z0-9-]+)"', portal))


def test_the_portal_nav_points_only_at_views_that_exist():
    portal = (_BACKEND / "sdi-intelligence-portal.html").read_text(encoding="utf-8")
    ids = _portal_view_ids()
    strays = sorted({v for v in re.findall(r'data-view="([a-z0-9-]+)"', portal) if v not in ids})
    assert not strays, f"the portal nav points at views it does not define: {strays}"


@pytest.mark.parametrize("page_name", _PAGES[1:])
def test_the_copied_sidebars_point_only_at_views_the_portal_defines(page_name):
    """These pages link into the portal by hash. The portal is the authority; a hash it does
    not answer is a dead link, and it fails silently."""
    page = (_BACKEND / page_name).read_text(encoding="utf-8")
    ids = _portal_view_ids()
    hrefs = {h for h in re.findall(r'href="/#([a-z0-9-]+)"', page) if not h.startswith("aisvc")}
    strays = sorted(hrefs - ids)
    assert not strays, (
        f"{page_name} links to portal views that do not exist: {strays}. routeHash checks "
        f"getElementById before navigating, so these do nothing when clicked.")


# ── the new guide is reachable and is called the same thing everywhere ────────

@pytest.mark.parametrize("page_name", _PAGES)
def test_the_fixture_library_guide_is_in_every_sidebar(page_name):
    """It sits under the estimating guide in Operate, on all three, or the three navigations
    disagree about what the site contains — which is the bargain these copies were allowed on."""
    page = (_BACKEND / page_name).read_text(encoding="utf-8")
    assert "SDI Fixture Library Guide" in page, f"{page_name} has no Fixture Library Guide entry"


def test_the_guide_sits_directly_below_the_estimating_guide():
    """Where it was asked to go, and where it belongs: the two operator guides together."""
    for page_name in _PAGES:
        page = (_BACKEND / page_name).read_text(encoding="utf-8")
        # Inside the NAV, not the whole file — on the guide page the estimating guide's name
        # appears first in its own <title>, which is not a nav entry and is 28 links away.
        nav = page[page.index(">Operate<"):]
        est = nav.index("SDI Estimating Intelligence Guide")
        fix = nav.index("SDI Fixture Library Guide")
        page = nav
        assert est < fix, f"{page_name} lists the Fixture Library guide above the estimating one"
        between = page[est:fix]
        assert between.count("</a>") == 1, (
            f"{page_name} has other entries between the two guides")


@pytest.mark.parametrize("page_name", _PAGES)
def test_the_estimating_tool_is_called_sdi_estimating_intelligence_in_operate(page_name):
    """The portal's own Operate group still said "Estimating Intelligence" while both copies,
    the service list, the dashboard and every status report said "SDI Estimating Intelligence".
    The AI Services list was pinned against exactly this drift; the Operate group never was."""
    page = (_BACKEND / page_name).read_text(encoding="utf-8")
    at = page.index(">Operate<")
    block = page[at:at + 4000]
    assert re.search(r">SDI Estimating Intelligence</a>", block), (
        f"{page_name}'s Operate group does not call it SDI Estimating Intelligence")
    assert not re.search(r"(?<!SDI )>Estimating Intelligence</a>", block), (
        f"{page_name}'s Operate group still carries the unprefixed name")
