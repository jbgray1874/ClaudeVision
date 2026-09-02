"""A finished estimate should arrive, not sit in a folder waiting to be found.

Every estimate so far has been delivered by somebody opening the output folder, attaching four
files and typing out what the number means. This closes that gap — and the two properties that
make it safe to leave running are that an empty box sends to nobody, and that a mail which will
not send never costs the run.
"""
from __future__ import annotations

import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
BACKEND = Path(__file__).resolve().parents[1] / "sdi-intelligence-backend"
sys.path.insert(0, str(BACKEND))

import estimate_email                                                    # noqa: E402
import estimate_routes                                                   # noqa: E402


# ── who it goes to ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("typed,expected", [
    ("james.gray@wearesdi.com", ["james.gray@wearesdi.com"]),
    ("a@b.co, c@d.co", ["a@b.co", "c@d.co"]),
    ("a@b.co; c@d.co\ne@f.co", ["a@b.co", "c@d.co", "e@f.co"]),
    ("<a@b.co>", ["a@b.co"]),
    ("a@b.co, A@B.CO", ["a@b.co"]),
    ("", []),
    (None, []),
])
def test_however_somebody_types_a_list_of_addresses(typed, expected):
    assert estimate_email.parse_recipients(typed)[0] == expected


def test_what_was_not_an_address_is_reported_not_dropped():
    """An estimate going to three people when four were asked for is exactly the kind of
    failure nobody notices."""
    good, bad = estimate_email.parse_recipients("real@sdi.com, tim, notanemail@")
    assert good == ["real@sdi.com"]
    assert bad == ["tim", "notanemail@"]


def test_a_typo_is_refused_before_the_drawings_are_staged(monkeypatch):
    """Staging clears and refills the job folder. A mistyped address must not cost that."""
    import ast
    source = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "start")
    body = ast.get_source_segment(source, fn)
    assert body.index("parse_recipients") < body.index("staging.stage("), (
        "checked before anything is staged, for the same reason the pricing method is")


# ── what it attaches ─────────────────────────────────────────────────────────

def test_the_customer_quote_is_withheld_while_the_estimate_is_provisional():
    """It is the one deliverable written to be read by a customer, and on a provisional
    estimate it looks exactly like a quotation for a figure nobody has stood behind."""
    files = [{"path": "out/12349_20260902.xlsx"}, {"path": "out/12349_report.html"},
             {"path": "out/12349_explained.md"}, {"path": "out/12349_quote.html"}]
    keep, held = estimate_email.choose_attachments(files, provisional=True,
                                                   include_quote=False)
    assert "out/12349_quote.html" not in keep
    assert len(keep) == 3
    assert held[0]["why"].startswith("the customer quote is not sent")


def test_the_quote_goes_when_it_is_asked_for():
    files = [{"path": "out/12349_quote.html"}]
    keep, held = estimate_email.choose_attachments(files, provisional=True,
                                                   include_quote=True)
    assert keep == ["out/12349_quote.html"] and not held


def test_a_file_this_service_cannot_reach_is_named_rather_than_lost(tmp_path):
    """The runner exists BECAUSE this service may not see the estimating share. A send that
    requires the attachments to be readable fails on the deployment it matters most on."""
    here = tmp_path / "report.html"
    here.write_text("<p>ok</p>", encoding="utf-8")
    message = EmailMessage()
    attached, skipped = estimate_email.attach_what_we_can(
        message, [str(here), r"\\sdi-dc01\shared$\gone.xlsx"])
    assert attached == ["report.html"]
    assert skipped and "not reachable" in skipped[0]["why"]
    assert skipped[0]["path"].endswith("gone.xlsx"), "named with its full path"


def test_a_file_too_large_to_attach_is_named_too(tmp_path, monkeypatch):
    big = tmp_path / "huge.xlsx"
    big.write_bytes(b"0" * 2048)
    monkeypatch.setattr(estimate_email, "MAX_ATTACHMENT_BYTES", 1024)
    attached, skipped = estimate_email.attach_what_we_can(EmailMessage(), [str(big)])
    assert not attached
    assert "too large" in skipped[0]["why"]


# ── when it sends, and when it does not ──────────────────────────────────────

def test_an_empty_box_sends_to_nobody():
    """So an engine test does not land in an estimator's inbox at two in the morning."""
    out = estimate_email.send([], "subject", "<p>x</p>", "x", [])
    assert out["sent"] is False
    assert "no recipients" in out["reason"]


def test_no_smtp_is_reported_rather_than_raised(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    out = estimate_email.send(["a@b.co"], "s", "<p>x</p>", "x", [])
    assert out["sent"] is False and "SMTP is not configured" in out["reason"]


def test_a_mail_that_will_not_send_never_costs_the_run(monkeypatch):
    """The runner is told the job is filed either way. Losing an estimate because a mail
    server was down would be the worst possible trade."""
    monkeypatch.setenv("SMTP_HOST", "smtp.invalid")
    monkeypatch.setenv("SMTP_FROM", "sdi@wearesdi.com")
    out = estimate_routes._email_finished_run(
        {"drawing_number": "12349-02", "client": "fanatics", "units": 7,
         "engine_price_gbp": 320.91},
        [{"path": "nowhere/x.xlsx"}], ["a@b.co"], False, True)
    assert out["sent"] is False and out["reason"]


def test_the_send_happens_outside_the_registry_lock():
    """Talking to a mail server takes seconds and can hang. Holding the lock through it would
    stall every other run, the page's polling and the runner's next heartbeat."""
    import ast
    source = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.FunctionDef) and n.name == "complete")
    for node in ast.walk(fn):
        if isinstance(node, ast.With):
            inside = ast.get_source_segment(source, node) or ""
            assert "_email_finished_run" not in inside, (
                "the mail is sent after the lock is released, not inside it")


# ── the note ─────────────────────────────────────────────────────────────────

def test_the_subject_says_SDI_Intelligence_and_never_AI():
    note = estimate_email.compose(
        {"drawing_number": "12349-02", "client": "fanatics", "units": 7,
         "engine_price_gbp": 320.91}, [], provisional=True)
    assert note["subject"].startswith("SDI Intelligence estimate, PROVISIONAL.")
    assert "£320.91/unit at 7 off" in note["subject"]
    assert "AI" not in note["subject"]


def test_the_note_points_at_the_explanation_rather_than_repeating_it():
    """This service has never read an estimate. Restating the detail here would be a second
    answer to the same question, computed somewhere with less information."""
    note = estimate_email.compose(
        {"drawing_number": "12349-02", "units": 7, "engine_price_gbp": 320.91},
        [{"path": "out/a.xlsx", "what": "the estimate"}], provisional=True)
    assert "AI Explanation" in note["html"] and "section 14" in note["html"]
    assert "a.xlsx" in note["html"] and "a.xlsx" in note["text"]
    assert "working pack, not a quote" in note["html"]


def test_a_client_name_with_an_ampersand_cannot_break_the_page():
    note = estimate_email.compose(
        {"drawing_number": "1", "client": "M&S <script>", "units": 1}, [])
    assert "<script>" not in note["html"]
    assert "M&amp;S" in note["html"]


# ── sending a run that has already finished ──────────────────────────────────

def _finished_run(**over):
    run = estimate_routes.Run(
        run_id="r1", client="fanatics", drawing_number="12349-02", units=7,
        job_folder="", output_path="", status="done", engine_price_gbp=320.91,
        deliverables=[{"name": "workbook", "path": "out/12349.xlsx"},
                      {"name": "report", "path": "out/12349_report.html"},
                      {"name": "quote", "path": "out/12349_quote.html"}])
    for key, value in over.items():
        setattr(run, key, value)
    estimate_routes._RUNS[run.run_id] = run
    return run


@pytest.fixture(autouse=True)
def _clean_registry():
    # TWO MODULES ARE CALLED config, and which one wins depends on who imported first.
    # src/config.py is the engine's and has no API_KEY; sdi-intelligence-backend/config.py is
    # the portal's and does. Alone, this file imports the portal's. In the full suite another
    # test has already put src/ on the path, so estimate_routes._check_key reaches for
    # config.API_KEY on the engine's module and raises AttributeError — a failure that
    # appears only when the suite runs together, which is the worst kind.
    #
    # Pinned here rather than worked around, because the collision is real: on a machine
    # where both directories are importable, the portal can bind the wrong config. Worth
    # fixing properly by naming one of them.
    if not hasattr(estimate_routes.config, "API_KEY"):
        estimate_routes.config.API_KEY = ""
    estimate_routes._RUNS.clear()
    yield
    estimate_routes._RUNS.clear()


def test_only_this_runs_own_files_can_be_sent():
    """The paths come back from a page, and this service can read whole shares. Accepting an
    arbitrary path would turn a send button into a way to mail anything the service account
    can see."""
    from fastapi import HTTPException
    _finished_run()
    with pytest.raises(HTTPException) as caught:
        estimate_routes.email_run(
            "r1", estimate_routes.SendRequest(recipients="a@b.co",
                                              files=[r"C:\ClaudeVision\.env"]), None)
    assert caught.value.status_code == 400
    assert ".env" in str(caught.value.detail), "refused by name, not silently dropped"


def test_a_run_with_no_deliverables_says_so():
    from fastapi import HTTPException
    _finished_run(deliverables=[])
    with pytest.raises(HTTPException) as caught:
        estimate_routes.email_run(
            "r1", estimate_routes.SendRequest(recipients="a@b.co"), None)
    assert caught.value.status_code == 409


def test_sending_to_nobody_is_refused_rather_than_quietly_doing_nothing():
    """Unlike the automatic send, where empty means "do not send", pressing Send with an
    empty box is a mistake and should say so."""
    from fastapi import HTTPException
    _finished_run()
    with pytest.raises(HTTPException) as caught:
        estimate_routes.email_run("r1", estimate_routes.SendRequest(recipients=""), None)
    assert caught.value.status_code == 400
    assert "at least one address" in str(caught.value.detail)


def test_an_explicit_choice_of_files_includes_the_quote_if_it_was_ticked():
    """The automatic send withholds the quote. A person ticking it has decided."""
    _finished_run()
    sent = {}

    def _fake(recipients, subject, html, text, paths):
        sent.update(recipients=recipients, paths=paths)
        return {"sent": True, "recipients": recipients, "attached": [p for p in paths]}

    original = estimate_email.send
    estimate_email.send = _fake
    try:
        estimate_routes.email_run(
            "r1", estimate_routes.SendRequest(recipients="a@b.co",
                                              files=["out/12349_quote.html"]), None)
    finally:
        estimate_email.send = original
    assert sent["paths"] == ["out/12349_quote.html"]


def test_with_no_choice_it_follows_the_same_rule_as_the_automatic_send():
    _finished_run()
    sent = {}

    def _fake(recipients, subject, html, text, paths):
        sent.update(paths=paths)
        return {"sent": True, "recipients": recipients, "attached": []}

    original = estimate_email.send
    estimate_email.send = _fake
    try:
        estimate_routes.email_run("r1", estimate_routes.SendRequest(recipients="a@b.co"), None)
    finally:
        estimate_email.send = original
    assert "out/12349_quote.html" not in sent["paths"], "the quote stays opt-in"
    assert len(sent["paths"]) == 2


def test_a_failed_send_is_reported_to_the_page_not_swallowed():
    from fastapi import HTTPException
    _finished_run()
    original = estimate_email.send
    estimate_email.send = lambda *a, **k: {"sent": False, "reason": "mailbox unavailable"}
    try:
        with pytest.raises(HTTPException) as caught:
            estimate_routes.email_run(
                "r1", estimate_routes.SendRequest(recipients="a@b.co"), None)
    finally:
        estimate_email.send = original
    assert caught.value.status_code == 502
    assert "mailbox unavailable" in str(caught.value.detail)
