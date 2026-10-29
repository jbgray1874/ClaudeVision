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
