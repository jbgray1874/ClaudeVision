"""Sue's TTI despatch view: named people, one workbook, and no writer at all.

Phase one of the TTI app. Sue Rogers, 26 October 2026, asked whether AI could
help with four trackers; this answers the first question - "what is due to
leave SDI on a day?" - and deliberately stops there.

The properties worth holding, in the order they would hurt:

  * there is NO writer. Completed Orders could not even be read when the pilot
    was written, and what counts as "dispatched" is Sue's to define, so the
    transfer half is written and not mounted;
  * the caller never names a file. The workbook is configuration, so this is
    one question about one known tracker rather than a spreadsheet reader
    pointed wherever a URL says;
  * it is for named Customer Services people, by Entra object ID, never a
    shared key - a live commercial tracker should have attributable reads;
  * the answer says which save of the plan it came from, because an answer is
    only as current as the copy behind it.
"""
import ast
import sys
import unittest
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

ROUTES = (BACKEND / "tti_despatch_routes.py").read_text(encoding="utf-8")
LOGIC = (BACKEND / "sue_despatch.py").read_text(encoding="utf-8")
READER = (BACKEND / "tracker_snapshot.py").read_text(encoding="utf-8")
PAGE = (BACKEND / "appportal" / "tti-despatch.html").read_text(encoding="utf-8")
APP = (BACKEND / "app.py").read_text(encoding="utf-8")
DEPLOY = (BACKEND / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")


class NoWriterTests(unittest.TestCase):
    def test_the_transfer_half_is_not_mounted(self):
        """It exists, it is tested, and nothing can call it over HTTP yet.

        Read as CODE: the docstring at the top of the routes names the function
        precisely to say it is NOT wired up, and a text match would pass on the
        comment that explains the rule rather than on the rule."""
        self.assertIn("def propose_completed_transfer", LOGIC)
        tree = ast.parse(ROUTES)
        imported, called = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.Call):
                target = node.func
                name = getattr(target, "id", None) or getattr(target, "attr", None)
                if name:
                    called.add(name)
        self.assertNotIn("propose_completed_transfer", imported)
        self.assertNotIn("propose_completed_transfer", called)
        self.assertEqual(imported & {"sue_despatch", "tracker_snapshot"}, set(),
                         "import the one function needed, not the module")
        self.assertIn("going_out", imported)
        self.assertNotIn("propose_completed_transfer", PAGE)

    def test_every_route_is_a_get(self):
        tree = ast.parse(ROUTES)
        verbs = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id == "router":
                verbs.add(node.attr)
        self.assertEqual(verbs, {"get"}, f"a non-GET route exists: {verbs}")

    def test_nothing_in_the_logic_can_write_or_send(self):
        for module, source in (("sue_despatch", LOGIC), ("tracker_snapshot", READER),
                               ("tti_despatch_routes", ROUTES)):
            with self.subTest(module=module):
                for forbidden in ("sendMail", "createReply", ".save(", "shutil",
                                  "open(" if module == "sue_despatch" else "\0"):
                    self.assertNotIn(forbidden, source)

    def test_the_workbook_is_opened_read_only(self):
        self.assertIn("read_only=True", READER)
        self.assertIn("data_only=True", READER)


class TheCallerNeverNamesAFileTests(unittest.TestCase):
    def test_the_only_thing_a_request_carries_is_a_date(self):
        handler = ROUTES.split("def leaving_on(", 1)[1].split("\n    return router", 1)[0]
        self.assertIn("day: str = Query(", ROUTES)
        self.assertIn("date.fromisoformat(day)", handler)
        # The path comes from configuration, not from the request.
        self.assertIn("plan_path()", handler)
        self.assertNotIn("Query(..., max_length=512)", handler)

    def test_an_unparseable_date_is_refused_rather_than_guessed(self):
        self.assertIn("A date is needed, as YYYY-MM-DD", ROUTES)

    def test_an_unconfigured_plan_says_so_instead_of_failing_obscurely(self):
        self.assertIn("SDI_TTI_DESPATCH_PLAN", ROUTES)
        self.assertIn("has not been configured", ROUTES)


class NamedPeopleTests(unittest.TestCase):
    def test_access_is_by_object_id_and_never_a_shared_key(self):
        gate = ROUTES.split("def allowed(", 1)[1].split("def make_router", 1)[0]
        self.assertIn("SDI_TTI_OIDS", gate)
        self.assertIn('user.get("kind") == "user"', gate)
        self.assertNotIn("x_sdi_key", gate)
        self.assertNotIn("API_KEY", gate)

    def test_nobody_named_means_nobody_in(self):
        """An empty list must deny, not admit everyone."""
        import tti_despatch_routes as routes
        import os
        os.environ.pop("SDI_TTI_OIDS", None)
        self.assertFalse(routes.allowed(object()))

    def test_both_routes_are_gated(self):
        for handler in ("def despatch(", "def leaving_on("):
            body = ROUTES.split(handler, 1)[1][:400]
            with self.subTest(handler=handler):
                self.assertIn("who(request)", body)

    def test_it_is_mounted_only_when_switched_on(self):
        self.assertIn('env.get("SDI_TTI_ENABLED", "").lower() != "yes"', ROUTES)
        self.assertIn("install_tti(app)", APP)
        self.assertIn('"/api/tti"', APP)


class TheAnswerIsHonestTests(unittest.TestCase):
    def test_it_reports_which_save_of_the_plan_it_read(self):
        self.assertIn("plan_saved", ROUTES)
        self.assertIn("plan_version", ROUTES)
        self.assertIn("only as current as that save", PAGE)

    def test_the_plans_own_save_time_is_used_not_the_hour_it_ran(self):
        """An answer dated "now" about a file saved last Tuesday is the lie
        that matters here."""
        handler = ROUTES.split("def leaving_on(", 1)[1]
        self.assertIn("st_mtime", handler)
        self.assertIn("as_of=saved.date()", handler)

    def test_the_screen_carries_the_caveat_and_refuses_a_pallet_total(self):
        self.assertIn("j.caveat", PAGE)
        self.assertIn("Pallets are not totalled", PAGE)
        self.assertNotIn("pallet_total +", PAGE)

    def test_unreadable_dates_are_offered_not_dropped(self):
        """The lines most likely to be missed are the ones it could not parse."""
        self.assertIn("unresolved_date_count", PAGE)
        self.assertIn("check these in the workbook", PAGE)

    def test_the_dispatch_column_is_read_and_not_the_due_date(self):
        answer = LOGIC.split("def going_out(", 1)[1]
        self.assertIn('"LORRY FROM SDI"', answer)
        self.assertNotIn('parsed = schedule_date(_get(row.cells, "DUE DATE")', answer)


class ItReachesTheServerTests(unittest.TestCase):
    """Three new modules and a page: the lesson from twice in one day."""

    def test_everything_the_service_imports_is_on_the_deploy(self):
        for name in ("sue_despatch.py", "tracker_snapshot.py",
                     "tti_despatch_routes.py", "appportal/tti-despatch.html"):
            with self.subTest(file=name):
                self.assertIn(f'"{name}"', DEPLOY)

    def test_the_page_is_checked_for_at_startup_not_at_the_first_click(self):
        self.assertIn("must be deployed with the code", ROUTES)


if __name__ == "__main__":
    unittest.main()
