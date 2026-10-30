"""How many times AM CRM asks Microsoft something, per question - on the
server's real configuration.

── WHY THIS FILE EXISTS ─────────────────────────────────────────────────────
On 30 October the live log said:

    read state=ok rows=913 ... sheet_reread=yes secs=17.6
    read state=ok rows=913 ... sheet_reread=no  secs=8.5

The second line is the cache WORKING - Graph said the file had not changed,
so the sheet was not read again - and it still took eight and a half
seconds. That is the wait a Sales Director judges the whole app on.

The cause: with SDI_VOICECRM_SHEET unset (as it is on the server), every
lookup asked Excel Online to list the workbook's worksheets before checking
whether anything had changed. That is a workbook call, and a sessionless one
makes Microsoft open the workbook to answer it - seconds, for a 913-row
tracker - to tell us sheet names we already had.

Every test of the read path ran with the sheet CONFIGURED, which skips that
call. So the slow path was the one place no test went, and these run the
server's configuration on purpose.

The numbers pinned here are Graph calls, not seconds: seconds depend on
Microsoft's day, calls depend only on this code.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from test_nicks_tracker_writes import WithAFakeWorkbook, BARBOUR      # noqa: E402
from fake_graph import FakeGraph, Reply                               # noqa: E402


def workbook_calls(graph):
    """Calls Excel Online has to open the workbook to answer."""
    return [u for u in graph.urls() if "/workbook" in u]


def worksheet_listings(graph):
    """"What tabs are there?" - not the usedRange calls that also contain
    /worksheets('...'), only the listing itself."""
    return [u for u in graph.urls() if u.rstrip("/").endswith("/workbook/worksheets")]


class AsTheServerIsConfigured(WithAFakeWorkbook):
    """SDI_VOICECRM_SHEET unset: the app finds the tab by its headings."""
    sheet_configured = False


class TheSecondQuestionTests(AsTheServerIsConfigured):
    """The cache hit. This is the line that said 8.5 seconds."""

    def test_an_unchanged_tracker_costs_one_call_and_no_workbook_open(self):
        self.store.rows("tok")                  # the first question reads it
        self.graph.calls.clear()
        again = self.store.rows("tok")
        self.assertTrue(again["reused"], "the cache did not answer")
        self.assertEqual(workbook_calls(self.graph), [],
                         "an unchanged tracker still made Excel Online open the "
                         "workbook - this was the 8.5 seconds")
        self.assertEqual(len(self.graph.calls), 1, self.graph.urls())

    def test_and_that_one_call_still_asks_as_this_person(self):
        """Fast must not mean unchecked: the metadata call is what refuses
        somebody who has lost access, and it is made every time."""
        self.store.rows("tok")
        for _ in range(3):
            self.graph.calls.clear()
            self.store.rows("tok")
            self.assertEqual(self.graph.count(f"/items/{FakeGraph.ITEM_ID}"), 1,
                             self.graph.urls())

    def test_ten_questions_in_a_row_open_the_workbook_once(self):
        self.store.rows("tok")
        self.graph.calls.clear()
        for _ in range(10):
            self.store.rows("tok")
        self.assertEqual(workbook_calls(self.graph), [])


class WhenTheTrackerHasChangedTests(AsTheServerIsConfigured):
    def test_a_changed_tracker_is_read_again_without_listing_the_tabs(self):
        """The full read: one metadata call and one sheet read. It used to be
        three, and two of them opened the workbook."""
        self.store.rows("tok")
        self.graph.ETAG = '"{GUID},8"'
        self.graph.calls.clear()
        again = self.store.rows("tok")
        self.assertFalse(again["reused"])
        self.assertEqual(worksheet_listings(self.graph), [],
                         "the tabs were listed again for a sheet already known")
        self.assertEqual(len(workbook_calls(self.graph)), 1, self.graph.urls())

    def test_and_the_answer_is_the_new_one(self):
        """Faster must not mean staler."""
        self.store.rows("tok")
        self.graph.grid[2][3] = "Closed"
        self.graph.ETAG = '"{GUID},8"'
        again = self.store.rows("tok")
        self.assertEqual(again["items"][0]["fields"]["STATUS"], "Closed")


class TheFirstQuestionAfterARestartTests(AsTheServerIsConfigured):
    def test_the_tabs_are_listed_once_to_find_the_tracker_and_never_again(self):
        self.store.rows("tok")
        self.assertEqual(len(worksheet_listings(self.graph)), 1)
        for _ in range(3):
            self.graph.ETAG = self.graph.ETAG.replace(",", ",9")   # keep changing it
            self.store.rows("tok")
        self.assertEqual(len(worksheet_listings(self.graph)), 1, self.graph.urls())


class TheRememberedTabIsOnlyAShortcutTests(AsTheServerIsConfigured):
    """Remembering the tab saves seconds. It must never mean answering from
    the wrong tab when somebody reorganises the workbook."""

    def test_a_renamed_tab_is_found_again(self):
        self.store.rows("tok")
        FakeGraph.SHEET = "Tracker 2026"
        self.addCleanup(setattr, FakeGraph, "SHEET", "Tracker")
        self.graph.sheets = ("Summary", "Tracker 2026")
        self.graph.ETAG = '"{GUID},8"'
        again = self.store.rows("tok")
        self.assertEqual(again.get("state"), "ok", again)
        self.assertEqual(again["sheet"], "Tracker 2026")
        self.assertEqual(len(again["items"]), 3)

    def test_and_after_that_the_new_name_is_the_one_remembered(self):
        self.store.rows("tok")
        FakeGraph.SHEET = "Tracker 2026"
        self.addCleanup(setattr, FakeGraph, "SHEET", "Tracker")
        self.graph.sheets = ("Summary", "Tracker 2026")
        self.graph.ETAG = '"{GUID},8"'
        self.store.rows("tok")
        self.graph.ETAG = '"{GUID},9"'
        self.graph.calls.clear()
        self.store.rows("tok")
        self.assertEqual(worksheet_listings(self.graph), [])

    def test_a_tab_that_lost_its_headings_is_not_answered_from(self):
        """The data moved to another tab and the old one now holds something
        else. Answering from it would read the wrong table as the tracker."""
        self.store.rows("tok")
        real_get = self.graph.get

        def tracker_moved(url, headers=None, params=None, **kw):
            if "/worksheets('Tracker')/usedRange" in url:
                self.graph.calls.append(("GET", url))
                return Reply(200, {"text": [["Archive"], ["nothing", "here"]],
                                   "rowIndex": 0, "columnIndex": 0})
            if "/worksheets('Live')/usedRange" in url:
                return real_get(url.replace("('Live')", "('Tracker')"),
                                headers=headers, params=params, **kw)
            return real_get(url, headers=headers, params=params, **kw)

        self.graph.get = tracker_moved
        self.graph.sheets = ("Summary", "Tracker", "Live")
        self.graph.ETAG = '"{GUID},8"'
        again = self.store.rows("tok")
        self.assertEqual(again["sheet"], "Live")
        self.assertEqual(len(again["items"]), 3)

    def test_the_pre_write_read_recovers_the_same_way(self):
        """The read before a write takes the light path, which also trusts
        the remembered tab. It must recover rather than refuse the change."""
        self.store.rows("tok")
        FakeGraph.SHEET = "Tracker 2026"
        self.addCleanup(setattr, FakeGraph, "SHEET", "Tracker")
        self.graph.sheets = ("Summary", "Tracker 2026")
        item, err = self.store.fetch("tok", BARBOUR)
        self.assertIsNone(err, err)
        self.assertEqual(item["fields"]["CLIENT"], "Barbour")


class EachWriterHasTheirOwnSessionTests(WithAFakeWorkbook):
    """── FIVE WRITERS, 30 OCTOBER ─────────────────────────────────────────
    There was one write session for the whole service, reused by whoever
    wrote next. Andy's change could go through a session Nick had opened."""

    def session_of_each_write(self):
        return [w for w in self.graph.written]

    def test_one_persons_changes_still_share_one_session(self):
        """The saving the shared session existed for is kept."""
        item = self.row()
        self.store.apply("tok-nick", item, "STATUS", "Closed")
        self.store.apply("tok-nick", item, "NEXT STEPS", "Invoice it")
        self.assertEqual(self.graph.count("createSession"), 1)

    def test_a_second_person_gets_a_session_of_their_own(self):
        item = self.row()
        self.store.apply("tok-nick", item, "STATUS", "Closed")
        self.store.apply("tok-andy", self.row(), "NEXT STEPS", "Invoice it")
        self.assertEqual(self.graph.count("createSession"), 2,
                         "Andy's change was sent through Nick's session")

    def test_no_token_is_kept_to_tell_them_apart(self):
        item = self.row()
        self.store.apply("tok-nick-secret", item, "STATUS", "Closed")
        held = self.store._live_session
        self.assertNotIn("tok-nick-secret", repr(held))
        self.assertIn("who", held)


if __name__ == "__main__":
    unittest.main()
