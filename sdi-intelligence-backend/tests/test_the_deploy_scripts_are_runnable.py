"""The deploy scripts, checked for the mistakes that only show on the laptop.

There is no PowerShell on the machine these tests run on, so nothing here
executes a script. What it checks are the three faults that have actually been
shipped to SDI-App01's laptop and failed there, each costing a round trip:

  1. A LOCAL VARIABLE WITH THE SAME NAME AS A [switch] PARAMETER.
     PowerShell variable names are case-insensitive, so `$check = "...path..."`
     inside a script whose param block declares `[switch]$Check` assigns a
     string to the switch and throws:

         Cannot convert the "...Check-AMCRM-Live.ps1" value of type
         "System.String" to type "System.Management.Automation.SwitchParameter"

     Ship-It.ps1 shipped with exactly that on 29 October and failed on its
     first run. A string landing on a [string] parameter is legal and is how
     several of these scripts resolve their own defaults, so only the
     type-incompatible collisions are faults.

  2. Restart-Service -ComputerName.
     That parameter does not exist in Windows PowerShell 5.1, which is what
     the laptop runs. It was handed over three times in one afternoon and
     failed every time. Remote control of the service is sc.exe with the
     machine as its first argument; Restart-Service without -ComputerName is
     the Remote Desktop form and is fine.

  3. Unbalanced brackets, which PowerShell only reports when it parses the
     file - that is, on the laptop, mid-deploy.
"""
import re
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
SCRIPTS = sorted(list((BACKEND / "deploy").glob("*.ps1"))
                 + list((REPO / "tools" / "start").glob("*.ps1")))


def strip(source: str) -> str:
    """Comments and string literals removed, so brackets inside them do not count."""
    out = re.sub(r"<#.*?#>", "", source, flags=re.S)
    out = "\n".join(re.sub(r"#.*$", "", line) for line in out.split("\n"))
    out = re.sub(r'"(?:[^"`]|`.)*"', '""', out)
    return re.sub(r"'[^']*'", "''", out)


def params(source: str) -> dict:
    """{name_lowercase: declared type} from the script's param block."""
    block = re.search(r"param\s*\((.*?)\n\)", source, re.S)
    if not block:
        return {}
    found = {}
    for kind, name in re.findall(r"\[(\w+)\]\s*\$(\w+)", block.group(1)):
        found[name.lower()] = kind.lower()
    return found


class TheScriptsAreThereTests(unittest.TestCase):
    def test_the_ones_this_project_hands_people_exist(self):
        names = {s.name for s in SCRIPTS}
        for needed in ("Deploy-AMCRM.ps1", "Check-AMCRM-Live.ps1", "Ship-It.ps1",
                       "push-to-server.ps1"):
            with self.subTest(script=needed):
                self.assertIn(needed, names)


class NoLocalShadowsASwitchTests(unittest.TestCase):
    """Fault 1. The one that broke Ship-It on its first run."""

    def test_no_script_assigns_a_value_to_its_own_switch_parameter(self):
        for script in SCRIPTS:
            source = script.read_text(encoding="utf-8", errors="replace")
            declared = params(source)
            switches = {n for n, kind in declared.items() if kind == "switch"}
            if not switches:
                continue
            after = source[re.search(r"param\s*\((.*?)\n\)", source, re.S).end():]
            for name in re.findall(r"^\s*\$(\w+)\s*=", after, re.M):
                with self.subTest(script=script.name, variable=name):
                    self.assertNotIn(
                        name.lower(), switches,
                        f"${name} in {script.name} is also a [switch] parameter; "
                        f"PowerShell names are case-insensitive, so this assigns "
                        f"a value to the switch and throws at run time")


class NoCommandThatDoesNotExistTests(unittest.TestCase):
    """Fault 2. Handed over three times in one afternoon, wrong every time."""

    def test_nothing_calls_restart_service_with_computername(self):
        for script in SCRIPTS:
            # Comments stripped first: these scripts explain at length WHY the
            # parameter does not exist, and a test that could not tell the
            # explanation from the mistake would fail on the fix for it.
            source = strip(script.read_text(encoding="utf-8", errors="replace"))
            with self.subTest(script=script.name):
                self.assertNotRegex(
                    source, r"Restart-Service[^\n]*-ComputerName",
                    f"{script.name} uses Restart-Service -ComputerName, which does "
                    f"not exist in Windows PowerShell 5.1. Use sc.exe \\\\<server> "
                    f"stop/start, or Restart-Service on the server itself.")

    def test_the_remote_restart_goes_through_sc_exe(self):
        """The two scripts that restart the service from the laptop both use
        the mechanism that is known to work from there."""
        for name in ("Deploy-AMCRM.ps1", "Check-AMCRM-Live.ps1"):
            source = (BACKEND / "deploy" / name).read_text(encoding="utf-8")
            with self.subTest(script=name):
                self.assertRegex(source, r"sc\.exe\s+\"?\\\\")


# ── WHY THERE IS NO BRACKET-BALANCE TEST HERE ───────────────────────────────
# There was one, and it failed on Deploy-AMCRM.ps1 and one-db-password.ps1 -
# two scripts that have been run against the live server many times. Counting
# brackets in PowerShell needs a PowerShell parser: here-strings, regex
# literals and $( ) subexpressions all defeat a regex, and the version written
# here reported two working scripts as broken.
#
# A test that is wrong about code that works is worse than no test. It teaches
# people to ignore the suite, which costs more than the bug it was looking for.
# Anything that needs a real parse belongs on a machine that has PowerShell:
#
#     powershell -NoProfile -Command "[System.Management.Automation.Language.Parser]::ParseFile(
#         '<path>', [ref]$null, [ref]$errors); $errors"


class TheScriptsSayWhereToRunThemTests(unittest.TestCase):
    """"I can't guess where to run commands" - and every one of these is for
    the laptop, which the file should say before anybody has to ask."""

    def test_the_am_crm_scripts_name_the_machine_in_their_first_lines(self):
        for name in ("Deploy-AMCRM.ps1", "Check-AMCRM-Live.ps1", "Ship-It.ps1"):
            head = (BACKEND / "deploy" / name).read_text(encoding="utf-8")[:1200]
            with self.subTest(script=name):
                self.assertRegex(head.upper(), r"ON THE LAPTOP")


if __name__ == "__main__":
    unittest.main()


class ShipItDoesTheWholeJobTests(unittest.TestCase):
    """"was there any git pulls?" - a fair question, asked after being handed
    two commands that do not pull.

    push-to-server.ps1 copies the whole backend folder and is the only way the
    estimating API reaches the server. It does NOT pull, so running it by hand
    after forgetting the pull copies yesterday. Both halves of that have cost a
    deploy, so Ship-It pulls once and then runs whichever copier the change
    actually needs.
    """

    SHIP = (BACKEND / "deploy" / "Ship-It.ps1").read_text(encoding="utf-8")

    def test_it_pulls_before_it_copies_anything(self):
        pull = self.SHIP.index("git pull")
        for copier in ("Deploy-AMCRM.ps1", "push-to-server.ps1"):
            with self.subTest(copier=copier):
                self.assertLess(pull, self.SHIP.index(copier),
                                f"{copier} is run before the pull")

    def test_it_runs_the_whole_folder_copier_when_the_change_needs_it(self):
        self.assertIn("push-to-server.ps1", self.SHIP)
        self.assertIn("-Apply", self.SHIP)
        named = self.SHIP.split("$alsoNeeded = @(", 1)[1].split(")", 1)[0]
        for name in ("app.py", "estimate_routes.py", "estimating_job_tools.py"):
            with self.subTest(file=name):
                self.assertIn(f'"{name}"', named)

    def test_the_files_it_watches_for_are_the_ones_the_other_list_leaves_out(self):
        """Two lists that can disagree is one more than there should be."""
        deploy = (BACKEND / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")
        warned = set(re.findall(r'"([\w.]+\.py)"',
                                deploy.split("$NotCopied = @(", 1)[1].split(")", 1)[0]))
        watched = set(re.findall(r'"([\w.]+\.py)"',
                                 self.SHIP.split("$alsoNeeded = @(", 1)[1].split(")", 1)[0]))
        self.assertEqual(warned, watched,
                         "Deploy-AMCRM warns about one set of files and Ship-It "
                         "deploys another")


class SettingsAreChangedByACommandNotByHandTests(unittest.TestCase):
    """Every setting in this project has been handed over as a line of text and
    an unspoken "you know what to do with that". You do not: open a share, find
    the file, find the line, decide whether to replace or add one, save it
    without breaking the encoding, remember the restart. Five chances to get it
    wrong on a file that is hand-edited over a share, is not in version
    control, and that every app reads once at startup.
    """

    SET = (BACKEND / "deploy" / "Set-Setting.ps1").read_text(encoding="utf-8")

    def test_it_takes_a_backup_before_it_writes(self):
        backup = self.SET.index("Copy-Item")
        write = self.SET.index("WriteAllLines")
        self.assertLess(backup, write, "it writes before backing up")
        self.assertIn(".bak", self.SET)

    def test_a_failed_backup_stops_it_writing_at_all(self):
        after = self.SET.split("Could not write a backup", 1)[0][-400:]
        self.assertIn("try {", after)
        self.assertIn("Stop-Here", self.SET.split("Copy-Item", 1)[1][:400])

    def test_it_writes_utf8_without_a_byte_order_mark(self):
        """A BOM makes the FIRST setting unreadable, and it fails as though
        that setting were simply absent."""
        self.assertIn("UTF8Encoding($false)", self.SET)
        self.assertIn("WriteAllLines", self.SET)

    def test_it_replaces_an_existing_line_rather_than_adding_a_second(self):
        """Two lines for one setting is a file where the answer depends on
        which one is read last."""
        self.assertIn("$lines[$at] = $new", self.SET)
        self.assertIn("Expected one $Name line", self.SET)

    def test_it_never_prints_a_value(self):
        """Object IDs, keys and client secrets, and a console scrollback gets
        pasted into chats."""
        self.assertIn("character(s) written", self.SET)
        self.assertNotIn("Say \"$Name=$Value", self.SET)
        self.assertNotIn("Write-Host $Value", self.SET)
        shown = self.SET.split("if ($Show)", 1)[1].split("exit 0", 1)[0]
        self.assertIn("no value is ever printed", shown)
        self.assertNotIn("$Matches[2]}", shown)

    def test_it_says_a_restart_is_needed(self):
        self.assertIn("read ONCE, at startup", self.SET)
        self.assertIn("Check-AMCRM-Live.ps1 -Restart", self.SET)

    def test_it_can_say_what_it_would_do_without_doing_it(self):
        self.assertIn("-WhatIf", self.SET)
        self.assertIn("Nothing was written", self.SET)

    def test_it_edits_the_env_beside_the_service_which_is_the_one_that_wins(self):
        """config.py reads two files called .env and the service-specific one
        beats the shared one. Editing the wrong one changes nothing and the
        file plainly contains the line saying otherwise."""
        self.assertIn("sdi-intelligence-backend\\.env", self.SET)
        self.assertIn("beside the service wins", self.SET)


class TheCheckReportsOnWhatWasDeployedTests(unittest.TestCase):
    """"this has nothing to do with nick? it's estimating?"

    Ship-It ends by running Check-AMCRM-Live, and that script only ever looked
    at Nick's tracker. So a deploy of estimating changes finished with a
    confident report about the AM CRM write fix and said nothing at all about
    what had just been deployed.
    """

    CHECK = (BACKEND / "deploy" / "Check-AMCRM-Live.ps1").read_text(encoding="utf-8")

    def test_the_other_apps_get_a_line_each(self):
        for setting in ("SDI_ESTIMATOR_OIDS", "SDI_TTI_OIDS", "SDI_OPS_OIDS"):
            with self.subTest(setting=setting):
                self.assertIn(setting, self.CHECK)

    def test_it_checks_the_shared_access_rule_is_on_the_server(self):
        """Without access.py, a GROUP id in any setting matches nobody and
        only individual object IDs work - half-working, and silent about it."""
        self.assertIn('Live "access.py" "def may_use"', self.CHECK)
        self.assertIn("a group id in any setting matches nobody", self.CHECK)

    def test_the_verdict_says_which_sections_are_about_which_app(self):
        verdict = self.CHECK.split("# ── Verdict", 1)[1]
        self.assertIn("Section 7 is everything else", verdict)
        self.assertIn("AM CRM:", verdict)

    def test_it_still_never_prints_a_setting_value(self):
        seven = self.CHECK.split('Head "7.', 1)[1]
        self.assertIn("never printed", seven.lower() + self.CHECK.lower())
        self.assertNotIn("$seen[$app.Setting]}", seven)

    def test_it_points_at_the_command_that_sets_a_missing_one(self):
        self.assertIn("Set-Setting.ps1 $($app.Setting)", self.CHECK)

    def test_it_reports_on_the_screens_too_not_only_the_backend(self):
        """── THE SAME GAP, IN A NEW FORM ──────────────────────────────────
        Section 7 read .py files and settings. A deploy whose whole change was
        a PAGE therefore finished with a clean report that said nothing about
        it - which is how "it's estimating?" happened the first time.
        """
        self.assertIn("The screens", self.CHECK)
        self.assertIn('File = "appportal/estimating-pocket.html"', self.CHECK)

    def test_every_marker_it_looks_for_really_is_in_the_page(self):
        """── A CHECK THAT CRIES WOLF IS WORSE THAN NO CHECK ───────────────
        The screens section proves a deploy landed by finding a string in the
        file on the server. If that string is not in the page in the first
        place - a wording change, a typo - the check reports "missing or older
        code" after a perfectly good deploy, every time, and the next real
        failure is the one nobody believes.

        So the markers are read out of the script and put to the real files.
        """
        import re
        section = self.CHECK.split('Say "The screens" White', 1)[1] \
                            .split("# ── Verdict", 1)[0]
        pairs = re.findall(r'File\s*=\s*"([^"]+)";[^}]*?Marker\s*=\s*"([^"]*)"',
                           section, re.S)
        self.assertTrue(pairs, "no page/marker pairs found - did the shape change?")
        for filename, marker in pairs:
            with self.subTest(file=filename, marker=marker):
                page = BACKEND / filename
                self.assertTrue(page.is_file(), f"{filename} is not in the repo")
                if marker:
                    self.assertIn(marker, page.read_text(encoding="utf-8"),
                                  f"Check-AMCRM-Live looks for {marker!r} in "
                                  f"{filename} and it is not there, so the check "
                                  f"would report a good deploy as a failure")

    def test_the_pages_it_names_are_on_the_deploy(self):
        """A page the check verifies but the deploy never copies would be
        reported missing for ever, correctly and uselessly."""
        import re
        section = self.CHECK.split('Say "The screens" White', 1)[1] \
                            .split("# ── Verdict", 1)[0]
        deploy = (BACKEND / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")
        for filename in set(re.findall(r'File\s*=\s*"([^"]+)"', section)):
            with self.subTest(file=filename):
                self.assertIn(f'"{filename}"', deploy,
                              f"{filename} is checked but never deployed")

    def test_every_local_module_the_app_imports_is_deployed(self):
        """── A MISSING FILE HERE IS NOT A MISSING FEATURE ─────────────────
        Deploy-AMCRM copies a NAMED list. A new module that voicecrm.py
        imports, but the list does not name, is an ImportError the moment the
        service restarts - so the deploy "succeeds" and the app is down, which
        is worse than the change simply not landing.
        """
        deploy = (BACKEND / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")
        local = {p.stem for p in BACKEND.glob("*.py")}
        for module in ("voicecrm", "voicecrm_connector"):
            source = (BACKEND / f"{module}.py").read_text(encoding="utf-8")
            imported = set(re.findall(r"^\s*import\s+([a-z_][a-z0-9_]*)",
                                      source, re.M))
            for name in sorted(imported & local):
                with self.subTest(module=module, imports=name):
                    self.assertTrue(
                        f'"{name}.py"' in deploy or name in self.NOT_COPIED,
                        f"{module}.py imports {name}.py, and Deploy-AMCRM "
                        f"neither copies it nor warns that it does not")

    NOT_COPIED = ("app", "config", "auth", "public_surface")

    def test_every_function_is_defined_before_it_is_used(self):
        """── POWERSHELL RESOLVES FUNCTIONS AT RUNTIME ─────────────────────
        A function used in section 5 and defined in section 7 parses fine,
        passes every syntax check, and then throws "is not recognized" on the
        line that uses it - taking the rest of the check down with it. That is
        how `Live` shipped broken for about four minutes.
        """
        import re
        for name in ("Check-AMCRM-Live.ps1", "Ship-It.ps1", "Set-Setting.ps1",
                     "Deploy-AMCRM.ps1"):
            source = (BACKEND / "deploy" / name).read_text(encoding="utf-8")
            # Strip comments: a function named in a comment is not a call.
            code = "\n".join(l for l in source.splitlines()
                              if not l.strip().startswith("#"))
            defined = {m.group(1): m.start() for m in
                       re.finditer(r"^function\s+([A-Za-z][\w-]*)", code, re.M)}
            for func, at in defined.items():
                # Calls look like "Func " or "(Func " at a statement position.
                for call in re.finditer(r"(?<![\w-])" + re.escape(func)
                                        + r"(?=\s+[\"$\w-])", code):
                    if call.start() < at:
                        self.fail(f"{name}: {func} is used at character "
                                  f"{call.start()} and not defined until {at}")

    def test_the_check_reports_who_sees_whose_records(self):
        """Four people were being onboarded at once. A check that says the
        write path is healthy, and nothing about whether they each see their
        OWN rows, is answering the wrong question that week."""
        self.assertIn("SDI_VOICECRM_OWNERS", self.CHECK)
        self.assertIn('Live "crm_owners.py"', self.CHECK)

    def test_it_catches_the_setting_written_before_the_code_was_deployed(self):
        """── THE ORDERING MISTAKE THIS EXISTS FOR ─────────────────────────
        SDI_VOICECRM_OWNERS does nothing until crm_owners.py is on the server.
        Written first and deployed later, it leaves exactly the silent state
        it was meant to prevent - everybody seeing one person's records, with
        a setting in .env that says otherwise.
        """
        self.assertIn("is being IGNORED", self.CHECK)

    def test_the_settings_it_reports_are_the_ones_the_apps_actually_ask(self):
        """Two lists that can disagree is one more than there should be."""
        for setting, filename in (("SDI_ESTIMATOR_OIDS", "app.py"),
                                  ("SDI_TTI_OIDS", "tti_despatch_routes.py"),
                                  ("SDI_OPS_OIDS", "sdi_ops_routes.py")):
            source = (BACKEND / filename).read_text(encoding="utf-8")
            with self.subTest(setting=setting):
                self.assertIn(f'access.may_use("{setting}"', source)
                self.assertIn(f'Setting = "{setting}"', self.CHECK)
                self.assertIn(f'File = "{filename}"', self.CHECK)
