"""Compare-SameDay-K.ps1: what Muhammad has changed on K:, compared with the repository - reading only.

4 November 2026: "I asked what he had put into the K: and if we can compare that with what's in the repo - not to do
anything with it but just to understand it ... I don't want his code pushed." Publish-SameDay-Code.ps1 sends K:'s code
to GitHub; this must never send anything, never write to K:, and never put keys or data in its report.

There is no PowerShell here, so these read the script.
"""
import re
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
SCRIPT = (DEPLOY / "Compare-SameDay-K.ps1").read_text(encoding="utf-8")
PUBLISH = (DEPLOY / "Publish-SameDay-Code.ps1").read_text(encoding="utf-8")


def code(source: str) -> str:
    out = re.sub(r"<#.*?#>", "", source, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in out.split("\n"))


BODY = code(SCRIPT)


def ps_list(source: str, name: str) -> list:
    m = re.search(r"\$" + name + r" = @\((.*?)\)\n", source, flags=re.S)
    return re.findall(r'"([^"]*)"', m.group(1))


class NothingIsSentTests(unittest.TestCase):
    def test_no_git_command_that_writes_to_github_or_history(self):
        for verb in ('"push"', '"commit"', '"merge"', '"tag"', "git push", "git commit", "push origin"):
            with self.subTest(verb=verb):
                self.assertNotIn(verb, BODY)

    def test_github_is_only_fetched(self):
        self.assertIn('fetch -q origin "+refs/heads/*:refs/remotes/origin/*"', BODY)
        self.assertEqual(len(re.findall(r"\bfetch\b", BODY)), 1)

    def test_k_is_only_read(self):
        # robocopy FROM K: into the working folder; documents copied TO the working folder; nothing else touches $Source
        self.assertIn('$robo = @($auto, (Join-Path $Work "SDI_Automation")', BODY)
        self.assertIn("Copy-Item -LiteralPath $from -Destination $Work", BODY)
        self.assertNotIn("/MIR", BODY)
        self.assertNotIn("/PURGE", BODY)
        for line in BODY.splitlines():
            if re.search(r"Remove-Item|Set-Content|Out-File|WriteAll|New-Item", line):
                with self.subTest(line=line.strip()):
                    self.assertNotRegex(line, r"\$(Source|auto)\b")

    def test_its_own_folder_never_publish_or_update_s(self):
        for folder in ("C:\\ClaudeVision*", "C:\\SDI_Automation*", "C:\\SameDayRepo*", "C:\\SameDayDeploy*"):
            with self.subTest(folder=folder):
                self.assertIn(f'$full -like "{folder}"', BODY)
        self.assertIn('[string]$Work = "C:\\SameDayCompare"', BODY)
        self.assertIn("exists and is not this script's", BODY)
        self.assertIn("belongs to another repository", BODY)

    def test_the_folder_is_emptied_only_after_it_is_proved_its_own(self):
        self.assertLess(BODY.index("belongs to another repository"), BODY.index("Remove-Item -Recurse -Force"))


class TheSameFilesAsPublishTests(unittest.TestCase):
    def test_same_skip_lists_and_documents(self):
        for name in ("skipDirs", "skipFiles", "docs"):
            with self.subTest(name=name):
                self.assertEqual(ps_list(SCRIPT, name), ps_list(PUBLISH, name))

    def test_no_keys_or_data_in_the_report(self):
        for skipped in (".env", "*.db", "studio_data", "client_files", "logs", "out"):
            with self.subTest(skipped=skipped):
                self.assertIn(skipped, ps_list(SCRIPT, "skipDirs") + ps_list(SCRIPT, "skipFiles"))
        self.assertIn('$_.Name -like ".env*" -and $_.Name -ne ".env.example"', BODY)
        self.assertIn("NoKeys ([string]$_)", BODY)
        self.assertIn(re.search(r"\$keyShape = '([^']+)'", PUBLISH).group(1),
                      re.search(r"\$keyShape = '([^']+)'", SCRIPT).group(1))


class ItComparesRightTests(unittest.TestCase):
    def test_against_the_last_copy_of_k_and_the_servers_branch(self):
        self.assertIn('"--grep=^SameDay from K:"', BODY)
        self.assertIn('"refs/remotes/origin/from-k"', BODY)
        self.assertIn('[string]$Branch = "claude/inspiring-planck-8juriz"', BODY)
        self.assertIn('"refs/remotes/origin/$Branch"', BODY)

    def test_line_endings_on_the_folder_itself(self):
        """K: keeps Windows line endings; set only on 'add', a comparison read the file on disk and showed every line
        of a changed file as changed (checked with git on 4 Nov)."""
        self.assertIn("& git -C $Work config core.autocrlf true", BODY)
        self.assertLess(BODY.index("config core.autocrlf true"), BODY.index("add -A"))

    def test_nothing_is_committed_only_staged_here(self):
        self.assertIn("& git.exe -C $Work add -A", BODY)
        self.assertIn('"diff", "--cached"', BODY)


class PowerShellTrapsTests(unittest.TestCase):
    def test_ascii_only(self):
        self.assertTrue(all(ord(c) < 128 for c in SCRIPT))

    def test_no_variable_is_read_as_a_drive(self):
        for line in BODY.splitlines():
            for s in re.findall(r'"[^"]*"', line):
                self.assertIsNone(re.search(r"\$(?!env:)[A-Za-z_]\w*:", s), line)

    def test_no_function_shadows_git(self):
        self.assertNotRegex(BODY, r"(?im)^function\s+git\b")

    def test_fails_closed_on_k(self):
        self.assertIn('try { $readable = Test-Path -LiteralPath "$auto\\brief_lite\\lite_app.py" -ErrorAction Stop } '
                      'catch { $readable = $false }', BODY)

    def test_helpers_before_use(self):
        for fn in ("Head", "Yes", "Warn", "Say", "Stop-Here", "RunGit", "GitText", "NoKeys", "Counts"):
            with self.subTest(fn=fn):
                first_use = min(m.start() for m in re.finditer(r"(?<![\w-])" + re.escape(fn) + r"\b(?!\()", BODY)
                                if not BODY[max(0, m.start() - 9):m.start()].endswith("function "))
                self.assertLess(BODY.index("function " + fn), first_use)


if __name__ == "__main__":
    unittest.main()
