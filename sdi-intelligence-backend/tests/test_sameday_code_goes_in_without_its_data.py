"""Publish-SameDay-Code.ps1: SameDay's code into its private repository, and
nothing else.

"Create the private repo for SameDay" - James Gray, 4 November 2026. The code
lives on K:, which no Claude session can read; ClaudeVision is public, so it
cannot go there. The danger in moving it is everything that sits beside the
code on K: - the keys, the chats, client profiles, what account managers
uploaded - so that is what these pin.

There is no PowerShell here, so these read the script.
"""
import re
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent / "deploy" / "Publish-SameDay-Code.ps1"
          ).read_text(encoding="utf-8")


def code(source: str) -> str:
    out = re.sub(r"<#.*?#>", "", source, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in out.split("\n"))


BODY = code(SCRIPT)


class NothingButCodeTests(unittest.TestCase):
    def test_the_keys_data_and_uploads_are_never_copied(self):
        files = BODY.split("$skipFiles = @(", 1)[1].split(")", 1)[0]
        for name in ('".env"', '"*.db"', '"*.npz"', '"client_profiles.json"', '"*.log"'):
            with self.subTest(name=name):
                self.assertIn(name, files)
        dirs = BODY.split("$skipDirs = @(", 1)[1].split(")", 1)[0]
        for name in ('"out"', '"client_files"', '"backups"', '"studio_data"', '".venv-gpu"'):
            with self.subTest(name=name):
                self.assertIn(name, dirs)

    def test_big_files_are_left_behind_and_named(self):
        self.assertIn('"/MAX:5000000"', BODY)
        self.assertIn("left on K: (over 5 MB)", BODY)

    def test_a_gitignore_keeps_later_copies_clean_too(self):
        self.assertIn('Join-Path $Work ".gitignore"', BODY)


class KeysStopItBeforeAnythingIsSentTests(unittest.TestCase):
    def test_the_key_check_comes_before_the_commit_and_the_push(self):
        self.assertLess(BODY.index("$keyShape ="), BODY.index('RunGit @("commit"'))
        self.assertLess(BODY.index("$keyShape ="), BODY.index('RunGit @("push"'))

    def test_a_key_is_reported_by_file_and_line_never_its_text(self):
        for line in BODY.splitlines():
            if "$hit" in line and "Write-Host" in line:
                with self.subTest(line=line.strip()):
                    self.assertIn("$hit.Path", line)
                    self.assertNotIn("$hit.Line ", line + " ")
                    self.assertNotIn("Matches", line)

    def test_a_settings_file_stops_it_too(self):
        self.assertIn('$_.Name -like ".env*" -and $_.Name -ne ".env.example"', BODY)


class ItGoesToThePrivateRepositoryOnlyTests(unittest.TestCase):
    def test_the_address_is_sdi_sameday(self):
        self.assertIn('$Repo = "https://jbgray1874@github.com/jbgray1874/sdi-sameday.git"', BODY)
        self.assertNotIn("ClaudeVision.git", BODY)

    def test_it_never_empties_a_folder_it_does_not_own(self):
        guard = BODY.split("$full = ", 1)[1].split("Yes \"Working folder", 1)[0]
        for protected in ('"C:\\ClaudeVision*"', '"C:\\SDI_Automation*"'):
            self.assertIn(protected, guard)
        self.assertIn("exists and is not this script's", guard)
        self.assertIn("belongs to another repository", guard)


class PowerShellTrapsTests(unittest.TestCase):
    def test_no_function_shadows_git(self):
        """Function names are case-blind and beat programs: a function called
        Git would call itself instead of git.exe, for ever."""
        self.assertNotRegex(BODY, r"(?im)^\s*function\s+git\b")
        self.assertIn("& git.exe -C $Work @Arguments | Out-Host", BODY)


if __name__ == "__main__":
    unittest.main()


class ItFailsClosedTests(unittest.TestCase):
    """4 November: run in a window that could not see K:, the readability
    check ERRORED - and an error inside an if's condition makes PowerShell
    skip the whole if, so it printed "[ok] readable" and went on. Robocopy
    then stopped it; nothing was sent, but the check had said yes."""

    def test_the_share_is_read_by_its_full_name_not_a_drive_letter(self):
        self.assertIn('$Source = "\\\\sdi-dc01\\shareddata$\\Shared\\IT\\', BODY)
        self.assertNotIn('$Source = "K:', BODY)

    def test_no_path_from_the_share_is_built_by_a_command_that_can_throw(self):
        self.assertNotRegex(BODY, r"Join-Path \$(Source|auto)\b")

    def test_the_readability_check_is_caught_and_stops(self):
        check = BODY.split("$readable = $false", 1)[1].split('Yes "SameDay', 1)[0]
        self.assertIn("-ErrorAction Stop } catch { $readable = $false }", check)
        self.assertIn("if (-not $readable) {", check)
        self.assertIn("Stop-Here", check)

    def test_the_copy_is_checked_before_anything_is_committed(self):
        self.assertLess(BODY.index('"The copy does not hold brief_lite\\lite_app.py'),
                        BODY.index('RunGit @("commit"'))

    def test_the_readiness_check_reads_the_same_share(self):
        check = (Path(__file__).resolve().parent.parent / "deploy" / "Check-SameDay-Ready.ps1"
                 ).read_text(encoding="utf-8")
        self.assertIn('$Source = "\\\\sdi-dc01\\shareddata$\\Shared\\IT\\', check)
