"""Install-SameDay.ps1: a new app beside SDI Intelligence, never on top of it.

"this is a new application called sameday. it's a new web app, with its own
existence that will be added to the sdiintelligence web portal but it's not to
over ride anything in there already" - James Gray, 3 November 2026.

There is no PowerShell here, so these read the script. What they pin is that
promise: SDI Intelligence's service is only ever looked at; Python 3.11 goes
in beside whatever is there without changing PATH, the py launcher or file
types; an existing install is never overwritten without -Update, and an update
never replaces the server's own data or keys; the firewall gains two rules and
loses none; and the keys are never opened or printed.
"""
import re
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent / "deploy" / "Install-SameDay.ps1"
          ).read_text(encoding="utf-8")


def code(source: str) -> str:
    """Without comments, so a sentence about a thing is not mistaken for it."""
    out = re.sub(r"<#.*?#>", "", source, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in out.split("\n"))


BODY = code(SCRIPT)


class SDIIntelligenceIsOnlyLookedAtTests(unittest.TestCase):
    def test_every_mention_of_its_service_is_a_read(self):
        """A read, or a sentence on the screen naming it - never an action."""
        for line in BODY.splitlines():
            if "SDIIntelligence" in line:
                with self.subTest(line=line.strip()):
                    said = re.match(r"\s*(Stop-Here|Yes|Warn|Say) \"", line)
                    self.assertTrue("Get-Service" in line or said, line)

    def test_nothing_is_stopped_removed_or_mirrored(self):
        for verb in ("Stop-Service", "Restart-Service", "Remove-Item", "Remove-NetFirewallRule",
                     "Set-NetFirewallRule", "Disable-NetFirewallRule", "/PURGE", "/MIR",
                     "C:\\ClaudeVision", "8071", "setx", "[Environment]::SetEnvironmentVariable"):
            with self.subTest(verb=verb):
                self.assertNotIn(verb.lower(), BODY.lower())

    def test_nssm_only_ever_touches_sameday_s_two_services(self):
        self.assertIn('Name = "SDISameDay"', BODY)
        self.assertIn('Name = "SDICraft"', BODY)
        calls = re.findall(r'Nssm @\("(\w+)", \$name', BODY)
        self.assertTrue(calls)
        self.assertNotRegex(BODY, r'Nssm @\("\w+", "(?!SDISameDay|SDICraft)')


class PythonGoesInBesideTests(unittest.TestCase):
    def test_path_launcher_and_file_types_are_left_alone(self):
        for setting in ("PrependPath=0", "Include_launcher=0", "AssociateFiles=0",
                        "InstallAllUsers=1"):
            self.assertIn(setting, BODY)

    def test_only_when_missing(self):
        install = BODY.split('Head "2.', 1)[1].split('Head "3.', 1)[0]
        self.assertLess(install.index("if (Test-Path -LiteralPath $Python)"),
                        install.index("Invoke-WebRequest"))

    def test_sameday_names_its_python_by_full_path(self):
        self.assertIn('$Python = "C:\\Program Files\\Python311\\python.exe"', BODY)
        self.assertNotRegex(BODY, r"(^|\s)(py|python)(\.exe)? -")


class AnInstallIsNeverOverwrittenTests(unittest.TestCase):
    def test_an_existing_install_needs_update(self):
        self.assertIn("if ($installed -and -not $Update)", BODY)
        self.assertIn('if ($svc -and -not $Update) { Stop-Here', BODY)

    def test_a_port_in_use_by_something_else_stops_it(self):
        self.assertIn("Something else is already listening on port", BODY)

    def test_an_update_keeps_the_server_s_own_data_and_keys(self):
        update = BODY.split("if ($Update) {", 2)[2] if BODY.count("if ($Update) {") > 1 \
            else BODY.split("if ($Update) {", 1)[1]
        update = update.split("}", 1)[0]
        for kept in ('"out"', '"client_files"', '"studio_data"', '".env"', '"lite.db"',
                     '"craft.db"'):
            with self.subTest(kept=kept):
                self.assertIn(kept, update)

    def test_old_copies_of_the_code_are_not_copied(self):
        self.assertIn('$skipDirs = @("backups"', BODY)


class TheKeysTests(unittest.TestCase):
    def test_never_opened(self):
        for line in BODY.splitlines():
            if "$keys" in line:
                with self.subTest(line=line.strip()):
                    self.assertNotIn("Get-Content", line)

    def test_narrowed_to_the_services_and_administrators(self):
        self.assertIn('/inheritance:r /grant:r "*S-1-5-18:(R)" "*S-1-5-32-544:(F)"', BODY)

    def test_a_log_tail_has_keys_removed_before_it_is_shown(self):
        tail = BODY.split("function SafeTail", 1)[1].split("\n}", 1)[0]
        self.assertIn("[key removed]", tail)


class TheNetworkTests(unittest.TestCase):
    def test_two_rules_for_its_own_ports_from_private_addresses_only(self):
        self.assertIn('"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"', BODY)
        self.assertIn("-LocalPort $app.Port -RemoteAddress $AllowFrom", BODY)
        self.assertIn("Port = 5020", BODY)
        self.assertIn("Port = 5030", BODY)

    def test_the_source_is_the_share_not_a_drive_letter(self):
        self.assertIn('$Source = "\\\\sdi-dc01\\shareddata$\\Shared\\IT\\', BODY)

    def test_cpu_packages_because_there_is_no_gpu(self):
        self.assertIn("-replace '\\+cu\\d+', ''", BODY)


class ItEndsByCheckingTests(unittest.TestCase):
    def test_it_waits_for_the_apps_to_answer_and_says_sdi_intelligence_is_still_up(self):
        self.assertIn("http://localhost:$($app.Port)$($app.Probe)", BODY)
        self.assertIn("SDI Intelligence is still running, untouched", BODY)


if __name__ == "__main__":
    unittest.main()
