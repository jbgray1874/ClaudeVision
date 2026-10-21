"""The morning email offers both ways to take the briefing further.

Nick Garrish, 21 October 2026: "can the link to Sdi intelligence and the speech be
linked through directly to ChatGPT ... I think it currently still linked back to the
other agent?"

Both, not one instead of the other. A ChatGPT deep link ANSWERS IN WRITING - nothing
can make it start speaking, because only the person can turn voice mode on - and the
app's Listen button speaks on one tap, which is the point of it at 07:50.
"""
import re
import sys
from datetime import date
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import morning_review as mr  # noqa: E402

REVIEW = {
    "date": date(2026, 10, 21).isoformat(),
    "owner": "NG",
    "counts": {"active": 12, "conflicts": 2, "overdue": 3, "ordered_past_end": 1,
               "missing": 4, "contact": 5, "due": 6},
    "previous_counts": {},
    "top": [{"facts": {"account": "TESCO", "unit": "Mobile", "job": "Digital ticketing",
                       "code": "AD-HOC", "am": "NG", "pm": "YM", "action": "20 October",
                       "end": "30 October", "budget": "£3,000"}}],
}
WORDS = {"movement": "Nothing moved.",
         "items": [{"issue": "Overdue by a day.", "decision": "Confirm the date."}]}


@pytest.fixture(autouse=True)
def _public_host(monkeypatch):
    monkeypatch.setenv("SDI_PUBLIC_HOSTS", "sdiintelligence.example.net")
    for name in ("SDI_REVIEW_LISTEN_URL", "SDI_REVIEW_CHATGPT_URL"):
        monkeypatch.delenv(name, raising=False)


def test_both_buttons_are_in_the_email_and_go_to_different_places():
    out = mr.render(REVIEW, WORDS)
    listen, ask = mr.listen_url(), mr.chatgpt_url()
    assert "sdiintelligence.example.net" in listen and "briefing=1" in listen
    assert ask.startswith("https://chatgpt.com/?q=")
    for body in (out["html"], out["text"]):
        assert listen in body, body[:400]
        assert ask in body, body[:400]


def test_the_chatgpt_link_asks_the_connector_for_the_briefing():
    """Without "Using SDI Tracker" ChatGPT answers from the conversation, not the
    tracker, and the briefing is whatever it can remember."""
    ask = mr.chatgpt_url()
    from urllib.parse import parse_qs, urlparse
    question = parse_qs(urlparse(ask).query)["q"][0]
    assert question.lower().startswith("using sdi tracker,"), question
    assert "briefing" in question.lower()


def test_the_email_says_which_button_speaks():
    """At 07:50 on a phone, "speaks now" vs "answers in writing" is the whole choice."""
    html = mr.render(REVIEW, WORDS)["html"]
    listen_at, ask_at = html.index("Listen to this briefing"), html.index("Ask ChatGPT")
    assert listen_at < ask_at, "the one that speaks comes first"
    assert "reads this aloud" in html
    assert "answers in writing" in html
    assert "voice mode" in html


def test_the_text_only_email_carries_both_links_too():
    text = mr.render(REVIEW, WORDS)["text"]
    assert "Listen to this briefing: https://" in text
    assert "Ask ChatGPT about it" in text and "voice mode" in text


@pytest.mark.parametrize("value, expect", [
    ("https://chatgpt.com/g/g-custom", "https://chatgpt.com/g/g-custom"),
    ("off", ""),
    ("OFF", ""),
])
def test_the_chatgpt_button_can_be_pointed_elsewhere_or_removed(monkeypatch, value, expect):
    monkeypatch.setenv("SDI_REVIEW_CHATGPT_URL", value)
    assert mr.chatgpt_url() == expect
    html = mr.render(REVIEW, WORDS)["html"]
    assert ("Ask ChatGPT" in html) == bool(expect)
    assert "Listen to this briefing" in html, "removing one must not remove the other"


def test_the_listen_button_still_wins_when_it_is_overridden(monkeypatch):
    """SDI_REVIEW_LISTEN_URL was the one-line way to swap the button over before
    there were two of them. It still decides where Listen goes."""
    monkeypatch.setenv("SDI_REVIEW_LISTEN_URL", "https://example.net/elsewhere")
    assert mr.listen_url() == "https://example.net/elsewhere"
    assert "https://example.net/elsewhere" in mr.render(REVIEW, WORDS)["html"]


def test_a_link_cannot_break_out_of_the_html():
    monkeypatch_value = "https://chatgpt.com/?q=a'><script>alert(1)</script>"
    import os
    os.environ["SDI_REVIEW_CHATGPT_URL"] = monkeypatch_value
    try:
        html = mr.render(REVIEW, WORDS)["html"]
        assert "<script>" not in html, html[:400]
        assert "&lt;script&gt;" in html
    finally:
        del os.environ["SDI_REVIEW_CHATGPT_URL"]


def test_both_settings_are_written_down():
    """A switch nobody can find is a switch nobody uses."""
    doc = re.search(r'^"""(.*?)"""', mr.__doc__ or "", re.S)
    text = mr.__doc__ or ""
    for name in ("SDI_REVIEW_LISTEN_URL", "SDI_REVIEW_CHATGPT_URL"):
        assert name in text, f"{name} is not in morning_review's own documentation"
