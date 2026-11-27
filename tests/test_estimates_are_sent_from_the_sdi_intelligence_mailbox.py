"""Estimate e-mails are sent from the SDI Intelligence mailbox through Microsoft Graph (D-545).

James Gray, 16 Oct 2026: "For our email responses from our site can we make them be sent from
SDIIntelligence" — as Nick's morning review already is (From: SDI Intelligence
<sdi-intelligence@wearesdi.com>). SDI_ESTIMATE_FROM names the mailbox; the same app
registration and Exchange access policy the morning review uses send it. Unset, SMTP as before.
A Graph failure with SMTP configured still sends, and says the sender changed.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "sdi-intelligence-backend"
sys.path.insert(0, str(BACKEND))

import estimate_email  # noqa: E402

MAILBOX = "sdi-intelligence@wearesdi.com"


class _Res:
    def __init__(self, status, body=None):
        self.status_code, self._body, self.text = status, body or {}, ""

    def json(self):
        return self._body


class _Graph:
    """A stand-in for Microsoft Graph that records every call."""

    def __init__(self, fail_send=False):
        self.calls = []
        self.fail_send = fail_send

    def post(self, url, headers=None, json=None):
        self.calls.append(("POST", url, json))
        if url.endswith("/sendMail"):
            if self.fail_send:
                return _Res(403, {"error": {"code": "ErrorAccessDenied",
                                            "message": "Access is denied."}})
            return _Res(202)
        if url.endswith("/messages"):
            return _Res(201, {"id": "M1"})
        if url.endswith("/createUploadSession"):
            return _Res(201, {"uploadUrl": "https://upload.example/M1"})
        if url.endswith("/attachments"):
            return _Res(201)
        if url.endswith("/send"):
            return _Res(202)
        return _Res(404)

    def put(self, url, content=None, headers=None):
        self.calls.append(("PUT", url, headers))
        return _Res(200)


@pytest.fixture
def graph(monkeypatch):
    monkeypatch.setenv("SDI_ESTIMATE_FROM", MAILBOX)
    monkeypatch.delenv("SDI_ESTIMATE_REPLY_TO", raising=False)
    monkeypatch.setattr(estimate_email, "_graph_token", lambda: ("TOKEN", ""))
    g = _Graph()
    real = estimate_email.send_via_graph
    monkeypatch.setattr(estimate_email, "send_via_graph",
                        lambda *a, **k: real(*a, **dict(k, client=k.get("client") or g)))
    return g


def test_with_the_mailbox_named_the_estimate_goes_from_it_through_graph(graph, tmp_path):
    book = tmp_path / "job.xlsx"
    book.write_bytes(b"PK-workbook")
    out = estimate_email.send(["nick.garrish@wearesdi.com", "james.gray@wearesdi.com"],
                              "0356454 — SDI Intelligence estimate", "<p>Morning</p>", "Morning",
                              [str(book)])
    assert out["sent"] is True and out["via"] == f"Microsoft Graph as {MAILBOX}"
    assert out["attached"] == ["job.xlsx"]
    (method, url, body), = graph.calls
    assert url == f"https://graph.microsoft.com/v1.0/users/{MAILBOX}/sendMail"
    assert body["saveToSentItems"] is True
    m = body["message"]
    assert [r["emailAddress"]["address"] for r in m["toRecipients"]] == [
        "nick.garrish@wearesdi.com", "james.gray@wearesdi.com"]
    assert m["body"] == {"contentType": "HTML", "content": "<p>Morning</p>"}
    (att,) = m["attachments"]
    assert att["name"] == "job.xlsx" and base64.b64decode(att["contentBytes"]) == b"PK-workbook"
    assert "replyTo" not in m


def test_a_reply_to_can_point_replies_at_a_person(graph, monkeypatch):
    monkeypatch.setenv("SDI_ESTIMATE_REPLY_TO", "james.gray@wearesdi.com")
    estimate_email.send(["a@b.co"], "s", "<p>x</p>", "x", [])
    m = graph.calls[0][2]["message"]
    assert m["replyTo"] == [{"emailAddress": {"address": "james.gray@wearesdi.com"}}]


def test_a_large_estimate_is_drafted_attached_and_sent(graph, tmp_path, monkeypatch):
    monkeypatch.setattr(estimate_email, "_GRAPH_ONE_REQUEST_BYTES", 10)
    monkeypatch.setattr(estimate_email, "_GRAPH_INLINE_FILE_BYTES", 20)
    small, big = tmp_path / "note.html", tmp_path / "book.xlsx"
    small.write_bytes(b"x" * 15)
    big.write_bytes(b"y" * 50)
    out = estimate_email.send(["a@b.co"], "s", "<p>x</p>", "x", [str(small), str(big)])
    assert out["sent"] is True and out["attached"] == ["note.html", "book.xlsx"]
    urls = [c[1].rsplit("/", 1)[-1] for c in graph.calls]
    assert urls[0] == "messages"                                  # the draft
    assert "attachments" in urls and "createUploadSession" in urls
    assert any(c[0] == "PUT" for c in graph.calls)               # the big file, uploaded
    assert urls[-1] == "send"


def test_unset_it_is_smtp_exactly_as_before(monkeypatch):
    monkeypatch.delenv("SDI_ESTIMATE_FROM", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    called = []
    monkeypatch.setattr(estimate_email, "send_via_graph", lambda *a, **k: called.append(1))
    out = estimate_email.send(["a@b.co"], "s", "<p>x</p>", "x", [])
    assert not called and "SMTP is not configured" in out["reason"]


def test_a_graph_refusal_with_no_smtp_is_reported_not_raised(monkeypatch):
    monkeypatch.setenv("SDI_ESTIMATE_FROM", MAILBOX)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setattr(estimate_email, "_graph_token", lambda: ("TOKEN", ""))
    out = estimate_email.send_via_graph(["a@b.co"], "s", "<p>x</p>", [],
                                        client=_Graph(fail_send=True))
    assert out["sent"] is False and "ErrorAccessDenied" in out["reason"]


def test_a_graph_failure_falls_back_to_smtp_and_says_the_sender_changed(monkeypatch):
    monkeypatch.setenv("SDI_ESTIMATE_FROM", MAILBOX)
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SMTP_FROM", "estimating@wearesdi.com")
    monkeypatch.setattr(estimate_email, "send_via_graph",
                        lambda *a, **k: {"sent": False, "reason": "Graph sendMail 403"})
    sent = []

    class _SMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **k):
            pass

        def login(self, *a):
            pass

        def send_message(self, m):
            sent.append(m["From"])

    monkeypatch.setattr(estimate_email.smtplib, "SMTP", _SMTP)
    out = estimate_email.send(["a@b.co"], "s", "<p>x</p>", "x", [])
    assert out["sent"] is True and sent == ["estimating@wearesdi.com"]
    assert out["graph_failed"] == "Graph sendMail 403"
    assert out["via"] == "SMTP as estimating@wearesdi.com"


def test_no_token_is_said_by_name(monkeypatch):
    monkeypatch.setenv("SDI_ESTIMATE_FROM", MAILBOX)
    monkeypatch.setattr(estimate_email, "_graph_token",
                        lambda: (None, "SDI_CLIENT_ID / SDI_CLIENT_SECRET are not set"))
    out = estimate_email.send_via_graph(["a@b.co"], "s", "<p>x</p>", [], client=_Graph())
    assert out["sent"] is False and "SDI_CLIENT_ID" in out["reason"]
