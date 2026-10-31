"""SDI Remote Control Intelligence: it looks, and that is all it does.

"We need to set up a tunnel also for me to run these commands on the laptop and
server from my phone." Most of what that meant was four read-only checks that
cost a trip to the laptop all day: which commit is running, is the service up,
can it reach the shares, and what does the log say.

So it answers those four and is given no way to do anything else. An
authenticated "run anything" route on the public address would be the
highest-value target in the estate, and would undo the boundaries the rest of
this service spends its time holding.

The property that needed finding rather than designing: the access log carries
OAuth authorization codes, because uvicorn records whole request lines and the
private assistant's sign-in callback has code= in its query string. Serving a
log tail without redaction would have published them.
"""
import ast
import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import sdi_ops_routes as ops  # noqa: E402

SOURCE = (BACKEND / "sdi_ops_routes.py").read_text(encoding="utf-8")
PAGE = (BACKEND / "appportal" / "sdi-remote-control.html").read_text(encoding="utf-8")
APP = (BACKEND / "app.py").read_text(encoding="utf-8")
DEPLOY = (BACKEND / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")


class ItCannotActTests(unittest.TestCase):
    def test_the_only_write_is_the_restart(self):
        """Phase two, agreed 30 October: exactly one action. A second POST
        appearing here is a new remote control, and needs agreeing too."""
        posts = [node for node in ast.walk(ast.parse(SOURCE))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name) and node.func.value.id == "router"
                 and node.func.attr not in ("get",)]
        self.assertEqual(len(posts), 1, "a second non-GET route exists")
        self.assertEqual(posts[0].func.attr, "post")
        self.assertEqual(posts[0].args[0].value, "/restart")

    def test_the_restart_route_exists_only_when_switched_on(self):
        guarded = SOURCE.split("if restart_on:", 1)[1]
        self.assertIn('@router.post("/restart")', guarded[:80])

    def test_it_cannot_run_a_command_or_touch_a_service(self):
        for forbidden in ("subprocess", "os.system", "popen", "sc.exe",
                          "Restart-Service", "shutil", "os.remove", "rmtree"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, SOURCE)

    def test_it_cannot_write_anything(self):
        for writing in ("write_text", "write_bytes", '"w"', "'w'", "mkdir"):
            with self.subTest(writing=writing):
                self.assertNotIn(writing, SOURCE)

    def test_the_caller_cannot_name_a_file(self):
        """The log path is configuration. A caller supplies a line count and a
        search term, and nothing that is a location."""
        tree = ast.parse(SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                names = {a.arg for a in node.args.args}
                self.assertEqual(names & {"path", "file", "url", "cmd", "command"},
                                 set(), f"{node.name} accepts a location")

    def test_the_page_says_what_it_can_and_cannot_do(self):
        self.assertIn("can restart this one service and\n    nothing else", PAGE)
        self.assertIn("cannot run a command, change a setting or deploy", PAGE)
        self.assertIn("Remote Desktop", PAGE)


class TheLogIsRedactedTests(unittest.TestCase):
    """Found in today's own log, not imagined."""

    REAL = ('INFO:     10.0.0.5:58091 - "GET /api/private-email/auth/callback'
            '?code=1.ARAAklm08JRCIkma1YKZ7-D1f8ygfyb3OMJMmi1-zENq0jsAAJAQAA.BQAB'
            '&client_info=eyJ1aWQiOiI1YWNmNmIzNy0xNDdmIn0&state=4cRJOPwm HTTP/1.1" 302 Found')

    def test_an_authorization_code_never_leaves_the_machine(self):
        out = ops.redact(self.REAL)
        self.assertNotIn("1.ARAAklm08JRCIkma", out)
        self.assertNotIn("code=", out)
        self.assertNotIn("eyJ1aWQiOi", out)
        # Still useful: the path, the verb and the outcome survive.
        self.assertIn("/api/private-email/auth/callback", out)
        self.assertIn("302 Found", out)

    def test_named_secrets_are_removed_wherever_they_appear(self):
        # ── THE EXAMPLES ARE MADE UP, AND THAT IS NOT FUSSINESS ──────────────
        # The first draft of this test used the REAL client secret, copied from
        # where it should never have been either. GitHub's push protection
        # refused the commit and was right to. A test about not leaking secrets
        # is the last place to paste one.
        invented = "NOT-A-REAL-SECRET-0000000000000000000000"
        for line in (f"client_secret: {invented}",
                     "token=abc123def456", "PASSWORD: hunter2hunter2",
                     "sig=deadbeef"):
            with self.subTest(line=line):
                out = ops.redact(line)
                self.assertIn("[removed]", out)
                self.assertNotIn("hunter2hunter2", out)
                self.assertNotIn(invented, out)

    def test_a_long_token_shaped_string_goes_even_unnamed(self):
        out = ops.redact("bearer " + "A" * 60)
        self.assertNotIn("A" * 60, out)

    def test_an_ordinary_line_is_left_alone(self):
        plain = "[private-email] no usable session: the sign-in has expired."
        self.assertEqual(ops.redact(plain), plain)

    def test_redaction_happens_on_the_server_not_in_the_page(self):
        self.assertIn("redact(l)", SOURCE)
        self.assertNotIn("redact", PAGE)


class NamedPeopleTests(unittest.TestCase):
    def test_access_is_by_object_id_and_never_a_shared_key(self):
        gate = SOURCE.split("def allowed(", 1)[1].split("def log_path", 1)[0]
        self.assertIn("SDI_OPS_OIDS", gate)
        self.assertNotIn("x_sdi_key", gate)
        self.assertNotIn("API_KEY", gate)

    def test_nobody_named_means_nobody_in(self):
        os.environ.pop("SDI_OPS_OIDS", None)
        self.assertFalse(ops.allowed(object()))

    def test_every_route_is_gated(self):
        """who(request) is the first thing each route does, after its
        docstring - not merely somewhere in it."""
        found = {}
        for node in ast.walk(ast.parse(SOURCE)):
            if isinstance(node, ast.FunctionDef) and any(
                    isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and getattr(d.func.value, "id", "") == "router"
                    for d in node.decorator_list):
                body = [s for s in node.body if not (isinstance(s, ast.Expr)
                        and isinstance(getattr(s, "value", None), ast.Constant))]
                found[node.name] = ast.unparse(body[0])
        # The switched-off stub names two settings and nothing else, to anyone:
        # that is what SwitchedOffSaysSoTests below is about.
        found.pop("off", None)
        self.assertEqual(set(found), {"console", "status", "health", "tail",
                                      "person", "restart"})
        for name, first in found.items():
            with self.subTest(route=name):
                self.assertEqual(first, "who(request)")

    def test_it_is_mounted_only_when_switched_on(self):
        self.assertIn('env.get("SDI_OPS_ENABLED", "").lower() != "yes"', SOURCE)
        self.assertIn("install_ops(app)", APP)
        self.assertIn('"/api/ops"', APP)


class SettingsAreNamedNotShownTests(unittest.TestCase):
    def test_status_reports_whether_a_setting_is_set_not_its_value(self):
        status = SOURCE.split("def status(", 1)[1].split("@router.get", 1)[0]
        self.assertIn('bool((os.getenv(name) or "").strip())', status)
        # No os.getenv result reaches the response as a value.
        self.assertNotIn('os.getenv(name)}', status)
        self.assertIn("never their values", status)

    def test_the_secret_settings_are_among_those_only_named(self):
        self.assertIn('"SDI_API_KEY"', SOURCE)
        self.assertNotIn("SDI_PRIVATE_CLIENT_SECRET", PAGE)


class ItReachesTheServerTests(unittest.TestCase):
    def test_the_module_and_the_page_are_on_the_deploy(self):
        for name in ("sdi_ops_routes.py", "appportal/sdi-remote-control.html"):
            with self.subTest(file=name):
                self.assertIn(f'"{name}"', DEPLOY)

    def test_the_page_is_checked_for_at_startup(self):
        self.assertIn("must be deployed with the code", SOURCE)


if __name__ == "__main__":
    unittest.main()


class SwitchedOffSaysSoTests(unittest.TestCase):
    """── "NOT FOUND" IS THE WRONG ANSWER TO "IS IT ON?" ────────────────────
    With SDI_OPS_ENABLED unset, nothing was mounted, so the portal card opened
    and the browser showed {"detail":"Not Found"}. That reads as broken - a
    card for an app that does not exist - when the truth is that it is built
    and not switched on. The two need different people to fix them, and the
    page cannot tell you which it is if nothing answers.
    """

    def app_with(self, enabled):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        made = FastAPI()
        ops.install(made, env={"SDI_OPS_ENABLED": enabled} if enabled else {})
        return TestClient(made)

    def test_switched_off_it_explains_itself_rather_than_404(self):
        answer = self.app_with(None).get("/api/ops")
        self.assertEqual(answer.status_code, 503)
        detail = answer.json()["detail"]
        self.assertIn("not", detail.lower())
        self.assertIn("SDI_OPS_ENABLED", detail)
        self.assertIn("SDI_OPS_OIDS", detail)
        self.assertIn("restart", detail.lower())

    def test_every_path_under_it_says_the_same_thing(self):
        client = self.app_with(None)
        for path in ("/api/ops", "/api/ops/status", "/api/ops/health",
                     "/api/ops/log?lines=40"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 503)

    def test_the_explanation_names_settings_and_never_their_values(self):
        """An unconfigured app saying so is not a leak. Saying what is IN the
        settings would be."""
        detail = self.app_with(None).get("/api/ops").json()["detail"]
        for leak in ("=yes", "oid", "@", "10.0.0", "C:\\"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, detail.replace("SDI_OPS_ENABLED=yes", ""))

    def test_switched_on_it_is_the_real_console(self):
        """The stub must not be what gets mounted when it IS switched on."""
        import os
        os.environ["SDI_OPS_OIDS"] = "somebody"
        self.addCleanup(os.environ.pop, "SDI_OPS_OIDS", None)
        answer = self.app_with("yes").get("/api/ops/status")
        # Not 503-with-an-explanation: the real routes are gated, so a stranger
        # is refused by the object-ID list instead.
        self.assertEqual(answer.status_code, 403)
