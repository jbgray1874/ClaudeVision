"""Update-SameDay.ps1: the server's SameDay from its private repository - the code, and nothing else.

4 November 2026: the "any order", noisy-room and phone changes were made in sdi-sameday. Muhammad's
UPDATE_SAME_DAY.bat copies K: (the older code) and starts a second SameDay outside its service. The first version of
this ran on the server and stopped at "git is not installed on this server"; the server has no git and needs none -
like Ship-It, this runs on the laptop and copies over the admin share. What must never happen: the keys, chats,
uploads or spend log replaced; SDI Intelligence touched; the old code lost.

There is no PowerShell here, so these read the script.
"""
import re
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "deploy" / "Update-SameDay.ps1"
SCRIPT = PATH.read_text(encoding="utf-8")


def code(source: str) -> str:
    out = re.sub(r"<#.*?#>", "", source, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in out.split("\n"))


BODY = code(SCRIPT)


class WhereAndHowItRunsTests(unittest.TestCase):
    def test_it_runs_from_the_laptop_like_ship_it(self):
        head = SCRIPT.split("#>", 1)[0]
        self.assertIn("Run FROM THE LAPTOP, VPN connected", head)
        self.assertIn(r".\sdi-intelligence-backend\deploy\Update-SameDay.ps1 -Branch claude/inspiring-planck-8juriz", head)
        self.assertIn("The server has no git, and needs none", head)          # why it runs on the laptop
        self.assertIn('$Target = "\\\\$Server\\c$\\SDI_Automation"', BODY)
        self.assertNotIn("C:\\Tools", BODY)

    def test_ascii_only(self):
        self.assertTrue(all(ord(c) < 128 for c in SCRIPT))

    def test_no_variable_is_read_as_a_drive(self):
        """"$Server:" in a double-quoted string is a drive-qualified variable to PowerShell - a parse error."""
        for line in BODY.splitlines():
            for s in re.findall(r'"[^"]*"', line):
                with self.subTest(line=line.strip()):
                    self.assertIsNone(re.search(r"\$(?!env:)[A-Za-z_]\w*:", s))

    def test_it_takes_the_private_repository_only(self):
        self.assertIn('$Repo = "https://jbgray1874@github.com/jbgray1874/sdi-sameday.git"', BODY)
        self.assertNotIn("ClaudeVision.git", BODY)
        self.assertNotIn("UPDATE_SAME_DAY.bat", BODY)
        self.assertNotIn("shareddata", BODY)          # never K:

    def test_its_own_working_copy_never_the_publish_scripts(self):
        self.assertIn('$Code = "C:\\SameDayDeploy"', BODY)
        self.assertNotIn("C:\\SameDayRepo", BODY)

    def test_no_function_shadows_git(self):
        self.assertNotRegex(BODY, r"(?im)^\s*function\s+git\b")
        self.assertIn("& git.exe -C $Code @Arguments | Out-Host", BODY)

    def test_it_fails_closed_before_anything_is_changed(self):
        checks = BODY.split('Head "2.', 1)[0]
        self.assertIn("-ErrorAction Stop } catch { $installed = $false }", checks)
        self.assertIn("Connect FortiClient VPN", checks)
        self.assertIn('"MISSING"', checks)
        self.assertIn("UNKNOWN*", checks)


class NothingButCodeTests(unittest.TestCase):
    def test_the_servers_data_is_never_copied_over(self):
        files = BODY.split("$skipFiles = @(", 1)[1].split(")", 1)[0]
        for name in ('".env"', '"*.db"', '"*.npz"', '"client_profiles.json"', '"*.log"', '"PHONE_LINK.txt"'):
            with self.subTest(name=name):
                self.assertIn(name, files)
        dirs = BODY.split("$skipDirs = @(", 1)[1].split(")", 1)[0]
        for name in ('"out"', '"client_files"', '"backups"', '"studio_data"', '".venv-gpu"', '"logs"', '".git"'):
            with self.subTest(name=name):
                self.assertIn(name, dirs)

    def test_a_key_in_the_repository_stops_it_before_the_copy(self):
        self.assertLess(BODY.index("$keyShape ="), BODY.index("$robo = @($auto, $Target"))

    def test_it_copies_and_never_mirrors(self):
        self.assertNotIn("/MIR", BODY)
        self.assertNotIn("/PURGE", BODY)


class TheOldCodeIsKeptTests(unittest.TestCase):
    def test_kept_before_it_is_replaced_and_said_how_to_put_back(self):
        self.assertLess(BODY.index("$robo = @($Target, $keep"), BODY.index("$robo = @($auto, $Target"))
        self.assertIn(r'$keep = "$Target\backups\before-update-', BODY)
        self.assertGreaterEqual(BODY.count('robocopy `"$keep`" `"$Target`" /E'), 2)

    def test_a_failed_copy_never_restarts_anything(self):
        failed = BODY.split("$robo = @($auto, $Target", 1)[1].split("[IO.File]::WriteAllLines", 1)[0]
        self.assertIn("exit 1", failed)
        self.assertLess(BODY.index("[IO.File]::WriteAllLines"), BODY.index("Restart-One $name"))


class OnlySameDayIsRestartedTests(unittest.TestCase):
    def test_only_its_own_two_services(self):
        self.assertIn('$Services = @("SDISameDay", "SDICraft")', BODY)
        self.assertIn('& sc.exe "\\\\$Server" stop $Name', BODY)
        self.assertIn('& sc.exe "\\\\$Server" start $Name', BODY)
        for line in BODY.splitlines():
            if "SDIIntelligence" in line:
                with self.subTest(line=line.strip()):
                    self.assertNotRegex(line, r"Restart-One|stop|start|Restart-Service")

    def test_no_second_copy_outside_the_service(self):
        self.assertNotIn("Start-Process", BODY)
        self.assertNotIn("lite_app.py\"", BODY.split('Head "5.', 1)[1])


class ItProvesItRunsTheNewCodeTests(unittest.TestCase):
    def test_the_running_version_names_the_branch_and_commit(self):
        self.assertIn('$want = ("$stamp repo $Branch $commit").Trim()', BODY)
        self.assertIn("(New-Object Text.ASCIIEncoding)", BODY)    # no byte-order mark in VERSION.txt
        # /api/version answers without the team code (the laptop is not the server); /api/status would not
        self.assertIn('$Version = "http://${Server}:5020/api/version"', BODY)
        self.assertIn("if ($now -eq $want) { break }", BODY)

    def test_the_laptops_copy_is_always_exactly_the_branch(self):
        self.assertIn('RunGit @("reset", "-q", "--hard", "origin/$Branch")', BODY)
        self.assertIn("exists and is not this script's", BODY)
        self.assertIn("belongs to another repository", BODY)

    def test_it_says_whether_sameday_can_read_the_drives(self):
        """Past jobs live on W:; a Windows service has no mapped drives, so SameDay maps them itself and says
        (in /api/version) whether it can read them - printed here, with what to do if not."""
        self.assertIn("$reads = $script:Answer.can_read", BODY)
        self.assertIn('foreach ($d in @("W", "S", "K"))', BODY)
        self.assertIn("LITE_DRIVES", BODY)

    def test_a_log_pasted_into_chat_has_no_keys(self):
        self.assertIn("[key removed]", BODY)


if __name__ == "__main__":
    unittest.main()
