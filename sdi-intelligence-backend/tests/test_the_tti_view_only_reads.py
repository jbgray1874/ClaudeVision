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
LOADER = (BACKEND / "tti_data.py").read_text(encoding="utf-8")
SEARCH = (BACKEND / "tti_search.py").read_text(encoding="utf-8")
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
                               ("tti_search", SEARCH), ("tti_data", LOADER),
                               ("tti_despatch_routes", ROUTES)):
            with self.subTest(module=module):
                for forbidden in ("sendMail", "createReply", ".save(", "shutil",
                                  "open(" if module in ("sue_despatch", "tti_search")
                                  else "\0"):
                    self.assertNotIn(forbidden, source)

    def test_the_workbook_is_opened_read_only(self):
        self.assertIn("read_only=True", READER)
        self.assertIn("data_only=True", READER)


class TheCallerNeverNamesAFileTests(unittest.TestCase):
    def test_a_request_carries_a_date_or_words_and_never_a_location(self):
        """Six views now, and not one of them takes a path, a URL or a sheet
        name. The workbook is configuration; the search box takes words."""
        self.assertIn("day: str = Query(", ROUTES)
        self.assertIn("date.fromisoformat(day)", ROUTES)
        for handler in ("def leaving_on(", "def search(", "def chase_list(",
                        "def overdue(", "def morning_summary(", "def quality("):
            body = ROUTES.split(handler, 1)[1].split("\n    @router", 1)[0]
            with self.subTest(handler=handler):
                for location in ("path", "file", "url", "site", "sheet", "root"):
                    self.assertNotIn(f"{location}: str = Query", body)
        # The search term is bounded, so nobody pastes a file into it.
        self.assertIn("q: str = Query(..., max_length=MAX_QUERY)", ROUTES)

    def test_the_workbook_is_configuration_in_the_one_module_that_opens_it(self):
        self.assertIn("SDI_TTI_PLAN_SITE", LOADER)
        self.assertIn("SDI_TTI_DESPATCH_PLAN", LOADER)
        self.assertIn("has not been configured", LOADER)

    def test_an_unparseable_date_is_refused_rather_than_guessed(self):
        self.assertIn("A date is needed, as YYYY-MM-DD", ROUTES)




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

    def test_every_route_is_gated(self):
        for handler in ("def despatch(", "def leaving_on(", "def search(",
                        "def chase_list(", "def overdue(", "def morning_summary(",
                        "def morning_as_text(", "def quality("):
            body = ROUTES.split(handler, 1)[1][:400]
            with self.subTest(handler=handler):
                self.assertIn("who(request)", body)

    def test_it_is_mounted_only_when_switched_on(self):
        self.assertIn('env.get("SDI_TTI_ENABLED", "").lower() != "yes"', ROUTES)
        self.assertIn("install_tti(app)", APP)
        self.assertIn('"/api/tti"', APP)


class TheAnswerIsHonestTests(unittest.TestCase):
    def test_it_reports_which_save_of_the_plan_it_read(self):
        """Six views, one provenance. It is attached by the loader rather than
        by each route, so a seventh view cannot be added without it."""
        self.assertIn("plan_saved", LOADER)
        self.assertIn("plan_version", LOADER)
        self.assertIn("rows_read", LOADER)
        self.assertIn("plan.provenance()", ROUTES)
        self.assertIn("only as current as that save", PAGE)

    def test_no_json_view_answers_without_the_provenance(self):
        """Every JSON answer leaves through answered(), which is where the
        plan's save time is attached. A route that returned JSONResponse
        directly would answer without saying how old the reading is."""
        for handler in ("def leaving_on(", "def search(", "def chase_list(",
                        "def overdue(", "def morning_summary(", "def quality("):
            body = ROUTES.split(handler, 1)[1].split("\n    @router", 1)[0]
            with self.subTest(handler=handler):
                self.assertIn("answered(plan,", body)
                self.assertNotIn("return JSONResponse", body)

    def test_the_plans_own_save_time_is_used_not_the_hour_it_ran(self):
        """An answer dated "now" about a file saved last Tuesday is the lie
        that matters here. Every view reads as_of the plan's save date."""
        self.assertIn("st_mtime", LOADER)
        for handler in ("def leaving_on(", "def search(", "def chase_list(",
                        "def overdue(", "def morning_summary(", "def quality("):
            body = ROUTES.split(handler, 1)[1].split("\n    @router", 1)[0]
            with self.subTest(handler=handler):
                self.assertIn("as_of=plan.saved.date()", body)
        self.assertNotIn("as_of=date.today()", ROUTES)
        self.assertNotIn("as_of=datetime.now", ROUTES)

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
                     "tti_despatch_routes.py", "tti_plan_source.py", "tti_data.py",
                     "tti_search.py", "appportal/tti-despatch.html"):
            with self.subTest(file=name):
                self.assertIn(f'"{name}"', DEPLOY)

    def test_the_page_is_checked_for_at_startup_not_at_the_first_click(self):
        self.assertIn("must be deployed with the code", ROUTES)


if __name__ == "__main__":
    unittest.main()
