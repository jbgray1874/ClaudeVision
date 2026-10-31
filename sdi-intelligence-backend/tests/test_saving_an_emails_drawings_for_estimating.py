"""An email's drawings, saved to Live Enquiry from the private assistant.

"if we receive an email with a pdf / pdf's in the email app SDI private
assistant I want to be able to save that down to the file system and then go
to the other app, open up the estimate and run an estimate" - James Gray,
30 October 2026.

What would hurt if it drifted: a saved revision replacing the drawing an
estimate was already run from; a typed client name that walks out of Live
Enquiry; a logo in the signature filed as a part; one oversized attachment
costing the whole save; and a link that does not land on the pack.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import enquiry_filing as filing  # noqa: E402
from private_email import Denied, Policy  # noqa: E402

PAGE = (BACKEND / "private-email.html").read_text(encoding="utf-8")
PDF = b"%PDF-1.7 drawing"


class WithAFolder(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Live Enquiry"
        self.root.mkdir()

    def save(self, files, client="Boots", reference="12552"):
        return filing.file_for_estimating(self.root, client, reference, files)


class WhereItGoesTests(WithAFolder):
    def test_client_then_job_the_two_levels_estimating_starts_from(self):
        out = self.save([("12552 GA.pdf", PDF)])
        self.assertEqual(out["relative"], "Boots/12552")
        self.assertEqual((self.root / "Boots" / "12552" / "12552 GA.pdf").read_bytes(), PDF)
        self.assertEqual(out["saved"], ["12552 GA.pdf"])

    def test_typed_names_are_cleaned_into_folder_names(self):
        out = self.save([("a.pdf", PDF)], client="M&S", reference='0359962: "rev B"')
        self.assertEqual(out["client"], "M&S")
        self.assertEqual(out["reference"], "0359962- -rev B-")

    def test_a_name_cannot_walk_out_of_live_enquiry(self):
        for client, reference in (("..", "x"), ("x", ".."), ("../..", "HR"),
                                  ("a/../../b", "c"), ("C:\\Windows", "x")):
            with self.subTest(client=client, reference=reference):
                try:
                    out = self.save([("a.pdf", PDF)], client, reference)
                except filing.Refused:
                    continue
                written = Path(out["folder_path"]).resolve()
                self.assertIn(self.root.resolve(), written.parents)

    def test_both_names_are_needed(self):
        for client, reference in (("", "12552"), ("Boots", "  "), ("...", "1")):
            with self.subTest(client=client, reference=reference):
                with self.assertRaises(filing.Refused):
                    self.save([("a.pdf", PDF)], client, reference)

    def test_live_enquiry_out_of_reach_says_so(self):
        with self.assertRaises(filing.Refused) as said:
            filing.file_for_estimating(self.root / "gone", "Boots", "1", [("a.pdf", PDF)])
        self.assertIn("cannot be reached", str(said.exception))


class WhatGoesTests(WithAFolder):
    def test_only_what_the_estimate_reads(self):
        out = self.save([("GA.pdf", PDF), ("logo.png", b"png"), ("prices.xlsx", b"x"),
                         ("base.DXF", b"dxf"), ("frame.SLDPRT", b"sw")])
        self.assertEqual(sorted(out["saved"]), ["GA.pdf", "base.DXF", "frame.SLDPRT"])
        self.assertEqual({s["name"] for s in out["skipped"]}, {"logo.png", "prices.xlsx"})

    def test_the_list_is_the_one_staging_runs_from(self):
        try:
            import staging
        except Exception as exc:                                   # noqa: BLE001
            self.skipTest(f"staging cannot be imported here: {exc}")
        self.assertEqual(filing.DRAWINGS, staging.DRAWING_SUFFIXES)

    def test_a_senders_file_name_is_only_a_name(self):
        out = self.save([("..\\..\\evil.pdf", PDF), ("dir/GA.pdf", PDF)])
        self.assertEqual(sorted(out["saved"]), ["GA.pdf", "evil.pdf"])
        self.assertTrue((self.root / "Boots" / "12552" / "evil.pdf").exists())


class NeverOverTests(WithAFolder):
    def test_the_same_file_twice_is_left_alone(self):
        self.save([("GA.pdf", PDF)])
        out = self.save([("GA.pdf", PDF)])
        self.assertEqual(out["saved"], [])
        self.assertEqual(out["skipped"], [{"name": "GA.pdf", "why": "already in the folder"}])
        self.assertEqual(len(list((self.root / "Boots" / "12552").iterdir())), 1)

    def test_a_revision_goes_beside_it_never_over_it(self):
        """The estimate run from the first one still has to be explainable."""
        self.save([("GA.pdf", PDF)])
        out = self.save([("GA.pdf", PDF + b" rev B")])
        self.assertEqual(out["saved"], ["GA (2).pdf"])
        folder = self.root / "Boots" / "12552"
        self.assertEqual((folder / "GA.pdf").read_bytes(), PDF)
        self.assertEqual((folder / "GA (2).pdf").read_bytes(), PDF + b" rev B")

    def test_every_write_is_exclusive(self):
        source = (BACKEND / "enquiry_filing.py").read_text(encoding="utf-8")
        self.assertIn('open(target, "xb")', source)
        self.assertNotIn('"wb"', source)


class OneLiveEnquiryTests(unittest.TestCase):
    """Four copies of one default. If they disagreed, a pack would be saved
    where the Folders and Start screens never look."""

    def test_the_defaults_agree(self):
        import public_surface
        self.assertEqual(filing.LIVE_ENQUIRY_DEFAULT, public_surface.ENQUIRY_DEFAULT)
        tools = (BACKEND / "estimating_job_tools.py").read_text(encoding="utf-8")
        self.assertIn(filing.LIVE_ENQUIRY_DEFAULT.split("\\")[-1], tools)
        if not os.getenv("SDI_LIVE_ENQUIRY_ROOT"):
            import estimating_job_tools
            self.assertEqual(str(estimating_job_tools.LIVE_ENQUIRY_ROOT),
                             filing.LIVE_ENQUIRY_DEFAULT)

    def test_the_setting_moves_it(self):
        with patch.dict(os.environ, {"SDI_LIVE_ENQUIRY_ROOT": r"\\elsewhere\LE"}):
            self.assertEqual(str(filing.live_enquiry_root()), r"\\elsewhere\LE")


# ── The route ────────────────────────────────────────────────────────────────
OWNER = {"kind": "user", "tid": "tenant", "oid": "owner", "name": "James"}
SAME = {"Origin": "https://private.example.test", "X-SDI-Private-Action": "1"}


class FakeMailbox:
    """Attachments by id. 'big' is refused the way Graph's 25 MB limit is."""
    FILES = {"a1": {"name": "GA.pdf", "contentType": "application/pdf", "content": PDF},
             "a2": {"name": "base.dxf", "contentType": "image/vnd.dxf", "content": b"dxf"},
             "logo": {"name": "logo.png", "contentType": "image/png", "content": b"png"}}

    def __init__(self, transport, owner):
        pass

    def attachment(self, message_id, attachment_id):
        if attachment_id == "big":
            raise Denied("That attachment is larger than 25MB. Open it in Outlook.")
        return dict(self.FILES[attachment_id])


class TheRouteTests(WithAFolder):
    def client(self, claims=OWNER):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import private_email_routes as routes
        mailbox = patch.object(routes, "GraphMailbox", FakeMailbox)
        mailbox.start()
        self.addCleanup(mailbox.stop)
        where = patch.dict(os.environ, {"SDI_LIVE_ENQUIRY_ROOT": str(self.root)})
        where.start()
        self.addCleanup(where.stop)
        auth = Mock(current_user=Mock(return_value=claims),
                    graph_token=Mock(return_value="token"))
        pages = Path(self.temp.name) / "pages"
        pages.mkdir(exist_ok=True)
        (pages / "private-email-readonly.html").write_text("<p>stub", encoding="utf-8")
        app = FastAPI()
        app.include_router(routes.make_router(auth, Policy("tenant", "owner", True), None,
                                              "https://private.example.test",
                                              page_dir=pages))
        return TestClient(app)

    def post(self, body, headers=SAME, claims=OWNER):
        return self.client(claims).post("/api/private-email/file-for-estimating",
                                        json=body, headers=headers)

    BODY = {"message_id": "m1", "attachment_ids": ["a1", "a2"],
            "client": "Boots", "reference": "12552"}

    def test_saved_and_handed_the_link_that_opens_the_pack(self):
        r = self.post(self.BODY)
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual(sorted(out["saved"]), ["GA.pdf", "base.dxf"])
        self.assertEqual(out["estimate_url"], "/estimating?pack=Boots%2F12552")

    def test_one_unreadable_attachment_does_not_cost_the_others(self):
        r = self.post({**self.BODY, "attachment_ids": ["a1", "big"]})
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual(out["saved"], ["GA.pdf"])
        self.assertEqual(out["skipped"][0]["id"], "big")
        self.assertIn("25MB", out["skipped"][0]["why"])

    def test_from_another_site_nothing_is_written(self):
        r = self.post(self.BODY, headers={"Origin": "https://evil.test",
                                          "X-SDI-Private-Action": "1"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse((self.root / "Boots").exists())

    def test_only_the_owner(self):
        r = self.post(self.BODY, claims={**OWNER, "oid": "someone-else"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse((self.root / "Boots").exists())

    def test_it_never_touches_the_mailbox_beyond_reading(self):
        """It reads attachments and writes to the share. No draft, no send."""
        source = (BACKEND / "private_email_routes.py").read_text(encoding="utf-8")
        route = source.split("def file_for_estimating(", 1)[1].split("@router.", 1)[0]
        for verb in ("create_reply", "create_draft", "store.", "send"):
            self.assertNotIn(verb, route.replace("sender", ""))


class ThePageTests(unittest.TestCase):
    def test_it_offers_only_drawings(self):
        self.assertIn("const DRAWINGS=['.pdf','.dxf','.dwg','.sldprt','.sldasm','.slddrw',"
                      "'.step','.stp'];", PAGE)
        self.assertEqual(filing.DRAWINGS, ('.pdf', '.dxf', '.dwg', '.sldprt', '.sldasm',
                                           '.slddrw', '.step', '.stp'))

    def test_it_posts_the_write_with_the_confirmation_header(self):
        self.assertIn("api('/file-for-estimating',", PAGE)
        self.assertIn("'X-SDI-Private-Action':'1'", PAGE)

    def test_the_link_is_the_one_the_server_built(self):
        self.assertIn("link.href=r.estimate_url", PAGE)

    def test_the_job_number_is_a_suggestion_in_the_box(self):
        self.assertIn("job.value=guessJob(m.subject)", PAGE)


if __name__ == "__main__":
    unittest.main()
