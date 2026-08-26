"""Three copies of one list of names, and two of them had stopped agreeing with the third.

The portal builds its AI Services nav at run time from a SERVICES array, so renaming a service
there renames it everywhere the portal shows it. The estimating page and the guide do not: each
carries a HAND-COPIED sidebar, written when there was one list and nobody had renamed anything.

So when the services were renamed to `SDI <thing> Intelligence`, the portal changed and those two
did not. The estimating page went on offering "Estimating", "AI Voice Agents" and "Sage X3
Acceleration Program" while the portal one click away called the same things "SDI Estimating
Intelligence", "SDI Voice Intelligence" and "SDI ERP Intelligence · Sage X3" — and it had no entry
at all for SDI Technical Design Intelligence, which is the second workstream of the whole
programme.

WHY THAT IS WORSE THAN UNTIDY. These are the names in the status reports, in the roadmap, and in
what James tells the board. A person reading "Estimating" in one place and "SDI Estimating
Intelligence" in another has to work out whether they are the same thing, and the honest answer
from the screen alone is that they might not be. A navigation that disagrees with itself is a
navigation nobody trusts to be complete.

WHY THE COPIES STAY. The portal's list lives in JavaScript inside its own page; the estimating
page and the guide are separate static files served straight off disk. Sharing one list means
either serving the nav from the backend — a template layer for two files — or fetching it, which
puts a network call in front of the sidebar rendering. Neither is worth it for a list that changes
twice a year.

So the duplication is deliberate and this test is the price of it. It is the same bargain already
made for the print picker's ENGINE_OUTPUT_PATTERNS: two copies of a rule are allowed, and a test
pins them together so drift fails the suite instead of reaching a screen.

THE PORTAL IS THE AUTHORITY. It is where a service is defined, where its detail page comes from,
and where a new one gets added. If these ever disagree, the portal is right and the copies are
stale — never the other way round.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _ROOT / "sdi-intelligence-backend"

_PORTAL = (_BACKEND / "sdi-intelligence-portal.html").read_text(encoding="utf-8")
_COPIES = {
    "sdi-estimating-intelligence.html": None,
    "sdi-estimating-guide.html": None,
}
for _name in _COPIES:
    _COPIES[_name] = (_BACKEND / _name).read_text(encoding="utf-8")


def _unescape_js(text: str) -> str:
    """The array mixes literal characters with \\uXXXX escapes for the same ones."""
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)


def _portal_services():
    """(id, name) in the order the portal lists them."""
    out = []
    for m in re.finditer(r"\{id:'([a-z0-9-]+)',\s*name:'((?:[^'\\]|\\.)*)'", _PORTAL):
        name = _unescape_js(m.group(2)).replace("\\'", "'")
        out.append((m.group(1), name))
    return out


def _nav_services(page: str):
    """(id, label) from one hand-copied sidebar, in order. The plain /#aisvc 'Overview' link is
    not a service and is skipped."""
    block = page[page.index('>AI Services<'):page.index('>Operate<')]
    return [(m.group(1), m.group(2))
            for m in re.finditer(r'href="/#aisvc-([a-z0-9-]+)">([^<]+)</a>', block)]


def _as_html(name: str) -> str:
    return name.replace("&", "&amp;")


# ── the array is readable at all ───────────────────────────────────────────────

def test_the_portal_defines_services_this_test_can_read():
    """If the array's shape changes, every assertion below would pass on an empty list — which
    is the failure mode where a pinning test quietly stops pinning."""
    services = _portal_services()
    assert len(services) >= 20, f"only {len(services)} services parsed out of the portal"
    assert ("estimating", "SDI Estimating Intelligence") in services
    assert ("technical-design", "SDI Technical Design Intelligence") in services


@pytest.mark.parametrize("page_name", sorted(_COPIES))
def test_the_sidebar_lists_every_service_the_portal_has(page_name):
    """A missing entry is the expensive one: SDI Technical Design Intelligence was absent from
    both copies, so half the programme was unreachable from either page."""
    portal_ids = [i for i, _ in _portal_services()]
    nav_ids = [i for i, _ in _nav_services(_COPIES[page_name])]
    missing = [i for i in portal_ids if i not in nav_ids]
    assert not missing, f"{page_name} has no sidebar entry for: {', '.join(missing)}"


@pytest.mark.parametrize("page_name", sorted(_COPIES))
def test_no_sidebar_entry_points_at_a_service_that_does_not_exist(page_name):
    """A dead link is worse than a missing one — the portal resolves #aisvc-<id> by looking the
    id up in SERVICES, so an unknown id silently does nothing at all."""
    portal_ids = {i for i, _ in _portal_services()}
    strays = [i for i, _ in _nav_services(_COPIES[page_name]) if i not in portal_ids]
    assert not strays, f"{page_name} links to services the portal does not define: {strays}"


@pytest.mark.parametrize("page_name", sorted(_COPIES))
def test_every_service_is_called_what_the_portal_calls_it(page_name):
    """THE ASSERTION THIS FILE EXISTS FOR."""
    portal = {i: n for i, n in _portal_services()}
    wrong = [(i, label, portal[i])
             for i, label in _nav_services(_COPIES[page_name])
             if i in portal and label != _as_html(portal[i])]
    assert not wrong, "\n".join(
        f"{page_name}: #{i} is called {label!r} here and {want!r} in the portal"
        for i, label, want in wrong)


@pytest.mark.parametrize("page_name", sorted(_COPIES))
def test_the_order_matches_the_portal(page_name):
    """Estimating first, Technical Design second — the two workstreams, in the order the
    programme presents them. A sidebar in a different order reads as a different list."""
    portal_ids = [i for i, _ in _portal_services()]
    nav_ids = [i for i, _ in _nav_services(_COPIES[page_name])]
    assert nav_ids == portal_ids, (
        f"{page_name} lists the services in a different order from the portal")


# ── the page's own name for itself ─────────────────────────────────────────────

@pytest.mark.parametrize("page_name", sorted(_COPIES))
def test_the_operate_link_agrees_with_the_service_it_opens(page_name):
    """The Operate group links to /estimating, which IS the estimating service. It said
    "Estimating Intelligence" while the service it opens is "SDI Estimating Intelligence"."""
    page = _COPIES[page_name]
    block = page[page.index('>Operate<'):page.index('>Govern<')]
    m = re.search(r'href="/estimating">([^<]+)</a>', block)
    assert m, f"{page_name} has no Operate link to /estimating"
    assert m.group(1) == "SDI Estimating Intelligence", (
        f"{page_name} calls it {m.group(1)!r} in Operate")


@pytest.mark.parametrize("page_name", sorted(_COPIES))
def test_exactly_one_entry_is_marked_as_the_page_you_are_on(page_name):
    """is-here is what tells you where you are. Two of them, or none, and the sidebar stops
    answering the question it exists to answer."""
    assert _COPIES[page_name].count("sdinav-item is-here") == 1
