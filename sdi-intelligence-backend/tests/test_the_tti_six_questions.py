"""The TTI tracker's six everyday questions, and the ways each one can lie.

Selina Kuddus, Lee Merril and Sue Rogers do these by eye across seventeen
weekly sheets. Automating them is only worth anything if the answers are
right, so each test below is a way one of them could be confidently wrong:

  * a free-text cell that says "Del Note -" read as a delivery note, which
    turns the one line that needs chasing into the one that looks finished;
  * a chase list that chases a blank invoice column three weeks out, which is
    a list nobody reads twice;
  * "nobody updated this" counted together with "this is not planned yet",
    which hides the first inside the second - 114 of the latter in the real
    workbook, and the ones that matter lost among them;
  * a morning summary that says "nothing is due out" over the top of a line
    whose date could not be read;
  * a pallet count of "two" totalled as if it were 2;
  * the same order on two rows counted twice, or flagged as a mistake when it
    is a genuine split delivery.
"""
import sys
import unittest
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sue_despatch import SourceRow                                   # noqa: E402
import tti_search as tti                                            # noqa: E402

SAVED = date(2026, 10, 28)          # a Wednesday

# The real workbook's columns, confirmed against TTI_Delivery_Schedule_2021_V3.xlsx
# (17 weekly sheets, "Oct 26 WK 40" to "Feb 27 Wk 8").
COLUMNS = ("DUE DATE", "TTI ACCOUNT", "WHO PAYING", "SDI ORDER NO", "CUSTOMER PO",
           "CHINA,UK OR POLAND MAN", "PART CODE", "DESCRIPTION", "QTY", "COMMENTS",
           "TRAILER", "DEL ADD", "PALLETS", "NUMBER/PALLET", "LORRY FROM SDI",
           "LORRY FROM POLAND", "INTO ELC OR LOCAL DESTNATION", "LABEL + Batch DONE",
           "BOOKED IN WITH TTI", "INVOICE NUMBER", "PROOF OF EXPORT", "VALUE")


def row(sheet="Oct 26 WK 40", number=5, **given) -> SourceRow:
    cells = {name: "" for name in COLUMNS}
    cells.setdefault("SDI ORDER NO", "")
    unknown = set(given) - set(COLUMNS)
    assert not unknown, f"not a real column: {unknown}"
    cells.update(given)
    return SourceRow(sheet, number, cells)


ORDER = {"SDI ORDER NO": "15194", "PART CODE": "ABC-1", "DESCRIPTION": "Gondola"}


class TheFreeTextColumnTests(unittest.TestCase):
    """COMMENTS is where the real state of an order lives, in sentences."""

    def test_a_pick_note_number_is_found(self):
        found = tti.notes("Pick note number: 40015908 \nDel Note -")
        self.assertEqual(found["pick_note"], "40015908")

    def test_picked_and_a_number_is_a_pick_note(self):
        """How most picked lines are written in the plan. Only "Pick note
        number:" was read, so 28 of the 29 picked lines in the workbook looked
        unpicked, and none of them could reach the chase list."""
        for cell, pick in (("Picked-  40015862\nDel Note - ", "40015862"),
                           ("PICKED -  40015822\nDEL NOTE - ", "40015822"),
                           ("Picked 40015863", "40015863")):
            with self.subTest(cell=cell):
                found = tti.notes(cell)
                self.assertEqual(found["pick_note"], pick)
                self.assertEqual(found["delivery_note"], "")

    def test_picked_as_an_ordinary_word_is_not_a_pick_note(self):
        found = tti.notes("Picked up by FedEx, tracking 77812233")
        self.assertEqual(found["pick_note"], "")

    def test_a_dash_is_not_a_delivery_note(self):
        """── THE ONE THAT WOULD HAVE HURT ──────────────────────────────────
        "Del Note -" is somebody filling the field in to say there is not one
        yet. Reading the dash as a delivery note marks the line despatched."""
        found = tti.notes("Pick note number: 40015908 \nDel Note -")
        self.assertEqual(found["delivery_note"], "")

    def test_two_labels_on_one_line_do_not_bleed_into_each_other(self):
        found = tti.notes("Pick note 40015908 Del Note 50021117")
        self.assertEqual(found["pick_note"], "40015908")
        self.assertEqual(found["delivery_note"], "50021117")

    def test_the_pick_note_does_not_swallow_the_delivery_note(self):
        """Without cutting at the next label, the first number found after
        "pick note" could be the delivery note on the same line."""
        found = tti.notes("Pick note - Del Note 50021117")
        self.assertEqual(found["pick_note"], "")
        self.assertEqual(found["delivery_note"], "50021117")

    def test_awaiting_a_po_is_recognised_in_the_words_people_use(self):
        for phrase in ("await po", "awaiting PO from TTI", "chasing po",
                       "need PO before we pick", "no PO yet"):
            with self.subTest(phrase=phrase):
                self.assertTrue(tti.notes(phrase)["awaiting_po"], phrase)

    def test_an_ordinary_comment_is_not_read_as_awaiting_a_po(self):
        for phrase in ("PO received 12/10", "Poland manufacture", "Polished finish",
                       "customer PO 9981 on file"):
            with self.subTest(phrase=phrase):
                self.assertFalse(tti.notes(phrase)["awaiting_po"], phrase)

    def test_an_empty_cell_is_not_an_error(self):
        found = tti.notes(None)
        self.assertEqual((found["pick_note"], found["delivery_note"]), ("", ""))


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            row(number=5, **ORDER, **{"CUSTOMER PO": "PO9981",
                                      "TTI ACCOUNT": "TTI-001",
                                      "LORRY FROM SDI": "Wed 28th Oct"}),
            row("Nov 26 WK 45", 9, **{"SDI ORDER NO": "15300", "PART CODE": "XYZ",
                                      "DESCRIPTION": "Shelf",
                                      "COMMENTS": "replaces 15194"}),
        ]

    def test_an_order_number_finds_its_own_line(self):
        answer = tti.find(self.rows, "15194", as_of=SAVED)
        self.assertEqual(answer["match_count"], 1)
        self.assertEqual(answer["matches"][0]["source"], "Oct 26 WK 40!row 5")

    def test_a_mention_in_the_comments_is_offered_separately_not_mixed_in(self):
        """── WHY RANKED RATHER THAN FILTERED ───────────────────────────────
        "replaces 15194" in another line's comments is sometimes exactly what
        was wanted and never the line asked about. Mixing the two makes the
        caller do the sorting; dropping it loses the useful half."""
        answer = tti.find(self.rows, "15194", as_of=SAVED)
        self.assertEqual(answer["mention_count"], 1)
        self.assertEqual(answer["mentions"][0]["source"], "Nov 26 WK 45!row 9")
        self.assertNotIn("Nov 26 WK 45!row 9",
                         [m["source"] for m in answer["matches"]])

    def test_a_customer_po_and_a_part_code_and_an_account_all_find_the_line(self):
        for term in ("PO9981", "ABC-1", "TTI-001"):
            with self.subTest(term=term):
                self.assertEqual(tti.find(self.rows, term, as_of=SAVED)["match_count"], 1)

    def test_searching_across_every_sheet_at_once(self):
        answer = tti.find(self.rows, "15300", as_of=SAVED)
        self.assertEqual(answer["matches"][0]["sheet"], "Nov 26 WK 45")

    def test_nothing_matching_says_so_rather_than_returning_everything(self):
        answer = tti.find(self.rows, "99999", as_of=SAVED)
        self.assertEqual((answer["match_count"], answer["mention_count"]), (0, 0))

    def test_an_empty_search_matches_nothing_rather_than_the_whole_book(self):
        answer = tti.find(self.rows, "   ", as_of=SAVED)
        self.assertEqual(answer["match_count"], 0)

    def test_each_result_carries_the_sheet_and_row_it_came_from(self):
        for line in tti.find(self.rows, "15194", as_of=SAVED)["matches"]:
            self.assertRegex(line["source"], r".+!row \d+")

    def test_both_dates_are_given_and_labelled(self):
        """A due date and a departure date are different questions. A caller
        handed one unlabelled cannot tell which they have."""
        line = tti.find(self.rows, "15194", as_of=SAVED)["matches"][0]
        self.assertEqual(line["departs"], "2026-10-28")
        self.assertIn("departs_basis", line)
        self.assertIn("due", line)


class ChaseListTests(unittest.TestCase):
    def test_a_blank_invoice_column_weeks_out_is_not_a_chase(self):
        """── WHY THERE IS A HORIZON ────────────────────────────────────────
        Without one, the chase list is every incomplete cell in a seventeen
        week plan, which is the same as having no list."""
        far = [row(**ORDER, **{"CUSTOMER PO": "PO1", "LORRY FROM SDI": "20/12/2026"})]
        answer = tti.chase(far, as_of=SAVED)
        reasons = {g["reason"] for g in answer["groups"]}
        self.assertNotIn("not_booked_in_with_tti", reasons)
        self.assertNotIn("despatched_not_invoiced", reasons)

    def test_a_departure_this_week_without_a_booking_is_a_chase(self):
        soon = [row(**ORDER, **{"CUSTOMER PO": "PO1", "LORRY FROM SDI": "30/10/2026"})]
        reasons = {g["reason"] for g in tti.chase(soon, as_of=SAVED)["groups"]}
        self.assertIn("not_booked_in_with_tti", reasons)

    def test_picked_with_no_delivery_note_after_the_departure_date(self):
        late = [row(**ORDER, **{"CUSTOMER PO": "PO1", "LORRY FROM SDI": "20/10/2026",
                                "COMMENTS": "Pick note number: 40015908 \nDel Note -"})]
        groups = {g["reason"]: g for g in tti.chase(late, as_of=SAVED)["groups"]}
        self.assertIn("picked_but_not_despatched", groups)
        self.assertIn("40015908", groups["picked_but_not_despatched"]["lines"][0]["because"])

    def test_a_line_with_its_delivery_note_is_not_chased_for_picking(self):
        done = [row(**ORDER, **{"CUSTOMER PO": "PO1", "LORRY FROM SDI": "20/10/2026",
                                "INVOICE NUMBER": "INV-1",
                                "BOOKED IN WITH TTI": "YES",
                                "LABEL + Batch DONE": "YES",
                                "PROOF OF EXPORT": "POE-1",
                                "COMMENTS": "Pick note 40015908 Del Note 50021117"})]
        self.assertEqual(tti.chase(done, as_of=SAVED)["line_count"], 0)

    def test_gone_and_not_invoiced(self):
        gone = [row(**ORDER, **{"CUSTOMER PO": "PO1", "LORRY FROM SDI": "20/10/2026",
                                "BOOKED IN WITH TTI": "YES",
                                "LABEL + Batch DONE": "YES"})]
        reasons = {g["reason"] for g in tti.chase(gone, as_of=SAVED)["groups"]}
        self.assertIn("despatched_not_invoiced", reasons)

    def test_proof_of_export_is_only_chased_once_it_is_invoiced_and_gone(self):
        """It applies to exports, and the workbook does not say which were.
        So it is raised late, and the reason says the judgement is the
        reader's rather than pretending the sheet knows."""
        invoiced = [row(**ORDER, **{"CUSTOMER PO": "PO1",
                                    "LORRY FROM SDI": "20/10/2026",
                                    "INVOICE NUMBER": "INV-1",
                                    "BOOKED IN WITH TTI": "YES",
                                    "LABEL + Batch DONE": "YES"})]
        groups = {g["reason"]: g for g in tti.chase(invoiced, as_of=SAVED)["groups"]}
        self.assertIn("no_proof_of_export", groups)
        self.assertIn("only applies if", groups["no_proof_of_export"]["lines"][0]["because"])

    def test_no_customer_po_is_a_chase_whatever_the_date(self):
        nopo = [row(**ORDER, **{"LORRY FROM SDI": "20/12/2026"})]
        reasons = {g["reason"] for g in tti.chase(nopo, as_of=SAVED)["groups"]}
        self.assertIn("awaiting_customer_po", reasons)

    def test_a_cell_filled_in_to_say_nothing_yet_is_not_an_answer(self):
        """"TBC" in the booked-in column is not a booking, and "TBC" in the
        PO column is not a PO: Sue's word for waiting on information. Counting
        them as answers is how a column comes to look complete while nothing
        has happened."""
        vague = [row(**ORDER, **{"CUSTOMER PO": "TBC", "LORRY FROM SDI": "30/10/2026",
                                 "BOOKED IN WITH TTI": "-"})]
        reasons = {g["reason"] for g in tti.chase(vague, as_of=SAVED)["groups"]}
        self.assertIn("awaiting_customer_po", reasons)
        self.assertIn("not_booked_in_with_tti", reasons)

    def test_leaving_after_the_customer_wanted_it_is_raised(self):
        late = [row(**ORDER, **{"CUSTOMER PO": "PO1", "DUE DATE": "30/10/2026",
                                "LORRY FROM SDI": "06/11/2026",
                                "BOOKED IN WITH TTI": "YES",
                                "LABEL + Batch DONE": "YES"})]
        groups = {g["reason"]: g for g in tti.chase(late, as_of=SAVED)["groups"]}
        self.assertIn("late_against_due_date", groups)
        self.assertIn("7 day(s) later", groups["late_against_due_date"]["lines"][0]["because"])

    def test_nothing_says_in_zero_days(self):
        """"Due to leave in 0 day(s)" is how a reader stops trusting a list."""
        today = [row(**ORDER, **{"CUSTOMER PO": "PO1", "LORRY FROM SDI": "28/10/2026"})]
        for group in tti.chase(today, as_of=SAVED)["groups"]:
            for line in group["lines"]:
                self.assertNotIn("0 day", line["because"])
                self.assertNotIn("in 1 days", line["because"])

    def test_every_chased_line_says_which_row_it_is(self):
        some = [row(**ORDER, **{"LORRY FROM SDI": "30/10/2026"})]
        for group in tti.chase(some, as_of=SAVED)["groups"]:
            for line in group["lines"]:
                self.assertEqual(line["source"], "Oct 26 WK 40!row 5")


class OverdueAndUndatedTests(unittest.TestCase):
    """── THE DISTINCTION THIS EXISTS TO MAKE ──────────────────────────────
    The real workbook has 114 rows with no departure date. Almost all are
    normal: a plan running seventeen weeks out is meant to have blanks at the
    far end. The ones that matter are the rows whose customer due date has
    already gone by - and those are invisible in a count of blanks."""

    def test_a_past_due_date_with_no_departure_is_found(self):
        answer = tti.overdue_undated(
            [row(**ORDER, **{"DUE DATE": "01/10/2026"})], as_of=SAVED)
        self.assertEqual(answer["line_count"], 1)
        self.assertEqual(answer["lines"][0]["overdue_by_days"], 27)

    def test_a_future_due_date_with_no_departure_is_normal_and_not_listed(self):
        answer = tti.overdue_undated(
            [row(**ORDER, **{"DUE DATE": "20/12/2026"})], as_of=SAVED)
        self.assertEqual(answer["line_count"], 0)

    def test_a_past_due_date_that_is_already_planned_out_is_not_listed(self):
        answer = tti.overdue_undated(
            [row(**ORDER, **{"DUE DATE": "01/10/2026",
                             "LORRY FROM SDI": "30/10/2026"})], as_of=SAVED)
        self.assertEqual(answer["line_count"], 0)

    def test_an_unreadable_due_date_is_counted_not_claimed_as_overdue(self):
        """It cannot be shown to be overdue and it cannot be ruled out, so it
        is neither - and it is counted, so it cannot hide."""
        answer = tti.overdue_undated(
            [row(**ORDER, **{"DUE DATE": "ASAP ish"})], as_of=SAVED)
        self.assertEqual(answer["line_count"], 0)
        self.assertEqual(answer["unreadable_due_date_count"], 1)

    def test_the_oldest_comes_first(self):
        answer = tti.overdue_undated([
            row(number=5, **ORDER, **{"DUE DATE": "20/10/2026"}),
            row(number=6, **{"SDI ORDER NO": "2", "PART CODE": "B",
                             "DUE DATE": "01/09/2026"}),
        ], as_of=SAVED)
        self.assertEqual([l["overdue_by_days"] for l in answer["lines"]], [57, 8])


class MorningSummaryTests(unittest.TestCase):
    def test_it_names_what_is_due_out_today_with_its_row(self):
        answer = tti.morning([row(**ORDER, **{"LORRY FROM SDI": "28/10/2026"})],
                             day=SAVED, as_of=SAVED)
        self.assertEqual(answer["due_out_count"], 1)
        self.assertIn("Oct 26 WK 40!row 5", tti.summary_text(answer))

    def test_a_line_going_today_without_its_paperwork_is_flagged_not_dropped(self):
        answer = tti.morning([row(**ORDER, **{"LORRY FROM SDI": "28/10/2026"})],
                             day=SAVED, as_of=SAVED)
        self.assertEqual(answer["incomplete_count"], 1)
        self.assertIn("not booked in with TTI", answer["incomplete"][0]["missing"])
        # Still counted as going out: it is on the plan for today either way.
        self.assertEqual(answer["due_out_count"], 1)

    def test_planned_to_have_left_and_not_invoiced_is_called_slipped_honestly(self):
        """Either it did not go, or it went and the sheet has not caught up.
        The two look identical from here, and saying which would be a guess."""
        answer = tti.morning([row(**ORDER, **{"LORRY FROM SDI": "20/10/2026"})],
                             day=SAVED, as_of=SAVED)
        self.assertEqual(answer["slipped_count"], 1)
        self.assertEqual(answer["slipped"][0]["slipped_by_days"], 8)
        self.assertIn("has not caught up", answer["note"])

    def test_a_line_that_went_and_was_invoiced_has_not_slipped(self):
        answer = tti.morning(
            [row(**ORDER, **{"LORRY FROM SDI": "20/10/2026", "INVOICE NUMBER": "INV-1"})],
            day=SAVED, as_of=SAVED)
        self.assertEqual(answer["slipped_count"], 0)

    def test_an_unreadable_date_is_counted_and_said_in_the_text(self):
        """── "NOTHING IS DUE OUT" IS A CLAIM ───────────────────────────────
        A line whose date could not be read cannot be ruled out of today. The
        summary that says "nothing is due out" over the top of one is the
        sentence somebody acts on."""
        answer = tti.morning([row(**ORDER, **{"LORRY FROM SDI": "ask Sue"})],
                             day=SAVED, as_of=SAVED)
        self.assertEqual(answer["due_out_count"], 0)
        self.assertEqual(answer["unreadable_date_count"], 1)
        self.assertIn("cannot read", tti.summary_text(answer))

    def test_a_blank_departure_cell_is_not_an_unreadable_one(self):
        answer = tti.morning([row(**ORDER, **{"LORRY FROM SDI": ""})],
                             day=SAVED, as_of=SAVED)
        self.assertEqual(answer["unreadable_date_count"], 0)

    def test_the_text_says_when_the_plan_was_read_and_what_a_plan_is_not(self):
        answer = tti.morning([], day=SAVED, as_of=SAVED)
        text = tti.summary_text(answer)
        self.assertIn("2026-10-28", text)
        self.assertIn("not confirmation that goods have left", text)

    def test_an_empty_day_says_nothing_is_going_rather_than_showing_blank(self):
        self.assertIn("Nothing in the plan is set to leave SDI today",
                      tti.summary_text(tti.morning([], day=SAVED, as_of=SAVED)))


class DataQualityTests(unittest.TestCase):
    def test_a_pallet_count_stored_as_text_is_reported(self):
        answer = tti.data_quality([row(**ORDER, **{"PALLETS": "two"})], as_of=SAVED)
        groups = {g["problem"] for g in answer["groups"]}
        self.assertIn("pallets_not_a_number", groups)

    def test_a_real_number_is_not_reported(self):
        for good in (4, "4", 4.0, "4.0", "1,200"):
            with self.subTest(value=good):
                answer = tti.data_quality([row(**ORDER, **{"PALLETS": good})],
                                          as_of=SAVED)
                self.assertNotIn("pallets_not_a_number",
                                 {g["problem"] for g in answer["groups"]})

    def test_an_unreadable_date_is_reported_with_the_cell_as_written(self):
        answer = tti.data_quality([row(**ORDER, **{"LORRY FROM SDI": "ask Sue"})],
                                  as_of=SAVED)
        groups = {g["problem"]: g for g in answer["groups"]}
        self.assertIn("unreadable_departure_date", groups)
        self.assertIn("ask Sue", groups["unreadable_departure_date"]["lines"][0]["what"])

    def test_a_blank_or_tbc_date_is_not_reported_as_unreadable(self):
        for ordinary in ("", "TBC", "N/A", "-"):
            with self.subTest(cell=ordinary):
                answer = tti.data_quality(
                    [row(**ORDER, **{"LORRY FROM SDI": ordinary})], as_of=SAVED)
                self.assertNotIn("unreadable_departure_date",
                                 {g["problem"] for g in answer["groups"]})

    def test_a_corrected_month_spelling_is_used_and_declared(self):
        """"FRI 6TH NIV TBC", order 15194, is November. The correction is
        taken - and reported, so the cell gets fixed rather than relied on."""
        answer = tti.data_quality(
            [row(**ORDER, **{"LORRY FROM SDI": "FRI 6TH NIV TBC"})], as_of=SAVED)
        self.assertEqual(answer["spelling_correction_count"], 1)
        said = answer["spelling_corrections"][0]
        self.assertEqual(said["read_as"], "2026-11-06")
        self.assertEqual(said["cell"], "FRI 6TH NIV TBC")
        self.assertIn("weekday agrees", said["basis"])

    def test_the_same_order_and_part_twice_is_listed_as_written(self):
        answer = tti.data_quality([
            row("Nov 26 WK 45", 9, **{"SDI ORDER NO": "15300", "PART CODE": "XYZ-1",
                                      "DESCRIPTION": "Shelf"}),
            row("Nov 26 WK 45", 10, **{"SDI ORDER NO": "15300", "PART CODE": "xyz 1",
                                       "DESCRIPTION": "Shelf again"}),
        ], as_of=SAVED)
        self.assertEqual(answer["duplicate_count"], 1)
        found = answer["duplicate_order_lines"][0]
        self.assertEqual(found["count"], 2)
        # The spelling the sheet has, not the normalised form used to match.
        self.assertEqual(found["part"], "XYZ-1")
        self.assertEqual(len(found["sources"]), 2)

    def test_a_duplicate_is_not_called_a_mistake(self):
        """A split delivery is two rows for one order and part, and it is
        correct. Listing it is useful; asserting it is wrong is not."""
        answer = tti.data_quality([
            row(number=9, **{"SDI ORDER NO": "1", "PART CODE": "A", "DESCRIPTION": "x"}),
            row(number=10, **{"SDI ORDER NO": "1", "PART CODE": "A", "DESCRIPTION": "x"}),
        ], as_of=SAVED)
        self.assertIn("genuine split delivery", answer["note"])

    def test_an_order_line_with_no_order_number_is_reported(self):
        answer = tti.data_quality([row(**{"PART CODE": "ABC", "DESCRIPTION": "Thing"})],
                                  as_of=SAVED)
        self.assertIn("no_order_number", {g["problem"] for g in answer["groups"]})

    def test_a_clean_workbook_reports_nothing(self):
        answer = tti.data_quality(
            [row(**ORDER, **{"PALLETS": 4, "QTY": 12, "LORRY FROM SDI": "30/10/2026",
                             "DUE DATE": "30/10/2026"})], as_of=SAVED)
        self.assertEqual(answer["problem_count"], 0)


class EveryAnswerCitesItsSourceTests(unittest.TestCase):
    """The property that makes all six usable: an answer somebody cannot check
    at source is one they have to take on trust, and they should not have to."""

    ROWS = [row(**ORDER, **{"CUSTOMER PO": "PO9981", "LORRY FROM SDI": "28/10/2026",
                            "DUE DATE": "01/10/2026", "PALLETS": "two"}),
            row("Nov 26 WK 45", 9, **{"SDI ORDER NO": "15300", "PART CODE": "XYZ",
                                      "DESCRIPTION": "Shelf", "DUE DATE": "01/10/2026"})]

    def test_search_chase_overdue_and_morning_all_cite_the_row(self):
        for name, lines in (
                ("find", tti.find(self.ROWS, "15194", as_of=SAVED)["matches"]),
                ("overdue", tti.overdue_undated(self.ROWS, as_of=SAVED)["lines"]),
                ("morning", tti.morning(self.ROWS, day=SAVED, as_of=SAVED)["due_out"]),
                ("chase", [l for g in tti.chase(self.ROWS, as_of=SAVED)["groups"]
                           for l in g["lines"]])):
            with self.subTest(view=name):
                self.assertTrue(lines, f"{name} found nothing to check")
                for line in lines:
                    self.assertRegex(line["source"], r".+!row \d+")

    def test_data_quality_cites_the_row_too(self):
        answer = tti.data_quality(self.ROWS, as_of=SAVED)
        for group in answer["groups"]:
            for item in group["lines"]:
                self.assertRegex(item["source"], r".+!row \d+")

    def test_every_view_states_the_date_it_read_the_plan_as(self):
        for name, answer in (
                ("chase", tti.chase(self.ROWS, as_of=SAVED)),
                ("overdue", tti.overdue_undated(self.ROWS, as_of=SAVED)),
                ("quality", tti.data_quality(self.ROWS, as_of=SAVED))):
            with self.subTest(view=name):
                self.assertEqual(answer["as_of"], "2026-10-28")

    def test_no_view_invents_a_pallet_total(self):
        """Rows are order lines, not evidenced shipments, and the same pallet
        count appears on several. Phase one refused to total them; adding five
        more views is not a reason to start."""
        answers = [tti.find(self.ROWS, "15194", as_of=SAVED),
                   tti.chase(self.ROWS, as_of=SAVED),
                   tti.overdue_undated(self.ROWS, as_of=SAVED),
                   tti.morning(self.ROWS, day=SAVED, as_of=SAVED),
                   tti.data_quality(self.ROWS, as_of=SAVED)]
        for answer in answers:
            for key in answer:
                self.assertNotIn("pallet_total", key)


class RowsThatAreNotOrderLinesTests(unittest.TestCase):
    def test_a_header_or_notes_row_is_ignored_by_every_view(self):
        noise = [SourceRow("Oct 26 WK 40", 2, {"COMMENTS": "week commencing", "QTY": ""})]
        self.assertEqual(tti.find(noise, "week", as_of=SAVED)["match_count"], 0)
        self.assertEqual(tti.chase(noise, as_of=SAVED)["line_count"], 0)
        self.assertEqual(tti.overdue_undated(noise, as_of=SAVED)["line_count"], 0)
        self.assertEqual(tti.morning(noise, day=SAVED, as_of=SAVED)["due_out_count"], 0)
        self.assertEqual(tti.data_quality(noise, as_of=SAVED)["problem_count"], 0)

    def test_a_sheet_with_different_column_spelling_still_reads(self):
        """The real workbook spells one heading "INTO ELC OR LOCAL DESTNATION".
        Columns are matched with punctuation and case removed, so a tidied-up
        spelling in a later sheet does not silently empty the field."""
        tidied = SourceRow("Feb 27 Wk 8", 4, {
            "SDI Order No": "15999", "Part Code": "Q-1", "Description": "Bay",
            "Lorry from SDI": "30/10/2026",
            "Into ELC or Local Destination": "ELC"})
        line = tti.find([tidied], "15999", as_of=SAVED)["matches"][0]
        self.assertEqual(line["destination"], "ELC")
        self.assertEqual(line["departs"], "2026-10-30")


if __name__ == "__main__":
    unittest.main()


class ThisWeekTests(unittest.TestCase):
    """Today, Tomorrow and This week replaced "Next Thursday": Monday to Friday,
    from one reading of the plan."""

    def setUp(self):
        from sue_despatch import going_out_week
        self.week = going_out_week
        self.rows = [
            row(number=3, **{"SDI ORDER NO": "15178", "LORRY FROM SDI": "Mon 2nd Nov"}),
            row(number=4, **{"SDI ORDER NO": "15178", "LORRY FROM SDI": "Mon 2nd Nov"}),
            row(number=5, **{"SDI ORDER NO": "15188", "LORRY FROM SDI": "Weds 4th Nov"}),
            row(number=6, **{"SDI ORDER NO": "16001", "LORRY FROM SDI": "Sat 7th Nov"}),
            row(number=7, **{"SDI ORDER NO": "16002", "LORRY FROM SDI": "Mon 9th Nov"}),
            row(number=8, **{"SDI ORDER NO": "16003", "LORRY FROM SDI": "TBC"}),
        ]

    def test_any_day_gives_its_monday_to_friday(self):
        answer = self.week(self.rows, day=date(2026, 11, 4), as_of=SAVED)
        self.assertEqual(answer["week_start"], "2026-11-02")
        self.assertEqual([d["day"][-2:] for d in answer["days"]][:5], ["02", "03", "04", "05", "06"])
        self.assertEqual([d["line_count"] for d in answer["days"][:5]], [2, 0, 1, 0, 0])

    def test_a_weekend_departure_is_shown_only_when_there_is_one(self):
        answer = self.week(self.rows, day=date(2026, 11, 2), as_of=SAVED)
        self.assertEqual(answer["days"][-1]["day"], "2026-11-07")      # the Saturday
        self.assertEqual(answer["week_end"], "2026-11-07")
        self.assertEqual(answer["line_count"], 4)
        later = self.week(self.rows, day=date(2026, 11, 9), as_of=SAVED)
        self.assertEqual(len(later["days"]), 5)                         # no empty weekend

    def test_next_weeks_lines_stay_in_next_week(self):
        answer = self.week(self.rows, day=date(2026, 11, 2), as_of=SAVED)
        orders = [l["order"] for d in answer["days"] for l in d["lines"]]
        self.assertNotIn("16002", orders)

    def test_lines_with_no_date_are_given_once_not_per_day(self):
        answer = self.week(self.rows, day=date(2026, 11, 2), as_of=SAVED)
        self.assertEqual(answer["no_date_count"], 1)
        self.assertNotIn("lines", answer)                               # only per day


class DoneNotNeededOrStillToDoTests(unittest.TestCase):
    """Sue Rogers, 29 October 2026: "TBC as waiting information, N/A as that
    process is not needed etc for that job" - and the label column holds what
    still has to be done ("NEEDED", "Need to Relabel"), not that it was."""

    def test_each_cell_reads_as_its_writer_meant(self):
        for cell, meant in (("N/A", "not_needed"), ("n/a", "not_needed"), ("NA", "not_needed"),
                            ("TBC", "to_do"), ("", "to_do"), ("-", "to_do"),
                            ("NEEDED", "to_do"), ("Need to Relabel", "to_do"),
                            ("NEED NEW LABEL", "to_do"), ("NEEDED TBC", "to_do"),
                            ("AWAIT PO", "to_do"), ("AWAITPO", "to_do"),
                            ("20.10.26", "done"), ("PROOF DONE", "done"), ("YES", "done"),
                            ("Free of Charge", "done"), ("5014849", "done")):
            with self.subTest(cell=cell):
                self.assertEqual(tti._state(cell), meant)

    def soon(self, **cells):
        base = {"CUSTOMER PO": "PO1", "LORRY FROM SDI": "30/10/2026",
                "BOOKED IN WITH TTI": "20.10.26", "LABEL + Batch DONE": "DONE",
                "DEL ADD": "ELC"}
        base.update(cells)
        return {g["reason"]: g for g in tti.chase([row(**ORDER, **base)], as_of=SAVED)["groups"]}

    def test_a_step_marked_not_needed_is_not_chased(self):
        groups = self.soon(**{"BOOKED IN WITH TTI": "N/A", "LABEL + Batch DONE": "N/A",
                              "CUSTOMER PO": "N/A"})
        self.assertNotIn("not_booked_in_with_tti", groups)
        self.assertNotIn("labels_not_done", groups)
        self.assertNotIn("awaiting_customer_po", groups)

    def test_labels_still_needed_are_chased_and_the_cell_is_quoted(self):
        groups = self.soon(**{"LABEL + Batch DONE": "Need to Relabel"})
        self.assertIn("“Need to Relabel”", groups["labels_not_done"]["lines"][0]["because"])

    def test_a_free_of_charge_line_with_no_invoice_needed_is_not_chased(self):
        gone = [row(**ORDER, **{"CUSTOMER PO": "Free of Charge", "LORRY FROM SDI": "20/10/2026",
                                "INVOICE NUMBER": "N/A", "BOOKED IN WITH TTI": "N/A",
                                "LABEL + Batch DONE": "N/A"})]
        reasons = {g["reason"] for g in tti.chase(gone, as_of=SAVED)["groups"]}
        self.assertNotIn("despatched_not_invoiced", reasons)

    def test_loaded_in_the_trailer_column_means_it_has_gone(self):
        """"Despatch guys add in trailer column loaded." Loaded and not
        invoiced is a chase even before the planned day has passed."""
        groups = self.soon(**{"TRAILER": "LOADED"})
        self.assertIn("despatched_not_invoiced", groups)
        self.assertIn("LOADED", groups["despatched_not_invoiced"]["lines"][0]["because"])
        self.assertTrue(tti.find([row(**ORDER, **{"TRAILER": "Loaded - LLU7063A"})],
                                 "15194", as_of=SAVED)["matches"][0]["loaded"])


class PalletsThisWeekTests(unittest.TestCase):
    def test_pallets_are_added_per_day_and_for_the_week(self):
        from sue_despatch import going_out_week
        rows = [row(number=3, **{"SDI ORDER NO": "15178", "LORRY FROM SDI": "Mon 2nd Nov", "PALLETS": 30}),
                row(number=4, **{"SDI ORDER NO": "15178", "LORRY FROM SDI": "Mon 2nd Nov", "PALLETS": 17}),
                row(number=5, **{"SDI ORDER NO": "15188", "LORRY FROM SDI": "Weds 4th Nov", "PALLETS": "8"}),
                row(number=6, **{"SDI ORDER NO": "15189", "LORRY FROM SDI": "Weds 4th Nov", "PALLETS": "tbc"})]
        week = going_out_week(rows, day=date(2026, 11, 3), as_of=SAVED)
        self.assertEqual([d["pallet_total"] for d in week["days"]], [47, 0, 8, 0, 0])
        self.assertEqual(week["pallet_total"], 55)
        self.assertEqual(week["pallet_lines_as_text"][0]["pallets_as_recorded"], "tbc")
