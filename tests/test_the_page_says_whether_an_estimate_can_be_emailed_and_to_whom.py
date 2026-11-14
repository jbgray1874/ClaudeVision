"""The page says whether a finished estimate can be e-mailed, by which sender, and to whom.

14 Nov 2026. The estimating page said "SMTP is not configured on this server, so nothing can
be sent yet". The service has two senders, the SDI Intelligence mailbox and SMTP, and the page
asked about SMTP alone: a service that sends from the mailbox said nothing could be sent. On
the same day the saved list was empty and Self-Running filed estimates and e-mailed nobody,
and the page said nothing about that. JG: "the e-mails go to those people ... this is very
important".

Settings are named, never shown.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
sys.path.insert(0, str(BACKEND))

import estimate_email  # noqa: E402

PAGE = (BACKEND / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")


@pytest.fixture()
def no_sender(monkeypatch):
    for name in ("SDI_ESTIMATE_FROM", "SMTP_HOST", "SMTP_FROM", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def _app_registration(monkeypatch, client_id="an-id", secret="a-secret"):
    import auth
    monkeypatch.setattr(auth, "CLIENT_ID", client_id, raising=False)
    monkeypatch.setattr(auth, "CLIENT_SECRET", secret, raising=False)


def test_a_service_that_sends_from_the_mailbox_says_so_with_no_smtp(no_sender, monkeypatch):
    monkeypatch.setenv("SDI_ESTIMATE_FROM", "intelligence@example.test")
    _app_registration(monkeypatch)
    got = estimate_email.sending_state()
    assert got["can_send"] is True and "intelligence@example.test" in got["sender"]
    assert got["smtp_configured"] is False and got["missing"] == []


def test_a_service_with_smtp_alone_says_smtp(no_sender, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "mail.example.test")
    monkeypatch.setenv("SMTP_FROM", "estimates@example.test")
    got = estimate_email.sending_state()
    assert got["can_send"] is True and got["sender"] == "SMTP as estimates@example.test"


def test_with_neither_sender_it_says_nothing_can_be_sent_and_names_what_is_missing(no_sender):
    got = estimate_email.sending_state()
    assert got["can_send"] is False and got["sender"] == ""
    assert got["missing"] == ["SDI_ESTIMATE_FROM", "SMTP_HOST", "SMTP_FROM"]
    assert "SDI_ESTIMATE_FROM" in got["why"] and "SMTP_HOST" in got["why"]


def test_a_mailbox_named_without_its_app_registration_cannot_send_and_says_which(no_sender,
                                                                              monkeypatch):
    monkeypatch.setenv("SDI_ESTIMATE_FROM", "intelligence@example.test")
    _app_registration(monkeypatch, client_id="an-id", secret="")
    got = estimate_email.sending_state()
    assert got["can_send"] is False and got["missing"] == ["SDI_CLIENT_SECRET"]
    assert "SDI_CLIENT_SECRET" in got["why"]


def test_no_setting_value_is_ever_returned(no_sender, monkeypatch):
    monkeypatch.setenv("SDI_ESTIMATE_FROM", "intelligence@example.test")
    monkeypatch.setenv("SMTP_HOST", "mail.example.test")
    monkeypatch.setenv("SMTP_FROM", "estimates@example.test")
    monkeypatch.setenv("SMTP_PASSWORD", "hunter2-not-a-real-one")
    _app_registration(monkeypatch, secret="the-secret-value")
    said = repr(estimate_email.sending_state())
    assert "hunter2" not in said and "the-secret-value" not in said and "an-id" not in said


def test_the_recipients_answer_carries_the_sending_state():
    routes = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
    assert routes.count('out["sending"] = estimate_email.sending_state()') == 2, \
        "both reading and saving the list say whether it can be delivered"


def test_the_page_no_longer_says_nothing_can_be_sent_on_smtp_alone():
    assert "SMTP is not configured on this server, so nothing can be sent yet" not in PAGE
    assert "d.sending" in PAGE and "s.can_send" in PAGE


def test_the_page_says_when_no_default_list_is_saved():
    assert "NO DEFAULT LIST IS SAVED" in PAGE and "e-mailed to nobody" in PAGE
    assert "Save as the default list" in PAGE
