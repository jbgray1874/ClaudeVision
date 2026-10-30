"""Reusing a parse of the Despatch Plan, without reusing anybody's access.

Six views and a voice assistant now ask the same workbook questions, often
two or three in a row. Fetching and re-parsing seventeen weekly sheets for
each would make the chase list slow enough that people stop opening it.

So a parse is reused - and that is exactly the kind of saving that quietly
becomes a permission hole. The property that must hold:

    EVERY call still asks SharePoint about the file with THAT person's token.

If their access has gone, the metadata request refuses and they get nothing,
cache or no cache. What is saved is a download and a parse, and only when
SharePoint's own eTag says the file has not been saved since. Nobody is ever
admitted by a copy somebody else's rights fetched.

The second property: the reading's age is never overstated. The save time
comes back from SharePoint on every call, so a reused parse is still reported
with SharePoint's current answer about when the file was last written.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import tti_data                                                     # noqa: E402
import tti_plan_source as plan                                      # noqa: E402

SOURCE = (BACKEND / "tti_data.py").read_text(encoding="utf-8")
SAVED = datetime(2026, 10, 23, 14, 5, tzinfo=timezone.utc)

# A one-row workbook, built here rather than committed, so the test does not
# depend on a copy of somebody's commercial tracker being in the repository.
HEADERS = ["DUE DATE", "SDI ORDER NO", "PART CODE", "DESCRIPTION",
           "LORRY FROM SDI", "COMMENTS"]


def workbook(order: str) -> bytes:
    import io
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "Oct 26 WK 40"
    sheet.append(HEADERS)
    sheet.append(["30/10/2026", order, "ABC-1", "Gondola", "30/10/2026", ""])
    held = io.BytesIO()
    book.save(held)
    return held.getvalue()


class Fetch:
    """Stands in for SharePoint. Counts what it was asked for, and can refuse
    the way a person who has lost access is refused."""

    def __init__(self, order="15194", version='"ETAG-1"'):
        self.order, self.version = order, version
        self.asked, self.downloaded, self.refuse = 0, 0, ""

    def __call__(self, token, client=None, known_version=""):
        self.asked += 1
        if self.refuse:
            raise plan.PlanUnavailable(self.refuse)
        if known_version and known_version == self.version:
            return None, SAVED, self.version
        self.downloaded += 1
        return workbook(self.order), SAVED, self.version


class ReusingAParseTests(unittest.TestCase):
    def setUp(self):
        tti_data.forget()
        self.fetch = Fetch()
        self._real = plan.fetch_plan
        plan.fetch_plan = self.fetch
        self.addCleanup(setattr, plan, "fetch_plan", self._real)
        self.addCleanup(tti_data.forget)
        for key, value in (("SDI_TTI_PLAN_SITE", "host:/sites/X"),
                           ("SDI_TTI_PLAN_PATH", "General/Plan.xlsx")):
            import os
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)

    def test_the_first_reading_downloads_and_parses(self):
        first = tti_data.rows_for("tok-sue")
        self.assertEqual(len(first.rows), 1)
        self.assertEqual(self.fetch.downloaded, 1)
        self.assertFalse(first.reused)

    def test_an_unchanged_file_is_not_downloaded_or_parsed_again(self):
        tti_data.rows_for("tok-sue")
        again = tti_data.rows_for("tok-selina")
        self.assertEqual(self.fetch.downloaded, 1)
        self.assertTrue(again.reused)
        self.assertEqual(len(again.rows), 1)

    def test_sharepoint_is_asked_on_every_single_call(self):
        """── THE PROPERTY THAT MAKES THE CACHE SAFE ────────────────────────
        A reused parse must not mean a skipped question. The metadata request
        is what checks this person's access, so it happens every time."""
        for _ in range(4):
            tti_data.rows_for("tok-anyone")
        self.assertEqual(self.fetch.asked, 4)

    def test_a_person_who_has_lost_access_gets_nothing_although_rows_are_held(self):
        """The one that would have been a real hole: Sue reads the plan, Lee's
        access to the site is removed that afternoon, Lee asks."""
        held = tti_data.rows_for("tok-sue")
        self.assertEqual(len(held.rows), 1)
        self.fetch.refuse = ("Your account does not have access to the plan in "
                             "SharePoint.")
        with self.assertRaises(tti_data.Unavailable) as refused:
            tti_data.rows_for("tok-lee")
        self.assertIn("does not have access", str(refused.exception))

    def test_a_saved_workbook_is_read_again(self):
        tti_data.rows_for("tok-sue")
        self.fetch.version, self.fetch.order = '"ETAG-2"', "15999"
        after = tti_data.rows_for("tok-sue")
        self.assertEqual(self.fetch.downloaded, 2)
        self.assertFalse(after.reused)
        self.assertEqual(after.rows[0].cells["SDI ORDER NO"], "15999")

    def test_a_workbook_that_will_not_open_says_so_rather_than_failing_obscurely(self):
        def broken(token, client=None, known_version=""):
            return b"this is not a spreadsheet", SAVED, '"E"'

        plan.fetch_plan = broken
        with self.assertRaises(tti_data.Unavailable) as refused:
            tti_data.rows_for("tok")
        self.assertIn("could not be read", str(refused.exception))


class TheReadingsAgeIsNeverOverstatedTests(unittest.TestCase):
    def setUp(self):
        tti_data.forget()
        self.fetch = Fetch()
        self._real = plan.fetch_plan
        plan.fetch_plan = self.fetch
        self.addCleanup(setattr, plan, "fetch_plan", self._real)
        self.addCleanup(tti_data.forget)
        import os
        for key, value in (("SDI_TTI_PLAN_SITE", "host:/sites/X"),
                           ("SDI_TTI_PLAN_PATH", "General/Plan.xlsx")):
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)

    def test_the_save_time_is_sharepoints_not_the_hour_this_ran(self):
        for reading in (tti_data.rows_for("tok"), tti_data.rows_for("tok")):
            self.assertEqual(reading.saved, SAVED)

    def test_a_reused_parse_still_reports_sharepoints_current_save_time(self):
        tti_data.rows_for("tok")
        later = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)

        def touched(token, client=None, known_version=""):
            # Same eTag, different reported save time: unusual, and the answer
            # must follow SharePoint rather than what was remembered.
            return None, later, self.fetch.version

        plan.fetch_plan = touched
        self.assertEqual(tti_data.rows_for("tok").saved, later)

    def test_the_provenance_every_answer_carries(self):
        said = tti_data.rows_for("tok").provenance()
        self.assertEqual(said["plan_saved"], SAVED.isoformat())
        self.assertEqual(said["rows_read"], 1)
        self.assertFalse(said["plan_reused_from_cache"])
        self.assertTrue(tti_data.rows_for("tok").provenance()["plan_reused_from_cache"])


class NoConfigurationNoGuessingTests(unittest.TestCase):
    def setUp(self):
        import os
        tti_data.forget()
        for key in ("SDI_TTI_PLAN_SITE", "SDI_TTI_PLAN_PATH", "SDI_TTI_DESPATCH_PLAN"):
            os.environ.pop(key, None)
        self.addCleanup(tti_data.forget)

    def test_an_unconfigured_plan_says_what_to_set(self):
        with self.assertRaises(tti_data.Unavailable) as refused:
            tti_data.rows_for("tok")
        self.assertIn("SDI_TTI_PLAN_SITE", str(refused.exception))
        self.assertIn("has not been configured", str(refused.exception))

    def test_sharepoint_wins_over_a_local_snapshot(self):
        """A file of unknown freshness answering a despatch question is worse
        than no answer, so the local copy is never the default."""
        import os
        os.environ["SDI_TTI_DESPATCH_PLAN"] = r"C:\nowhere\plan.xlsx"
        os.environ["SDI_TTI_PLAN_SITE"] = "host:/sites/X"
        os.environ["SDI_TTI_PLAN_PATH"] = "General/Plan.xlsx"
        for key in ("SDI_TTI_DESPATCH_PLAN", "SDI_TTI_PLAN_SITE", "SDI_TTI_PLAN_PATH"):
            self.addCleanup(os.environ.pop, key, None)
        fetch = Fetch()
        real = plan.fetch_plan
        plan.fetch_plan = fetch
        self.addCleanup(setattr, plan, "fetch_plan", real)
        tti_data.rows_for("tok")
        self.assertEqual(fetch.asked, 1, "the local snapshot was preferred")


class NothingTouchesTheDiskTests(unittest.TestCase):
    def test_the_rows_live_in_this_process_and_nowhere_else(self):
        for writing in ("write_text", "write_bytes", "NamedTemporary", "pickle",
                        "shelve", "sqlite3", "json.dump"):
            with self.subTest(writing=writing):
                self.assertNotIn(writing, SOURCE)

    def test_the_cache_can_be_emptied_without_a_restart(self):
        self.assertIn("def forget(", SOURCE)

    def test_it_is_locked_because_a_web_server_is_several_people_at_once(self):
        self.assertIn("threading.Lock()", SOURCE)
        self.assertIn("with _lock:", SOURCE)


if __name__ == "__main__":
    unittest.main()
