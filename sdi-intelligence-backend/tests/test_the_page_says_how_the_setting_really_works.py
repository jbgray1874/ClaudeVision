"""What the portal tells you to type must be what the code reads.

26 October 2026. The Status Reports page said to add a root to SDI_FILE_ROOTS
"comma-separated alongside the existing AISheets root". config.py splits that
setting on a PIPE. Following the instruction gives you one long root that
matches nothing, a service that can reach no files, and no clue why - the
setting is present, it is spelled correctly, and it is wrong.

It also offered a "K:" path. The service runs as a service account with no
login session, so a drive letter is not a mapping it has lost; it is a path
that was never there. app.py's own health check says so, which means this has
cost somebody a day already.

Documentation that drifts from the code is not a cosmetic problem when it is
the documentation for how to configure the thing.
"""
import re
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

PORTAL = (BACKEND / "sdi-intelligence-portal.html").read_text(encoding="utf-8")
CONFIG = (BACKEND / "config.py").read_text(encoding="utf-8")


def advice() -> list[str]:
    """Every sentence in the portal that tells somebody to edit SDI_FILE_ROOTS."""
    return [line for line in PORTAL.splitlines()
            if "SDI_FILE_ROOTS" in line and ".env" in line]


class SeparatorTests(unittest.TestCase):
    def test_the_code_still_splits_on_a_pipe(self):
        """If this changes, the advice below has to change with it."""
        line = [l for l in CONFIG.splitlines() if l.startswith("FILE_ROOTS =")][0]
        self.assertIn('split("|")', line)

    def test_nothing_tells_anybody_to_use_a_comma(self):
        for line in advice():
            with self.subTest(line=line[:90]):
                self.assertNotIn("comma-separated", line.lower())
                self.assertNotIn("comma separated", line.lower())

    def test_where_a_separator_is_named_it_is_the_pipe(self):
        named = [l for l in advice() if "separat" in l.lower()]
        self.assertTrue(named, "no advice names a separator at all")
        for line in named:
            with self.subTest(line=line[:90]):
                self.assertIn("|", line)


class DriveLetterTests(unittest.TestCase):
    def test_no_advice_offers_a_MAPPED_drive_as_the_value_to_type(self):
        """A service account has no K:. Saying so beats a reachable:false that
        reads like a permissions problem.

        C: is not the same thing and is allowed: it is a local disk the service
        can genuinely see, and C:\\ClaudeVision\\output\\reports is a real root.
        A mapped network drive is the one that exists for a logged-in person
        and not for a service."""
        for line in advice():
            with self.subTest(line=line[:90]):
                typed = re.findall(r"<code>([A-Za-z]):\\\\?[^<]*</code>", line)
                mapped = [d for d in typed if d.upper() != "C"]
                self.assertEqual(mapped, [], f"offers a mapped drive: {mapped}")

    def test_the_health_check_still_warns_about_mapped_drives(self):
        app = (BACKEND / "app.py").read_text(encoding="utf-8")
        self.assertIn("mapped_drive", app)
        # Wrapped across two source lines, so match a piece that is contiguous.
        self.assertIn("This is a mapped drive letter", app)
        self.assertIn("Drive letters belong to a login", app)


if __name__ == "__main__":
    unittest.main()
