"""The e-mail's walkthrough button opens a page that answers from the estimate (D-610).

31 Oct 2026, James: "The voice also should be a button on the e-mail that starts the portal in
a new area where it lists the commentary also and it also allows an area where questions on
the estimate can be asked ... for the print out on the screen for the multi-unit runs, if we
can show the price for each unit number we're pricing, instead of just stating the price for
one unit."

  * the runner reports the unit cost at every quantity; the service keeps it; the card and the
    run panel show "1 off £538.06 · 5 off £401.20 · 10 off £377.00";
  * a finished run with a walkthrough gets a record on disk under a random token, so the
    e-mail's link survives a restart of the service; the e-mail carries a button to it;
  * the page plays the walkthrough, shows its words, the prices and the run's own files, and
    answers questions from the estimate's own record, never a path a caller typed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools" / "runner"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimate_qa  # noqa: E402
import live_enquiry_runner as L  # noqa: E402
import sdi_estimate_runner as runner  # noqa: E402
from test_estimate_queue import _check_in, _request, api  # noqa: E402,F401

PAGE = (BACKEND / "sdi-walkthrough.html").read_text(encoding="utf-8")
ESTIMATING = (BACKEND / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")
APP = (BACKEND / "app.py").read_text(encoding="utf-8")


# ── the price at every quantity ────────────────────────────────────────────────────────

def test_the_runner_reads_the_unit_cost_at_every_quantity():
    summary = {"quantity_sweep": {"rows": [
        {"quantity": 10, "unit": 377.0}, {"quantity": 1, "unit": 538.064},
        {"quantity": 5, "unit": "401.2"}, {"quantity": "x", "unit": 1}, {"quantity": 50}]}}
    assert runner.quantity_prices_from(summary) == [
        {"quantity": 1, "unit_gbp": 538.06}, {"quantity": 5, "unit_gbp": 401.2},
        {"quantity": 10, "unit_gbp": 377.0}]
    assert runner.quantity_prices_from({"quantity_sweep": {"rows": [
        {"quantity": 1, "unit": 538.06}]}}) == [], "one quantity is the unit cost already"
    assert runner.quantity_prices_from({}) == []


def test_the_runner_sends_them_with_the_completion(tmp_path):
    rec = tmp_path / "12678-01-GA.json"
    rec.write_text(json.dumps({"final_estimate": {"totals": {"unit_gbp": 538.06}},
                               "quantity_sweep": {"rows": [{"quantity": 1, "unit": 538.06},
                                                           {"quantity": 5, "unit": 401.2}]}}))
    sent = {}

    class _Req:
        def post(self, url, json=None, **kw):
            sent.update(json or {})

            class _R:
                status_code = 200

                @staticmethod
                def raise_for_status():
                    return None
            return _R()

    runner._finish(_Req(), "http://x/api/estimate", {}, "r1", "rnr", "done", "", [],
                   deliverables=[{"name": rec.name, "path": str(rec)}])
    assert sent["unit_cost_gbp"] == 538.06
    assert sent["quantity_prices"] == [{"quantity": 1, "unit_gbp": 538.06},
                                       {"quantity": 5, "unit_gbp": 401.2}]


def test_the_page_shows_every_quantity_on_the_card_and_the_run_panel():
    fn = ESTIMATING[ESTIMATING.index("function pricesText("):]
    fn = fn[:fn.index("async function refreshSelf")]
    assert 'p.quantity + " off " + money(p.unit_gbp)' in fn and '.join(" · ")' in fn
    card = ESTIMATING[ESTIMATING.index("recent.map(r =>"):]
    assert "pricesText(r.quantity_prices, r.unit_gbp" in card[:600]
    assert "r.walkthrough_url" in card[:900]
    done = ESTIMATING[ESTIMATING.index('setStatus("ok","Complete");'):]
    assert 'pricesText(s.quantity_prices, s.engine_price_gbp, s.units)' in done[:600]
    assert "s.walkthrough_url" in done[:800]


def test_the_watcher_carries_them_to_the_card():
    import self_running as sr
    attempt = L._attempt_from({"status": "done", "engine_price_gbp": 538.06,
                               "quantity_prices": [{"quantity": 1, "unit_gbp": 538.06},
                                                   {"quantity": 5, "unit_gbp": 401.2}],
                               "walkthrough_url": "http://PC:8071/estimating/walkthrough/t"},
                              {"status": "running", "queued_at": "2026-10-31T19:16:33"})
    ledger = {"jobs": {"k": {"customer": "M&S", "drawing": "12678-01-GA",
                             "attempts": [attempt]}}}
    row = sr.recent_runs(ledger)[0]
    assert row["quantity_prices"][1] == {"quantity": 5, "unit_gbp": 401.2}
    assert row["walkthrough_url"].endswith("/estimating/walkthrough/t")


# ── the service: a record on disk, a link in the e-mail ────────────────────────────────

@pytest.fixture()
def service(api, tmp_path, monkeypatch):
    er, root = api
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SDI_PORTAL_URL", "http://DESKTOP-GFAAP80:8071")
    out = tmp_path / "out"
    out.mkdir()
    files = {}
    for name, body in {"12678-01-GA_20261031.xlsx": b"PK", "12678-01-GA_report.html": b"<p>r",
                       "12678-01-GA_walkthrough.wav": b"RIFF" + b"\0" * 64,
                       "12678-01-GA_walkthrough.txt": "SDI Intelligence walkthrough.".encode(),
                       "12678-01-GA_quote.html": b"<p>quote</p>",
                       "12678-01-GA.json": json.dumps({"final_estimate": {"totals": {
                           "unit_gbp": 538.06}}}).encode()}.items():
        (out / name).write_bytes(body)
        files[name] = str(out / name)
    return er, root, files


def _finish_a_run(er, root, files, prices=None):
    _check_in(er)
    run_id = er.start(_request(er, root))["run_id"]
    _check_in(er)
    er.complete(run_id, er.CompleteRequest(
        runner_id="rnr-1", status="done", unit_cost_gbp=538.06,
        quantity_prices=prices or [{"quantity": 1, "unit_gbp": 538.06},
                                   {"quantity": 5, "unit_gbp": 401.2}],
        deliverables=[{"name": n, "path": p} for n, p in files.items()]))
    return er._RUNS[run_id]


def test_a_finished_run_keeps_its_prices_and_gets_a_walkthrough_that_outlives_a_restart(service):
    er, root, files = service
    run = _finish_a_run(er, root, files)
    snap = run.as_json()
    assert snap["quantity_prices"] == [{"quantity": 1, "unit_gbp": 538.06},
                                       {"quantity": 5, "unit_gbp": 401.2}]
    assert snap["walkthrough_url"] == ("http://DESKTOP-GFAAP80:8071/estimating/walkthrough/"
                                       + run.walkthrough)
    er._RUNS.clear()                                          # the service restarts
    view = er.walkthrough_view(run.walkthrough)
    assert view["drawing_number"] == run.drawing_number and view["units"] == run.units
    assert view["audio"] == "12678-01-GA_walkthrough.wav"
    assert view["commentary"] == "SDI Intelligence walkthrough."
    assert view["quantity_prices"][1]["unit_gbp"] == 401.2
    assert not any("\\" in str(v) or "/out/" in str(v) for v in view.values()), "no paths"


def test_the_page_serves_only_the_runs_own_files_and_holds_the_quote(service):
    er, root, files = service
    token = _finish_a_run(er, root, files).walkthrough
    got = er.walkthrough_file(token, "12678-01-GA_walkthrough.wav")
    assert Path(got.path).name == "12678-01-GA_walkthrough.wav"
    for bad in ("..\\secret.txt", "../../etc/passwd", "other.xlsx"):
        with pytest.raises(er.HTTPException) as no:
            er.walkthrough_file(token, bad)
        assert no.value.status_code == 404
    with pytest.raises(er.HTTPException) as held:
        er.walkthrough_file(token, "12678-01-GA_quote.html")
    assert held.value.status_code == 403


def test_an_unknown_or_malformed_token_is_not_found(service):
    er, _, _ = service
    for token in ("nope", "A" * 24, "../../x"):
        with pytest.raises(er.HTTPException) as no:
            er.walkthrough_view(token)
        assert no.value.status_code == 404


def test_a_run_without_a_walkthrough_gets_no_page(service):
    er, root, files = service
    plain = {n: p for n, p in files.items() if "_walkthrough" not in n}
    run = _finish_a_run(er, root, plain)
    assert run.walkthrough == "" and run.as_json()["walkthrough_url"] == ""


def test_the_email_carries_the_button(service, monkeypatch):
    er, root, files = service
    run = _finish_a_run(er, root, files)
    sent = {}
    monkeypatch.setattr(er.estimate_email, "send", lambda to, subject, html, text, paths: (
        sent.update(html=html, text=text), {"sent": True})[1])
    er._email_finished_run(run.as_json(), run.deliverables, ["james.gray@wearesdi.com"],
                           False, True)
    url = run.as_json()["walkthrough_url"]
    assert f'href="{url}"' in sent["html"] and "Listen to the walkthrough" in sent["html"]
    assert sent["text"].startswith(f"Listen to the walkthrough and ask about this estimate: {url}")


def test_the_button_goes_inside_the_notes_own_frame():
    import importlib
    sys.path.insert(0, str(BACKEND))
    ew = importlib.import_module("estimate_walkthrough")
    note = ew.email_button({"html": '<div style="x"><p>Here is the estimate</p></div>',
                            "text": "Here is the estimate"}, "http://PC:8071/estimating/walkthrough/t")
    assert note["html"].startswith('<div style="x"><p style="margin:14px 0 4px"><a href=')
    assert note["html"].index("Listen to the walkthrough") < note["html"].index("Here is")


# ── the question box ───────────────────────────────────────────────────────────────────

def test_a_question_is_answered_from_the_runs_own_record(service, monkeypatch):
    er, root, files = service
    token = _finish_a_run(er, root, files).walkthrough
    monkeypatch.setattr(er, "_ENGINE_PYTHON", sys.executable)
    seen = {}

    def fake_run(cmd, input=None, **kw):
        seen.update(cmd=cmd, payload=json.loads(input))
        return subprocess.CompletedProcess(cmd, 0, stdout='noise\n{"status": "answered", '
                                                          '"answer": "Labour is 200 pounds."}\n',
                                           stderr="")

    monkeypatch.setattr(er.subprocess, "run", fake_run)
    got = er.walkthrough_ask(token, er.AskRequest(question="  What is the labour?  "))
    assert got == {"status": "answered", "answer": "Labour is 200 pounds."}
    assert seen["cmd"][1].endswith("estimate_qa.py")
    assert seen["payload"]["question"] == "What is the labour?"
    assert [Path(p).name for p in seen["payload"]["records"]] == ["12678-01-GA.json"]
    assert seen["payload"]["commentary"] == "SDI Intelligence walkthrough."


def test_an_empty_question_or_no_engine_says_so(service, monkeypatch):
    er, root, files = service
    token = _finish_a_run(er, root, files).walkthrough
    with pytest.raises(er.HTTPException) as empty:
        er.walkthrough_ask(token, er.AskRequest(question="  "))
    assert empty.value.status_code == 400
    monkeypatch.setattr(er, "_ENGINE_PYTHON", str(Path("/no/such/python")))
    got = er.walkthrough_ask(token, er.AskRequest(question="Why?"))
    assert got["status"] == "unavailable" and "machine that runs estimates" in got["answer"]


def test_the_engine_answers_only_from_the_estimate(tmp_path):
    rec = tmp_path / "r.json"
    rec.write_text(json.dumps({
        "drawing_number": "12678-01-GA", "customer": "M&S", "requested_order_quantity": 1,
        "final_estimate": {"totals": {"unit_gbp": 538.06, "material_gbp": 300,
                                      "labour_gbp": 200},
                           "labour_rows": [{"operation": "Weld (CO2)", "total_value_gbp": 90},
                                           {"operation": "Laser", "total_value_gbp": 20}]},
        "review_flags": ["1 line carries no price"]}))
    asked = {}

    def fake_ask(prompt, **kw):
        asked.update(prompt=prompt, kw=kw)
        return {"answer": "The largest labour line is Weld (CO2) at £90."}

    got = estimate_qa.answer({"question": "What drives labour?", "records": [str(rec)],
                              "commentary": "SDI walkthrough.",
                              "quantity_prices": [{"quantity": 1, "unit_gbp": 538.06},
                                                  {"quantity": 5, "unit_gbp": 401.2}]},
                             ask=fake_ask)
    assert got == {"status": "answered", "answer": "The largest labour line is Weld (CO2) at £90."}
    p = asked["prompt"]
    assert "QUESTION: What drives labour?" in p and "Never invent or recalculate a price" in p
    assert '"unit_gbp": 401.2' in p and '"line": "Weld (CO2)"' in p and "SDI walkthrough." in p
    assert "never describe it as a customer quotation" in p
    assert asked["kw"]["temperature"] == 0.0


def test_no_answer_from_the_model_is_said_never_invented(tmp_path):
    got = estimate_qa.answer({"question": "Why?", "records": []}, ask=lambda p, **k: None)
    assert got["status"] == "unavailable" and "workbook and report hold every figure" in got["answer"]
    assert estimate_qa.answer({"question": ""}, ask=lambda p, **k: {"answer": "x"})["status"] == \
        "unavailable"


# ── the page ───────────────────────────────────────────────────────────────────────────

def test_the_page_plays_lists_prices_and_asks_through_its_own_token():
    assert 'const API = "/api/estimate/walkthrough/" + encodeURIComponent(TOKEN);' in PAGE
    assert '<audio id="audio" controls' in PAGE and "fileUrl(w.audio)" in PAGE
    assert 'id="prices"' in PAGE and "Price at each quantity" in PAGE
    assert 'id="words"' in PAGE and "textContent = w.commentary" in PAGE
    assert 'api(API + "/ask", {method: "POST"' in PAGE and 'id="question"' in PAGE
    assert "nothing on this page is a" in PAGE.replace("\n", " ").replace("  ", " ")
    assert "innerHTML = '<span class=\"err\">' + esc(" in PAGE, "server words are escaped"


def test_the_portal_serves_the_page_signed_in_like_the_estimating_page():
    route = APP[APP.index('@app.get("/estimating/walkthrough/{token}")'):]
    route = route[:route.index("# THE TECHNICAL DESIGN WORKFLOW MAPS.")]
    assert "auth.current_user(request) is None" in route and "login_redirect" in route
    assert "sdi-walkthrough.html" in APP and "_PAGE_HEADERS" in route
