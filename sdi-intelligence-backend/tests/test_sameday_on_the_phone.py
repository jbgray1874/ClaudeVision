"""SDI SameDay on the phone, carried by SDI Intelligence at /sameday/ (sameday_proxy.py).

"The app needs to work on the phone" - James Gray, 4 November 2026. SDI Intelligence already reaches phones (App
Proxy: https, Microsoft sign-in); SameDay is only on 127.0.0.1:5020. What must hold: from outside, only a person
signed in with their SDI account; this portal's sign-in cookie never reaches SameDay; SameDay is told the address it
is carried at, so its page asks for /sameday/... and never this portal's own /api/...

SameDay is replaced by a stand-in (httpx.MockTransport) that records what it was sent.
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import auth  # noqa: E402
import sameday_proxy as sd  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PUBLIC = "sdiintelligence.example.net"
ME = {"name": "James Gray", "email": "james@example.com", "oid": "1", "kind": "user"}


class Base(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.answer = lambda req: httpx.Response(200, headers={"content-type": "text/html"}, text="<p>SameDay</p>")

        def handler(req):
            self.sent.append(req)
            return self.answer(req)
        sd._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.saved = (auth.current_user, auth.PUBLIC_HOSTS, auth.ENABLED)
        auth.PUBLIC_HOSTS = {PUBLIC}
        auth.ENABLED = True
        self.user = ME
        auth.current_user = lambda request: (self.user if auth.request_host(request) == PUBLIC else
                                             {"name": "Office network (not signed in)", "kind": "anonymous"})
        app = FastAPI()
        sd.install(app)
        self.c = TestClient(app, follow_redirects=False)

    def tearDown(self):
        auth.current_user, auth.PUBLIC_HOSTS, auth.ENABLED = self.saved
        asyncio.run(sd._client.aclose())
        sd._client = None

    def outside(self, method, path, **kw):
        h = dict(kw.pop("headers", {}), host=PUBLIC)
        return self.c.request(method, path, headers=h, **kw)


class WhoGetsInTests(Base):
    def test_signed_in_on_a_phone(self):
        r = self.outside("GET", "/sameday/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("SameDay", r.text)

    def test_signed_out_is_sent_to_sign_in_and_back(self):
        self.user = None
        r = self.outside("GET", "/sameday/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/auth/login?next=%2Fsameday%2F", r.headers["location"])
        self.assertEqual(self.sent, [])
        r = self.outside("POST", "/sameday/api/chat", json={})
        self.assertEqual(r.status_code, 401)

    def test_the_service_key_is_not_a_person(self):
        self.user = {"name": "Service account (X-SDI-Key)", "kind": "machine"}
        self.assertEqual(self.outside("GET", "/sameday/").status_code, 403)
        self.assertEqual(self.sent, [])

    def test_never_open_to_the_internet_where_sign_in_is_not_set_up(self):
        auth.ENABLED = False
        self.user = {"name": "Unauthenticated (SSO not configured)", "kind": "anonymous"}
        self.assertEqual(self.outside("GET", "/sameday/").status_code, 403)

    def test_a_write_from_another_site_is_refused(self):
        r = self.outside("POST", "/sameday/api/chat", json={}, headers={"origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.sent, [])
        r = self.outside("POST", "/sameday/api/chat", json={"t": 1}, headers={"origin": "https://" + PUBLIC})
        self.assertEqual(r.status_code, 200)

    def test_the_office_address_sends_the_page_to_microsoft_sign_in(self):
        """8 Nov 2026 (James: "why does it think I'm Andy ... it needs to read the person who is logged in"): the office
        address is plain http, so nobody is signed in there. The page goes to the published https address, where
        Microsoft 365 says who it is - the same page, the same query."""
        r = self.c.get("/sameday/?s=abc", headers={"host": "10.0.0.5:8071"})
        self.assertEqual((r.status_code, r.headers["location"]), (302, f"https://{PUBLIC}/sameday/?s=abc"))
        self.assertEqual(self.sent, [])                                    # SDI Live never saw an unnamed visit

    def test_the_checks_on_the_office_address_carry_on(self):
        r = self.c.get("/sameday/api/version", headers={"host": "10.0.0.5:8071"})      # the watch and the laptop scripts
        self.assertEqual(r.status_code, 200)

    def test_it_can_be_turned_off_and_does_nothing_where_nothing_is_published(self):
        os.environ["SDI_SAMEDAY_OFFICE_SIGNIN"] = "no"
        try:
            self.assertEqual(self.c.get("/sameday/", headers={"host": "10.0.0.5:8071"}).status_code, 200)
        finally:
            os.environ.pop("SDI_SAMEDAY_OFFICE_SIGNIN", None)
        auth.PUBLIC_HOSTS = set()
        self.assertEqual(self.c.get("/sameday/", headers={"host": "10.0.0.5:8071"}).status_code, 200)


class WhatSameDayIsSentTests(Base):
    def test_the_prefix_and_the_exact_address(self):
        self.outside("GET", "/sameday/file?p=C%3A%5Cout%5Ca%20b.png")
        req = self.sent[0]
        self.assertEqual(str(req.url), sd.UPSTREAM + "/file?p=C%3A%5Cout%5Ca%20b.png")
        self.assertEqual(req.headers["x-forwarded-prefix"], "/sameday")
        self.assertEqual(req.headers["x-forwarded-proto"], "https")
        self.assertEqual(req.headers["x-sdi-user"], "james@example.com")

    def test_never_this_portals_sign_in_cookie(self):
        self.outside("GET", "/sameday/api/status", headers={"cookie": "sdi_session=secret-value; other=1",
                                                            "authorization": "Bearer x", "x-sdi-key": "k"})
        req = self.sent[0]
        for h in ("cookie", "authorization", "x-sdi-key"):
            self.assertNotIn(h, req.headers)

    def test_an_upload_arrives_whole(self):
        body = b"--b\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.pdf\"\r\n\r\n%PDF-1\r\n--b--\r\n"
        self.outside("POST", "/sameday/api/upload", content=body, headers={
            "origin": "https://" + PUBLIC, "content-type": "multipart/form-data; boundary=b"})
        self.assertEqual(self.sent[0].content, body)
        self.assertEqual(self.sent[0].headers["content-type"], "multipart/form-data; boundary=b")

    def test_the_bare_address_goes_to_the_page(self):
        r = self.outside("GET", "/sameday")
        self.assertEqual((r.status_code, r.headers["location"]), (308, "/sameday/"))


class WhatComesBackTests(Base):
    def test_a_redirect_and_the_service_worker_stay_under_sameday(self):
        self.answer = lambda req: httpx.Response(302, headers={"location": "/", "service-worker-allowed": "/",
                                                               "set-cookie": "lite_access=x; Path=/"})
        r = self.outside("GET", "/sameday/unlock")
        self.assertEqual(r.headers["location"], "/sameday/")
        self.assertEqual(r.headers["service-worker-allowed"], "/sameday/")
        self.assertNotIn("set-cookie", r.headers)

    def test_a_render_comes_back_as_it_is(self):
        png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 50
        self.answer = lambda req: httpx.Response(200, headers={"content-type": "image/png"}, content=png)
        r = self.outside("GET", "/sameday/file?p=x")
        self.assertEqual(r.content, png)
        self.assertEqual(r.headers["content-type"], "image/png")

    def test_sameday_not_running_is_said_plainly(self):
        def down(req):
            raise httpx.ConnectError("refused", request=req)
        self.answer = down
        r = self.outside("GET", "/sameday/")
        self.assertEqual(r.status_code, 503)
        self.assertIn("SameDay isn't answering", r.text)
        r = self.outside("GET", "/sameday/api/status")
        self.assertEqual(r.status_code, 503)
        self.assertIn("error", r.json())


class WiredInTests(unittest.TestCase):
    SRC = (BACKEND / "app.py").read_text(encoding="utf-8")

    def test_the_public_surface_lets_it_through_and_the_route_checks_who(self):
        allow = self.SRC.split("_PUBLIC_ALLOW = (", 1)[1].split(")", 1)[0]
        self.assertIn('"/sameday",', allow)
        self.assertIn("from sameday_proxy import install as install_sameday", self.SRC)
        self.assertIn("install_sameday(app)", self.SRC)

    def test_every_sdi_live_file_is_on_the_deploy(self):
        """8 Nov 2026 ("stillandy..."): sameday_proxy.py was on no deploy list, so Ship-It said all ok and the server
        kept the old one - the office address never went to sign-in."""
        deploy = (BACKEND / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")
        listed = deploy.split("$Files = @(", 1)[1].split("\n)", 1)[0]
        for f in sorted(BACKEND.glob("sameday_*.py")):
            with self.subTest(file=f.name):
                self.assertIn(f'"{f.name}"', listed)

    def test_it_can_be_switched_off(self):
        old = os.environ.get("SDI_SAMEDAY_ENABLED")
        os.environ["SDI_SAMEDAY_ENABLED"] = "no"
        try:
            app = FastAPI()
            sd.install(app)
            self.assertFalse([r for r in app.routes if getattr(r, "path", "").startswith("/sameday")])
        finally:
            if old is None:
                os.environ.pop("SDI_SAMEDAY_ENABLED", None)
            else:
                os.environ["SDI_SAMEDAY_ENABLED"] = old

    def test_it_only_ever_talks_to_sameday(self):
        self.assertEqual(sd.UPSTREAM, os.getenv("SDI_SAMEDAY_UPSTREAM", "http://127.0.0.1:5020").rstrip("/"))
        req = type("R", (), {})()
        req.scope = {"raw_path": b"/sameday//evil.example/x"}
        req.url = type("U", (), {"path": "/sameday//evil.example/x", "query": ""})()
        self.assertTrue(sd.upstream_url(req).startswith(sd.UPSTREAM + "/"))


if __name__ == "__main__":
    unittest.main()
