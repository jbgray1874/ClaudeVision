"""Selecting a message shows what it says, what it asks, and a suggested reply.

James Gray, 26 October 2026: "is the code written to summarise the e-mails when
I select them and is the response created?" It was written and it was not
connected. This is the connection, and the properties that make it reviewable:

  * /suggest reads one message and returns wording. It writes nothing anywhere -
    saving is still /proposals and /confirm, which show you the text first;
  * the summary and the draft come from one reading, so a summary that is wrong
    says the wording is wrong;
  * no suggestion is never a broken screen: it says why, and the box still works.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

import httpx

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import private_draft_writer as writer           # noqa: E402
from private_email import Denied, GraphMailbox  # noqa: E402

OWNER = "5acf6b37-147f-4468-bdb1-ecc3da1f1076"
PAGE = (BACKEND / "private-email.html").read_text(encoding="utf-8")
ROUTES = (BACKEND / "private_email_routes.py").read_text(encoding="utf-8")


class FullMessageTests(unittest.TestCase):
    """The list carries previews. A reply needs the body."""

    def test_the_body_is_asked_for_only_when_a_message_is_opened(self):
        asked = []

        def request(method, url, **kwargs):
            asked.append((url, kwargs.get("params")))
            return {"id": OWNER} if url.endswith("/me") else {"id": "m1", "body": {}}

        GraphMailbox(request, OWNER).full("m1")
        select = [p for url, p in asked if url.endswith("/messages/m1")][0]["$select"]
        self.assertIn("body", select)
        self.assertIn("hasAttachments", select)

    def test_the_owner_is_checked_first(self):
        box = GraphMailbox(lambda *a, **k: {"id": "someone-else"}, OWNER)
        with self.assertRaises(Denied):
            box.full("m1")


class SuggestRouteTests(unittest.TestCase):
    def test_the_route_writes_nothing_to_the_mailbox(self):
        """It reads one message and returns text. If this ever grows a write,
        the suggestion stops being free to be wrong."""
        body = ROUTES.split("def suggest(", 1)[1].split("@router.", 1)[0]
        for write in ("createReply", "store.propose", "store.confirm",
                      "mailbox.create_reply", '"POST"', "DELETE"):
            self.assertNotIn(write, body, f"/suggest must not {write}")
        self.assertIn("mailbox.full", body)
        self.assertIn("writer.compose", body)

    def test_an_absent_suggestion_says_why(self):
        self.assertIn("why_not", ROUTES)
        self.assertIn("Suggestions are switched off", ROUTES)
        self.assertIn("could not be reached", ROUTES)

    def test_what_james_types_is_bounded_before_it_reaches_the_model(self):
        self.assertIn("instruction: str = Field(default=\"\", max_length=1000)", ROUTES)


class PageTests(unittest.TestCase):
    def test_the_reading_is_rendered_above_the_wording(self):
        """Append order in renderDetail decides what is read first - not where
        the functions happen to sit in the file."""
        detail = PAGE.split("function renderDetail(", 1)[1].split("\nasync function", 1)[0]
        section = detail.index("el('section',null,box,'reading')")
        wording = detail.index("'PREPARE A REPLY'")
        textarea = detail.index("el('textarea',null,box)")
        self.assertLess(section, wording,
                        "the summary must be read before the draft, not after it")
        self.assertLess(wording, textarea)

    def test_the_summary_the_asks_and_the_gaps_all_reach_the_screen(self):
        for shown in ("WHAT THIS SAYS", "WHAT IT ASKS FOR",
                      "YOU STILL NEED TO FILL IN"):
            self.assertIn(shown, PAGE)

    def test_a_missing_summary_is_a_warning_not_a_blank(self):
        self.assertIn("Read the message in Outlook before trusting any wording", PAGE)
        self.assertIn("'warn'", PAGE)

    def test_typing_is_never_overwritten_by_a_late_suggestion(self):
        """A suggestion that arrives after you have started writing must not
        take the keyboard off you."""
        self.assertIn("replace||!input.value.trim()", PAGE.replace(" ", ""))

    def test_a_suggestion_for_a_message_you_have_left_is_discarded(self):
        """Click three messages quickly and the answers come back in any order.
        Each one checks it is still the selected message before it renders."""
        self.assertGreaterEqual(PAGE.count("state.selected?.id!==mine"), 3)

    def test_the_page_never_renders_an_attachment_itself(self):
        self.assertIn("link.download=a.name", PAGE)
        for render in ("<iframe", "innerHTML", "document.write",
                       "createObjectURL", "srcdoc"):
            self.assertNotIn(render, PAGE, f"{render} would run a sender's file here")

    def test_an_attached_email_is_named_as_one_rather_than_offered(self):
        self.assertIn("open this one in Outlook", PAGE)
        self.assertIn("a.kind==='fileAttachment'", PAGE)

    def test_attachments_are_only_asked_for_when_there_are_some(self):
        self.assertIn("if(m.hasAttachments)listFiles", PAGE.replace(" ", ""))

    def test_the_ids_are_escaped_into_the_url(self):
        """A Graph message id is base64-ish and contains characters that mean
        something in a path."""
        self.assertEqual(PAGE.count("encodeURIComponent"), 3)


class ComposeStillHoldsTests(unittest.TestCase):
    """The wiring must not have loosened what the writer promises."""

    def test_the_writer_still_cannot_reach_a_mailbox(self):
        source = (BACKEND / "private_draft_writer.py").read_text(encoding="utf-8")
        for forbidden in ("graph.microsoft.com", "httpx", "requests", "createReply"):
            self.assertNotIn(forbidden, source)

    def test_a_blank_answer_has_every_key_the_page_reads(self):
        for key in ("summary", "asks", "draft", "gaps"):
            self.assertIn(key, writer._blank())


if __name__ == "__main__":
    unittest.main()
