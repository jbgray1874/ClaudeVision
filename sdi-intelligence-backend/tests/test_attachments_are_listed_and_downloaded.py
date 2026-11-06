"""An attachment can be seen, and leaves as a download rather than as a page.

James Gray, 26 October 2026: "Need to be able to view attachments also."

The mailbox is reachable from the internet, and an attachment is a file a
stranger chose and labelled. Two properties follow, and they are what these
tests are for:

  * listing is metadata only, so rendering a message never pulls a file out of
    the mailbox; content costs a second, deliberate request for one named
    attachment;
  * content leaves as a download on a neutral type, with sniffing off and
    scripts forbidden - so an HTML or SVG attachment cannot run as a page on
    the origin that holds the mailbox session.
"""
import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from private_email import Denied, GraphMailbox, MAX_ATTACHMENT, _file_name

OWNER = "5acf6b37-147f-4468-bdb1-ecc3da1f1076"
FILE = "microsoft.graph.fileAttachment"


def mailbox(answers):
    """A mailbox whose Graph calls are answered from `answers`, keyed on the
    tail of the URL. Records what was asked."""
    asked = []

    def request(method, url, **kwargs):
        asked.append((method, url, kwargs.get("params")))
        for tail, answer in answers.items():
            if url.endswith(tail):
                return answer
        return {}

    box = GraphMailbox(request, OWNER)
    box.asked = asked
    return box


ME = {"id": OWNER}
PDF = base64.b64encode(b"%PDF-1.7 a real drawing").decode()


class ListingTests(unittest.TestCase):
    def test_what_is_attached_is_listed_without_any_content(self):
        box = mailbox({"/me": ME, "/attachments": {"value": [
            {"id": "a1", "name": "bay-unit.pdf", "contentType": "application/pdf",
             "size": 41234, "isInline": False,
             "@odata.type": FILE},
            {"id": "a2", "name": "logo.png", "contentType": "image/png",
             "size": 812, "isInline": True,
             "@odata.type": FILE}]}})
        out = box.attachments("msg-1")
        self.assertEqual([a["name"] for a in out["attachments"]],
                         ["bay-unit.pdf", "logo.png"])
        self.assertEqual(out["attachments"][0]["size"], 41234)
        self.assertTrue(out["attachments"][1]["isInline"])
        # Nothing resembling content came back, and none was asked for.
        for item in out["attachments"]:
            self.assertNotIn("contentBytes", item)
            self.assertNotIn("content", item)
        select = [p for _, url, p in box.asked if url.endswith("/attachments")][0]
        self.assertNotIn("contentBytes", select["$select"])

    def test_the_mailbox_owner_is_checked_before_anything_is_listed(self):
        box = mailbox({"/me": {"id": "somebody-else"}})
        with self.assertRaises(Denied):
            box.attachments("msg-1")

    def test_a_message_with_no_attachments_lists_none(self):
        box = mailbox({"/me": ME, "/attachments": {"value": []}})
        self.assertEqual(box.attachments("msg-1")["attachments"], [])

    def test_the_review_says_which_messages_have_attachments(self):
        """So the list can show it without a request per message."""
        source = (Path(__file__).resolve().parent.parent
                  / "private_email.py").read_text(encoding="utf-8")
        self.assertIn("hasAttachments", source)


class ContentTests(unittest.TestCase):
    def one(self, **over):
        item = {"@odata.type": FILE, "name": "bay-unit.pdf",
                "contentType": "application/pdf", "contentBytes": PDF}
        item.update(over)
        return mailbox({"/me": ME, "/a1": item})

    def test_an_attachment_comes_back_as_its_bytes(self):
        got = self.one().attachment("msg-1", "a1")
        self.assertEqual(got["content"], b"%PDF-1.7 a real drawing")
        self.assertEqual(got["name"], "bay-unit.pdf")

    def test_an_attached_email_or_a_link_is_refused_with_a_reason(self):
        for kind in ("microsoft.graph.itemAttachment",
                     "microsoft.graph.referenceAttachment"):
            with self.subTest(kind=kind):
                with self.assertRaises(Denied) as caught:
                    self.one(**{"@odata.type": kind}).attachment("msg-1", "a1")
                self.assertIn("Outlook", str(caught.exception))

    def test_content_that_is_missing_or_not_base64_is_refused_not_guessed(self):
        for bad in (None, "", "not base64 at all!!", 12345):
            with self.subTest(bad=bad):
                with self.assertRaises(Denied):
                    self.one(contentBytes=bad).attachment("msg-1", "a1")

    def test_something_enormous_is_refused_rather_than_held_in_memory(self):
        huge = base64.b64encode(b"x" * (MAX_ATTACHMENT + 1)).decode()
        with self.assertRaises(Denied) as caught:
            self.one(contentBytes=huge).attachment("msg-1", "a1")
        self.assertIn("Outlook", str(caught.exception))

    def test_the_owner_is_checked_before_content_is_fetched(self):
        box = mailbox({"/me": {"id": "somebody-else"}})
        with self.assertRaises(Denied):
            box.attachment("msg-1", "a1")
        self.assertEqual([url for _, url, _ in box.asked
                          if url.endswith("/a1")], [])


class FileNameTests(unittest.TestCase):
    """The name is a stranger's text that ends up in a download header and on
    somebody's disk."""

    def test_a_path_is_reduced_to_a_name(self):
        self.assertEqual(_file_name(r"..\..\Windows\System32\evil.dll"), "evil.dll")
        self.assertEqual(_file_name("/etc/passwd"), "passwd")
        self.assertEqual(_file_name("../../../secret.pdf"), "secret.pdf")

    def test_control_characters_cannot_forge_a_header(self):
        forged = _file_name('a\r\nContent-Type: text/html\r\n\r\nb.pdf')
        for break_out in ("\r", "\n", "\x00", "Content-Type:"):
            self.assertNotIn(break_out, forged)
        self.assertTrue(forged)
        for raw in ("a\nb", "a\x00b", "a\rb", "a\x1bb"):
            with self.subTest(raw=raw):
                clean = _file_name(raw)
                self.assertTrue(clean.isprintable(), clean)

    def test_an_empty_or_absent_name_still_has_one(self):
        for nothing in (None, "", "   ", "...", "/"):
            with self.subTest(nothing=nothing):
                self.assertEqual(_file_name(nothing), "attachment")

    def test_a_long_name_is_cut_and_a_normal_one_is_untouched(self):
        self.assertEqual(_file_name("Morrisons bay unit - rev C.pdf"),
                         "Morrisons bay unit - rev C.pdf")
        self.assertLessEqual(len(_file_name("x" * 500 + ".pdf")), 160)


class ServedAsADownloadTests(unittest.TestCase):
    """The headers are the whole defence, so they are read from the source."""

    def setUp(self):
        self.source = (Path(__file__).resolve().parent.parent
                       / "private_email_routes.py").read_text(encoding="utf-8")

    def test_it_never_leaves_as_a_page_on_this_origin(self):
        self.assertIn('"Content-Disposition":', self.source)
        self.assertIn("attachment; filename=", self.source)
        self.assertIn('"X-Content-Type-Options": "nosniff"', self.source)
        self.assertIn("default-src 'none'; sandbox", self.source)
        self.assertNotIn("inline; filename", self.source)

    def test_the_senders_type_is_not_what_it_is_served_as(self):
        """A label on the response, never the media type - or image/png on a
        file of HTML would be rendered as HTML by a browser that sniffs."""
        self.assertIn("media_type=OCTET", self.source)
        self.assertIn("X-Sdi-Stated-Type", self.source)

    def test_a_non_ascii_name_survives_without_breaking_the_header(self):
        from urllib.parse import quote
        name = "Zeichnung – größe.pdf"
        ascii_name = name.encode("ascii", "replace").decode().replace('"', "_")
        self.assertNotIn("–", ascii_name)
        self.assertIn("%", quote(name, safe=""))
        self.assertIn("filename*=UTF-8''", self.source)


if __name__ == "__main__":
    unittest.main()
