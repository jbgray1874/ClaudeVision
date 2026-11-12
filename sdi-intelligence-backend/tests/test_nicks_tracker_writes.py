"""Nick's tracker: the write path, which until now had no tests at all.

591 tests in this repository and not one covered the only code in the estate
that writes to somebody's live file. The write is four Graph calls deep, so
testing it needed something that behaves like Excel Online rather than
something that returns 200 - that is tests/fake_graph.py, which holds a real
grid, so a write has to land on the right cell to pass.

What is pinned here, in the order it would hurt Nick:

  * a SAVED change is never reported as a failure. 23 October 2026: a cell was
    written, read back a fraction of a second later from a copy that had not
    caught up, and a change safely in the file was reported to him as failed.
    He then had every reason to believe writing was broken;
  * an UNSAVED change is never reported as saved - the other side of the same
    coin, and the worse one;
  * one cell is written and nothing else moves. The whole-file replace that
    ChatGPT's own SharePoint connector offered him is what this exists to
    avoid;
  * a formula cell is never typed over;
  * somebody else's edit is never overwritten: the row's fingerprint is
    re-checked immediately before the write;
  * a second confirm never writes twice;
  * and the number of Graph round trips a change costs, because performance
    that was fixed once and not pinned comes back.
"""
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx                                                        # noqa: E402

import voicecrm_excel as store                                      # noqa: E402
from fake_graph import GRAPH, FakeGraph                              # noqa: E402

SITE = "sdidisplays.sharepoint.com:/sites/CRMTEST"
XLSX = "CRM TEST - 2026 Account and Project Tracker.xlsx"
# The columns the app depends on, as voicecrm.py sets them.
KEY_COLUMNS = ["CLIENT", "JOB", "AM Owner", "STATUS", "NEXT STEPS",
               "KEY DATES FOR NEXT STEPS", "BUDGET COST", "CONFIDENCE"]

BARBOUR = "xl3"                 # sheet row 3, the first record
TPS = "xl4"


class WithAFakeWorkbook(unittest.TestCase):
    """One ExcelStore against one FakeGraph, as a single change really runs."""

    lagging = False
    refuse = None
    no_session = False
    sheet_configured = True

    def setUp(self):
        self.graph = FakeGraph(lagging=self.lagging, refuse=self.refuse,
                              no_session=self.no_session)
        self.real_client = httpx.Client
        httpx.Client = self.graph
        # ExcelStore pools one client for the life of the process, so each test
        # drops the pool and lets it be created again against this fake.
        store.reset_pool()
        self.addCleanup(store.reset_pool)
        self.addCleanup(setattr, httpx, "Client", self.real_client)

        self.store = store.ExcelStore()
        self.store.site = SITE
        self.store.xlsx = XLSX
        self.store.sheet = FakeGraph.SHEET if self.sheet_configured else ""
        self.store.configured = True
        self.store.missing = []
        self.store.key_columns = list(KEY_COLUMNS)

    def row(self, item_id=BARBOUR):
        item, err = self.store.fetch("tok", item_id)
        self.assertIsNone(err, f"fetch failed: {err}")
        return item


class ReadingTheTrackerTests(WithAFakeWorkbook):
    def test_the_headings_are_found_below_the_title_row(self):
        """Nick's sheet has a title above the headings. Reading the title as
        headings matched none of his 76 records."""
        data = self.store.rows("tok")
        self.assertEqual(data["state"], "ok")
        self.assertEqual(data["header_row"], 2)
        self.assertIn("AM Owner", data["headers"])
        self.assertEqual(len(data["items"]), 3)

    def test_each_row_is_addressed_by_its_sheet_row(self):
        data = self.store.rows("tok")
        self.assertEqual([i["id"] for i in data["items"]], ["xl3", "xl4", "xl5"])
        self.assertEqual(data["items"][0]["fields"]["CLIENT"], "Barbour")

    def test_the_data_sheet_is_chosen_over_a_summary_tab(self):
        """Real trackers put summary tabs in front of the data. "First sheet"
        read the summary and found no records."""
        self.store.sheet = ""
        data = self.store.rows("tok")
        self.assertEqual(data["sheet"], FakeGraph.SHEET)
        self.assertEqual(len(data["items"]), 3)

    def test_the_chosen_sheet_is_remembered_so_it_is_not_hunted_twice(self):
        """Finding the data tab means reading the summary tabs in front of it.
        Once found it is tried first, so a later read that does happen costs
        one call rather than two."""
        self.store.sheet = ""
        self.store.rows("tok")
        self.assertEqual(self.graph.count("usedRange"), 2)   # Summary, then Tracker
        self.graph.ETAG = '"{GUID},8"'            # somebody saves the file
        self.graph.calls.clear()
        self.store.rows("tok")
        self.assertEqual(self.graph.count("usedRange"), 1,
                         "the summary tab was searched again")

    def test_a_row_carries_a_fingerprint_that_changes_with_its_contents(self):
        before = self.row()["eTag"]
        self.graph.grid[2][3] = "Closed"             # somebody edits STATUS
        self.assertNotEqual(self.row()["eTag"], before)


class ASavedChangeIsNeverReportedAsFailedTests(WithAFakeWorkbook):
    """The 23 October fault, pinned so it cannot come back."""

    def test_an_ordinary_change_saves_and_says_so(self):
        err = self.store.apply("tok", self.row(), "BUDGET COST", "15500")
        self.assertIsNone(err, f"a good write was reported as {err}")
        self.assertEqual(self.graph.cell("G3"), "15500")

    def test_the_write_and_the_read_back_share_one_session(self):
        """Not to make the write persist - it persists either way - but so the
        two calls are the same conversation and cannot disagree."""
        self.store.apply("tok", self.row(), "STATUS", "Closed")
        self.assertEqual(len(self.graph.written), 1)
        _, _, had_session = self.graph.written[0]
        self.assertTrue(had_session, "the write carried no session id")

    def test_three_changes_in_one_sentence_share_one_session(self):
        """"Change the status, the next steps and the date" is three writes.
        A session each was six Graph calls spent on bookkeeping - and opening
        three sessions on a shared workbook is worse manners than one."""
        item = self.row()
        for field, value in (("STATUS", "Closed"), ("NEXT STEPS", "Invoice it"),
                             ("CONFIDENCE", "90%")):
            self.assertIsNone(self.store.apply("tok", item, field, value))
        self.assertEqual(self.graph.count("createSession"), 1)
        self.assertEqual({had for _, _, had in self.graph.written}, {True})

    def test_the_session_is_handed_back_when_asked_for(self):
        self.store.apply("tok", self.row(), "STATUS", "Closed")
        self.store.close_session("tok")
        self.assertEqual(self.graph.sessions, set(),
                         "a session was left open on a shared workbook")

    def test_an_expired_session_is_replaced_and_the_write_tried_once_more(self):
        """Excel expires a session after a few minutes idle. The first attempt
        changed nothing, so writing again is a retry and not a second write."""
        item = self.row()
        self.assertIsNone(self.store.apply("tok", item, "STATUS", "Closed"))
        real_patch = self.graph.patch
        refused = {"n": 0}

        def expired_once(url, headers=None, json=None, **kw):
            if refused["n"] == 0 and (headers or {}).get("workbook-session-id"):
                refused["n"] += 1
                self.graph.calls.append(("PATCH", url))
                from fake_graph import Reply
                return Reply(404, {"error": {"code": "InvalidSession",
                                             "message": "session not found"}})
            return real_patch(url, headers=headers, json=json, **kw)

        self.graph.patch = expired_once
        self.addCleanup(setattr, self.graph, "patch", real_patch)
        err = self.store.apply("tok", item, "NEXT STEPS", "Invoice it")
        self.assertIsNone(err, f"an expired session was reported as {err}")
        self.assertEqual(self.graph.cell("E3"), "Invoice it")
        self.assertEqual(self.graph.count("createSession"), 2)
        # One cell, written once - the refused attempt changed nothing.
        self.assertEqual([w for w in self.graph.written if w[0] == "E3"],
                         [("E3", "Invoice it", True)])

    def test_a_refusal_that_is_not_about_the_session_is_not_retried(self):
        """A locked file must not be written to twice on the way to failing."""
        item = self.row()
        self.graph.refuse = {"status": 423, "code": "resourceLocked"}
        self.store.apply("tok", item, "STATUS", "Closed")
        self.assertEqual(sum(1 for method, _ in self.graph.calls if method == "PATCH"), 1)


class ALaggingReadNeverLosesAChangeTests(WithAFakeWorkbook):
    """A sessionless read can be answered from a copy that has not caught up."""

    lagging = True
    no_session = True        # so the write has no session to make the read reliable

    def test_a_stale_read_back_with_no_session_still_reports_saved(self):
        """── THE ONE THAT COST NICK'S CONFIDENCE ───────────────────────────
        The PATCH answered 200 and the value IS in the file. A second call
        that cannot see it yet says nothing about the first. Reporting failure
        here is what made him believe writing was broken."""
        err = self.store.apply("tok", self.row(), "BUDGET COST", "15500")
        self.assertIsNone(err, f"a saved change was reported as {err}")
        self.assertEqual(self.graph.cell("G3"), "15500")


class AnUnsavedChangeIsNeverReportedAsSavedTests(WithAFakeWorkbook):
    """The other side of the coin, and the worse one."""

    def test_a_cell_that_really_differs_inside_one_session_is_reported_not_saved(self):
        item = self.row()
        real_patch = self.graph.patch

        def accept_but_do_nothing(url, headers=None, json=None, **kw):
            self.graph.calls.append(("PATCH", url))
            self.graph.written.append(("(ignored)", "", True))
            from fake_graph import Reply
            return Reply(200, {"values": [[""]]})      # 200, and the cell unchanged

        self.graph.patch = accept_but_do_nothing
        self.addCleanup(setattr, self.graph, "patch", real_patch)
        err = self.store.apply("tok", item, "BUDGET COST", "15500")
        self.assertIsNotNone(err, "a change that did not happen was reported as saved")
        self.assertEqual(err["state"], "not_saved")
        self.assertIn("still reads", err["detail"])
        self.assertIn("request-id", err["detail"],
                      "a failure must be traceable with Microsoft")

    def test_a_refused_write_is_reported_with_its_graph_detail(self):
        item = self.row()
        self.graph.refuse = {"status": 423, "code": "resourceLocked"}
        err = self.store.apply("tok", item, "STATUS", "Closed")
        self.assertIsNotNone(err)
        self.assertEqual(err["state"], "tracker_unavailable")
        self.assertIn("can't be saved", err["detail"])

    def test_a_column_that_is_not_in_the_sheet_is_refused_before_any_write(self):
        err = self.store.apply("tok", self.row(), "INVENTED COLUMN", "x")
        self.assertIsNotNone(err)
        self.assertIn("was not found", err["detail"])
        self.assertEqual(self.graph.written, [])


class OneCellAndNothingElseTests(WithAFakeWorkbook):
    """What ChatGPT's own SharePoint connector could not offer him."""

    def test_only_the_named_cell_changes(self):
        before = [list(r) for r in self.graph.grid]
        self.store.apply("tok", self.row(), "STATUS", "Closed")
        after = self.graph.grid
        differences = [(r, c) for r in range(len(after)) for c in range(len(after[r]))
                       if before[r][c] != after[r][c]]
        self.assertEqual(differences, [(2, 3)], f"more than one cell moved: {differences}")

    def test_the_file_is_never_uploaded_or_replaced(self):
        self.store.apply("tok", self.row(), "STATUS", "Closed")
        for method, url in self.graph.calls:
            self.assertNotIn("/content", url, "the file itself was touched")
            self.assertNotEqual(method, "PUT")

    def test_the_address_is_worked_out_from_the_header_row_not_assumed(self):
        """BUDGET COST is the seventh column, so column G - and the record is
        sheet row 3, below the title and the headings."""
        self.store.apply("tok", self.row(), "BUDGET COST", "15500")
        self.assertEqual(self.graph.written[0][0], "G3")
        self.store.apply("tok", self.row(TPS), "CONFIDENCE", "80%")
        self.assertEqual(self.graph.written[1][0], "H4")

    def test_a_formula_cell_is_recognised_and_not_typed_over(self):
        """MARGIN is calculated. Writing a fixed value into it silently
        replaces the calculation, and nobody would see it happen."""
        item = self.row()
        self.assertTrue(self.store.is_formula("tok", item, "MARGIN"))
        self.assertFalse(self.store.is_formula("tok", item, "BUDGET COST"))

    def test_the_formula_check_costs_no_round_trip_of_its_own(self):
        """It used to be a separate Graph call for one cell, made immediately
        after a request that had just read the whole sheet."""
        item = self.row()
        self.graph.calls.clear()
        self.store.is_formula("tok", item, "MARGIN")
        self.store.is_formula("tok", item, "BUDGET COST")
        self.assertEqual(self.graph.calls, [])

    def test_an_unreadable_formula_check_refuses_rather_than_guesses(self):
        """If it cannot tell whether the cell is calculated, it says it is.
        Refusing a change somebody can make by hand is the cheap mistake;
        flattening a formula nobody notices is the expensive one.

        Reached by a row that came from a read without formulas - the copy
        fallback - so the one-cell question is still asked, and can still fail.
        """
        item = dict(self.row())
        item["_has_formulas"] = False

        def unreachable(*a, **kw):
            raise httpx.ConnectError("no route")

        self.graph.get = unreachable
        self.assertTrue(self.store.is_formula("tok", item, "BUDGET COST"),
                        "an unreadable cell was treated as safe to write over")


class WhenExcelOnlineWillNotOpenTheFileTests(WithAFakeWorkbook):
    refuse = {"status": 503, "code": "ServiceUnavailable"}

    def test_a_lookup_falls_back_to_a_copy_and_says_so(self):
        """Reads keep working from a downloaded copy. Nothing can be saved,
        and the answer carries that rather than looking normal."""
        made = self.graph

        def download(token):
            return _real_workbook_bytes(), None

        self.store.download = download
        data = self.store.rows("tok")
        self.assertEqual(data["state"], "ok")
        self.assertEqual(data["source"], "copy")
        self.assertIn("can't be saved", data["note"])
        self.assertEqual(len(data["items"]), 3)
        del made

    def test_a_copy_that_cannot_be_read_reports_the_original_refusal(self):
        self.store.download = lambda token: (b"not a spreadsheet", None)
        data = self.store.rows("tok")
        self.assertNotEqual(data.get("state"), "ok")
        self.assertIn("copy_error", data)

    def test_a_refusal_is_told_apart_from_a_lack_of_access(self):
        self.assertTrue(store.excel_refused({"state": "graph_error", "status": 503,
                                             "detail": "ServiceUnavailable"}))
        self.assertTrue(store.excel_refused({"state": "graph_error", "status": 423,
                                             "detail": "resourceLocked"}))
        # 403 is the person's access, and saying "the file is broken" would send
        # somebody to repair a file that is fine.
        self.assertFalse(store.excel_refused({"state": "graph_error", "status": 403,
                                              "detail": "accessDenied"}))


def _real_workbook_bytes() -> bytes:
    """An actual .xlsx matching the fake grid, for the copy fallback to parse."""
    import io
    from openpyxl import Workbook
    from fake_graph import HEADINGS, RECORDS, TITLE
    book = Workbook()
    summary = book.active
    summary.title = "Summary"
    summary.append(["Summary"])
    sheet = book.create_sheet(FakeGraph.SHEET)
    sheet.append(list(TITLE))
    sheet.append(list(HEADINGS))
    for record in RECORDS:
        sheet.append(["3000" if str(c).startswith("=") else c for c in record])
    held = io.BytesIO()
    book.save(held)
    return held.getvalue()


if __name__ == "__main__":
    unittest.main()


class WhatAChangeCostsInRoundTripsTests(WithAFakeWorkbook):
    """── WHY THESE NUMBERS ARE ASSERTED ──────────────────────────────────────
    Each Graph call is a round trip to Microsoft, and they run one after
    another. On 29 October 2026 a single saved change cost ELEVEN of them -
    propose re-read the whole sheet and then asked a separate question about
    one cell, confirm re-read the whole sheet again, and the site's id (which
    never changes) was fetched twice on the way. Three changes in one sentence
    came to thirty-six, which is most of a minute of waiting that the person
    experiences as the app being slow.

    Performance that was fixed once and not pinned comes back, so the counts
    are asserted. If a change here makes one of these numbers go up, that is
    the point: it should be a decision, not a surprise.
    """

    def calls(self):
        return sum(1 for _ in self.graph.calls)

    def test_a_lookup_costs_three_calls_once_and_then_one(self):
        """Three the first time in the life of the process - the site, then
        finding the file - and ONE after that while the file is unchanged: the
        file's metadata, read as this person, which is also what says whether
        the sheet needs reading again.

        It was three every single time. Nick asks several questions in a row."""
        self.store.rows("tok")
        self.assertEqual(self.calls(), 3, self.graph.urls())
        for _ in range(3):
            self.graph.calls.clear()
            self.store.rows("tok")
            self.assertEqual(self.calls(), 1, self.graph.urls())

    def test_the_sites_id_is_asked_for_once_in_the_life_of_the_process(self):
        """It is an identifier, not a credential, and it does not change. It
        was fetched before every question and twice per saved change."""
        self.store.rows("tok")
        self.store.fetch("tok", BARBOUR)
        self.store.rows("tok")
        self.store.fetch("tok", BARBOUR)
        # The site-resolution call specifically - the file's own path lookup
        # has /sites/ in it too, and counting both proves nothing.
        self.assertEqual(self.graph.count(f"/sites/{SITE}"), 1, self.graph.urls())

    def test_a_saved_change_costs_five_calls_not_eleven(self):
        """propose (fetch) + confirm (fetch, then the write) as voicecrm.py
        runs them. The two sheet reads are both live and both deliberate: each
        one is what catches a colleague's edit before a write. Everything else
        that used to be in here was waste."""
        self.store.rows("tok")                       # the question first
        self.graph.calls.clear()

        propose, _ = self.store.fetch("tok", BARBOUR)
        self.store.is_formula("tok", propose, "BUDGET COST")
        at_propose = self.calls()

        confirm, _ = self.store.fetch("tok", BARBOUR)
        self.store.apply("tok", confirm, "BUDGET COST", "15500")

        self.assertEqual(at_propose, 1, f"propose: {self.graph.urls()}")
        self.assertEqual(self.calls(), 5, self.graph.urls())
        self.assertEqual(self.graph.cell("G3"), "15500")

    def test_a_later_change_costs_four_because_the_session_is_already_open(self):
        item = self.row()
        self.store.apply("tok", item, "STATUS", "Closed")
        self.graph.calls.clear()
        again, _ = self.store.fetch("tok", BARBOUR)
        self.store.is_formula("tok", again, "NEXT STEPS")
        self.store.apply("tok", again, "NEXT STEPS", "Invoice it")
        self.assertEqual(self.calls(), 3, self.graph.urls())

    def test_three_changes_in_one_sentence_cost_thirteen_not_thirty_three(self):
        """One session serves all three. This is the sentence Nick actually
        says - "change the status, the next steps and the confidence" - and it
        used to be eleven round trips apiece."""
        self.store.rows("tok")
        self.graph.calls.clear()
        for field, value in (("STATUS", "Closed"), ("NEXT STEPS", "Invoice it"),
                             ("CONFIDENCE", "90%")):
            proposed, _ = self.store.fetch("tok", BARBOUR)
            self.store.is_formula("tok", proposed, field)
            confirmed, _ = self.store.fetch("tok", BARBOUR)
            self.assertIsNone(self.store.apply("tok", confirmed, field, value))
        self.assertLessEqual(self.calls(), 13, self.graph.urls())
        self.assertEqual(self.graph.count("createSession"), 1)
        self.assertEqual(self.graph.count("/sites/"), 0)       # cached
        for address, expected in (("D3", "Closed"), ("E3", "Invoice it"),
                                  ("H3", "90%")):
            self.assertEqual(self.graph.cell(address), expected)

    def test_one_pooled_connection_rather_than_one_per_call(self):
        """Seven HTTP clients per change meant seven TLS handshakes to
        graph.microsoft.com, which is most of a round trip each before any of
        Graph's answer arrives."""
        made = {"n": 0}
        real = httpx.Client

        def counted(*args, **kwargs):
            made["n"] += 1
            return self.graph

        httpx.Client = counted
        store.reset_pool()
        self.addCleanup(setattr, httpx, "Client", real)
        item, _ = self.store.fetch("tok", BARBOUR)
        self.store.is_formula("tok", item, "BUDGET COST")
        self.store.apply("tok", item, "BUDGET COST", "15500")
        self.store.rows("tok")
        self.assertEqual(made["n"], 1, "a client was opened per call again")


class TheLookupCacheIsNotAPermissionHoleTests(WithAFakeWorkbook):
    """The saving that quietly becomes a way in, if it is done carelessly."""

    def test_the_file_is_asked_about_as_this_person_on_every_lookup(self):
        """A reused reading must not mean a skipped question. The metadata
        request is what checks this person's access, so it happens every time."""
        self.store.rows("tok")                      # locates the file
        for _ in range(3):
            self.graph.calls.clear()
            self.store.rows("tok")
            metadata = [u for u in self.graph.urls() if "/workbook" not in u]
            self.assertEqual(len(metadata), 1, self.graph.urls())

    def test_somebody_who_has_lost_access_gets_nothing_though_rows_are_held(self):
        held = self.store.rows("tok")
        self.assertEqual(len(held["items"]), 3)
        real_get = self.graph.get

        def refuse_the_file(url, headers=None, params=None, **kw):
            # Both ways of asking about the file: by its ids, and by its path
            # in the site. A person who has lost access is refused either way,
            # and a fake that refused only one would prove nothing.
            if "/workbook" not in url and ("/items/item-1" in url
                                           or "/drive/root:/" in url):
                self.graph.calls.append(("GET", url))
                from fake_graph import Reply
                return Reply(403, {"error": {"code": "accessDenied",
                                             "message": "no access"}})
            return real_get(url, headers=headers, params=params, **kw)

        self.graph.get = refuse_the_file
        after = self.store.rows("tok")
        self.assertNotEqual(after.get("state"), "ok")
        self.assertEqual(after["items"], [])

    def test_a_saved_file_is_read_again(self):
        self.store.rows("tok")
        self.graph.grid[2][3] = "Closed"
        self.graph.ETAG = '"{GUID},8"'            # Graph says the file changed
        again = self.store.rows("tok")
        self.assertFalse(again["reused"])
        self.assertEqual(again["items"][0]["fields"]["STATUS"], "Closed")

    def test_the_read_before_a_write_is_never_reused(self):
        """── THE ONE THAT WOULD HAVE BEEN A REAL HOLE ───────────────────────
        That read computes the row's fingerprint and is the only thing
        standing between a colleague's edit and being overwritten. Excel
        Online can batch a co-author's save so the eTag lags it by seconds, so
        a cached grid there would let a stale fingerprint match."""
        self.store.rows("tok")
        for _ in range(2):
            self.graph.calls.clear()
            self.store.fetch("tok", BARBOUR)
            self.assertEqual(self.graph.count("usedRange"), 1,
                             "the pre-write read came from the cache")

    def test_asking_to_reuse_the_pre_write_read_is_refused_outright(self):
        """Not left to a side effect. A reused pre-write read was prevented
        only because a light read carries no version to match - so flipping
        may_reuse on in fetch() broke nothing any test could see. It is an
        invariant now, and it raises."""
        import httpx as _httpx
        with self.assertRaises(ValueError) as refused:
            self.store._load(_httpx.Client(), "tok", with_formulas=True,
                             may_reuse=True)
        self.assertIn("stops a colleague's edit being overwritten",
                      str(refused.exception))

    def test_the_fingerprint_still_catches_an_edit_made_since_the_proposal(self):
        """End to end: the row is read, somebody else changes it, and the
        fingerprint taken before the write no longer matches."""
        proposed, _ = self.store.fetch("tok", BARBOUR)
        self.graph.grid[2][3] = "Someone else got here first"
        at_confirm, _ = self.store.fetch("tok", BARBOUR)
        self.assertNotEqual(at_confirm["eTag"], proposed["eTag"],
                            "a colleague's edit was invisible to the version check")

    def test_nothing_is_written_to_disk(self):
        source = (BACKEND / "voicecrm_excel.py").read_text(encoding="utf-8")
        for writing in ("write_text", "write_bytes", "NamedTemporary", "pickle",
                        "shelve", "sqlite3"):
            with self.subTest(writing=writing):
                self.assertNotIn(writing, source)

    def test_a_save_drops_the_held_reading_at_once(self):
        """── "I JUST CHANGED THAT" ──────────────────────────────────────────
        The lookup cache refreshes when Graph's eTag changes, and Excel Online
        can batch a save so the eTag lags it. Waiting for that would mean the
        question right after a change still answered with the old value - the
        same loss of confidence as the failed-write report, by another route.
        So a successful write drops the held reading itself, without waiting
        to be told.
        """
        self.store.rows("tok")
        item, _ = self.store.fetch("tok", BARBOUR)
        self.assertIsNone(self.store.apply("tok", item, "STATUS", "Closed"))
        # The eTag deliberately does NOT change: Excel has not caught up.
        self.graph.calls.clear()
        after = self.store.rows("tok")
        self.assertFalse(after["reused"], "a question after a save used the old reading")
        self.assertEqual(after["items"][0]["fields"]["STATUS"], "Closed")

    def test_a_stale_remembered_address_is_located_again_rather_than_failing(self):
        """The short path to the sheet is built from the file's remembered ids.
        If the workbook has been renamed or replaced since, that read 404s -
        and a 404 on the pre-write read would read as "your record is gone"."""
        self.store.rows("tok")                      # locates the file
        real_get = self.graph.get
        gone = {"n": 0}

        def moved_once(url, headers=None, params=None, **kw):
            if "usedRange" in url and gone["n"] == 0:
                gone["n"] += 1
                self.graph.calls.append(("GET", url))
                from fake_graph import Reply
                return Reply(404, {"error": {"code": "itemNotFound",
                                             "message": "no such item"}})
            return real_get(url, headers=headers, params=params, **kw)

        self.graph.get = moved_once
        item, err = self.store.fetch("tok", BARBOUR)
        self.assertIsNone(err, f"a moved workbook was not located again: {err}")
        self.assertEqual(item["fields"]["CLIENT"], "Barbour")
