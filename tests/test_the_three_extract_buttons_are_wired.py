"""Three buttons, one builder, one endpoint — and the wiring between them actually meeting.

A button that posts to a path no router serves fails at the only moment it matters, in front of
somebody who wanted an answer. The page's router prefix is /api/estimate, and the first version
of this posted to /api/extract — which would have 404'd on every press. That is the class of
defect these tests exist for: each end of the wire is fine and the two do not meet.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PAGE = ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html"
ROUTES = ROOT / "sdi-intelligence-backend" / "estimate_routes.py"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _routes() -> str:
    return ROUTES.read_text(encoding="utf-8")


# ── the three buttons exist, where they were asked for ────────────────────────────────


@pytest.mark.parametrize("element_id,label", [
    ("exBoms", "SDI Estimating Intel BOMs Extract"),
    ("exRoutes", "SDI Estimating Intel Routes Extract"),
    ("exBoth", "SDI Intel BOMs and Routes"),
])
def test_each_button_is_on_the_page_with_its_name(element_id, label):
    page = _page()
    assert f'id="{element_id}"' in page
    assert label in page


def test_the_buttons_sit_below_the_drawings_panel():
    """Asked for in the dead space below Drawings, which is also where they belong: they read
    that panel."""
    page = _page()
    drawings_at = page.index("<h2>Drawings</h2>")
    extract_at = page.index('id="extractCard"')
    assert drawings_at < extract_at


def test_every_button_starts_disabled():
    """Nothing is pressable before there is a pack to read."""
    page = _page()
    for element_id in ("exBoms", "exRoutes", "exBoth"):
        block = page[page.index(f'id="{element_id}"'):][:200]
        assert "disabled" in block, element_id


# ── the wire meets at both ends ───────────────────────────────────────────────────────


def test_the_page_posts_to_a_path_the_router_actually_serves():
    """THE DEFECT THIS CATCHES. The router is mounted at /api/estimate, so a handler declared
    @router.post("/extract") serves /api/estimate/extract. The first version of the page posted
    to /api/extract and would have 404'd on every press."""
    page, routes = _page(), _routes()
    posted = re.findall(r'api\("(/api/[^"]+)"', page)
    assert "/api/estimate/extract" in posted, f"the page posts to {posted}"
    assert '@router.post("/extract")' in routes
    assert 'APIRouter(prefix="/api/estimate"' in routes


def test_the_three_kinds_the_page_sends_are_the_three_the_endpoint_accepts():
    """A fourth kind on either side is a button that refuses itself."""
    page, routes = _page(), _routes()
    sent = set(re.findall(r'\["ex\w+","(\w+)"', page))
    assert sent == {"boms", "routes", "both"}, sent
    accepted = re.search(r'if kind not in \(([^)]+)\)', routes).group(1)
    assert {k.strip().strip('"') for k in accepted.split(",")} == sent


def test_the_builder_accepts_exactly_those_three_kinds():
    import bom_and_route_extract as bre
    for kind in ("boms", "routes", "both"):
        tables = bre.build_tables({"job_number": "x"}, kind)
        assert tables is not None, kind


# ── what the page does with the answer ────────────────────────────────────────────────


def test_a_missing_endpoint_is_reported_rather_than_going_quiet():
    """A button that goes silent on a 404 teaches people it is broken and they stop pressing it.
    One that says the service has not been updated yet sends them to the right person."""
    page = _page()
    assert "does not have the /api/extract endpoint yet" in page
    assert "EXTRACT REFUSED" in page


def test_the_output_is_shown_on_screen_and_linked():
    """Asked for: output in the estimating folder AND on screen, the same way a run reports."""
    page = _page()
    assert 'id="exOut"' in page
    assert "saved " in page and "file(s):" in page


def test_the_page_never_claims_a_price():
    page = _page()
    block = page[page.index('id="extractCard"'):page.index('id="exOut"')]
    assert "Prices nothing" in block


# ── the endpoint's refusals ───────────────────────────────────────────────────────────


def test_no_record_is_an_explained_404_not_empty_sheets():
    """Returning blank tables would read as "this pack contains nothing", which is the one answer
    this feature must never give by accident."""
    routes = _routes()
    assert "nothing to extract yet" in routes
    assert "press SDI (UK) Intelligence Estimator" in routes, "and names what produces it"


def test_an_empty_route_list_is_explained_as_a_fact_about_the_record():
    routes = _routes()
    assert "fact about the record, not about the pack" in routes
    assert "money_provenance" in routes, "and points at where the reason is recorded"


def test_the_endpoint_needs_no_client_or_quantity():
    """Needing a client before somebody can see what is in a pack is the wrong way round."""
    routes = _routes()
    model = routes[routes.index("class ExtractRequest"):routes.index("def _extract_job_label")]
    for required_in_an_estimate in ("units", "quantity_breaks"):
        assert required_in_an_estimate not in model
    assert "client: Optional[str] = None" in model


def test_the_buttons_are_gated_on_drawings_and_a_runner_only():
    page = _page()
    block = page[page.index("const exMissing"):page.index("runBtn.textContent")]
    assert "at least one drawing" in block
    assert "runnersOnline" in block
    for estimate_only in ("number of units", "client", "drawing number"):
        assert estimate_only not in block, f"an extract must not require {estimate_only}"


# ── every run writes them, so the files are always there ──────────────────────────────


def test_the_run_writes_the_extracts_beside_the_audit():
    """So the endpoint is a rebuild rather than the only way to get them, and a job that has
    been estimated already has its BOMs and routes on the share."""
    source = (ROOT / "src" / "main.py").read_text(encoding="utf-8", errors="ignore")
    assert "from bom_and_route_extract import write_both as _write_extracts" in source
    assert "boms_and_routes_" in source, "and the paths are recorded on the record"


# ── the record it reads is the job's, never a test fixture ────────────────────────────


def test_the_endpoint_cannot_reach_a_replay_fixture():
    """A REVIEW CONDITION, PINNED. The extract must be taken from the job's own saved record
    under the output share — never from tests/replay, whose fixtures are deliberately older,
    reduced, and in at least one case pre-workbook. A button that silently answered from a
    frozen fixture would show an estimator last week's BOM and look entirely healthy doing it.

    Proven by reading the search roots rather than by running it, because the failure would be a
    path this code never builds: the roots are the output share and the engine root, and a
    relative path list that contains no test directory.
    """
    routes = _routes()
    block = routes[routes.index("@router.post(\"/extract\")"):]
    block = block[:block.index("return {\"ok\": True")]
    assert "for root in (config.OUTPUT_ROOT, getattr(config, \"ENGINE_ROOT\", None)):" in block, \
        "the search roots are the output share and the engine root, and nothing else"
    for never in ("tests", "replay", "fixture"):
        assert never not in block, (
            f"the extract endpoint mentions {never!r} — the record it reads must be the job's "
            f"own, produced by a run on this box")
    # and the relative paths under those roots are the three the engine actually writes
    for rel in ("Path(\"json\")", "Path(\"output\") / \"json\"", "Path(f\"{label}.json\")"):
        assert rel in block


def test_a_record_found_is_named_in_the_answer():
    """So "which record did this come from" never needs asking. The reviewer's own correction
    turned on exactly this: a probe was run against tests/replay/7332-01 and read as a failed
    freeze of the live job, because nothing on the output said which file had been opened."""
    routes = _routes()
    assert 'lines.append(f"Read from {found_at}.")' in routes
    assert '"record": found_at' in routes, "and it is in the payload, not only the console"
