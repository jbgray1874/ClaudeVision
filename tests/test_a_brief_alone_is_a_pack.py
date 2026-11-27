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
    assert sorted(p.name for p in folder.iterdir()) == ["ENQUIRY_BRIEF.png", "ENQUIRY_BRIEF.txt"]
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
                 job_folder="J", output_path="O")
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
                 job_folder="J", output_path="O")
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
