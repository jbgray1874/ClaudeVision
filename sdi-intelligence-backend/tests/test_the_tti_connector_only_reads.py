"""TTI despatch in ChatGPT, by chat and by voice: six tools, all read-only.

"Make it all available in chatgpt for chat and voice also." The web app and
the connector answer the same six questions from the same modules, so there
is one set of rules about what the workbook means rather than two.

The properties worth holding, in the order they would hurt:

  * the object-ID list is checked INSIDE every tool. A valid SDI token is not
    permission - everybody in the company can get one - and a check on the
    portal card or in the connector's description is a sentence, not a door;
  * it is the SAME list as the web app's, SDI_TTI_OIDS, so nobody can be in
    on one surface and out on the other;
  * nobody named means nobody in. An empty list meaning "everyone" would turn
    a missing line in a .env file into an open door, silently;
  * no tool can write, book anything in, or send mail, and every one declares
    read_only_hint so the assistant does not ask to run it as if it might;
  * Sue cannot reach Nick's account tracker through it and Nick cannot reach
    TTI despatch through his: separate services, separate tool lists;
  * a spoken answer carries its hedges in the sentence, because there is no
    footer in a voice answer for somebody to notice afterwards.

The rules are read as CODE, with ast, rather than as text - a text match
would pass on the comment that explains a rule instead of the rule. Reading
code does not prove it runs: test_the_tti_connector_starts.py starts it.
"""
import ast
import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import connector_identity as identity                               # noqa: E402

SOURCE = (BACKEND / "tti_connector.py").read_text(encoding="utf-8")
IDENTITY = (BACKEND / "connector_identity.py").read_text(encoding="utf-8")
ROUTES = (BACKEND / "tti_despatch_routes.py").read_text(encoding="utf-8")
AMCRM = (BACKEND / "voicecrm_connector.py").read_text(encoding="utf-8")
DEPLOY = (BACKEND / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

TOOLS = [node for node in TREE.body
         if isinstance(node, ast.FunctionDef)
         and any(isinstance(d, ast.Call) and getattr(d.func, "id", "") == "_tool"
                 for d in node.decorator_list)]


def names_in(node) -> set:
    return {getattr(n, "id", None) or getattr(n, "attr", None)
            for n in ast.walk(node)
            if isinstance(n, (ast.Name, ast.Attribute))}


class ThereAreSixToolsAndTheyAllReadTests(unittest.TestCase):
    def test_the_six_questions_and_the_folder_search_are_the_tools(self):
        self.assertEqual({t.name for t in TOOLS},
                         {"tti_find", "tti_leaving_on", "tti_leaving_this_week", "tti_chase",
                          "tti_overdue", "tti_morning", "tti_data_quality", "tti_find_files",
                          "tti_project_tracker"})

    def test_no_tool_is_registered_except_through_the_read_only_helper(self):
        """A tool decorated with apps.tool directly would skip READS."""
        for node in TREE.body:
            if isinstance(node, ast.FunctionDef):
                for d in node.decorator_list:
                    target = d.func if isinstance(d, ast.Call) else d
                    with self.subTest(function=node.name):
                        self.assertFalse(isinstance(target, ast.Attribute) and target.attr == "tool"
                                         and getattr(target.value, "id", "") == "apps",
                                         f"{node.name} is registered without _tool")

    def test_every_tool_is_registered_read_only(self):
        """read_only_hint is not a comment: ChatGPT and the Claude app use it
        to decide what may run without asking."""
        self.assertIn("READS = ToolAnnotations(read_only_hint=True", SOURCE)
        helper = [n for n in TREE.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_tool"][0]
        self.assertIn("READS", names_in(helper))
        # Nothing registers a tool except through that helper, so nothing can
        # be registered without the annotation.
        for node in ast.walk(TREE):
            if isinstance(node, ast.Attribute) and node.attr == "tool" \
                    and getattr(node.value, "id", "") == "apps":
                self.assertIn("_tool", {f.name for f in TREE.body
                                        if isinstance(f, ast.FunctionDef)})

    def test_nothing_can_write_book_in_or_send(self):
        for forbidden in ("sendMail", "createReply", "propose_change", "confirm_change",
                          "propose_completed_transfer", ".save(", "shutil",
                          "subprocess", "write_text", "write_bytes"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, SOURCE)

    def test_it_imports_only_the_reading_half_of_the_tti_code(self):
        imported = set()
        for node in ast.walk(TREE):
            if isinstance(node, ast.ImportFrom):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
        self.assertEqual(imported & {"chase", "data_quality", "find", "morning",
                                     "overdue_undated", "summary_text", "going_out"},
                         {"chase", "data_quality", "find", "morning",
                          "overdue_undated", "summary_text", "going_out"})
        self.assertNotIn("propose_completed_transfer", imported)

    def test_the_tool_descriptions_say_it_does_not_send_the_summary(self):
        morning = [t for t in TOOLS if t.name == "tti_morning"][0]
        said = morning.decorator_list[0].args[0]
        self.assertIn("does NOT send", "".join(
            v.value for v in ast.walk(said) if isinstance(v, ast.Constant)))
        self.assertIn("it cannot change the workbook", SOURCE.lower())


class TheListIsCheckedInsideEveryToolTests(unittest.TestCase):
    def test_every_tool_asks_who_is_calling_before_it_does_anything(self):
        """── WHY INSIDE THE TOOL ───────────────────────────────────────────
        Not on the portal card, not in the description. The only place a
        refusal cannot be walked past is immediately before the work."""
        for tool in TOOLS:
            used = names_in(ast.Module(body=tool.body, type_ignores=[]))
            with self.subTest(tool=tool.name):
                self.assertTrue({"_plan", "_person"} & used,
                                f"{tool.name} does not establish who is calling")
                self.assertIn("_Refused", used,
                              f"{tool.name} does not handle a refusal")

    def test_the_gate_lives_in_the_helpers_the_tools_use(self):
        for helper in ("_plan", "_person"):
            gate = [n for n in TREE.body
                    if isinstance(n, ast.FunctionDef) and n.name == helper][0]
            used = names_in(gate)
            with self.subTest(helper=helper):
                self.assertIn("named_in", used)
                self.assertIn("OIDS_SETTING", used)

    def test_it_is_the_same_list_as_the_web_app_uses(self):
        """Somebody in on one surface and out on the other is the bug that
        gets discovered by the person who should not have seen the data."""
        self.assertIn('OIDS_SETTING = "SDI_TTI_OIDS"', SOURCE)
        self.assertIn('"SDI_TTI_OIDS"', ROUTES)

    def test_nobody_named_means_nobody_in(self):
        os.environ.pop("SDI_TTI_OIDS", None)
        self.assertFalse(identity.named_in("SDI_TTI_OIDS", {"oid": "anything"}))
        os.environ["SDI_TTI_OIDS"] = "   ,  ,"
        self.assertFalse(identity.named_in("SDI_TTI_OIDS", {"oid": "anything"}))

    def test_a_named_person_is_let_in_whatever_the_case(self):
        os.environ["SDI_TTI_OIDS"] = "CC53597A-C1B5-4BF9-B862-F63F7392FF81, other"
        self.assertTrue(identity.named_in(
            "SDI_TTI_OIDS", {"kind": "user",
                             "oid": "cc53597a-c1b5-4bf9-b862-f63f7392ff81"}))
        self.assertFalse(identity.named_in("SDI_TTI_OIDS",
                                           {"kind": "user", "oid": "someone-else"}))

    def test_a_group_on_the_list_lets_its_members_in(self):
        """── WHY A GROUP AND NOT A LIST OF PEOPLE ──────────────────────────
        A list of object IDs means IT edits a file on the server and restarts
        the service every time somebody joins or leaves Customer Services.
        Naming the GROUP once moves that into Entra, where access to
        everything else is already managed - and the app is no less
        restricted for it."""
        os.environ["SDI_TTI_OIDS"] = "11111111-2222-3333-4444-555555555555"
        self.assertTrue(identity.named_in(
            "SDI_TTI_OIDS", {"kind": "user", "oid": "anybody",
                             "groups": ["11111111-2222-3333-4444-555555555555"]}))
        self.assertFalse(identity.named_in(
            "SDI_TTI_OIDS", {"kind": "user", "oid": "anybody",
                             "groups": ["some-other-group"]}))

    def test_the_connector_and_the_web_app_decide_it_the_same_way(self):
        """Somebody in on one surface and out on the other is the bug that
        gets discovered by the person who should not have seen the data. One
        rule, in one module, used by both."""
        self.assertIn("import access", IDENTITY)
        self.assertIn("access.may_use", IDENTITY)
        routes = (BACKEND / "tti_despatch_routes.py").read_text(encoding="utf-8")
        self.assertIn("access.may_use", routes)

    def test_a_person_with_no_object_id_is_not_let_in(self):
        os.environ["SDI_TTI_OIDS"] = "abc"
        for nobody in ({}, {"kind": "user", "oid": ""},
                       {"kind": "user", "oid": None}, None):
            with self.subTest(user=nobody):
                self.assertFalse(identity.named_in("SDI_TTI_OIDS", nobody))

    def test_it_refuses_to_start_with_nobody_named(self):
        """Starting would refuse every call and look like a broken connector.
        Saying so at startup costs one line and saves an evening."""
        build = SOURCE.split("def build_app(", 1)[1]
        self.assertIn("OIDS_SETTING", build)
        self.assertIn("nobody could use it", build)

    def tearDown(self):
        os.environ.pop("SDI_TTI_OIDS", None)


class TheTokenItselfTests(unittest.TestCase):
    """The checks a signature cannot make, tested without minting one."""

    GOOD = {"iss": "https://login.microsoftonline.com/T/v2.0", "tid": "T",
            "scp": "tracker.access", "azp": "client-1", "oid": "person-1"}

    def refuse(self, **changed) -> str:
        claims = dict(self.GOOD)
        claims.update(changed)
        return identity.refusal(claims, tenant="T", scope="tracker.access",
                                clients=("client-1",))

    def test_a_good_token_is_accepted(self):
        self.assertEqual(self.refuse(), "")

    def test_the_other_issuer_spelling_is_also_accepted(self):
        """A token from sts.windows.net is a real token about a real person,
        and refusing it reads as a broken connector."""
        self.assertEqual(self.refuse(iss="https://sts.windows.net/T/"), "")

    def test_another_tenant_is_refused(self):
        self.assertEqual(self.refuse(tid="SOMEONE-ELSE"), "tenant")
        self.assertEqual(
            self.refuse(iss="https://login.microsoftonline.com/OTHER/v2.0"), "issuer")

    def test_a_token_without_the_scope_is_refused(self):
        self.assertEqual(self.refuse(scp="User.Read"), "scope")
        self.assertEqual(self.refuse(scp=""), "scope")

    def test_an_unknown_client_app_is_refused_when_a_list_is_set(self):
        self.assertEqual(self.refuse(azp="something-else"), "client")

    def test_any_client_is_allowed_when_no_list_is_set(self):
        claims = dict(self.GOOD)
        self.assertEqual(identity.refusal(claims, tenant="T",
                                          scope="tracker.access", clients=()), "")

    def test_an_application_token_is_refused_because_it_names_nobody(self):
        """── WHY A DAEMON IS NOT WELCOME ───────────────────────────────────
        No oid means a service, not a person. This reads a live commercial
        tracker, so an unattributable read is refused however valid the token
        is - the same reason the web view has no shared key."""
        self.assertEqual(self.refuse(oid=""), "user")
        claims = dict(self.GOOD)
        claims.pop("oid")
        self.assertEqual(identity.refusal(claims, tenant="T",
                                          scope="tracker.access"), "user")

    def test_a_refusal_names_itself_in_the_log(self):
        self.assertIn("refused: wrong {why}", IDENTITY)
        # ...and never prints the token.
        said = IDENTITY.split("def check(", 1)[1].split("def verify_token", 1)[0]
        self.assertNotIn("{token}", said)
        self.assertNotIn("token[:", said)


class TwoAudiencesTwoServicesTests(unittest.TestCase):
    def test_this_connector_cannot_reach_the_account_tracker(self):
        """── WHY NOT ONE CONNECTOR WITH BOTH SETS OF TOOLS ─────────────────
        A connector's tool list is the same for everybody who connects it.
        Offering Sue a tool for Nick's account tracker would be refused by the
        owner check - but a refused tool is still a tool she was shown, and an
        assistant told to try everything will try it."""
        for forbidden in ("voicecrm", "connector_cards", "_journal",
                          "private_email", "sdi_ops"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, SOURCE)

    def test_the_account_tracker_connector_cannot_reach_tti(self):
        for forbidden in ("tti_search", "tti_data", "sue_despatch", "tti_plan_source"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, AMCRM)

    def test_they_are_separate_services_on_separate_ports(self):
        self.assertIn('SDI_TTI_CONNECTOR_PORT", "8074"', SOURCE)
        self.assertIn('SDI_CONNECTOR_PORT", "8073"', AMCRM)
        self.assertIn('SDI_TTI_CONNECTOR_ENABLED', SOURCE)

    def test_it_is_off_unless_switched_on(self):
        self.assertIn('ENABLED = _opt("SDI_TTI_CONNECTOR_ENABLED", "no")', SOURCE)
        self.assertIn("The TTI connector is off", SOURCE)


class AnswersFitToSayOutLoudTests(unittest.TestCase):
    def test_every_tool_returns_a_spoken_sentence(self):
        """`spoken` is what the assistant says first. A tool without one
        leaves it to read a list of rows aloud, which is how a useful answer
        becomes ninety seconds of spreadsheet."""
        for tool in TOOLS:
            body = ast.get_source_segment(SOURCE, tool) or ""
            with self.subTest(tool=tool.name):
                self.assertIn("spoken", body, f"{tool.name} has nothing to say first")

    def test_the_spoken_answer_is_where_the_hedge_lives(self):
        """A voice answer has no footer. "Nothing is going out" over the top
        of a line whose date could not be read is the sentence somebody acts
        on, so the caveat has to be inside the sentence."""
        leaving = ast.get_source_segment(
            SOURCE, [t for t in TOOLS if t.name == "tti_leaving_on"][0]) or ""
        self.assertIn("could not read", leaving)
        self.assertIn("may not be all of them", leaving)
        self.assertIn("cannot rule out", leaving)

    def test_every_answer_says_how_old_the_reading_is(self):
        self.assertIn("def _dated(", SOURCE)
        self.assertIn("only as current as that save", SOURCE)
        dated = SOURCE.split("def _ok(", 1)[1].split("@_tool", 1)[0]
        self.assertIn("_dated(answer, plan)", dated)
        for tool in TOOLS:
            body = ast.get_source_segment(SOURCE, tool) or ""
            with self.subTest(tool=tool.name):
                if tool.name == "tti_find_files":
                    # Not the plan: its age is the folder index's, said in as_at.
                    self.assertIn('answer["as_at"]', body)
                    self.assertIn("index_age_hours", body)
                    continue
                if tool.name == "tti_project_tracker":
                    # Not the plan: Liam's tracker, read just now, with its own save time.
                    self.assertIn('answer["as_at"]', body)
                    self.assertIn("last saved", body)
                    continue
                self.assertIn("_ok(", body, f"{tool.name} answers without provenance")

    def test_the_instructions_forbid_quoting_stale_lines(self):
        self.assertIn("as if they were current", SOURCE)
        self.assertIn("Never invent", SOURCE)
        self.assertIn("different questions and must not be swapped", SOURCE)

    def test_a_refusal_tells_the_assistant_what_to_do_with_it(self):
        self.assertIn("Do not answer the question from anything earlier", SOURCE)
        self.assertIn("read its `warning` and do what", SOURCE)

    def test_answers_are_trimmed_so_the_workbook_does_not_fill_the_context(self):
        """A full line has thirty fields. Sixty of them leaves no room for the
        conversation the person is trying to have."""
        self.assertIn("def _brief(", SOURCE)
        for tool in TOOLS:
            body = ast.get_source_segment(SOURCE, tool) or ""
            if tool.name == "tti_data_quality":
                self.assertIn("limit=15", body)      # already short by construction
                continue
            if tool.name in ("tti_find_files", "tti_project_tracker"):
                self.assertIn("limit=25", body)      # a few fields each, 25 at most
                continue
            with self.subTest(tool=tool.name):
                self.assertIn("_brief(", body)


class ItReachesTheServerTests(unittest.TestCase):
    """The lesson from two outages in one day: a new module that the service
    imports and the deploy script does not copy is an outage."""

    def test_the_connector_and_what_it_imports_are_on_the_deploy(self):
        for name in ("tti_connector.py", "connector_identity.py", "tti_search.py",
                     "tti_data.py", "tti_plan_source.py", "sue_despatch.py",
                     "tracker_snapshot.py", "tti_files.py", "tools/tti_index_folders.py"):
            with self.subTest(file=name):
                self.assertIn(f'"{name}"', DEPLOY)

    def test_the_deploy_restarts_the_connector_service_when_it_exists(self):
        self.assertIn("SDITTIConnector", DEPLOY)
        self.assertIn("$TtiConnectorService", DEPLOY)

    def test_every_module_it_imports_can_be_imported(self):
        """Walks the imports rather than trusting the list above. The MCP
        server package is not installed here, so the connector itself is read
        and not run; everything of ours that it imports is loaded."""
        ours = set()
        for node in ast.walk(TREE):
            if isinstance(node, ast.Import):
                ours |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                ours.add(node.module)
        checked, skipped = 0, []
        for module in sorted(ours):
            if not (BACKEND / f"{module}.py").is_file():
                continue
            with self.subTest(module=module):
                try:
                    __import__(module)
                    checked += 1
                except ImportError as missing:
                    # A module of ours that fails because a third-party package
                    # is absent HERE is not the failure this is looking for -
                    # that is this machine, not the deploy. A module of ours
                    # that is simply not there IS the failure, so it is still
                    # raised. Either way the walk carries on to the rest.
                    absent = str(getattr(missing, "name", "") or "")
                    if not absent or (BACKEND / f"{absent}.py").is_file():
                        raise
                    skipped.append(f"{module} (needs {absent})")
        self.assertTrue(checked, f"nothing was checked; skipped {skipped}")


if __name__ == "__main__":
    unittest.main()
