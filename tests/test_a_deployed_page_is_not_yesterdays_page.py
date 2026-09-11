"""The three documents the service serves are never cached, and the page it serves has the buttons.

WHAT HAPPENED. Three extract buttons were written into sdi-estimating-intelligence.html, committed,
and pulled onto the box. The service reads that file from disk on every request, so they were live
the moment the pull landed — no restart needed. They were still not on the page in front of the
person who had just deployed them, because none of the page routes set a cache header and the
browser applied its own heuristic: it had a copy, so it used it.

Two failures, and the second is the expensive one:

  "It is not deployed" and "your browser is showing you yesterday" look identical from the page.
  The diagnosis went to the service, the service was fine.

  A hard refresh fixes it for the person who knows to do one. Every estimator with the page open
  keeps the old one, and they have no reason to suspect the page at all.

So the routes say no-store, and these tests hold that. The second half checks the thing the cache
was hiding: that the served document really does contain the three buttons and the endpoint they
post to, because a cache header proves freshness and not content.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
APP = BACKEND / "app.py"
PAGE = BACKEND / "sdi-estimating-intelligence.html"


def _app() -> str:
    return APP.read_text(encoding="utf-8")


# ── every document route is no-store ──────────────────────────────────────────────────


@pytest.mark.parametrize("route,handler", [
    ("/", "def home()"),
    ("/estimating", "def estimating_page()"),
    ("/guide", "def estimating_guide()"),
])
def test_each_page_route_refuses_to_be_cached(route, handler):
    """Read per-handler rather than counting occurrences, so a header added to two routes and
    forgotten on the third fails here instead of on somebody's screen."""
    source = _app()
    start = source.index(handler)
    body = source[start:start + 700]
    assert "_PAGE_HEADERS" in body, (
        f"{route} serves a document with no cache header — a browser will decide for itself "
        f"how long to keep it, and after a deploy it keeps the old one")


def test_no_store_means_no_store():
    source = _app()
    block = source[source.index("_PAGE_HEADERS = "):]
    block = block[:block.index("\n\n")]
    assert "no-store" in block
    assert "must-revalidate" in block


def test_the_logo_keeps_its_cache_because_it_does_not_change():
    """A blanket no-store would be the other overreach. The brand logo is a binary that changes
    when somebody changes the brand, and re-fetching it on every page view is pure waste."""
    source = _app()
    assert 'headers={"Cache-Control": "public, max-age=300"}' in source


# ── what the cache was hiding ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("element_id", ["exBoms", "exRoutes", "exBoth"])
def test_the_served_document_carries_each_button(element_id):
    """The file the route hands out is this one — Path(__file__).with_name — so the document on
    disk IS what an estimator gets. Nothing else stands between them."""
    assert PAGE.is_file(), "the page must sit next to app.py or the route 404s"
    assert f'id="{element_id}"' in PAGE.read_text(encoding="utf-8")


def test_the_route_serves_the_file_that_holds_the_buttons():
    """Pins the link between the two halves of this test: the constant the route returns is the
    filename this test read. A renamed page would otherwise pass both halves separately."""
    source = _app()
    assert '_ESTIMATOR = Path(__file__).with_name("sdi-estimating-intelligence.html")' in source
    assert "FileResponse(str(_ESTIMATOR), headers=_PAGE_HEADERS)" in source


def test_the_version_the_service_is_running_is_on_every_response():
    """The header that answers "is the box current?" without an SSH and a git log. It already
    existed; this keeps it, because it is the one thing that distinguishes a stale service from a
    stale browser — the two failures this file is about."""
    source = _app()
    assert 'response.headers["X-SDI-Commit"] = SDI_COMMIT' in source
    assert 'expose_headers=["X-SDI-Commit"]' in source, (
        "and it is readable from the page's own fetches, not only from curl")


def test_the_page_and_the_router_agree_on_the_extract_path():
    """Held here as well as in the button-wiring test, because this file is what somebody reads
    when the buttons are on the page and do nothing."""
    page = PAGE.read_text(encoding="utf-8")
    routes = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
    posted = set(re.findall(r"['\"](/api/estimate/[a-z_]+)['\"]", page))
    assert "/api/estimate/extract" in posted, "the page posts to the extract endpoint"
    assert 'router = APIRouter(prefix="/api/estimate"' in routes
    assert '@router.post("/extract")' in routes
