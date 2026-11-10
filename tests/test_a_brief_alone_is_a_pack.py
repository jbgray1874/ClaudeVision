"""A brief alone is a pack (D-401).

6 Oct 2026: an internal site wants to post a typed brief to the estimating service and show
the estimators the costing workbook that comes back; the same thing as an app in the portal's
/app section. The LLM-only method already read a brief filed beside a render (D-360); every
stage refused a brief with nothing beside it — staging wanted drawings, main.py found no
files, the concept read had no page to render. So the brief is staged as its own page and
carried through unchanged, the model is given the words and told there are no images, the
run records which site asked, and the finished files are fetched by run id and name, never by
a path the caller typed.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
os.environ.setdefault("SDI_OFFLINE", "1")


# ── the concept read: words, and told there are no images ────────────────────────────────

def test_the_model_is_told_there_are_no_images_and_given_the_brief():
    import concept_scan as cs
    text = cs.concept_prompt_text([], "20 off half-A4 ticket holders in 1.2 mm steel")
    assert text.startswith(cs._TEXT_ONLY_PREAMBLE.strip()[:40])
    assert "20 off half-A4 ticket holders" in text
    with_image = cs.concept_prompt_text([b"png"], "a brief")
    assert not with_image.startswith(cs._TEXT_ONLY_PREAMBLE.strip()[:40])
    assert "1 image(s)" in with_image


def test_the_briefs_own_page_is_never_shown_to_the_model(tmp_path, monkeypatch):
    import concept_scan as cs
    monkeypatch.setattr(cs, "_cache_dir", lambda: tmp_path)
    assert cs.is_brief_page(r"C:\ClaudeVision\output\render_pdfs\ab12cd34-ENQUIRY_BRIEF.pdf")
    assert cs.is_brief_page("/stage/M&S/0359962/ENQUIRY_BRIEF.png")
    assert not cs.is_brief_page("9598-02-GA.pdf")
    # no pages and no brief is still a refusal; a brief alone reaches the model (which is
    # offline here, and says so — meaning the page gate was passed)
    with pytest.raises(cs.ConceptUnavailable, match="no pages"):
        cs.read_concept([], brief="")
    with pytest.raises(cs.ConceptUnavailable, match="SDI_OFFLINE"):
        cs.read_concept(["/x/ab12-ENQUIRY_BRIEF.pdf"], brief="a brief", refresh=True)


# ── staging: the brief becomes its own page ──────────────────────────────────────────────

@pytest.fixture()
def staging(tmp_path, monkeypatch):
    stub = types.ModuleType("config")
    stub.STAGING_ROOT = str(tmp_path / "SDIIntelligenceAISheet")
    monkeypatch.setitem(sys.modules, "config", stub)
    spec = importlib.util.spec_from_file_location(
        "staging", ROOT / "sdi-intelligence-backend" / "staging.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_brief_with_no_drawings_is_staged_as_a_page(staging):
    res = staging.stage_brief_only(client="M&S", drawing="0359962",
                                   brief="20 off half-A4 landscape ticket holders, 1.2 mm steel")
    folder = Path(res["folder"])
    assert sorted(p.name for p in folder.iterdir()) == ["ENQUIRY_BRIEF.png"]
    assert (folder / "ENQUIRY_BRIEF.png").stat().st_size > 1000
    assert res["copied_count"] == 1 and res["brief_only"] is True and res["skipped"] == []
    # a second staging replaces the first, as stage() does
    res2 = staging.stage_brief_only(client="M&S", drawing="0359962", brief="a different brief")
    assert res2["replaced_count"] == 1
    with pytest.raises(staging.StagingError):
        staging.stage_brief_only(client="M&S", drawing="0359962", brief="   ")


# ── the service: a brief queues a run, a site's key names it, the files come by run id ───

@pytest.fixture()
def er(monkeypatch, tmp_path):
    import estimate_routes
    estimate_routes._RUNS.clear()
    estimate_routes._RUNNERS.clear()
    monkeypatch.setattr(estimate_routes, "_other_local_services", lambda port: [])
    monkeypatch.setattr(estimate_routes.staging, "staging_root", lambda: tmp_path / "stage")
    monkeypatch.setattr(estimate_routes, "_within_a_root", lambda p: Path(p))
    monkeypatch.setattr(estimate_routes, "OUTPUT_ROOT", tmp_path / "out")
    monkeypatch.setattr(estimate_routes.config, "API_KEY", "portal-key", raising=False)
    monkeypatch.setattr(estimate_routes.config, "PARTNER_KEYS", {"briefsite": "site-key"},
                        raising=False)
    estimate_routes._RUNNERS["LAPTOP-abc"] = estimate_routes.Runner(runner_id="LAPTOP-abc",
                                                                    hostname="LAPTOP")
    return estimate_routes


def test_a_sites_key_opens_the_estimating_endpoints_and_names_the_site(er):
    from fastapi import HTTPException
    assert er._check_key("portal-key") == ""
    assert er._check_key("site-key") == "briefsite"
    with pytest.raises(HTTPException) as exc:
        er._check_key("wrong")
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException):
        er._check_key(None)


def test_a_brief_with_no_drawings_queues_an_llm_only_run(er):
    out = er.start_from_brief(er.BriefRequest(
        client="M&S", reference="0359962", units=20, quantity_breaks=[50, 100],
        brief="20 off half-A4 landscape ticket holders in 1.2 mm mild steel, RAL 7021"),
        x_sdi_key="site-key")
    assert out["enquiry_brief"] == "filed"
    run = er._RUNS[out["run_id"]]
    assert run.llm_only is True and run.requested_by == "briefsite"
    assert run.quantity_breaks == [50, 100] and run.units == 20
    folder = Path(run.job_folder)
    # the brief's page, the brief, and (10 Nov 2026) the marker that has the run say its stage
    assert sorted(p.name for p in folder.iterdir()) == ["ENQUIRY_BRIEF.png", "ENQUIRY_BRIEF.txt",
                                                         "PARTNER_API_RUN.json"]
    assert "1.2 mm mild steel" in (folder / "ENQUIRY_BRIEF.txt").read_text(encoding="utf-8")
    assert any("BRIEF ONLY" in line for line in run.log)
    assert any("briefsite site" in line for line in run.log)
    assert run.as_json()["requested_by"] == "briefsite"


def test_no_drawings_and_no_brief_is_still_refused(er):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        er.start(er.EstimateRequest(client="M&S", drawing_number="0359962", units=1,
                                    method="llm"), x_sdi_key="portal-key")
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc2:
        er.start_from_brief(er.BriefRequest(client="M&S", reference="0359962", units=1,
                                            brief="  "), x_sdi_key="portal-key")
    assert exc2.value.status_code == 400
    # an engine run cannot be started from a brief alone: the drawing readers need drawings
    with pytest.raises(HTTPException) as exc3:
        er.start(er.EstimateRequest(client="M&S", drawing_number="0359962", units=1,
                                    method="engine", enquiry_brief="a brief"),
                 x_sdi_key="portal-key")
    assert exc3.value.status_code == 400


def test_a_finished_runs_files_are_fetched_by_run_id_and_name_only(er, tmp_path):
    from fastapi import HTTPException
    book = tmp_path / "0359962_20261006_1407.xlsx"
    book.write_bytes(b"PK\x03\x04 a workbook")
    run = er.Run(run_id="r9", client="M&S", drawing_number="0359962", units=20,
                 job_folder="J", output_path="O", requested_by="briefsite")
    run.status = "running"
    run.deliverables = [{"name": book.name, "path": str(book)}]
    er._RUNS["r9"] = run
    with pytest.raises(HTTPException) as exc:
        er.deliverable("r9", book.name, x_sdi_key="site-key")
    assert exc.value.status_code == 409                      # not finished yet
    run.status = "done"
    resp = er.deliverable("r9", book.name, x_sdi_key="site-key")
    assert Path(resp.path) == book
    for bad in ("other.xlsx", "..\\secrets.env", str(book)):
        with pytest.raises(HTTPException) as exc2:
            er.deliverable("r9", bad, x_sdi_key="site-key")
        assert exc2.value.status_code == 404
    with pytest.raises(HTTPException) as exc3:
        er.deliverable("nope", book.name, x_sdi_key="site-key")
    assert exc3.value.status_code == 404


# ── the app in the portal, and the note for the other site ───────────────────────────────

def test_the_app_portal_lists_brief_to_book_with_its_page():
    import json
    cat = json.loads((ROOT / "sdi-intelligence-backend" / "services.json").read_text(encoding="utf-8"))
    entry = next(s for s in cat["services"] if s["id"] == "client-brief-lite")
    assert entry["app_url"] == "brief-estimate.html"
    page = ROOT / "sdi-intelligence-backend" / "appportal" / "brief-estimate.html"
    assert page.is_file()
    html = page.read_text(encoding="utf-8")
    assert "/brief'" in html and "/deliverables/" in html
    assert "provisional" in html.lower()
    assert (ROOT / "docs" / "Brief_to_Book_API.md").is_file()


def test_an_unreleased_quotation_is_never_handed_to_a_site(er, tmp_path, monkeypatch):
    from fastapi import HTTPException
    quote = tmp_path / "0359962_quote.html"
    quote.write_text("<html>quotation</html>", encoding="utf-8")
    run = er.Run(run_id="r10", client="M&S", drawing_number="0359962", units=20,
                 job_folder="J", output_path="O", requested_by="briefsite")
    run.status = "done"
    run.deliverables = [{"name": quote.name, "path": str(quote)}]
    er._RUNS["r10"] = run
    monkeypatch.setattr(er.quote_release, "looks_like_a_quote", lambda p: True)
    monkeypatch.setattr(er.quote_release, "may_go_to_a_customer", lambda p: False)
    with pytest.raises(HTTPException) as exc:
        er.deliverable("r10", quote.name, x_sdi_key="site-key")
    assert exc.value.status_code == 403
    monkeypatch.setattr(er.quote_release, "may_go_to_a_customer", lambda p: True)
    assert Path(er.deliverable("r10", quote.name, x_sdi_key="site-key").path) == quote


# ── 10 Nov 2026: Brief to Book made ready for its first live run, and for SDI Live's key ─────

def _site_run(er, run_id, site, status="done", tmp_path=None):
    run = er.Run(run_id=run_id, client="M&S", drawing_number="0359962", units=20,
                 job_folder="J", output_path="O", requested_by=site)
    run.status = status
    if tmp_path is not None:
        book = tmp_path / f"{run_id}.xlsx"
        book.write_bytes(b"PK\x03\x04 a workbook")
        run.deliverables = [{"name": book.name, "path": str(book)}]
    er._RUNS[run_id] = run
    return run


def test_a_site_sees_only_its_own_runs(er, tmp_path, monkeypatch):
    """A site's key listed every run and fetched any run's book: another site's, or the portal's."""
    from fastapi import HTTPException
    monkeypatch.setattr(er.config, "PARTNER_KEYS", {"briefsite": "site-key", "other": "other-key"},
                        raising=False)
    _site_run(er, "aaaaaaaaaaaa", "briefsite", tmp_path=tmp_path)
    _site_run(er, "bbbbbbbbbbbb", "other", tmp_path=tmp_path)
    _site_run(er, "cccccccccccc", "", tmp_path=tmp_path)                 # the portal's own run
    assert [r["run_id"] for r in er.recent(x_sdi_key="site-key")["runs"]] == ["aaaaaaaaaaaa"]
    assert er.status("aaaaaaaaaaaa", x_sdi_key="site-key")["run_id"] == "aaaaaaaaaaaa"
    for rid in ("bbbbbbbbbbbb", "cccccccccccc"):
        for call in (lambda: er.status(rid, x_sdi_key="site-key"),
                     lambda: er.run_summary(rid, x_sdi_key="site-key"),
                     lambda: er.deliverable(rid, f"{rid}.xlsx", x_sdi_key="site-key")):
            with pytest.raises(HTTPException) as exc:
                call()
            assert exc.value.status_code == 404
    # the portal still sees every run
    assert len(er.recent(x_sdi_key="portal-key")["runs"]) == 3
    assert er.status("bbbbbbbbbbbb", x_sdi_key="portal-key")["run_id"] == "bbbbbbbbbbbb"


def test_a_sites_key_does_nothing_but_brief_runs(er):
    """Release, override, batch, the self-running switch, who quotes go to: not for a site."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(er.router)
    c = TestClient(app)
    site, portal = {"X-SDI-Key": "site-key"}, {"X-SDI-Key": "portal-key"}
    for method, path in (("GET", "/api/estimate/runners"), ("GET", "/api/estimate/recipients"),
                         ("GET", "/api/estimate/self-running"), ("POST", "/api/estimate/release"),
                         ("POST", "/api/estimate/self-running/start"), ("POST", "/api/estimate"),
                         ("POST", "/api/estimate/batch"), ("POST", "/api/estimate/aaaaaaaaaaaa/abandon"),
                         ("POST", "/api/estimate/aaaaaaaaaaaa/email")):
        r = c.request(method, path, headers=site, json={})
        assert r.status_code == 403, (method, path, r.status_code)
        assert "partner site" in r.json()["detail"]
    assert c.get("/api/estimate", headers=site).status_code == 200
    assert c.get("/api/estimate/aaaaaaaaaaaa", headers=site).status_code == 404   # none yet
    assert c.get("/api/estimate/runners", headers=portal).status_code == 200      # portal untouched
    r = c.post("/api/estimate/brief", headers=site, json={
        "client": "M&S", "reference": "0359962", "units": 1,
        "brief": "A floor-standing gondola end, 1.2 mm mild steel, powder coated black."})
    assert r.status_code == 200, r.text


def test_a_brief_too_long_or_too_short_is_said_not_cut(er):
    from fastapi import HTTPException
    for brief, says in (("x" * 4001, "4,001 characters"), ("a ticket holder", "too short")):
        with pytest.raises(HTTPException) as exc:
            er.start_from_brief(er.BriefRequest(client="M&S", reference="0359962", units=1,
                                                brief=brief), x_sdi_key="site-key")
        assert exc.value.status_code == 400 and says in exc.value.detail
    assert not er._RUNS                                                   # nothing was queued


def test_a_brief_carries_its_delivery_postcode(er):
    out = er.start_from_brief(er.BriefRequest(
        client="M&S", reference="0359962", units=20, delivery_postcode=" le19  1wp ",
        brief="20 off half-A4 landscape ticket holders in 1.2 mm mild steel, RAL 7021"),
        x_sdi_key="site-key")
    folder = Path(er._RUNS[out["run_id"]].job_folder)
    import json
    assert json.loads((folder / "DELIVERY_DECLARED.json").read_text(encoding="utf-8"))["postcode"] == "LE19 1WP"


def test_the_page_asks_for_the_facts_and_shows_the_figure():
    html = (ROOT / "sdi-intelligence-backend" / "appportal" / "brief-estimate.html").read_text(encoding="utf-8")
    for box in ('id="h"', 'id="w"', 'id="d"', 'id="material"', 'id="finish"', 'id="print"', 'id="fixings"',
                'id="lighting"', 'id="load"', 'id="packing"', 'id="postcode"'):
        assert box in html, box
    assert "delivery_postcode:" in html                       # the postcode goes as its own field
    assert "of '+MAX.toLocaleString()+' characters" in html   # the length is shown, never cut
    assert "fetch('../api/me'" in html                        # the book is e-mailed to whoever ran it
    assert "'/summary'" in html and "unit_cost_gbp" in html   # the figure, and the stage while it runs
    assert "?run='" in html                                   # a reload finds the run again
    assert "Not a past job's" in html                         # the run clears the reference's folder
