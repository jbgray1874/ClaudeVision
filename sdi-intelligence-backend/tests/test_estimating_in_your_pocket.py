"""Estimating from a phone: what can be asked, and what stays in the office.

The full estimating screen assumes somebody is at a desk watching a run. An
engine run can take a couple of hours, so on a phone that is the wrong shape
entirely, and the pocket page is built on the opposite assumption: start it,
put the phone away, be told.

What is pinned here:

  * the questions endpoint answers about FILED jobs, not only runs the service
    still holds. It used to do only the latter, so everything from before the
    last restart replied "Run not found. The service may have restarted." -
    which, standing in front of a customer asking what we quoted last month,
    is the whole feature failing;
  * and it is confined to the approved areas by the same rule that confines
    browsing, because a question that names a folder is a path a caller
    supplied;
  * a missing figure is never reported as zero;
  * the page offers the four questions the record can actually answer, rather
    than an empty box that invites the ones it cannot;
  * nothing on the public surface grew. Releasing a quotation, changing
    recipients and the self-running switch stay inside the office.
"""
import json
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import estimating_job_tools as tools                                # noqa: E402
import public_surface                                              # noqa: E402

PAGE = (BACKEND / "appportal" / "estimating-pocket.html").read_text(encoding="utf-8")
ROUTES = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
DEPLOY = (BACKEND / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")

# The shape of a saved record, as answer_saved_record reads it.
RECORD = {
    "final_estimate": {"totals": {"unit_gbp": 1234.5, "material_gbp": 400.0,
                                  "labour_gbp": 700.25, "other_gbp": 134.25,
                                  "unit_cell": "Estimate!H42"}},
    "costed_job": {
        "lines": [{"part_number": "ABC-1", "qty_per_unit": 2,
                   "description": "Gondola upright", "material_label": "1.5mm CR4",
                   "charged_ext_gbp": 210.0, "charged_cell": "BOM!G7",
                   "route_operations": ["laser", "fold", "weld"]}],
        "release": {"status": "held", "reasons": ["Material not confirmed"]},
    },
}


class AskingAboutAFiledJobTests(unittest.TestCase):
    """── THE ONE THAT MADE THE FEATURE WORTH HAVING ───────────────────────"""

    def setUp(self):
        import tempfile
        self.area = Path(tempfile.mkdtemp())
        self.job = self.area / "Boots" / "12633 Gondola"
        self.job.mkdir(parents=True)
        (self.job / "12633_record.json").write_text(json.dumps(RECORD), encoding="utf-8")
        self._was = tools.BRIEFS_ROOT
        tools.BRIEFS_ROOT = self.area
        self.addCleanup(setattr, tools, "BRIEFS_ROOT", self._was)

    def test_a_filed_record_is_found_and_read(self):
        held = tools.filed_record("Boots/12633 Gondola")
        self.assertEqual(held["record_name"], "12633_record.json")
        self.assertEqual(held["folder_name"], "12633 Gondola")
        self.assertEqual(held["record"]["final_estimate"]["totals"]["unit_gbp"], 1234.5)

    def test_a_record_filed_one_level_down_is_found(self):
        deeper = self.area / "Boots" / "12700"
        (deeper / "output").mkdir(parents=True)
        (deeper / "output" / "12700_record.json").write_text(json.dumps(RECORD),
                                                             encoding="utf-8")
        self.assertEqual(tools.filed_record("Boots/12700")["record_name"],
                         "12700_record.json")

    def test_a_folder_with_no_record_says_so_rather_than_failing_obscurely(self):
        (self.area / "Empty").mkdir()
        with self.assertRaises(ValueError) as refused:
            tools.filed_record("Empty")
        self.assertIn("No saved estimate record", str(refused.exception))

    def test_two_records_in_one_folder_is_refused_rather_than_guessed(self):
        """Answering from whichever came first would attribute one job's price
        to another, and nothing on the screen would show it had happened."""
        both = self.area / "Twice"
        both.mkdir()
        for name in ("a_record.json", "b_record.json"):
            (both / name).write_text(json.dumps(RECORD), encoding="utf-8")
        with self.assertRaises(ValueError) as refused:
            tools.filed_record("Twice")
        self.assertIn("not clear which job", str(refused.exception))


class TheFolderNameIsAPathACallerSuppliedTests(AskingAboutAFiledJobTests):
    """It comes off a phone, so it is checked like one."""

    def test_it_cannot_climb_out_of_the_approved_area(self):
        outside = self.area.parent / "secrets"
        outside.mkdir(exist_ok=True)
        (outside / "x_record.json").write_text(json.dumps(RECORD), encoding="utf-8")
        for attempt in ("../secrets", "Boots/../../secrets", "..", "../"):
            with self.subTest(attempt=attempt):
                with self.assertRaises(ValueError):
                    tools.filed_record(attempt)

    def test_it_cannot_be_given_an_absolute_path(self):
        for attempt in (r"C:\Windows\win.ini", "/etc/passwd",
                        r"\\sdi-dc01\shareddata$\Shared"):
            with self.subTest(attempt=attempt):
                with self.assertRaises(ValueError):
                    tools.filed_record(attempt)

    def test_an_empty_name_is_refused(self):
        with self.assertRaises(ValueError) as refused:
            tools.filed_record("")
        self.assertIn("Name the job folder", str(refused.exception))

    def test_a_very_long_name_is_refused(self):
        with self.assertRaises(ValueError):
            tools.filed_record("a/" * 400)

    def test_it_uses_the_same_rule_as_browsing(self):
        """One place decides what a caller may name. Two would drift."""
        self.assertIn("def _segments(", (BACKEND / "estimating_job_tools.py")
                      .read_text(encoding="utf-8"))


class WhatCanBeAskedTests(unittest.TestCase):
    """Four topics, and an honest refusal for everything else."""

    def answer(self, question):
        return tools.answer_saved_record(RECORD, question)

    def test_what_did_it_come_out_at(self):
        said = self.answer("What did this come out at?")
        self.assertIn("£1234.50", said["answer"])
        self.assertIn("Estimate!H42", said["answer"])
        self.assertTrue(said["complete"])

    def test_a_named_part_gets_its_own_charged_figure(self):
        said = self.answer("what did ABC-1 cost")
        self.assertIn("ABC-1", said["answer"])
        self.assertIn("£210.00", said["answer"])

    def test_what_parts_are_in_it(self):
        said = self.answer("What parts are in it?")
        self.assertIn("ABC-1", said["answer"])
        self.assertIn("1.5mm CR4", said["answer"])

    def test_what_operations_did_it_need(self):
        said = self.answer("What operations did it need?")
        self.assertIn("laser", said["answer"])
        self.assertIn("may include proposed or uncharged work", said["answer"])

    def test_was_anything_held(self):
        said = self.answer("Was anything held or unresolved?")
        self.assertIn("held", said["answer"])
        self.assertIn("Material not confirmed", said["answer"])

    def test_a_question_it_cannot_answer_says_so_rather_than_inventing(self):
        said = self.answer("When will it be delivered?")
        self.assertIn("cannot establish that", said["answer"])
        self.assertEqual(said["sources"], [])
        self.assertFalse(said["complete"])

    def test_a_missing_figure_is_never_reported_as_zero(self):
        """"or 0" turned an absent total into "£0.00", stated as a calculated
        fact - the one thing this is not allowed to do."""
        thin = {"final_estimate": {"totals": {"unit_gbp": None, "unit_cell": ""}},
                "costed_job": {"lines": []}}
        said = tools.answer_saved_record(thin, "what did it cost")
        self.assertIn("not recorded", said["answer"])
        self.assertNotIn("£0.00", said["answer"])
        self.assertFalse(said["complete"])

    def test_an_empty_or_enormous_question_is_refused(self):
        for bad in ("", "   ", "x" * 501):
            with self.subTest(question=bad[:20]):
                with self.assertRaises(ValueError):
                    tools.answer_saved_record(RECORD, bad)


class TheRouteOffersBothAndPrefersTheFiledOneTests(unittest.TestCase):
    def test_the_request_takes_a_filed_job_as_well_as_a_run(self):
        self.assertIn("brief: str = \"\"", ROUTES)
        self.assertIn("area: str = \"brief", ROUTES)
        self.assertIn("run_id: str = \"\"", ROUTES)

    def test_naming_neither_is_refused_rather_than_guessed(self):
        self.assertIn("Name a filed job or a run to ask about", ROUTES)

    def test_a_folder_outside_the_approved_area_is_a_409_not_a_500(self):
        handler = ROUTES.split("def ask_saved_run(", 1)[1].split("\n@router", 1)[0]
        self.assertIn("filed_record(", handler)
        self.assertIn("HTTPException(409", handler)


class NothingOnThePublicSurfaceGrewTests(unittest.TestCase):
    """The page is new. The boundary is not."""

    def test_the_three_posts_are_still_the_three_posts(self):
        self.assertEqual(public_surface.PUBLIC_POST,
                         ("/api/estimate", "/api/estimate/brief",
                          "/api/estimate/tools/ask"))

    def test_the_page_calls_nothing_that_is_never_public(self):
        for forbidden in public_surface.NEVER_PUBLIC_POST:
            with self.subTest(path=forbidden):
                self.assertNotIn(forbidden, PAGE)

    def test_the_page_says_a_quotation_is_not_released_from_outside(self):
        self.assertIn("never released from outside the office", PAGE)

    def test_every_path_the_page_calls_is_allowed_from_outside(self):
        import re
        called = set(re.findall(r'api\("(/api/[^"?]+)', PAGE))
        self.assertTrue(called, "the page calls nothing")
        for path in sorted(called):
            with self.subTest(path=path):
                self.assertTrue(
                    path in ("/api/me", "/api/estimate", "/api/estimate/brief",
                             "/api/estimate/tools/ask", "/api/estimate/tools/briefs"),
                    f"{path} is not one of the paths this page is meant to use")


class ThePageIsBuiltForAPhoneTests(unittest.TestCase):
    def test_it_offers_the_questions_the_record_can_answer(self):
        """An empty box invites the questions it cannot answer, and the app
        looks stupid rather than bounded."""
        for prompt in ("What did this come out at?", "What parts are in it?",
                       "What operations did it need?",
                       "Was anything held or unresolved?"):
            with self.subTest(prompt=prompt):
                self.assertIn(prompt, PAGE)

    def test_every_answer_shows_where_it_came_from(self):
        self.assertIn("a.record_name", PAGE)
        self.assertIn("a.sources", PAGE)

    def test_an_incomplete_answer_is_marked_as_one(self):
        self.assertIn("a.complete", PAGE)
        self.assertIn("Incomplete", PAGE)

    def test_there_is_no_log_on_the_running_screen(self):
        """The reason this page exists: a two-hour run is not something to
        watch on a phone."""
        running = PAGE.split('id="s-today"', 1)[1].split("</section>", 1)[0]
        self.assertNotIn("log", running.lower())
        self.assertIn("you don't have to stay here", running)

    def test_a_started_run_says_who_it_will_email(self):
        self.assertIn("email_to", PAGE)
        self.assertIn("when it finishes", PAGE)

    def test_text_inputs_are_big_enough_that_ios_does_not_zoom(self):
        """Anything under 16px makes Safari zoom the page on focus, and the
        person then cannot see the button they were about to press."""
        self.assertIn("font-size:16px", PAGE)

    def test_the_navigation_is_at_the_bottom_where_thumbs_are(self):
        self.assertIn(".bar{position:fixed", PAGE)
        self.assertIn("bottom:0", PAGE)


class ItReachesTheServerTests(unittest.TestCase):
    def test_the_page_is_on_the_deploy(self):
        self.assertIn('"appportal/estimating-pocket.html"', DEPLOY)

    def test_the_deploy_warns_about_the_backend_files_it_does_not_copy(self):
        """A change to the estimating API deploys "successfully" through that
        script, restarts, and is not on the server at all."""
        self.assertIn("estimate_routes.py", DEPLOY)
        self.assertIn("estimating_job_tools.py", DEPLOY)
        self.assertIn("push-to-server.ps1 -Apply", DEPLOY)

    def test_it_is_reached_from_the_estimating_app_not_a_card_of_its_own(self):
        """── WHY IT IS NOT ON THE PORTAL GRID ──────────────────────────────
        "needs to be built inside of SDI Estimating Intelligence... or it's too
        cluttered." It is the same app in a different shape, not a second one,
        and the grid is where nine apps already compete for a glance."""
        catalogue = json.loads((BACKEND / "services.json").read_text(encoding="utf-8"))
        ids = {s["id"] for s in catalogue["services"]}
        self.assertNotIn("estimating-pocket", ids, "it has a card of its own again")
        (card,) = [s for s in catalogue["services"] if s["id"] == "estimating"]
        self.assertEqual(card["link"], "/app/estimating-pocket.html")
        self.assertIn("phone", card["linkLabel"].lower())

    def test_the_estimating_screen_links_to_it(self):
        """The way in, for somebody who opened the full screen on a phone."""
        full = (BACKEND / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")
        self.assertIn("/app/estimating-pocket.html", full)
        self.assertIn("On a phone", full)

    def test_and_it_links_back(self):
        self.assertIn('href="/estimating"', PAGE)
        self.assertIn("Full screen", PAGE)


class EveryPromptThePageOffersIsAnswerableTests(unittest.TestCase):
    """── THE GUARD THAT CAUGHT THE FIRST ONE ──────────────────────────────
    The page suggests four questions. "What did this come out at?" was one of
    them, and the record reader matched none of its words - so the app's own
    first suggestion returned "I cannot establish that from this saved
    record". A bounded tool that refuses the plainest form of the question it
    exists to answer reads as broken rather than careful.

    So the page's suggestions are read out of the page itself and each one is
    put to the reader. Adding a prompt the engine cannot answer fails here.
    """

    def prompts(self):
        import re
        block = PAGE.split("const ASKABLE = [", 1)[1].split("];", 1)[0]
        found = re.findall(r'"([^"]+)"', block)
        self.assertEqual(len(found), 4, f"expected four prompts, found {found}")
        return found

    def test_each_suggested_question_gets_a_real_answer(self):
        for prompt in self.prompts():
            with self.subTest(prompt=prompt):
                said = tools.answer_saved_record(RECORD, prompt)
                self.assertNotIn("cannot establish", said["answer"],
                                 f"the page suggests {prompt!r} and the record "
                                 f"reader does not understand it")
                self.assertTrue(said["sources"], prompt)

    def test_the_plainest_ways_of_asking_the_price_all_work(self):
        for phrasing in ("What did this come out at?", "what did it come out at",
                         "how much was it", "what did we quote for this",
                         "what's the price", "total cost please",
                         "what was it charged at"):
            with self.subTest(phrasing=phrasing):
                said = tools.answer_saved_record(RECORD, phrasing)
                self.assertIn("£1234.50", said["answer"])

    def test_a_question_about_something_else_still_refuses(self):
        """Widening the price words must not swallow everything."""
        for phrasing in ("when is it due", "who drew it", "what colour is it"):
            with self.subTest(phrasing=phrasing):
                self.assertIn("cannot establish",
                              tools.answer_saved_record(RECORD, phrasing)["answer"])

    def test_the_other_three_topics_still_route_to_themselves(self):
        self.assertIn("ABC-1", tools.answer_saved_record(RECORD, "what parts")["answer"])
        self.assertIn("laser", tools.answer_saved_record(RECORD, "what operations")["answer"])
        self.assertIn("Material not confirmed",
                      tools.answer_saved_record(RECORD, "anything held")["answer"])


# ── THE SCRIPT HAS TO SURVIVE BEING LOADED ──────────────────────────────────
# whoAmI() was called at the foot of the page and defined nowhere, and `me` was
# read by the start button and declared nowhere. Both are ReferenceErrors, so:
# the start button could never have worked at all, and the throw at the foot of
# the script killed the two lines after it - which are the ones that load the
# Ask browser. The page opened blank and the one button on it did nothing.
#
# Nothing caught it because every other test here reads the page as TEXT and
# asserts a string is present. "whoAmI" was present. It was present at the call
# and absent at the definition, which is exactly what reading for substrings
# cannot see.
#
# There is no JavaScript engine in this suite, so this does the one check that
# does not need one: every name the page CALLS, it also DECLARES. Browser and
# language globals are listed explicitly rather than guessed at, so a genuine
# typo shows up as a failure instead of being waved through.
BROWSER_GLOBALS = {
    # language
    "Number", "String", "Boolean", "Array", "Object", "JSON", "Math", "Date",
    "isFinite", "isNaN", "parseInt", "parseFloat", "encodeURIComponent",
    "decodeURIComponent", "Error", "Promise", "Set", "Map", "RegExp",
    # browser
    "fetch", "setTimeout", "clearTimeout", "setInterval", "clearInterval",
    "alert", "confirm", "document", "window", "location", "console",
    # the page's own two-character helpers, declared as arrow consts
    "$", "el", "icon", "api", "say",
}


class EveryNameThePageCallsIsDeclaredTests(unittest.TestCase):
    """The guard for the class of bug that shipped a page that could not run."""

    def script(self):
        return PAGE.split("<script>", 1)[1].split("</script>", 1)[0]

    def declared(self):
        import re
        body = self.script()
        names = set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", body))
        names |= set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", body))
        return names

    def called(self):
        import re
        body = self.script()
        # Strip strings and comments first: "What did this come out at?" is not
        # a call, and neither is anything inside a // note.
        body = re.sub(r"//[^\n]*", "", body)
        body = re.sub(r'"[^"\n]*"|\'[^\'\n]*\'|`[^`]*`', '""', body)
        out = set()
        for name in re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", body):
            if name in ("if", "for", "while", "switch", "catch", "function",
                        "return", "typeof", "await", "new"):
                continue
            out.add(name)
        return out

    def test_nothing_is_called_that_is_never_declared(self):
        missing = sorted(self.called() - self.declared() - BROWSER_GLOBALS)
        self.assertEqual(missing, [], f"the page calls {missing} and declares "
                                      f"them nowhere - it would throw on load")

    def test_who_am_i_in_particular_is_defined(self):
        """Named, because this is the one that shipped broken."""
        self.assertIn("async function whoAmI(", self.script())

    def test_the_signed_in_person_is_declared_before_the_button_reads_them(self):
        body = self.script()
        self.assertIn("let me = {}", body)
        self.assertLess(body.index("let me = {}"), body.index("me.email"),
                        "me is read before it is declared")

    def test_a_page_that_cannot_say_who_you_are_says_so(self):
        """Silently e-mailing the finished book to nobody is an hour of the
        engine's time that nobody hears about."""
        self.assertIn("could not read which account", PAGE)


class StartingFromAWrittenBriefTests(unittest.TestCase):
    """── THE SAME ENGINE, GIVEN WORDS INSTEAD OF GEOMETRY ─────────────────
    "it is exactly the same form as the main one" - it is, and that is the
    point. /api/estimate/brief hands straight through to /api/estimate with
    method="llm". So this is a second way IN on the Start screen, not a second
    app and not a second engine.
    """

    def start_screen(self):
        return PAGE.split('id="s-start"', 1)[1].split("</section>", 1)[0]

    def test_start_offers_both_ways_in(self):
        start = self.start_screen()
        self.assertIn("From a drawing pack", start)
        self.assertIn("From a written brief", start)

    def test_the_chosen_one_looks_chosen_on_a_phone(self):
        """There is no hover on a phone, so the pressed state must be styled."""
        self.assertIn(".chips button[aria-pressed=true]", PAGE)

    def test_it_posts_the_field_names_the_endpoint_actually_takes(self):
        """── WHAT THIS CATCHES ────────────────────────────────────────────
        BriefRequest takes `reference`, not `drawing_number`. Posting the
        wrong name is a 422 the person reads as "it just doesn't work", and
        no amount of reading the page's text would show it.
        """
        model = ROUTES.split("class BriefRequest(BaseModel):", 1)[1] \
                      .split("@router.post", 1)[0]
        required = {line.split(":", 1)[0].strip()
                    for line in model.splitlines()
                    if ":" in line and not line.strip().startswith(('"', "#"))
                    and line.startswith("    ")}
        required = {n for n in required if n and n.isidentifier()}
        self.assertIn("reference", required, "the endpoint changed shape")

        posted = PAGE.split('api("/api/estimate/brief"', 1)[1].split("});", 1)[0]
        for field in ("client", "reference", "units", "brief"):
            with self.subTest(field=field):
                self.assertIn(field + ":", posted)
        self.assertNotIn("drawing_number", posted)
        for field in posted.split("{", 1)[1].split("}", 1)[0].split(","):
            name = field.split(":", 1)[0].strip()
            if name:
                with self.subTest(field=name):
                    self.assertIn(name, required,
                                  f"the page posts {name!r} and BriefRequest "
                                  f"has no such field")

    def test_a_brief_too_thin_to_cost_is_refused_on_the_phone(self):
        """A one-line brief comes back as a sheet of assumptions, which wastes
        a run and reads as the engine being useless."""
        self.assertIn("too short to cost", PAGE)

    def test_the_quantity_breaks_are_checked_before_the_post(self):
        """A typo here otherwise reaches the runner and fails forty minutes in,
        on a phone that has long since been put away."""
        self.assertIn("function breaksOf(", PAGE)
        self.assertIn("Number.isInteger", PAGE)

    def test_the_book_is_called_provisional_where_it_is_started(self):
        """On the screen that starts it, not only in the reply afterwards."""
        self.assertIn("provisional", self.start_screen().lower())

    def test_the_page_computes_no_price_of_its_own(self):
        """── WHY THE ENGINE IS NOT PORTABLE ───────────────────────────────
        The engine is correct because it mirrors the workbook to the cell. A
        second implementation anywhere is a second answer that has to be proved
        equal to the first forever. This page must therefore only ever DISPLAY
        a figure the engine recorded - never arrive at one.
        """
        body = PAGE.split("<script>", 1)[1].split("</script>", 1)[0]
        for arithmetic in ("* 1.", "unit_gbp *", "* units", "units *",
                           "+ vat", "* 0.", "/ units"):
            with self.subTest(pattern=arithmetic):
                self.assertNotIn(arithmetic, body.lower())


if __name__ == "__main__":
    unittest.main()
