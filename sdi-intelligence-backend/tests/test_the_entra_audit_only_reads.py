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


# The one Set-Mg command allowed, and the only ways it may be called. It sets
# how THIS laptop's Graph module signs in; it writes nothing to Entra. Two
# spellings because the first version used one the module did not accept,
# swallowed the error, and left WAM on - see the script.
LOCAL_OPTIONS = ("Set-MgGraphOption -EnableLoginByWAM $false",
                 "Set-MgGraphOption -DisableLoginByWAM $true")
LOCAL_OPTION = LOCAL_OPTIONS[0]


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
        body = code()
        for allowed in LOCAL_OPTIONS:
            body = body.replace(allowed, "")
        for verb in ("New-Mg", "Set-Mg", "Update-Mg", "Remove-Mg", "Add-Mg",
                     "Invoke-Mg", "Restore-Mg", "Grant-Mg", "Revoke-Mg"):
            with self.subTest(verb=verb):
                self.assertNotIn(verb, body)

    def test_the_one_set_command_only_ever_switches_wam_off(self):
        """Set-MgGraphOption can set other things. Here it may set exactly
        one, to exactly one value."""
        calls = re.findall(r"Set-MgGraphOption[^\n]*", code())
        self.assertEqual(len(calls), 2)
        for call in calls:
            with self.subTest(call=call[:50]):
                self.assertTrue(call.startswith(LOCAL_OPTIONS),
                                f"Set-MgGraphOption used for something else: {call}")

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

    def test_it_knows_whether_switching_wam_off_worked(self):
        """── THE BUG IN THE FIRST FIX ─────────────────────────────────────
        "try { Set-MgGraphOption -DisableLoginByWAM $true } catch { }" - the
        parameter was wrong, the catch was empty, and WAM stayed on. The 07:34
        run printed "WAM is enabled by default" and survived on luck; the next
        crashed again. Whether it worked is now recorded, not assumed.
        """
        body = code()
        self.assertIn("$wamOff = $true", body)
        self.assertIn("if (-not $wamOff)", body)

    def test_code_sign_in_is_never_chosen_automatically(self):
        """── THE SECOND FIX THAT WAS WRONG ────────────────────────────────
        It fell back to code sign-in when WAM would not switch off. SDI's
        Conditional Access blocks code sign-in for admin accounts - "You don't
        have access to this ... an authentication flow that is restricted by
        your admin" - so the fallback led straight into a wall. It is only
        ever used when asked for by name.
        """
        body = code()
        self.assertNotIn("$useCode = $true", body)
        self.assertIn("$useCode = $DeviceCode.IsPresent", body)

    def test_when_wam_stays_on_it_says_how_to_avoid_the_crash(self):
        self.assertIn("plain", SCRIPT)
        self.assertIn("Windows PowerShell window", SCRIPT)
        self.assertIn("rather", SCRIPT)

    def test_the_output_survives_a_crash(self):
        """Twice it printed nothing anybody could paste."""
        self.assertIn("Start-Transcript", code())
        self.assertLess(code().index("Start-Transcript"), code().index("Head \"1."))

    def test_every_way_out_closes_the_transcript_and_says_where_it_is(self):
        body = code()
        self.assertIn("function Done(", body)
        exits = re.findall(r"^\s*exit\b.*$", body, re.M)
        self.assertEqual(exits, ["    exit $Code"],
                         f"an exit that skips Done, so the transcript path is never shown: {exits}")

    def test_a_slow_log_read_says_it_is_reading(self):
        """A long silent pause is indistinguishable from a hang."""
        self.assertIn("a large one takes a minute", SCRIPT)

    def test_there_is_a_route_that_needs_no_browser_window_at_all(self):
        self.assertIn("[switch]$DeviceCode", SCRIPT)
        self.assertIn("-UseDeviceCode", code())

    def test_a_missing_module_is_explained_not_crashed_into(self):
        self.assertIn("Install-Module Microsoft.Graph", SCRIPT)

    def test_it_names_the_gate_it_cannot_check(self):
        self.assertIn("SHAREPOINT", SCRIPT)


class TheAuditChecksTheIdentityTheAppActuallyUsesTests(unittest.TestCase):
    """── 30 OCTOBER, THE FIRST REAL RUN ───────────────────────────────────
    Nick's mailbox is nick.garrish@wearesdi.com. He signs in as
    nick.garrish@sdidisplays.co.uk. The settings had been written with the
    mailbox, every check that compared the settings with themselves passed,
    and he was locked out of his own records.

    The audit caught it because it compares Entra's SIGN-IN name - which is
    right only because the app also identifies people by sign-in name. If
    either side ever moved to the e-mail claim, the audit would go on
    reporting green against an identity the app no longer uses. So the
    three are pinned together.
    """

    def test_the_web_app_identifies_people_by_sign_in_name(self):
        source = (BACKEND / "auth.py").read_text(encoding="utf-8")
        self.assertIn('"email": c.get("preferred_username")', source)

    def test_the_chatgpt_connector_does_too(self):
        source = (BACKEND / "voicecrm_connector.py").read_text(encoding="utf-8")
        self.assertIn('email = c.get("preferred_username")', source)

    def test_and_the_audit_compares_the_sign_in_name(self):
        self.assertIn("$upn = $user.UserPrincipalName", code())
        self.assertIn("$key = $upn.ToLower()", code())

    def test_the_documented_example_uses_a_sign_in_name_that_differs(self):
        """The example people copy from is where the mistake started. It
        now shows the case that bites, with two domains in one setting."""
        owners = (BACKEND / "crm_owners.py").read_text(encoding="utf-8")
        self.assertIn("nick.garrish@sdidisplays.co.uk=NG", owners)
        self.assertNotIn("nick.garrish@wearesdi.com=NG", owners)


class ItFindsEveryoneTheChangeAffectsTests(unittest.TestCase):
    """"it doesn't affect any other user ... who also had read-only access?"

    It does, by design: before the owner map, everybody who opened AM CRM saw
    Nick's records; now anyone not in the map sees nothing. The audit answers
    "who is that?" from the logs instead of from memory.
    """

    def test_it_reads_who_has_used_am_crm_from_both_front_doors(self):
        body = code()
        self.assertIn('Service = "SDIIntelligence"', body)
        self.assertIn('Service = "SDITrackerConnector"', body)

    def test_it_only_counts_am_crm_lines(self):
        """The service log carries every app on the portal. Counting a TTI or
        estimating user as an AM CRM user would send somebody chasing access
        nobody needs."""
        self.assertIn(r"\[voicecrm\.[a-z]+\]", SCRIPT)
        self.assertIn(r"\[connector\]", SCRIPT)

    def test_the_log_tags_it_counts_are_the_only_ones_that_record_a_user(self):
        """If a new AM CRM log line starts recording users under another tag,
        the audit would silently stop counting those people."""
        tags = set()
        for path in BACKEND.glob("*.py"):
            for tag in re.findall(r'print\(f"\[([a-z_.]+)\][^"\n]*user=',
                                  path.read_text(encoding="utf-8")):
                tags.add(tag)
        for tag in tags:
            with self.subTest(tag=tag):
                self.assertTrue(tag.startswith("voicecrm.") or tag == "connector",
                                f"[{tag}] records a user and the audit does not count it")

    def test_it_finds_the_log_from_the_service_not_from_a_guess(self):
        self.assertIn("function LogFor(", SCRIPT)
        self.assertIn('GetValue("AppStdout")', SCRIPT)

    def test_an_unmapped_past_user_is_flagged_not_hidden(self):
        self.assertIn("has used AM CRM and is NOT mapped", SCRIPT)

    def test_its_variables_do_not_shadow_powershells_own(self):
        """$matches IS $Matches - PowerShell names are case-insensitive, and
        $Matches is what -match fills in. SettingLine reads it. Reusing the
        name for a list of log hits would hand SettingLine the wrong value on
        the next call. Same class of bug as $check shadowing [switch]$Check."""
        for name in ("$matches =", "$Matches =", "$input =", "$args =", "$error ="):
            with self.subTest(name=name):
                self.assertNotIn(name, code())


class ItFindsSecondAccountsTests(unittest.TestCase):
    """SDI moved from sdidisplays.co.uk to wearesdi.com. Nick signs in on the
    old domain with his mailbox on the new one, and somebody may have a
    separate account on each - whichever they use is the one that must be
    in the settings."""

    def test_it_searches_every_domain_by_the_name_before_the_at(self):
        self.assertIn("startswith($property,'$local@')", code())

    def test_by_sign_in_name_and_by_mailbox_separately(self):
        """Two queries, so one failing cannot hide the other."""
        self.assertIn('@("userPrincipalName", "mail")', code())

    def test_a_failed_lookup_says_so(self):
        self.assertIn("Could not check for a second account", SCRIPT)

    def test_a_disabled_second_account_is_not_raised_as_a_problem(self):
        """It cannot sign in. Flagging it would be crying wolf."""
        self.assertIn("which is DISABLED - cannot sign in, ignore", SCRIPT)

    def test_it_says_when_the_mailbox_differs_from_the_sign_in_name(self):
        self.assertIn("a different address from the sign-in name", SCRIPT)

    def test_a_name_with_an_apostrophe_cannot_break_the_query(self):
        """O'Brien would end the OData string early."""
        self.assertIn(""".Replace("'", "''")""", code())


if __name__ == "__main__":
    unittest.main()
