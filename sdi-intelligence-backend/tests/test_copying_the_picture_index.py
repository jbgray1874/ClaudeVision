"""Copy-SameDay-Index.ps1: Muhammad's picture index onto the server - from K:, the one way in, safely.

5 November 2026: Muhammad copies the picture index (all_img_index.npz), its job list (projects.db) and the thumbnails
to K:; this brings them to the server. A half-copied file must never go in, SameDay must be down for seconds not
minutes, the watch must not email about the swap, what is replaced is kept, and the keys and chats are never touched.
There is no PowerShell here, so these read the script.
"""
import re
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent / "deploy" / "Copy-SameDay-Index.ps1").read_text(encoding="utf-8")
BODY = "\n".join(re.sub(r"(^|\s)#.*$", "", x) for x in re.sub(r"<#.*?#>", "", SCRIPT, flags=re.S).split("\n"))


def at(text):
    i = BODY.find(text)
    assert i >= 0, text
    return i


class OrderTests(unittest.TestCase):
    def test_every_check_before_anything_changes(self):
        first_change = at("New-Item -ItemType Directory -Force -Path $keep")
        for check in ("[IO.Compression.ZipFile]::OpenRead($npz)", 'StartsWith("SQLite format 3")',
                      "is still being copied", 'There "$Target\\brief_lite\\lite_app.py"', "Win32_LogicalDisk"):
            with self.subTest(check=check):
                self.assertLess(at(check), first_change)

    def test_kept_then_copied_while_running_then_swapped_in_seconds(self):
        self.assertLess(at("Copy-Item -LiteralPath $p -Destination $keep"), at("-Destination $newNpz"))
        self.assertLess(at("-Destination $newNpz"), at("stop SDISameDay"))           # the long copy, SameDay up
        self.assertLess(at("stop SDISameDay"), at("Move-Item -LiteralPath $newNpz"))  # a rename, SameDay down
        self.assertLess(at("Move-Item -LiteralPath $newDb"), BODY.rindex('" start SDISameDay | Out-Null'))

    def test_the_thumbnails_stay_on_k_and_are_never_copied(self):
        """5 Nov (James: "use the index from the mounted K: ... this is a production server"): 14.7 GB of thumbnails
        were being copied onto the server's C: on a guess at their size."""
        self.assertNotIn("robocopy", BODY)
        self.assertNotIn("$Target\\all_img_thumbs", BODY)
        self.assertIn("The thumbnails stay on K:", BODY)

    def test_free_space_is_a_hard_gate(self):
        self.assertIn("nothing is copied onto a production server without that", BODY)
        self.assertIn("+ 20, 1)", BODY)                                 # 20 GB stays free
        self.assertLess(at("Win32_LogicalDisk"), at("New-Item -ItemType Directory -Force -Path $keep"))

    def test_the_watch_is_paused_for_the_swap_and_always_put_back(self):
        self.assertLess(at("/TN $Watch /DISABLE"), at("stop SDISameDay"))
        enables = [m.start() for m in re.finditer(r"/TN \$Watch /ENABLE", BODY)]
        self.assertEqual(len(enables), 3)      # when SameDay wouldn't stop, after the swap, after a put-back
        self.assertLess(at("didn't stop within a minute") - 300, enables[0])
        self.assertGreater(enables[1], at("Swapped in; SameDay is starting") - 200)


class HalfCopiedTests(unittest.TestCase):
    """5 Nov: it was run while Muhammad's copy was still going. A half-copied job list still looks like a database at
    its start, so both files must have stopped changing; and a job list SameDay can't read is put straight back."""

    def test_both_files_must_have_stopped_changing(self):
        self.assertIn("foreach ($p in @($npz, $db))", BODY)
        self.assertIn("$it.LastWriteTime -gt (Get-Date).AddMinutes(-2)", BODY)
        self.assertIn("is still being copied", BODY)

    def test_a_job_list_sameday_cant_read_is_put_back_by_itself(self):
        self.assertIn("[int]$past.jobs -le 0", BODY)
        back = BODY[at("[int]$past.jobs -le 0"):]
        self.assertIn('Copy-Item -LiteralPath "$keep\\projects.db" -Destination "$Target\\brief_lite\\projects.db"', back)
        self.assertLess(back.index("/DISABLE"), back.index("stop SDISameDay"))
        self.assertLess(back.index("start SDISameDay"), back.index("/ENABLE"))


class SafetyTests(unittest.TestCase):
    def test_a_failed_swap_puts_back_what_was_there(self):
        self.assertIn('@("$keep\\projects.db", "$Target\\brief_lite\\projects.db")', BODY)
        self.assertIn('@("$keep\\all_img_index.npz", "$Target\\all_img_index.npz")', BODY)

    def test_never_the_keys_or_the_chats_and_nothing_deleted(self):
        self.assertNotIn(".env", BODY)
        self.assertNotIn("lite.db", BODY)
        self.assertNotIn("/MIR", BODY)
        self.assertNotIn("/PURGE", BODY)
        for line in BODY.splitlines():
            if "Remove-Item" in line:
                with self.subTest(line=line.strip()):    # its own temporary files, or the index it put in itself
                    self.assertTrue("$newNpz, $newDb" in line or '"$Target\\all_img_index.npz"' in line, line)

    def test_from_the_folder_muhammad_was_asked_to_use(self):
        self.assertIn("SDI Same Day Intelligence\\index-for-server", BODY)

    def test_it_says_whether_sameday_uses_it(self):
        self.assertIn('$Version = "http://${Server}:5020/api/version"', BODY)
        self.assertIn("$past.pictures", BODY)
        self.assertIn("newer than the job index", BODY)


class PowerShellTrapsTests(unittest.TestCase):
    def test_ascii_only(self):
        self.assertTrue(all(ord(c) < 128 for c in SCRIPT))

    def test_no_variable_is_read_as_a_drive(self):
        for line in BODY.splitlines():
            for s in re.findall(r'"[^"]*"', line):
                self.assertIsNone(re.search(r"\$(?!env:)[A-Za-z_]\w*:", s), line)

    def test_helpers_before_use(self):
        for fn in ("Head", "Yes", "Warn", "Say", "Stop-Here", "There", "Size-MB", "Past-Work", "Service-State"):
            with self.subTest(fn=fn):
                uses = [m.start() for m in re.finditer(r"(?<![\w-])" + re.escape(fn) + r"\b", BODY)
                        if not BODY[max(0, m.start() - 9):m.start()].endswith("function ")]
                self.assertLess(at("function " + fn), min(uses))


if __name__ == "__main__":
    unittest.main()
