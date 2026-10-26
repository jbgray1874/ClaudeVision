import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from private_email import Policy, Denied, GraphMailbox, DraftStore
from private_email_routes import make_router


OWNER = {"oid": "owner", "tid": "tenant", "kind": "user"}
SOURCE = {"id": "message", "subject": "Review", "from": {"emailAddress": {"address": "sender@example.test"}}}


class PrivateEmailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = DraftStore(Path(self.temp.name) / "proposals.db")
        self.policy = Policy("tenant", "owner", True)

    def test_owner_allowed(self):
        self.policy.check(OWNER)

    def test_disabled_denies(self):
        with self.assertRaises(Denied): Policy().check(OWNER)

    def test_no_identity_bypasses(self):
        for user in (None, {}, {**OWNER, "kind": "machine"}, {**OWNER, "kind": "anonymous"},
                     {**OWNER, "oid": "other"}, {**OWNER, "tid": "other"}):
            with self.subTest(user=user), self.assertRaises(Denied): self.policy.check(user)

    def test_wrong_graph_mailbox_denied(self):
        with self.assertRaises(Denied): GraphMailbox(lambda *a, **k: {"id": "other"}, "owner").review()

    def test_window_excludes_old_and_future_even_if_provider_does_not(self):
        transport = Mock(side_effect=[{"id": "owner"}, {"value": [
            {"id": "old", "receivedDateTime": "2026-10-01T00:00:00Z"},
            {"id": "valid", "receivedDateTime": "2026-10-25T00:00:00Z"},
            {"id": "future", "receivedDateTime": "2026-10-28T00:00:00Z"}]}])
        result = GraphMailbox(transport, "owner").review(datetime(2026,10,26,tzinfo=timezone.utc))
        self.assertEqual([m["id"] for m in result["messages"]], ["valid"])
        self.assertTrue(result["complete"])

    def test_partial_retrieval_declared(self):
        transport = Mock(side_effect=[{"id": "owner"}, {"value": [], "@odata.nextLink": GraphMailbox.BASE + "/me/messages?$skiptoken=x"}])
        self.assertFalse(GraphMailbox(transport, "owner").review(max_pages=1)["complete"])

    def test_pagination_cannot_leak_token(self):
        for url in ("https://evil.test/me/messages", "https://graph.microsoft.com/v1.0/users/other/messages"):
            transport = Mock(side_effect=[{"id": "owner"}, {"value": [], "@odata.nextLink": url}])
            with self.subTest(url=url), self.assertRaises(Denied): GraphMailbox(transport,"owner").review()
            self.assertEqual(transport.call_count, 2)

    def proposal(self):
        return self.store.propose("owner", SOURCE, "Thanks — please confirm.")

    def mailbox(self):
        return Mock(source=Mock(return_value=SOURCE), create_reply=Mock(return_value={"id":"draft", "isDraft":True}))

    def test_proposal_does_not_write_to_mailbox(self):
        self.assertEqual(self.proposal()["body"], "Thanks — please confirm.")

    def test_confirm_is_idempotent(self):
        p, mailbox = self.proposal(), self.mailbox()
        a = self.store.confirm("owner",p["proposal_id"],p["digest"],mailbox)
        b = self.store.confirm("owner",p["proposal_id"],p["digest"],mailbox)
        self.assertEqual(a,b)
        mailbox.create_reply.assert_called_once()

    def test_changed_approval_denied(self):
        p, mailbox = self.proposal(), self.mailbox()
        for owner,digest in (("other",p["digest"]),("owner","tampered")):
            with self.assertRaises(Denied): self.store.confirm(owner,p["proposal_id"],digest,mailbox)
        mailbox.create_reply.assert_not_called()

    def test_expired_denied(self):
        p = self.proposal()
        with self.store.db() as db: db.execute("UPDATE proposals SET expires=0")
        with self.assertRaises(Denied): self.store.confirm("owner",p["proposal_id"],p["digest"],self.mailbox())

    def test_timeout_never_retried(self):
        p, mailbox = self.proposal(), self.mailbox()
        mailbox.create_reply.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError): self.store.confirm("owner",p["proposal_id"],p["digest"],mailbox)
        with self.assertRaises(Denied): self.store.confirm("owner",p["proposal_id"],p["digest"],mailbox)
        mailbox.create_reply.assert_called_once()

    def test_recipient_change_stops_write(self):
        p, mailbox = self.proposal(), self.mailbox()
        mailbox.source.return_value = {**SOURCE,"replyTo":[{"emailAddress":{"address":"changed@example.test"}}]}
        with self.assertRaises(Denied): self.store.confirm("owner",p["proposal_id"],p["digest"],mailbox)
        mailbox.create_reply.assert_not_called()

    def test_graph_uses_create_reply_not_send(self):
        transport = Mock(side_effect=[{"id":"owner"},{"id":"draft","isDraft":True}])
        GraphMailbox(transport,"owner").create_reply("id/with/slashes", "plain text")
        args, kwargs = transport.call_args
        self.assertEqual(args, ("POST",GraphMailbox.BASE+"/me/messages/id%2Fwith%2Fslashes/createReply"))
        self.assertEqual(kwargs["json"]["message"]["body"]["contentType"], "Text")

    def client(self, claims=OWNER):
        auth = Mock(current_user=Mock(return_value=claims),graph_token=Mock(return_value="test-token"))
        app = FastAPI()
        # The draft UI is not shipped (see test_a_server_without_the_draft_page_
        # cannot_serve_drafts), so these draft tests supply their own stub page.
        pages = Path(self.temp.name)/"pages"; pages.mkdir(exist_ok=True)
        (pages/"private-email.html").write_text("<!doctype html><p>stub draft page", encoding="utf-8")
        app.include_router(make_router(auth,self.policy,Path(self.temp.name)/"api.db",
                                       "https://private.example.test",drafts_enabled=True,
                                       page_dir=pages))
        return TestClient(app)

    def test_api_rejects_other_user(self):
        client = self.client({**OWNER,"oid":"other"})
        for route in ("/workspace","/review"):
            self.assertEqual(client.get('/api/private-email'+route).status_code,403)

    def test_cross_origin_write_denied(self):
        client = self.client()
        r = client.post('/api/private-email/proposals',json={"message_id":"x","body":"hello"},
                        headers={"Origin":"https://evil.test","X-SDI-Private-Action":"1"})
        self.assertEqual(r.status_code,403)

    def test_no_send_or_delete_routes(self):
        client = self.client()
        self.assertEqual(client.post('/api/private-email/send').status_code,404)
        self.assertEqual(client.delete('/api/private-email/messages/x').status_code,404)

    def test_private_page_no_store(self):
        r = self.client().get('/api/private-email/workspace')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers['cache-control'],'no-store')


if __name__ == '__main__': unittest.main()
