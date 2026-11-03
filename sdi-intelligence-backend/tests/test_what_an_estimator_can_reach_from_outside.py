"""The remote estimating boundary: reads by method, writes only where named.

26 October 2026. The staged change opened `/api/estimate` to named estimators
on the public address. The prefix is shared, so that also opened:

    /release and /release/withdraw   release a quotation to a customer
    /{run_id}/email                  email one out
    /recipients                      change who quotes are emailed to
    /self-running/start and /stop    the autonomous estimator's switch
    /logistics/split-scans           the delivery-note splitter

- along with /api/roots, /api/files and /api/file, which read every configured
share. The plan this was built to said "separate permissions for viewing,
starting a run and releasing or emailing a quote", and "without becoming a
browser for the whole K: drive". Both boundaries were open.

These are the two rules that close them, and the reason they live in a module
of their own: middleware on a running service cannot be exercised in a test,
and a rule nobody can exercise is a rule that drifts.
"""
import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import public_surface as surface  # noqa: E402

APP = (BACKEND / "app.py").read_text(encoding="utf-8")


class WritesTests(unittest.TestCase):
    def test_starting_work_and_asking_about_it_are_allowed(self):
        for path in ("/api/estimate", "/api/estimate/brief",
                     "/api/estimate/tools/ask", "/api/estimate/"):
            with self.subTest(path=path):
                self.assertTrue(surface.post_allowed(path))

    def test_releasing_emailing_and_the_switches_are_not(self):
        """The things a phone must not be a remote control for."""
        for path in surface.NEVER_PUBLIC_POST + (
                "/api/estimate/12345/email",
                "/api/estimate/12345/abandon",
                "/api/estimate/batch",
                "/api/estimate/llm",
                "/api/estimate/dm/extract",
                "/api/estimate/drawings/print"):
            with self.subTest(path=path):
                self.assertFalse(surface.post_allowed(path), path)

    def test_a_post_nobody_has_reviewed_is_refused(self):
        """The direction that matters: an endpoint added next month is closed
        until somebody puts it on the list deliberately."""
        for invented in ("/api/estimate/something-new",
                         "/api/estimate/tools/delete-everything",
                         "/api/estimate/v2/release"):
            with self.subTest(path=invented):
                self.assertFalse(surface.post_allowed(invented))

    def test_the_never_list_and_the_allow_list_do_not_overlap(self):
        self.assertFalse(set(surface.NEVER_PUBLIC_POST) & set(surface.PUBLIC_POST))

    def test_nothing_sneaks_through_on_spelling(self):
        for odd in ("/api/estimate/release/", "//api/estimate/release",
                    "/API/ESTIMATE/RELEASE", "/api/estimate/release?x=1",
                    "/api/estimate/../estimate/release", "", None):
            with self.subTest(path=odd):
                self.assertFalse(surface.post_allowed(odd))


class FileBrowserTests(unittest.TestCase):
    ROOT = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Live Enquiries\completed AI briefs"

    def setUp(self):
        os.environ["SDI_COMPLETED_AI_BRIEFS_ROOT"] = self.ROOT
        self.addCleanup(os.environ.pop, "SDI_COMPLETED_AI_BRIEFS_ROOT", None)

    def test_the_approved_folder_and_what_is_under_it(self):
        for inside in (self.ROOT, self.ROOT + "\\Harrods",
                       self.ROOT + "\\Harrods\\9439-07-04\\GA.pdf",
                       self.ROOT + "\\"):
            with self.subTest(path=inside):
                self.assertTrue(surface.under_the_briefs(inside))

    def test_every_other_share_is_refused(self):
        for outside in (r"\\sdi-dc01\shareddata$\Shared\Estimating",
                        r"\\sdi-dc01\shareddata$\Shared\HR",
                        r"\\sdi-dc01\shareddata$",
                        r"C:\ClaudeVision\sdi-intelligence-backend\.env",
                        r"\\another-server\share", "K:\\", ""):
            with self.subTest(path=outside):
                self.assertFalse(surface.under_the_briefs(outside))

    def test_a_name_that_merely_starts_the_same_is_outside(self):
        """"...completed AI briefs backup" is a different folder."""
        self.assertFalse(surface.under_the_briefs(self.ROOT + " backup"))
        self.assertFalse(surface.under_the_briefs(self.ROOT + "-old\\x.pdf"))

    def test_traversal_cannot_walk_out(self):
        for walk in (self.ROOT + r"\..\..\HR",
                     self.ROOT + r"\Harrods\..\..\..\payroll.xlsx",
                     self.ROOT + r"\.."):
            with self.subTest(path=walk):
                self.assertFalse(surface.under_the_briefs(walk))

    def test_the_default_root_has_the_shared_prefix(self):
        """It was missing, and the resulting error reads as a permissions
        problem on a share whose permissions are fine."""
        os.environ.pop("SDI_COMPLETED_AI_BRIEFS_ROOT", None)
        self.assertIn(r"shareddata$\Shared\Estimating", surface.briefs_root())


class TheGuardUsesThemTests(unittest.TestCase):
    """The rules above are only worth anything if the middleware applies them."""

    def test_the_guard_checks_both_before_letting_an_estimating_path_through(self):
        guard = APP.split("async def _public_surface_guard", 1)[1].split("\n# ──", 1)[0]
        self.assertIn("_public_post_allowed(path)", guard)
        self.assertIn("_under_the_briefs(", guard)
        self.assertIn('request.query_params.get("path"', guard)

    def test_the_write_check_sits_inside_the_non_read_branch(self):
        """A GET must not be made to pass a POST allow-list, or the screen
        stops working; a POST must not skip it."""
        guard = APP.split("async def _public_surface_guard", 1)[1]
        methods = guard.index('request.method not in ("GET", "HEAD", "OPTIONS")')
        checked = guard.index("_public_post_allowed(path)")
        confined = guard.index("_under_the_briefs(")
        self.assertLess(methods, checked)
        self.assertLess(checked, confined)

    def test_the_runner_paths_are_still_invisible(self):
        self.assertIn("_RUNNER_ONLY", APP)
        self.assertIn('"/api/estimate/runner"', APP)
        self.assertIn('"/api/estimate/self-running/heartbeat"', APP)

    def test_the_estimating_paths_are_named_and_nothing_wider(self):
        line = [l for l in APP.splitlines() if l.startswith("_PUBLIC_ESTIMATING =")][0]
        for allowed in ("/estimating", "/api/estimate", "/api/roots",
                        "/api/files", "/api/file"):
            self.assertIn(f'"{allowed}"', line)
        for never in ("/api/db", "/api/hr", "/api/change-register", "/workflow"):
            self.assertNotIn(never, line)


if __name__ == "__main__":
    unittest.main()


class BothApprovedAreasTests(unittest.TestCase):
    """The scanner grew a second folder; the public boundary has to know about
    it, or the drawings button works in the office and 403s on a phone."""

    BRIEFS = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Live Enquiries\completed AI briefs"
    ENQUIRY = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry"

    def setUp(self):
        for key in ("SDI_COMPLETED_AI_BRIEFS_ROOT", "SDI_LIVE_ENQUIRY_ROOT"):
            os.environ.pop(key, None)
            self.addCleanup(os.environ.pop, key, None)

    def test_both_approved_trees_are_reachable(self):
        for inside in (self.BRIEFS, self.BRIEFS + r"\Harrods\9439-07-04-GA\report.html",
                       self.ENQUIRY, self.ENQUIRY + r"\Boots\1234-01\GA.pdf"):
            with self.subTest(path=inside):
                self.assertTrue(surface.under_the_briefs(inside))

    def test_their_shared_parent_is_not(self):
        """Both sit under ...\\Estimating\\Completed. That parent holds other
        things and is not approved."""
        for outside in (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed",
                        r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating",
                        r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Live Enquiries"):
            with self.subTest(path=outside):
                self.assertFalse(surface.under_the_briefs(outside))

    def test_the_second_root_can_be_moved_without_a_code_change(self):
        os.environ["SDI_LIVE_ENQUIRY_ROOT"] = r"\\other\share\enquiries"
        self.assertTrue(surface.under_the_briefs(r"\\other\share\enquiries\Boots"))
        self.assertFalse(surface.under_the_briefs(self.ENQUIRY + r"\Boots"))


class NoLoginLoopTests(unittest.TestCase):
    """"For estimating it keeps bringing up the wearesdi login screen."

    26 October 2026, from a phone. The guard sent anyone who was not an
    estimator to sign in - including people already signed in. They came back,
    were still not on the list, and were sent again. Signing in cannot fix not
    being on a list, and on a phone the loop reads as a broken app with nothing
    to click and nothing to read.
    """

    GUARD = APP.split("async def _public_surface_guard", 1)[1].split("\n# ──", 1)[0]

    def test_only_somebody_not_signed_in_is_sent_to_sign_in(self):
        self.assertIn("signed_in is None", self.GUARD)
        redirect = self.GUARD.index("auth.login_redirect(request)")
        checked = self.GUARD.index("signed_in = auth.current_user")
        self.assertLess(checked, redirect, "it must know who you are first")

    def test_an_authenticated_outsider_is_told_why(self):
        """The sentence moved into access.why_refused, which every gated app
        now shares - so the test follows it there rather than pinning a copy
        of the words in app.py that would drift from the one people read."""
        self.assertIn('access.why_refused("SDI_ESTIMATOR_OIDS", signed_in)', self.GUARD)
        import sys
        sys.path.insert(0, str(BACKEND))
        import access
        said = access.why_refused("SDI_ESTIMATOR_OIDS",
                                  {"kind": "user", "oid": "somebody",
                                   "groups": ["a-group"]},
                                  env={"SDI_ESTIMATOR_OIDS": "someone-else"})
        self.assertIn("not on the list", said)
        self.assertIn("/api/me", said)
        self.assertIn("an admin account is a different account", said)

    def test_the_answer_is_still_403_and_not_a_redirect(self):
        after = self.GUARD.split("signed_in is not None", 1)[1][:400]
        self.assertIn("status_code=403", after)
        self.assertNotIn("login_redirect", after)


class LookingAndDoingAreDifferentPermissionsTests(unittest.TestCase):
    """── WHY THE LIST MOVED OFF THE SCREEN AND ONTO THE EXPENSIVE VERB ────
    "I was able to use and see estimating before without this environmental
    variable OIDS nonsense" - true, and the list arrived WITH putting
    estimating on the internet rather than being taken from anybody.

    But the AM CRM app, live for weeks, has no allow-list at all: anyone who
    can sign in reads it, what they see is filtered, and only named people may
    CHANGE anything. That is the house pattern, and a list standing between an
    employee and a screen they are allowed to look at was the wrong shape.

    So: looking is open to anyone signed in, and the one verb out here that
    queues work on a machine in the office and costs money is named-people
    only. Everything genuinely dangerous was already refused by path.
    """

    GUARD = APP.split("async def _public_surface_guard", 1)[1].split("\n# ──", 1)[0]
    LOOK = APP.split("def _public_estimator(", 1)[1].split("\ndef ", 1)[0]
    DO = APP.split("def _may_start_a_run(", 1)[1].split("\n\n@", 1)[0]

    def test_looking_needs_only_a_signed_in_person(self):
        self.assertIn("return True", self.LOOK)
        self.assertIn('user.get("kind") != "user"', self.LOOK)

    def test_looking_can_still_be_narrowed_if_it_is_ever_wanted(self):
        self.assertIn("SDI_ESTIMATOR_VIEWERS", self.LOOK)

    def test_starting_a_run_is_named_people_only(self):
        self.assertIn('access.may_use("SDI_ESTIMATOR_OIDS"', self.DO)

    def test_the_two_posts_that_queue_work_are_the_ones_held_to_the_list(self):
        named = APP.split("STARTS_A_RUN = (", 1)[1].split(")", 1)[0]
        self.assertIn('"/api/estimate"', named)
        self.assertIn('"/api/estimate/brief"', named)
        # Asking a question of a filed record queues nothing, so it is not
        # held to the list - that is the whole point of the split.
        self.assertNotIn("tools/ask", named)

    def test_the_check_sits_after_the_post_allow_list_not_before_it(self):
        """A POST nobody reviewed must be refused whoever is asking, before
        the question of who they are even arises."""
        allowed = self.GUARD.index("_public_post_allowed(path)")
        started = self.GUARD.index("STARTS_A_RUN")
        self.assertLess(allowed, started)

    def test_nothing_dangerous_became_reachable(self):
        """The split changes who may LOOK, not what may be done."""
        import public_surface
        self.assertEqual(public_surface.PUBLIC_POST,
                         ("/api/estimate", "/api/estimate/brief",
                          "/api/estimate/tools/ask", "/api/estimate/parity/job",
                          "/api/estimate/parity/period", "/api/estimate/parity/periods",
                          "/api/estimate/parity/ask",
                          "/api/estimate/self-running/start",
                          "/api/estimate/self-running/stop"))
        for never in public_surface.NEVER_PUBLIC_POST:
            with self.subTest(path=never):
                self.assertFalse(public_surface.post_allowed(never))

    def test_a_key_is_still_never_a_person(self):
        """auth.current_user returns a dict for an API key too; looking must
        not be opened to one just because the list is empty."""
        self.assertIn('user.get("kind") != "user"', self.LOOK)

    def test_the_refusal_says_which_half_was_refused(self):
        after = self.GUARD.split("STARTS_A_RUN", 1)[1][:600]
        self.assertIn("Looking is open to anyone signed in", after)
        self.assertIn("STARTING a run", after)


class TheEmailsQuestionScreenTests(unittest.TestCase):
    """D-613, 1 November 2026: the finished-estimate e-mail's button opens the
    estimate's question screen on a phone, through this address, with no VPN.
    Three things stood between the button and the answer: a signed-out phone
    got a 403 in JSON instead of the sign-in page, every estimating call
    answered 503 "Estimator API is not configured" because no SDI_API_KEY was
    set, and the question itself is a POST nobody had put on the list."""

    GUARD = APP.split("async def _public_surface_guard", 1)[1].split("\n# ──", 1)[0]
    TOKEN = "AbCdEfGhIjKlMnOpQrStUv"

    def test_a_question_from_the_email_page_is_allowed(self):
        self.assertTrue(surface.post_allowed(f"/api/estimate/walkthrough/{self.TOKEN}/ask"))
        self.assertTrue(surface.post_allowed(f"/api/estimate/walkthrough/{self.TOKEN}/ask/"))

    def test_nothing_else_under_walkthrough_is_opened_by_it(self):
        for path in (f"/api/estimate/walkthrough/{self.TOKEN}",
                     f"/api/estimate/walkthrough/{self.TOKEN}/file/x.xlsx",
                     f"/api/estimate/walkthrough/{self.TOKEN}/ask/more",
                     "/api/estimate/walkthrough/short/ask",
                     "/api/estimate/walkthrough/../release/ask",
                     f"/api/estimate/walkthrough/{self.TOKEN}/../../release",
                     f"/API/ESTIMATE/WALKTHROUGH/{self.TOKEN}/ASK",
                     f"/x/api/estimate/walkthrough/{self.TOKEN}/ask",
                     f"/api/estimate/walkthrough/{'A' * 65}/ask"):
            with self.subTest(path=path):
                self.assertFalse(surface.post_allowed(path), path)

    def test_the_never_list_is_still_refused(self):
        for path in surface.NEVER_PUBLIC_POST:
            with self.subTest(path=path):
                self.assertFalse(surface.post_allowed(path))

    def test_a_signed_out_phone_is_sent_to_sign_in_for_any_estimating_page(self):
        self.assertIn('path.startswith("/estimating/")', self.GUARD)
        branch = self.GUARD.split('path.startswith("/estimating/")', 1)[1][:300]
        self.assertIn('request.method in ("GET", "HEAD")', branch)
        self.assertIn("signed_in is None", branch)
        self.assertIn("auth.login_redirect(request)", branch)

    def test_no_key_to_translate_is_not_a_503(self):
        estimate = self.GUARD.split('if path == "/api/estimate" or path.startswith("/api/estimate/"):', 1)[1]
        estimate = estimate.split("return await call_next(request)", 1)[0]
        self.assertIn("if config.API_KEY:", estimate)
        self.assertNotIn("if not config.API_KEY:", estimate)
        refusal = estimate.split('elif getattr(config, "PARTNER_KEYS", None):', 1)[1]
        self.assertIn("status_code=503", refusal)
        self.assertIn("Set SDI_API_KEY", refusal)


class ParityFromOutsideTests(unittest.TestCase):
    """D-619/D-621, 1 November 2026: parity "in the web portal inside the network or on VPN,
    and also the phone or tablet with only wifi or data". The review: do not broaden access;
    a filed comparison holds copies of the manual costing sheets. So from outside, running a
    comparison, reading the filed ones and opening any file in the parity folder are all held
    to the named estimators, as starting a run is."""

    GUARD = APP.split("async def _public_surface_guard", 1)[1].split("\n# ──", 1)[0]

    def test_the_three_comparisons_are_named_and_the_upload_stays_inside(self):
        import public_surface
        self.assertEqual(public_surface.PARITY_POST,
                         ("/api/estimate/parity/job", "/api/estimate/parity/period",
                          "/api/estimate/parity/periods", "/api/estimate/parity/ask"))
        for path in public_surface.PARITY_POST:
            self.assertTrue(public_surface.post_allowed(path))
        self.assertIn("/api/estimate/parity", public_surface.NEVER_PUBLIC_POST)
        self.assertFalse(public_surface.post_allowed("/api/estimate/parity"))

    def test_every_parity_route_and_file_is_named_people_only(self):
        gate = self.GUARD.split("PARITY IS FOR THE NAMED ESTIMATORS", 1)[1][:900]
        self.assertIn("_is_parity(path)", gate)
        self.assertIn('_under_parity(\n                        request.query_params.get("path", ""))', gate)
        self.assertIn("not _may_start_a_run(request)", gate)
        self.assertIn("parity is for the named estimators", gate)

    def test_the_gate_names_reads_as_well_as_runs(self):
        import public_surface
        for path in ("/api/estimate/parity/find", "/api/estimate/parity/reports",
                     "/api/estimate/parity/task/ab12cd34", "/api/estimate/parity/job"):
            self.assertTrue(public_surface.is_parity(path))
        self.assertFalse(public_surface.is_parity("/api/estimate/parityx"))

    def test_the_filed_comparisons_are_in_the_parity_folder_and_manual_estimates_are_not(self):
        import public_surface
        report = (public_surface.PARITY_DEFAULT
                  + r"\Acme\12677-01-GA\2026-11-01 14-05-00_ab12cd34\12677.full_parity.html")
        self.assertTrue(public_surface.under_parity(report))
        self.assertTrue(public_surface.under_the_briefs(report))
        self.assertFalse(public_surface.under_parity(public_surface.PARITY_DEFAULT + r" backup\x.html"))
        manual = (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates"
                  r"\2026\Acme\12677\12677.xls")
        self.assertFalse(public_surface.under_the_briefs(manual))


class TheSelfRunningSwitchFromThePhoneTests(unittest.TestCase):
    """D-641, 3 November 2026. JG: "open the self-running controls from outside... needs to
    run from the phone". The switch was on NEVER_PUBLIC_POST, so a phone got "That action is
    only available on the office network". Switching it on queues estimates, so it is opened
    to the people who may start a run and nobody else; the watcher's heartbeat and stopping a
    single running job stay inside the office."""

    GUARD = APP.split("async def _public_surface_guard", 1)[1].split("\n# ──", 1)[0]

    def test_the_switch_may_be_pressed_from_outside(self):
        for path in ("/api/estimate/self-running/start", "/api/estimate/self-running/stop",
                     "/api/estimate/self-running/start/"):
            with self.subTest(path=path):
                self.assertTrue(surface.post_allowed(path))

    def test_it_is_held_to_the_named_estimators(self):
        self.assertEqual(surface.SELF_RUNNING_POST,
                         ("/api/estimate/self-running/start",
                          "/api/estimate/self-running/stop"))
        at = self.GUARD.index("in _SELF_RUNNING_POST and not _may_start_a_run(request)")
        self.assertLess(self.GUARD.index("_public_post_allowed(path)"), at)
        self.assertIn("limited to the named estimators", self.GUARD[at:at + 600])

    def test_the_watchers_beat_and_stopping_a_job_stay_inside(self):
        self.assertIn("/api/estimate/self-running/heartbeat", surface.NEVER_PUBLIC_POST)
        self.assertFalse(surface.post_allowed("/api/estimate/self-running/heartbeat"))
        self.assertFalse(surface.post_allowed("/api/estimate/12345abcdef0/abandon"))
        self.assertIn('"/api/estimate/self-running/heartbeat"', APP.split("_RUNNER_ONLY = (", 1)[1][:200])

    def test_the_refusal_no_longer_names_the_switch(self):
        refusal = self.GUARD.split("only available on the office network", 1)[1][:200]
        self.assertNotIn("self-running", refusal)
