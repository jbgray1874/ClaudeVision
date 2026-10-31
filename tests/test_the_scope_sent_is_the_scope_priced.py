"""The scope sent is the scope priced, and the book says whether it was (D-604).

THE HPP 01:12 RUN OF 31 OCT. The main estimator went out as Samsung / TG_Standalone, with no
enquiry brief and no reference document, after a day of agreeing Pixel Inspiration, HPP unit
Design, the Samsung guide as a reference and a customer-only brief. Why is not known: an
earlier job's values left in the boxes and a reload clearing the brief and the ticks is a
plausible explanation, not a proven one, and nothing recorded what was meant. The LLM button had
shown a receipt of what it would send since D-479; the main estimator sent whatever was on the
page without a word, and nothing between the page and the book could say what had been meant.

So, end to end: the page shows the scope before it is sent and stops a run whose brief or
references the service did not file; the service keeps the scope as submitted and hands it to
the runner; the runner hands it to the engine; and the book's first page compares what reached
the engine with what was submitted.
"""
from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
    encoding="utf-8")
ROUTES = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")

import run_provenance as rp  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
# The queue's own fixture: the routes module with a stub config and a staged drawing.
from test_estimate_queue import _check_in, _request, api  # noqa: E402,F401


def _main_button() -> str:
    return PAGE[PAGE.index("runBtn.onclick = async"):PAGE.index("let seen = 0;",
                                                                  PAGE.index("runBtn.onclick = async"))]


# ── the page ─────────────────────────────────────────────────────────────────────────────

def test_the_main_button_shows_the_scope_before_it_sends_it():
    body = _main_button()
    receipt = body.index('confirm("Main SDI estimator.')
    for field in ("CUSTOMER: ", "DRAWING NUMBER: ", "QUANTITY: ", "PRODUCT: ",
                  "REFERENCE/STANDARDS: ", "ENQUIRY BRIEF: ", "DELIVERY: "):
        assert field in body[receipt:receipt + 2000], field
    assert receipt < body.index('api("/api/estimate",{method:"POST"'), "shown before it is sent"


def test_the_main_button_asks_before_running_without_a_brief():
    body = _main_button()
    ask = body.index('confirm("No enquiry brief is typed.')
    assert ask < body.index('api("/api/estimate",{method:"POST"')


def test_the_main_button_stops_a_run_whose_brief_or_references_were_not_filed():
    body = _main_button()
    after = body[body.index("const started = await r.json();"):]
    assert 'started.enquiry_brief !== "filed"' in after
    assert "!Array.isArray(started.reference_documents)" in after
    assert after.count('/abandon", {method:"POST"}') >= 2, "each one stops the run"


# ── the service ──────────────────────────────────────────────────────────────────────────

class _Run:
    client, drawing_number, units = "Pixel Inspiration", "HPP unit Design", 1


def test_the_service_keeps_the_scope_as_submitted():
    import estimate_routes as er
    scope = er.submitted_scope(_Run(), "both", "  Customer brief text  ", "filed",
                               ["Samsung guide.pdf"])
    assert scope == {"client": "Pixel Inspiration", "drawing_number": "HPP unit Design",
                     "units": 1, "method": "both", "brief_chars": 19,
                     "brief_sha256": er.brief_fingerprint("Customer brief text"),
                     "brief_status": "filed", "reference_documents": ["Samsung guide.pdf"]}
    said = er.scope_sentence(scope)
    assert "customer Pixel Inspiration" in said and "drawing HPP unit Design" in said
    assert "brief 19 chars (filed)" in said and "reference documents: Samsung guide.pdf" in said


def test_the_service_records_it_and_hands_it_to_the_runner():
    assert "run.submitted_scope = submitted_scope(run, method, req.enquiry_brief, _brief_status," in ROUTES
    claim = ROUTES[ROUTES.index("def claim("):ROUTES.index("def _file_enquiry_brief(")]
    assert '"submitted_scope": dict(run.submitted_scope),' in claim
    assert '"submitted_scope": dict(self.submitted_scope),' in ROUTES, "and on the run's status"


def test_the_runner_hands_it_to_the_engine(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools" / "runner"))
    import sdi_estimate_runner as runner
    (tmp_path / "output" / "estimates").mkdir(parents=True)
    (tmp_path / "output" / "json").mkdir(parents=True)
    tpl = tmp_path / "Blank Estimate Sheet  WB 2026.xlsx"
    tpl.write_bytes(b"present is all the runner checks")
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(tpl))
    seen = {}

    class _Done:
        returncode = 0
        stdout = iter(())

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(runner.subprocess, "Popen",
                        lambda *a, **k: (seen.update(k.get("env") or {}), _Done())[1])

    class _Req:
        def post(self, *a, **k):
            class _R:
                @staticmethod
                def raise_for_status():
                    return None
            return _R()

    scope = {"client": "Pixel Inspiration", "brief_chars": 1970,
             "reference_documents": ["Samsung guide.pdf"]}
    job = {"run_id": "r1", "client": "Pixel Inspiration", "units": 1,
           "drawing_number": "HPP unit Design", "job_folder": str(tmp_path),
           "output_path": str(tmp_path / "share"), "submitted_scope": scope}
    claimed = {"service": "http://localhost:8071", "commit": "33e6cc0"}
    runner._execute(_Req(), "http://x/api/estimate", {}, job, tmp_path, Path("python"), "rnr",
                    claimed_from=claimed)
    assert json.loads(seen[rp.SUBMITTED_SCOPE_ENV]) == scope
    assert json.loads(seen[rp.CLAIMED_FROM_ENV]) == claimed
    # A service that sent no scope field at all is passed as null, apart from an empty one.
    seen.clear()
    del job["submitted_scope"]
    runner._execute(_Req(), "http://x/api/estimate", {}, job, tmp_path, Path("python"), "rnr")
    assert seen[rp.SUBMITTED_SCOPE_ENV] == "null"


def test_the_runner_notes_which_service_it_claimed_from_and_its_commit(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools" / "runner"))
    import sdi_estimate_runner as runner

    class _Reply:
        status_code = 200
        headers = {"X-SDI-Commit": "33e6cc0"}

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"run": {"run_id": "r1"}}

    class _Req:
        @staticmethod
        def post(*a, **k):
            return _Reply()

    job, _ = runner._ask_for_work(_Req(), "http://localhost:8071", {}, "rnr", "pid 1", "b", None)
    assert job == {"run_id": "r1"}, "the job is the claim's own fields"
    assert runner._SERVICE_COMMIT["http://localhost:8071"] == "33e6cc0"
    source = (ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
    assert '"commit": _SERVICE_COMMIT.get(server, "")' in source, "and handed to the engine"


# ── the engine and the book ──────────────────────────────────────────────────────────────

def _job(tmp_path, brief="", refs=()):
    if brief:
        (tmp_path / "ENQUIRY_BRIEF.txt").write_text(brief, encoding="utf-8")
    if refs:
        (tmp_path / "REFERENCE_DOCUMENTS.json").write_text(json.dumps({"files": list(refs)}),
                                                            encoding="utf-8")
    return {"job_folder": str(tmp_path), "customer": "Pixel Inspiration",
            "declared_product": "HPP unit Design", "requested_order_quantity": 1}


def _submit(monkeypatch, **over):
    scope = {"client": "Pixel Inspiration", "drawing_number": "HPP unit Design", "units": 1,
             "method": "both", "brief_chars": 20, "brief_sha256": rp.brief_fingerprint("x" * 20),
             "brief_status": "filed", "reference_documents": ["Samsung guide.pdf"]}
    scope.update(over)
    monkeypatch.setenv(rp.SUBMITTED_SCOPE_ENV, json.dumps(scope))


def test_a_scope_that_arrived_whole_says_as_submitted(tmp_path, monkeypatch):
    _submit(monkeypatch)
    s = _job(tmp_path, brief="x" * 20, refs=["Samsung guide.pdf"])
    rp.record(s)
    assert rp.scope_mismatches(s) == []
    assert rp.scope_text(s) == ("customer Pixel Inspiration · drawing HPP unit Design · 1 off"
                                " · as submitted")


def test_a_scope_lost_in_transit_is_named_item_by_item(tmp_path, monkeypatch):
    """Had Pixel been submitted and Samsung received, with no brief and no reference in the
    folder, as the 01:12 book received: each loss is named."""
    _submit(monkeypatch)
    s = _job(tmp_path)
    s.update(customer="Samsung", declared_product="TG_Standalone")
    rp.record(s)
    bad = rp.scope_mismatches(s)
    assert "customer submitted as Pixel Inspiration, received as Samsung" in bad
    assert "drawing submitted as HPP unit Design, received as TG_Standalone" in bad
    assert "a brief of 20 characters was submitted and none reached the job folder" in bad
    assert "declared reference not received: Samsung guide.pdf" in bad
    assert "⚠ NOT AS SUBMITTED" in rp.scope_text(s)


def test_a_stale_brief_nobody_submitted_is_named(tmp_path, monkeypatch):
    _submit(monkeypatch, brief_chars=0, reference_documents=[])
    s = _job(tmp_path, brief="left from an earlier run")
    rp.record(s)
    assert any(m.startswith("no brief was submitted, yet one of") for m in rp.scope_mismatches(s))


def test_a_run_with_no_submission_says_so_and_compares_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(rp.SUBMITTED_SCOPE_ENV, raising=False)
    monkeypatch.delenv(rp.SERVICE_RUN_ID_ENV, raising=False)
    s = _job(tmp_path)
    rp.record(s)
    assert rp.scope_mismatches(s) == []
    assert rp.scope_text(s).endswith("no submission recorded to compare with: started by "
                                     "hand, so nothing was submitted")


def test_a_book_saved_before_the_gap_was_recorded_reads_as_it_did(tmp_path, monkeypatch):
    monkeypatch.delenv(rp.SUBMITTED_SCOPE_ENV, raising=False)
    s = _job(tmp_path)
    rp.record(s)
    s["run_provenance"].pop("submission_gap")
    assert rp.scope_text(s).endswith("no submission recorded to compare with")


# ── which link sent no scope (D-607) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("passed, says", [
    (None, "the runner passed none: a runner process started before D-604 passes none"),
    ("null", "the portal service sent no scope with the job: a service started before D-604"),
    ("{}", "the portal service sent no scope or an empty one"),
    ("{not json", "the scope the runner passed could not be read"),
])
def test_a_portal_run_with_no_scope_names_the_link_and_is_not_verified(
        tmp_path, monkeypatch, passed, says):
    """The HPP 03:18 book said "no submission recorded to compare with" on a portal run, and
    an old service, an old runner and a route that records none all read the same."""
    monkeypatch.setenv(rp.SERVICE_RUN_ID_ENV, "483dae8a401c")
    if passed is None:
        monkeypatch.delenv(rp.SUBMITTED_SCOPE_ENV, raising=False)
    else:
        monkeypatch.setenv(rp.SUBMITTED_SCOPE_ENV, passed)
    s = _job(tmp_path)
    rp.record(s)
    assert says in s["run_provenance"]["submission_gap"]
    text = rp.scope_text(s)
    assert "⚠ NOT VERIFIED: no submitted scope reached the engine; " + says in text
    assert not text.endswith(" · as submitted")


def test_a_run_whose_scope_arrived_records_no_gap(tmp_path, monkeypatch):
    monkeypatch.setenv(rp.SERVICE_RUN_ID_ENV, "483dae8a401c")
    _submit(monkeypatch)
    s = _job(tmp_path, brief="x" * 20, refs=["Samsung guide.pdf"])
    rp.record(s)
    assert s["run_provenance"]["submission_gap"] == ""
    assert rp.scope_text(s).endswith(" · as submitted")


def test_a_run_is_not_claimable_until_its_brief_is_filed_and_its_scope_recorded(api,
                                                                                monkeypatch):
    """Queued first and briefed after, a runner polling in between took a job with no brief
    filed and no scope recorded. Now the run is queued only once both are done."""
    er, tmp_path = api
    _check_in(er)
    filing = er._file_enquiry_brief
    seen = {}

    def _file_and_poll(run, job, brief):
        seen["claim_while_filing"] = _check_in(er)["run"]
        return filing(run, job, brief)

    monkeypatch.setattr(er, "_file_enquiry_brief", _file_and_poll)
    req = _request(er, tmp_path)
    req.enquiry_brief = "Pixel Inspiration HPP unit, one off, customer brief"
    run_id = er.start(req)["run_id"]
    assert seen["claim_while_filing"] is None, "claimed before its brief was filed"
    job = _check_in(er)["run"]
    assert job["run_id"] == run_id
    assert job["submitted_scope"]["brief_status"] == "filed"
    assert job["submitted_scope"]["brief_sha256"] == er.brief_fingerprint(req.enquiry_brief)


def test_a_batch_run_records_its_scope_too():
    batch = ROUTES[ROUTES.index("def batch("):ROUTES.index("def _scan_batch(")]
    scoped = batch.index("run.submitted_scope = submitted_scope(run, method, None, \"none\", [])")
    assert scoped < batch.index("_RUNS[run.run_id] = run"), "recorded before it is queued"


def test_the_scope_row_is_on_the_books_first_page(tmp_path, monkeypatch):
    _submit(monkeypatch)
    s = _job(tmp_path)
    rp.record(s)
    labels = [k for k, _ in rp.facts(s)]
    assert labels[:2] == ["Run ID", "Scope"]
    assert "Scope: customer Pixel Inspiration" in rp.workbook_line(s)


def test_the_saved_record_keeps_the_customer_the_run_was_given():
    main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert 'received_customer=str(summary.get("customer") or ""))' in main
    s = {"run_provenance": {"machine": "M", "received_customer": "Pixel Inspiration",
                            "submitted_scope": {"client": "Samsung"}, "received_scope": {}}}
    assert rp.scope_mismatches(s) == ["customer submitted as Samsung, received as Pixel Inspiration"]


# ── D-604a: content, not presence; a missing field is a mismatch; the exact list ──────────

def test_a_brief_of_200_characters_received_as_one_is_not_as_submitted(tmp_path, monkeypatch):
    """The reviewer's first reproduction."""
    sent = "Pixel Inspiration. " * 10 + "x"
    _submit(monkeypatch, brief_chars=len(sent.strip()), brief_sha256=rp.brief_fingerprint(sent))
    s = _job(tmp_path, brief="y", refs=["Samsung guide.pdf"])
    rp.record(s)
    bad = rp.scope_mismatches(s)
    assert any(m.startswith("the brief in the job folder is not the brief submitted") for m in bad)
    assert "NOT AS SUBMITTED" in rp.scope_text(s)


def test_the_same_brief_with_different_line_breaks_is_the_same_brief(tmp_path, monkeypatch):
    sent = "Customer: Pixel Inspiration.\nOne unit."
    _submit(monkeypatch, brief_chars=len(sent), brief_sha256=rp.brief_fingerprint(sent))
    s = _job(tmp_path, brief="Customer: Pixel Inspiration.  One unit.\n",
             refs=["Samsung guide.pdf"])
    rp.record(s)
    assert not any("brief" in m for m in rp.scope_mismatches(s))


def test_a_missing_customer_or_quantity_is_not_as_submitted(tmp_path, monkeypatch):
    """The reviewer's second reproduction."""
    _submit(monkeypatch)
    s = _job(tmp_path, brief="x" * 20, refs=["Samsung guide.pdf"])
    s.pop("customer"); s.pop("requested_order_quantity")
    rp.record(s)
    bad = rp.scope_mismatches(s)
    assert "customer submitted as Pixel Inspiration, none received" in bad
    assert "quantity submitted as 1, none received" in bad


def test_a_missing_drawing_is_not_as_submitted(tmp_path, monkeypatch):
    _submit(monkeypatch)
    s = _job(tmp_path, brief="x" * 20, refs=["Samsung guide.pdf"])
    s["declared_product"] = ""
    rp.record(s)
    assert "drawing submitted as HPP unit Design, none received" in rp.scope_mismatches(s)


def test_the_reference_list_must_match_exactly(tmp_path, monkeypatch):
    _submit(monkeypatch, reference_documents=["Samsung guide.pdf", "Spec sheet.pdf"])
    s = _job(tmp_path, brief="x" * 20, refs=["Samsung guide.pdf", "Other.pdf"])
    rp.record(s)
    bad = rp.scope_mismatches(s)
    assert "declared reference not received: Spec sheet.pdf" in bad
    assert "reference declared in the folder but not submitted: Other.pdf" in bad


def test_the_service_and_the_engine_fingerprint_a_brief_alike():
    import estimate_routes as er
    for text in ("", "a", "Customer: Pixel.\nOne unit.", "  spaced   out  ", "x" * 4000):
        assert er.brief_fingerprint(text) == rp.brief_fingerprint(text), text


# ── D-604b: a check that could not run is not agreement ────────────────────────────────

def test_a_received_brief_with_no_fingerprint_is_not_verified(tmp_path, monkeypatch):
    """The reviewer's reproduction: the received fingerprint missing read "as submitted"."""
    _submit(monkeypatch)
    s = _job(tmp_path, brief="x" * 20, refs=["Samsung guide.pdf"])
    rp.record(s)
    s["run_provenance"]["received_scope"].pop("brief_sha256")
    bad = rp.scope_mismatches(s)
    assert any(b.startswith(rp.UNVERIFIED) and "none to compare it with" in b for b in bad)
    text = rp.scope_text(s)
    assert "⚠ NOT VERIFIED:" in text and not text.endswith(" · as submitted")
    assert "NOT AS SUBMITTED" not in text, "a check that failed to run is not a difference found"


def test_nothing_recorded_of_what_arrived_is_not_verified(tmp_path, monkeypatch):
    _submit(monkeypatch)
    s = _job(tmp_path, brief="x" * 20, refs=["Samsung guide.pdf"])
    rp.record(s)
    s["run_provenance"].pop("received_scope")
    text = rp.scope_text(s)
    assert "⚠ NOT VERIFIED: nothing was recorded of what reached the job folder" in text


# ── which service queued it, on which build (D-607) ──────────────────────────────────────

def _claimed(monkeypatch, tmp_path, commit, engine="2be3423 · src ab12 (717 modules)"):
    monkeypatch.setenv(rp.CLAIMED_FROM_ENV, json.dumps(
        {"service": "http://localhost:8071", "commit": commit}))
    monkeypatch.setattr(rp, "_build_line", lambda: (engine, ""))
    s = _job(tmp_path)
    rp.record(s)
    return s


def test_a_service_on_another_commit_is_named_on_the_build_row(tmp_path, monkeypatch):
    """HPP 03:18: the engine was on 2be3423, the service that queued the job on 33e6cc0a."""
    s = _claimed(monkeypatch, tmp_path, "33e6cc0a")
    text = rp.build_text(s)
    assert "portal service http://localhost:8071 on 33e6cc0a" in text
    assert "⚠ NOT the engine's commit 2be3423" in text
    assert "Service: portal service http://localhost:8071 on 33e6cc0a" in rp.workbook_line(s)


def test_a_service_on_the_engines_commit_is_named_without_a_warning(tmp_path, monkeypatch):
    s = _claimed(monkeypatch, tmp_path, "2be3423")
    assert rp.build_text(s).endswith("portal service http://localhost:8071 on 2be3423")


def test_an_unknown_commit_is_neither_a_match_nor_a_mismatch(tmp_path, monkeypatch):
    s = _claimed(monkeypatch, tmp_path, "unknown")
    assert "⚠" not in rp.build_text(s)
    s = _claimed(monkeypatch, tmp_path, "")
    assert rp.build_text(s).endswith("which reported no commit")


def test_a_run_started_by_hand_names_no_service(tmp_path, monkeypatch):
    monkeypatch.delenv(rp.CLAIMED_FROM_ENV, raising=False)
    s = _job(tmp_path)
    rp.record(s)
    assert "portal service" not in rp.build_text(s)


def test_a_restart_names_another_service_on_this_machine_running_other_code():
    """Restarting 8072 left 8071 on 33e6cc0a, and the script said nothing about it."""
    ps = (ROOT / "tools" / "start" / "restart-service.ps1").read_text(encoding="utf-8")
    after = ps[ps.index('"  serving commit $serving'):]
    after = after[:after.index("\n} catch {")]
    assert "foreach ($other in @(8071, 8072, 8073))" in after
    assert 'Invoke-RestMethod "http://localhost:$other/api/health"' in after
    assert "$otherCommit -ne $head" in after and "ALSO SERVING" in after
