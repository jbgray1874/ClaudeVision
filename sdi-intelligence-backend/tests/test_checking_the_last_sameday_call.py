"""Check-SameDay-Call.ps1: what happened on the last SameDay call - read from the laptop, changing nothing.

4 November 2026: "the render didn't appear on the phone app". Played through the phone address with a stand-in render,
it appears, mid-call too - so the reason is on the server (never made, or failed), where a call keeps its error lines
off the screen. This shows them. There is no PowerShell here, so these read the script.
"""
import re
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent / "deploy" / "Check-SameDay-Call.ps1").read_text(encoding="utf-8")
BODY = "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in re.sub(r"<#.*?#>", "", SCRIPT, flags=re.S).split("\n"))


class ItOnlyReadsTests(unittest.TestCase):
    def test_no_writes_no_restarts(self):
        for verb in ("Set-Content", "Out-File", "Remove-Item", "Copy-Item", "Restart-Service", "sc.exe", "robocopy",
                     "-Method Post", "Invoke-WebRequest -Method", "New-Item"):
            with self.subTest(verb=verb):
                self.assertNotIn(verb, BODY)

    def test_from_the_laptop_through_the_office_address(self):
        self.assertIn("Run FROM THE LAPTOP, VPN connected", SCRIPT.split("#>", 1)[0])
        self.assertIn('$Via = "http://${Server}:8071/sameday"', BODY)
        self.assertIn(r'$Log = "\\$Server\c$\SDI_Automation\logs\SDISameDay.log"', BODY)

    def test_ascii_and_no_drive_traps(self):
        self.assertTrue(all(ord(c) < 128 for c in SCRIPT))
        for line in BODY.splitlines():
            for s in re.findall(r'"[^"]*"', line):
                self.assertIsNone(re.search(r"\$(?!env:)[A-Za-z_]\w*:", s), line)


class ItShowsWhatStopsARenderTests(unittest.TestCase):
    def test_the_cap_the_key_the_chat_and_the_log(self):
        for part in ('Ask "/api/status"', "$status.openai_key", "brief_lite_daily_cap_usd", 'Ask "/api/sessions"',
                     '"/api/session/"', "Select-String -Pattern $pattern"):
            with self.subTest(part=part):
                self.assertIn(part, BODY)

    def test_nothing_key_shaped_is_printed(self):
        self.assertIn("function NoKeys", BODY)
        self.assertIn("NoKeys ([string]$m.text)", BODY)
        self.assertIn("NoKeys ([string]$h.Line)", BODY)

    def test_fails_closed_on_the_log(self):
        self.assertIn("-ErrorAction Stop | Sort-Object LastWriteTime | Select-Object -Last 3) } catch { $files = @() }", BODY)

    def test_a_list_from_the_server_is_laid_out_item_by_item(self):
        """4 Nov: in Windows PowerShell 5.1 the chat list came back as one item, and every chat printed at once."""
        self.assertIn("function Items($Value) { return @($Value | ForEach-Object { $_ }) }", BODY)
        self.assertIn('$chats = Items (Ask "/api/sessions")', BODY)
        self.assertIn("Items $one.messages", BODY)

    def test_the_log_from_before_a_restart_is_read_too(self):
        """A restart starts a new log file - the call was in the one before."""
        self.assertIn('-Filter "SDISameDay*.log"', BODY)
        self.assertIn("rt tool|rt done", BODY)

    def test_any_chat_can_be_read(self):
        self.assertIn("[string]$Chat", BODY)


if __name__ == "__main__":
    unittest.main()
