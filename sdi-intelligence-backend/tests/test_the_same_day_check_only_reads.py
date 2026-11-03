"""Check-SameDay-Ready.ps1: before SDI Same Day goes on the server, it looks.

"we need to do checks first of all ... otherwise it's pure laziness on our
part" - James Gray, 30 October 2026, about the AM CRM access that then failed
for Kayleigh. Same Day is the next app on the server, so the checks come
first again: this script runs on the laptop against the code on K: and the
server, and changes nothing on either.

There is no PowerShell here, so these read the script. What they pin is what
would make it dangerous or useless: a write anywhere, a key printed into a
transcript that gets pasted into chat, or the one finding that matters most -
mapped drive letters in the code - not being looked for.
"""
import re
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent / "deploy" / "Check-SameDay-Ready.ps1"
          ).read_text(encoding="utf-8")


def code(source: str) -> str:
    """The script without its comments, so a sentence ABOUT copying is not
    mistaken for a copy."""
    out = re.sub(r"<#.*?#>", "", source, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in out.split("\n"))


class ItOnlyReadsTests(unittest.TestCase):
    def test_nothing_that_writes_copies_or_starts(self):
        body = code(SCRIPT)
        for verb in ("Copy-Item", "robocopy", "xcopy", "Remove-Item", "Set-Content",
                     "Add-Content", "Out-File", "New-Item", "Move-Item", "Start-Process",
                     "Start-Service", "Restart-Service", "sc.exe", "nssm.exe set",
                     "Invoke-Command", "Set-ItemProperty"):
            with self.subTest(verb=verb):
                self.assertNotIn(verb.lower(), body.lower())

    def test_it_says_where_to_run_it_and_that_it_only_reads(self):
        head = SCRIPT[:1600].upper()
        self.assertIn("FROM THE LAPTOP", head)
        self.assertIn("READS ONLY", head)


class ItNeverPrintsAKeyTests(unittest.TestCase):
    def test_a_key_hit_is_reported_by_file_and_line_only(self):
        section = SCRIPT.split('Head "2.', 1)[1].split('Head "3.', 1)[0]
        reports = [l for l in section.splitlines() if "$hit" in l and "Block" in l]
        self.assertTrue(reports, "the key report line has moved")
        for line in reports:
            self.assertIn("$hit.Path", line)
            self.assertIn("$hit.LineNumber", line)
            self.assertNotIn("$hit.Line ", line + " ")
            self.assertNotIn("Matches", line)

    def test_the_settings_file_on_the_server_is_never_opened(self):
        server = SCRIPT.split('Head "4.', 1)[1].split('Head "5.', 1)[0]
        self.assertIn("(not read)", server)
        self.assertNotIn("Get-Content", server)

    def test_the_keys_file_is_judged_by_its_permissions_never_opened(self):
        """2 November: the keys now travel in the K: folder. Who can read
        them is the question, and it is answered from the file's permissions,
        so the check never reads a key to answer it."""
        keys = SCRIPT.split('Head "2.', 1)[1].split('Head "3.', 1)[0]
        self.assertIn("Get-Acl -LiteralPath $keysFile", keys)
        for opener in ("Get-Content", "ReadAllText", "Select-String -LiteralPath $keysFile"):
            self.assertNotIn(opener, keys)
        # The key-shape scan looks everywhere EXCEPT the keys file.
        self.assertIn('$_.Name -notlike ".env*"', keys.split("$keyShape =", 1)[1])

    def test_a_key_anywhere_else_still_stops_the_install(self):
        keys = SCRIPT.split('Head "2.', 1)[1].split('Head "3.', 1)[0]
        self.assertIn('Block "Key-shaped text in', keys)

    def test_it_looks_for_all_three_providers_key_shapes(self):
        for shape in ("sk-ant-", "sk-proj-", "xai-"):
            self.assertIn(shape, SCRIPT)


class ItLooksForWhatWillBreakTests(unittest.TestCase):
    def test_mapped_drive_paths_are_looked_for_and_https_is_not_one(self):
        """The finding that matters most: a service has no W: or K:."""
        pattern = re.search(r"\$drivePath = '([^']+)'", SCRIPT).group(1)
        found = re.compile(pattern)
        self.assertTrue(found.search(r'PAST = "W:\\Projects\\Archive"'))
        self.assertTrue(found.search("open('K:/IT/x.json')"))
        self.assertFalse(found.search("https://api.openai.com/v1"))
        self.assertFalse(found.search(r"C:\SDI_Automation\.env"))

    def test_the_app_proxy_timeout_is_compared(self):
        self.assertIn("-gt 180", SCRIPT)

    def test_the_server_checks_the_guide_depends_on(self):
        for check in ("Python311", "Tools\\nssm.exe", "5020, 5030", "FreeSpace"):
            self.assertIn(check, SCRIPT)

    def test_the_port_is_left_closed_because_the_connector_is_on_the_server(self):
        self.assertIn("PORT 5020 NEEDS NO OPENING", SCRIPT)
        self.assertIn("LITE_TRUST_FROM=127.0.0.1", SCRIPT)

    def test_it_says_which_account_will_read_the_shares(self):
        self.assertIn('GetValue("ObjectName")', SCRIPT)

    def test_nothing_already_on_the_server_is_taken_over(self):
        """3 November: "a new application ... with its own existence ...
        not to over ride anything in there already". Its folder, its ports
        and its two service names are each checked as free - and a list that
        could not be read is never reported as free."""
        for name in ('"SDISameDay", "SDICraft"', "is not on the server yet",
                     "already answering on port", "already exists on the server"):
            self.assertIn(name, SCRIPT)
        names = SCRIPT.split("-- NEW NAMES ONLY", 1)[1].split("-- 5.", 1)[0]
        self.assertLess(names.index("if (-not $hive)"), names.index("the name is free"))

    def test_the_lesson_from_kayleigh_is_on_the_list(self):
        self.assertIn("AADSTS50105", SCRIPT)
        self.assertIn("Assignment", SCRIPT)


if __name__ == "__main__":
    unittest.main()
