"""A new message - not a reply - and it still cannot leave the mailbox.

James Gray, 26 October 2026: "can I ask it to prepare an email for me?" The app
only knew how to reply. This adds a new message, and the thing to be careful
about is that a new message is the ONE place the app chooses recipients rather
than reading them off a thread a person already has open.

So a reply's recipients are re-checked against the thread at save time; a new
message's cannot be, because there is nothing to check them against. Instead
they are parsed strictly, shown for approval, and carried inside the digest - so
approving one set of recipients cannot save a different one.

And it is still a draft. POST /me/messages creates one; sending is a different
endpoint this app has no code for and no permission to call.
"""
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from private_email import Denied, DraftStore, GraphMailbox, _addresses  # noqa: E402

OWNER = "5acf6b37-147f-4468-bdb1-ecc3da1f1076"


class AddressTests(unittest.TestCase):
    def test_the_usual_ways_people_type_recipients(self):
        for typed, expected in (
            ("nick@wearesdi.com", ["nick@wearesdi.com"]),
            ("a@x.com, b@y.com", ["a@x.com", "b@y.com"]),
            ("a@x.com; b@y.com", ["a@x.com", "b@y.com"]),
            ("a@x.com\nb@y.com", ["a@x.com", "b@y.com"]),
            ("<a@x.com>", ["a@x.com"]),
            ("A@X.com, a@x.COM", ["a@x.com"]),          # the same person once
        ):
            with self.subTest(typed=typed):
                self.assertEqual(_addresses(typed), expected)

    def test_anything_not_plainly_an_address_is_refused_not_guessed(self):
        """A mis-parsed recipient on a new message is an email to a stranger."""
        for typed in ("Nick", "nick@", "@wearesdi.com", "nick wearesdi.com",
                      "nick@wearesdi", "nick@@wearesdi.com", "nick<@>x.com"):
            with self.subTest(typed=typed):
                with self.assertRaises(Denied):
                    _addresses(typed)

    def test_a_display_name_is_refused_rather_than_half_understood(self):
        """"Nick Garrish <nick@wearesdi.com>" splits on the space, and "Nick"
        is not an address. Refusing is right: paste the address."""
        with self.assertRaises(Denied):
            _addresses("Nick Garrish <nick@wearesdi.com>")

    def test_nothing_typed_is_no_recipients(self):
        for quiet in ("", "   ", ",,", None):
            with self.subTest(quiet=quiet):
                self.assertEqual(_addresses(quiet), [])


class Mailbox:
    """Records what Graph was asked to do."""

    def __init__(self):
        self.calls = []

    def verify(self):
        pass

    def create_draft(self, to, subject, body):
        self.calls.append(("create_draft", to, subject, body))
        return {"id": "draft-1", "isDraft": True, "webLink": "https://outlook.test/d1"}

    def source(self, message_id):
        self.calls.append(("source", message_id))
        raise AssertionError("a new message has no source to read")

    def create_reply(self, *a):
        raise AssertionError("a new message must not go through createReply")


class NewMessageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DraftStore(str(Path(self.temp.name) / "drafts.db"))
        self.box = Mailbox()

    def propose(self, to="nick@wearesdi.com", subject="Tracker", body="Fixed."):
        return self.store.propose_new(OWNER, to, subject, body)

    def test_proposing_writes_nothing_to_the_mailbox(self):
        self.propose()
        self.assertEqual(self.box.calls, [])

    def test_confirming_saves_one_draft_and_never_sends(self):
        p = self.propose(body="The tracker reads and writes now.")
        out = self.store.confirm(OWNER, p["proposal_id"], p["digest"], self.box)
        self.assertEqual(out["isDraft"], True)
        self.assertEqual(len(self.box.calls), 1)
        kind, to, subject, body = self.box.calls[0]
        self.assertEqual(kind, "create_draft")
        self.assertEqual(to, [{"emailAddress": {"address": "nick@wearesdi.com"}}])
        self.assertEqual(subject, "Tracker")
        self.assertIn("reads and writes", body)

    def test_confirming_twice_saves_one_draft(self):
        p = self.propose()
        first = self.store.confirm(OWNER, p["proposal_id"], p["digest"], self.box)
        again = self.store.confirm(OWNER, p["proposal_id"], p["digest"], self.box)
        self.assertEqual(first, again)
        self.assertEqual(len(self.box.calls), 1)

    def test_approving_one_set_of_recipients_cannot_save_another(self):
        """The digest covers the recipients, so a changed To fails the match."""
        p = self.propose(to="nick@wearesdi.com")
        other = self.store.propose_new(OWNER, "someone.else@example.test",
                                       "Tracker", "Fixed.")
        with self.assertRaises(Denied):
            self.store.confirm(OWNER, p["proposal_id"], other["digest"], self.box)
        self.assertEqual(self.box.calls, [])

    def test_somebody_elses_proposal_is_refused(self):
        p = self.propose()
        with self.assertRaises(Denied):
            self.store.confirm("another-oid", p["proposal_id"], p["digest"], self.box)
        self.assertEqual(self.box.calls, [])

    def test_a_new_message_never_reads_a_thread_or_uses_create_reply(self):
        """Mailbox.source and create_reply both assert if reached."""
        p = self.propose()
        self.store.confirm(OWNER, p["proposal_id"], p["digest"], self.box)
        self.assertEqual([c[0] for c in self.box.calls], ["create_draft"])

    def test_an_empty_subject_or_body_is_refused(self):
        with self.assertRaises(Denied):
            self.propose(subject="   ")
        with self.assertRaises(Denied):
            self.propose(body="   ")

    def test_a_bad_address_stops_it_before_anything_is_stored(self):
        with self.assertRaises(Denied):
            self.propose(to="Nick")
        with self.assertRaises(Denied):
            self.propose(to="")

    def test_a_mailing_list_sized_send_is_refused(self):
        many = ", ".join(f"p{n}@example.test" for n in range(21))
        with self.assertRaises(Denied):
            self.propose(to=many)


class StillCannotSendTests(unittest.TestCase):
    def test_no_send_endpoint_is_built_anywhere(self):
        """Read as CODE, not as prose: the comments say "never /sendMail", and
        a test that matched the text would pass on the comment and miss the
        call. Docstrings are dropped, every other string literal is checked."""
        import ast

        def literals(tree):
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                    first = node.body[0] if node.body else None
                    if (isinstance(first, ast.Expr)
                            and isinstance(first.value, ast.Constant)
                            and isinstance(first.value.value, str)):
                        docstrings.add(id(first.value))
            return [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and id(n) not in docstrings]

        for name in ("private_email.py", "private_email_routes.py",
                     "private_draft_writer.py"):
            tree = ast.parse((BACKEND / name).read_text(encoding="utf-8"))
            for text in literals(tree):
                with self.subTest(file=name, text=text[:60]):
                    low = text.lower()
                    self.assertNotIn("sendmail", low)
                    self.assertFalse(low.endswith("/send"), text)
                    self.assertNotIn("/send/", low)

    def test_the_comment_promising_no_send_is_still_there(self):
        """The prose the test above deliberately ignores still has to say it."""
        source = (BACKEND / "private_email.py").read_text(encoding="utf-8")
        self.assertIn("sending is /send or /sendMail", source)

    def test_the_new_draft_is_checked_for_being_a_draft(self):
        source = (BACKEND / "private_email.py").read_text(encoding="utf-8")
        made = source.split("def create_draft", 1)[1].split("def create_reply", 1)[0]
        self.assertIn('result.get("isDraft") is not True', made)
        self.assertIn("/me/messages", made)

    def test_a_graph_answer_that_is_not_a_draft_is_refused(self):
        class Odd(GraphMailbox):
            def verify(self):
                pass

        box = Odd(lambda *a, **k: {"id": "x", "isDraft": False}, OWNER)
        with self.assertRaises(Denied):
            box.create_draft([{"emailAddress": {"address": "a@b.test"}}], "s", "b")


if __name__ == "__main__":
    unittest.main()
