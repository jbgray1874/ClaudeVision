"""Check-Entra-Access.ps1 audits Entra with a tenant admin's sign-in.

That makes it the most dangerous script in the repository if it ever does
more than look. It is run by somebody with the rights to assign, remove and
change accounts, against the directory every SDI login depends on - so the
promise in its header, "IT ONLY READS", is pinned here rather than trusted.

And it was written instead of asking four company directors to test their own
access by clicking a link, so the things it checks are pinned too: a check
that quietly stopped checking would put us straight back there.
"""
import re
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
SCRIPT = (BACKEND / "deploy" / "Check-Entra-Access.ps1").read_text(encoding="utf-8")


def code() -> str:
    """The script with its comments removed, so a word in an explanation is
    not mistaken for a command."""
    body = re.sub(r"<#.*?#>", "", SCRIPT, flags=re.S)
    return "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))


# The one Set-Mg command allowed, and the only way it may be called. It sets
# how THIS laptop's Graph module signs in; it writes nothing to Entra.
LOCAL_OPTION = "Set-MgGraphOption -DisableLoginByWAM $true"


class ItOnlyReadsTests(unittest.TestCase):
    def test_it_asks_for_read_scopes_and_nothing_else(self):
        declared = re.search(r"\$scopes\s*=\s*(.+)", code())
        self.assertIsNotNone(declared, "the scope list has changed shape")
        scopes = re.findall(r'"([A-Za-z.]+)"', declared.group(1))
        self.assertTrue(scopes)
        for scope in scopes:
            with self.subTest(scope=scope):
                self.assertTrue(scope.endswith(".Read.All"),
                                f"{scope} is not a read-only scope")

    def test_every_sign_in_route_uses_that_one_list(self):
        """There are two routes now - browser and device code. A second
        literal scope list on either is how a ReadWrite slips in unseen."""
        connects = re.findall(r"Connect-MgGraph[^\n]*", code())
        self.assertGreaterEqual(len(connects), 2)
        for line in connects:
            with self.subTest(call=line.strip()[:60]):
                self.assertIn("-Scopes $scopes", line)

    def test_it_calls_no_graph_command_that_changes_anything(self):
        """Graph PowerShell names every write with a verb. None may appear -
        apart from the one local sign-in preference, removed before checking
        so that it cannot hide anything else."""
        body = code().replace(LOCAL_OPTION, "")
        for verb in ("New-Mg", "Set-Mg", "Update-Mg", "Remove-Mg", "Add-Mg",
                     "Invoke-Mg", "Restore-Mg", "Grant-Mg", "Revoke-Mg"):
            with self.subTest(verb=verb):
                self.assertNotIn(verb, body)

    def test_the_one_set_command_only_ever_switches_wam_off(self):
        """Set-MgGraphOption can set other things. Here it may set exactly
        one, to exactly one value."""
        calls = re.findall(r"Set-MgGraphOption[^\n]*", code())
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith(LOCAL_OPTION))

    def test_it_does_not_touch_the_servers_settings(self):
        """It reads .env to compare. Writing it is Set-Setting's job, which
        takes a backup first and was built for exactly that."""
        for write in ("Set-Content", "Out-File", "WriteAllLines", "WriteAllText",
                      "Add-Content", "Copy-Item", "Move-Item", "Remove-Item"):
            with self.subTest(command=write):
                self.assertNotIn(write, code())

    def test_it_never_restarts_anything(self):
        for command in ("Restart-Service", "Stop-Service", "Start-Service", "sc.exe"):
            with self.subTest(command=command):
                self.assertNotIn(command, code())

    def test_it_signs_out_when_it_is_done(self):
        """A tenant-admin Graph session left open on a laptop is a session
        the next thing run on that laptop inherits."""
        self.assertIn("Disconnect-MgGraph", code())


class ItChecksTheThingsThatFailSilentlyTests(unittest.TestCase):
    def test_it_finds_the_application_by_id_not_by_name(self):
        """Two registrations in this tenant both read as "SDI Intelligence",
        and on 29 October a claim went on the wrong one."""
        self.assertIn("appId eq '$clientId'", code())
        self.assertNotRegex(code(), r"displayName eq '.*SDI")

    def test_it_compares_the_real_sign_in_address_with_the_one_we_hold(self):
        """"Thornhill" and "Thirnhill" are one keystroke apart, and the wrong
        one fails as "your records aren't mapped yet"."""
        self.assertIn("$upn.ToLower() -ne $wanted", code())

    def test_when_an_address_is_wrong_it_goes_and_finds_the_right_one(self):
        self.assertIn("startswith(displayName,'$first')", code())

    def test_group_assignment_uses_direct_membership(self):
        """Entra assignment does not flow through nested groups, so a
        transitive check would report people as fine who are locked out."""
        self.assertIn("Get-MgUserMemberOf", code())
        self.assertNotIn("TransitiveMemberOf", code())

    def test_it_checks_the_server_settings_against_entras_address(self):
        """Comparing the setting to the address WE typed would pass a typo
        straight through - it has to be the address Entra holds."""
        self.assertIn("$key = $upn.ToLower()", code())
        self.assertIn("$ownerMap.ContainsKey($key)", code())

    def test_it_catches_a_read_only_person_on_the_writers_list(self):
        self.assertIn("Is READ-ONLY but IS on the writers list", SCRIPT)

    def test_wam_is_switched_off_before_anything_signs_in(self):
        """── 30 OCTOBER ───────────────────────────────────────────────────
        Signing in through Windows' Web Account Manager inside Windows
        Terminal took the whole PowerShell process down - "process exited
        with code 5", after the sign-in, with no output and nothing a
        try/catch could see. It also offered to make the ADMIN account the
        laptop's default sign-in for every app. Off first, then sign in.
        """
        body = code()
        self.assertIn(LOCAL_OPTION, body)
        self.assertLess(body.index(LOCAL_OPTION), body.index("Connect-MgGraph"))

    def test_there_is_a_route_that_needs_no_browser_window_at_all(self):
        self.assertIn("[switch]$DeviceCode", SCRIPT)
        self.assertIn("-UseDeviceCode", code())

    def test_a_missing_module_is_explained_not_crashed_into(self):
        self.assertIn("Install-Module Microsoft.Graph", SCRIPT)

    def test_it_names_the_gate_it_cannot_check(self):
        self.assertIn("SHAREPOINT", SCRIPT)


if __name__ == "__main__":
    unittest.main()
