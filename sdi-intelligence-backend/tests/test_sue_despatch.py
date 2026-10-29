import unittest
from datetime import date, datetime

from sue_despatch import SourceRow, going_out, propose_completed_transfer, schedule_date


AS_OF = date(2026, 10, 26)


class DespatchQuestions(unittest.TestCase):
    def test_tentative_dispatch_is_named_and_not_proof(self):
        row = SourceRow("Nov week 1", 11, {
            "SDI ORDER NO": 15178, "PART CODE": "TIE-1191", "DESCRIPTION": "Wall bay",
            "LORRY FROM SDI": "Mon 2nd Nov TBC", "DUE DATE": date(2026, 11, 25),
            "PALLETS": 30,
        })
        result = going_out([row], day=date(2026, 11, 2), as_of=AS_OF)
        self.assertEqual(result["line_count"], 1)
        self.assertEqual(result["lines"][0]["source"], "Nov week 1!row 11")
        self.assertTrue(result["lines"][0]["tentative"])
        self.assertEqual(result["lines"][0]["date_basis"], "year inferred from snapshot")
        self.assertIsNone(result["pallet_total"])
        self.assertIn("not confirmation", result["caveat"])

    def test_due_date_is_not_dispatch_date(self):
        row = SourceRow("Nov week 1", 12, {
            "SDI ORDER NO": 15178, "DUE DATE": date(2026, 11, 25),
            "LORRY FROM SDI": "Mon 2nd Nov TBC", "DESCRIPTION": "Wall bay",
        })
        result = going_out([row], day=date(2026, 11, 25), as_of=AS_OF)
        self.assertEqual(result["line_count"], 0)

    def test_moved_and_compound_dates_are_unresolved(self):
        cells = ["Moved to 26 Nov not due from 14/10/2026", "13.11.26\n29/10/2026"]
        for raw in cells:
            with self.subTest(raw=raw):
                self.assertIsNone(schedule_date(raw, as_of=AS_OF).value)

    def test_wrong_weekday_is_unresolved(self):
        self.assertIsNone(schedule_date("Tue 2nd Nov TBC", as_of=AS_OF).value)

    def test_repeated_order_lines_are_not_summed_as_pallets(self):
        rows = [SourceRow("Nov week 1", n, {
            "SDI ORDER NO": 15178, "PART CODE": "TIE-1191", "PALLETS": 30,
            "LORRY FROM SDI": "Mon 2nd Nov TBC",
        }) for n in (11, 13)]
        result = going_out(rows, day=date(2026, 11, 2), as_of=AS_OF)
        self.assertEqual(result["line_count"], 2)
        self.assertIsNone(result["pallet_total"])


class TransferPreview(unittest.TestCase):
    def setUp(self):
        self.row = SourceRow("Nov week 1", 11, {
            "SDI ORDER NO": 15178, "PART CODE": "TIE-1191", "CUSTOMER PO": 4800282168,
            "DESCRIPTION": "Wall bay", "QTY": 180,
        })

    def test_plan_date_alone_cannot_transfer(self):
        proposal = propose_completed_transfer(self.row, dispatched_at=None,
            dispatch_evidence="", destination_headers=["SDI ORDER NO", "PART CODE"],
            destination_version="etag-1")
        self.assertEqual(proposal["state"], "blocked")
        self.assertIn("Actual dispatch time and evidence are required", proposal["blockers"])

    def test_unknown_destination_blocks(self):
        proposal = propose_completed_transfer(self.row,
            dispatched_at=datetime(2026, 11, 2, 12), dispatch_evidence="delivery note 123",
            destination_headers=None, destination_version=None)
        self.assertEqual(proposal["state"], "blocked")
        self.assertEqual(proposal["candidate_cells"], {})

    def test_verified_inputs_still_only_propose(self):
        proposal = propose_completed_transfer(self.row,
            dispatched_at=datetime(2026, 11, 2, 12), dispatch_evidence="delivery note 123",
            destination_headers=["SDI ORDER NO", "PART CODE", "QTY"],
            destination_version="etag-1")
        self.assertEqual(proposal["state"], "review_required")
        self.assertEqual(proposal["candidate_cells"]["QTY"], 180)
        self.assertIn("No duplicate search, cell write, or email", proposal["warning"])


if __name__ == "__main__":
    unittest.main()


class YearOfABareDate(unittest.TestCase):
    """A tracker rolls over every new year, and the year was taken from the
    snapshot. In December "Mon 5th Jan" meant the January ELEVEN MONTHS GONE,
    the row never matched the day Sue asked about, and "nothing due" is
    indistinguishable from a correct answer. Wrong every Christmas, right the
    rest of the year: the worst shape a bug can have.
    """

    def test_december_reads_january_forward(self):
        self.assertEqual(schedule_date("5th Jan", as_of=date(2026, 12, 28)).value,
                         date(2027, 1, 5))
        self.assertEqual(schedule_date("Tue 5th Jan", as_of=date(2026, 12, 28)).value,
                         date(2027, 1, 5))   # 5 Jan 2027 is a Tuesday

    def test_january_still_reads_december_back(self):
        """The mirror: a plan read in January referring to late December."""
        self.assertEqual(schedule_date("29th Dec", as_of=date(2027, 1, 4)).value,
                         date(2026, 12, 29))

    def test_a_weekday_that_fits_no_nearby_year_stays_unresolved(self):
        """Rather than silently becoming a different year's Tuesday."""
        got = schedule_date("Mon 5th Jan", as_of=date(2026, 12, 21))
        self.assertIsNone(got.value)
        self.assertEqual(got.basis, "weekday disagrees with date")

    def test_a_stated_year_is_never_second_guessed(self):
        for raw, expected in (("5th Jan 2029", date(2029, 1, 5)),
                              ("2024-03-04", date(2024, 3, 4)),
                              ("04/03/2024", date(2024, 3, 4))):
            with self.subTest(raw=raw):
                got = schedule_date(raw, as_of=date(2026, 10, 26))
                self.assertEqual(got.value, expected)
                self.assertEqual(got.basis, "stated date")

    def test_the_nearest_fitting_year_wins(self):
        self.assertEqual(schedule_date("5th Nov", as_of=date(2026, 10, 26)).value,
                         date(2026, 11, 5))
        self.assertEqual(schedule_date("5th Oct", as_of=date(2026, 12, 28)).value,
                         date(2026, 10, 5))

    def test_the_twenty_ninth_of_february_does_not_crash(self):
        got = schedule_date("29th Feb", as_of=date(2026, 2, 1))   # 2026 is not a leap year
        self.assertIsNone(got.value)


class NoDateIsNotAnUnreadableDate(unittest.TestCase):
    """"N/A" and "TBC" are not dates this failed to read. They are a plan that
    has not said yet, which is how a despatch plan normally looks weeks out.
    Counted together, the ordinary ones bury the ones worth checking - the
    first live read showed six "unreadable" lines of which four were blanks.
    """

    def rows(self):
        return [SourceRow("Oct 26 WK 40", 5, {"SDI ORDER NO": 16507,
                                              "LORRY FROM SDI": "N/A"}),
                SourceRow("Nov 26 WK 41", 5, {"SDI ORDER NO": 16679,
                                              "LORRY FROM SDI": "TBC"}),
                SourceRow("Nov 26 WK 41", 6, {"SDI ORDER NO": 16680,
                                              "LORRY FROM SDI": ""}),
                SourceRow("Nov 26 WK 41", 9, {"SDI ORDER NO": 15194,
                                              "LORRY FROM SDI":
                                              "Moved to 26 Nov not due from 14/10/2026"})]

    def test_the_two_are_counted_apart(self):
        out = going_out(self.rows(), day=date(2026, 10, 29), as_of=AS_OF)
        self.assertEqual(out["no_date_count"], 3)
        self.assertEqual(out["unresolved_date_count"], 1)

    def test_a_bare_tbc_is_no_date_and_a_dated_tbc_is_still_a_date(self):
        self.assertEqual(schedule_date("TBC", as_of=AS_OF).basis,
                         "no departure date set")
        dated = schedule_date("Mon 2nd Nov TBC", as_of=AS_OF)
        self.assertEqual(dated.value, date(2026, 11, 2))
        self.assertTrue(dated.tentative)

    def test_the_usual_ways_of_writing_nothing(self):
        for blank in ("N/A", "n/a", "TBC", "TBA", "-", "?", "", "  ", "none",
                      "Pending", "unknown"):
            with self.subTest(cell=blank):
                self.assertEqual(schedule_date(blank, as_of=AS_OF).basis,
                                 "no departure date set")


class NothingIsLeavingIsAClaim(unittest.TestCase):
    """It is only safe when nothing was unreadable. A line whose date could not
    be interpreted cannot be ruled OUT of the day being asked about."""

    PAGE = (__import__("pathlib").Path(__file__).resolve().parent.parent
            / "appportal" / "tti-despatch.html").read_text(encoding="utf-8")

    def test_the_screen_qualifies_an_empty_answer(self):
        self.assertIn('"No confirmed matches " + when', self.PAGE)
        self.assertIn("cannot be ruled out", self.PAGE)

    def test_a_found_answer_is_qualified_too(self):
        self.assertIn("so this may not", self.PAGE)

    def test_the_flat_sentence_survives_only_when_nothing_is_unreadable(self):
        said = self.PAGE.split("const unread =", 1)[1].split("renderUnused", 1)[0]
        flat = said.index('"Nothing in the plan is set to leave " + when')
        guard = said.index(": unread")
        self.assertLess(guard, flat, "the unreadable case must be handled first")


class ItReadsLikeEnglish(unittest.TestCase):
    """"1 line have a date this cannot read" was on the screen Sue would read."""

    PAGE = (__import__("pathlib").Path(__file__).resolve().parent.parent
            / "appportal" / "tti-despatch.html").read_text(encoding="utf-8")

    def test_the_verb_agrees_with_the_count(self):
        self.assertIn('const have = n => n === 1 ? " has" : " have";', self.PAGE)
        for summary in ("a date this cannot read", "no departure date set yet"):
            with self.subTest(summary=summary):
                before = self.PAGE.split(summary, 1)[0]
                self.assertIn("have(", before.rsplit("el(\"summary\"", 1)[1])


class AMisspeltMonth(unittest.TestCase):
    """"FRI 6TH NIV TBC", order 15194, Nov 26 WK 41 row 64 - the one genuinely
    unreadable line in the first live read of Sue's workbook. NIV is NOV.

    This is not fuzzy month matching. MAR and MAY are one letter apart, as are
    JAN and JUN, and correcting spellings in general would let a despatch slide
    three months and read as confidently as a right one. Three things must line
    up: the word is NOT a month, exactly one real month is one letter away, and
    a weekday in the cell agrees with the date that produces.
    """

    def test_the_real_cell_resolves_and_says_it_was_corrected(self):
        got = schedule_date("FRI 6TH NIV TBC", as_of=AS_OF)
        self.assertEqual(got.value, date(2026, 11, 6))      # a Friday
        self.assertIn("NIV", got.basis)
        self.assertIn("Nov", got.basis)
        self.assertTrue(got.tentative)                      # the TBC survives

    def test_without_a_weekday_there_is_nothing_to_check_it_against(self):
        self.assertIsNone(schedule_date("6TH NIV TBC", as_of=AS_OF).value)

    def test_a_weekday_that_disagrees_refuses_the_correction(self):
        self.assertIsNone(schedule_date("MON 6TH NIV", as_of=AS_OF).value)

    def test_months_that_are_one_letter_from_each_other_are_never_touched(self):
        """MAR, MAY, JAN and JUN are real months, so they never reach the
        correction at all - they resolve, or fail the weekday, as themselves."""
        from sue_despatch import _month_meant
        for real, number in (("mar", 3), ("may", 5), ("jan", 1), ("jun", 6)):
            with self.subTest(month=real):
                self.assertEqual(_month_meant(real), number)

    def test_a_word_near_two_months_is_refused(self):
        from sue_despatch import _month_meant
        self.assertIsNone(_month_meant("jbn"))     # jan and jun both one away
        self.assertIsNone(_month_meant("zzz"))
        self.assertIsNone(_month_meant(""))


class TheFirstLiveReadOfSuesWorkbook(unittest.TestCase):
    """Regression examples taken from the real workbook on 26 October 2026,
    so a later change has to argue with what is actually in it."""

    REAL = [
        ("Oct 26 WK 40", 3, 16737, "Missing Parts for TTI Belgium Address", ""),
        ("Oct 26 WK 40", 5, 16507, "1 X SANDER DEDMO 12515", "N/A"),
        ("Oct 26 WK 40", 10, None, "1 x 12700-GA Line Trimmer Pallet Display", ""),
        ("Nov 26 WK 41", 5, 16679, "DATA CAPTURE STAND", "TBC"),
        ("Nov 26 WK 41", 6, 16679, "CARRIAAGE", "TBC"),
        ("Nov 26 WK 41", 64, 15194, "Milwaukee Nord Gondola 90cm 1 Leg EMEA",
         "FRI 6TH NIV TBC"),
    ]

    def rows(self):
        return [SourceRow(sheet, row, {"SDI ORDER NO": order or "",
                                       "DESCRIPTION": what,
                                       "LORRY FROM SDI": cell})
                for sheet, row, order, what, cell in self.REAL]

    def test_the_blanks_are_ordinary_and_the_typo_resolves(self):
        out = going_out(self.rows(), day=date(2026, 11, 6), as_of=AS_OF)
        self.assertEqual(out["no_date_count"], 5)
        self.assertEqual(out["unresolved_date_count"], 0)
        self.assertEqual(out["line_count"], 1)
        self.assertEqual(out["lines"][0]["source"], "Nov 26 WK 41!row 64")
        self.assertIn("NIV", out["lines"][0]["date_basis"])

    def test_a_row_without_an_order_number_is_still_a_line(self):
        """"(no order number)" rows are real work on Sue's plan."""
        out = going_out(self.rows(), day=date(2026, 11, 6), as_of=AS_OF)
        kept = [l for l in out["no_date_lines"] if not l["order"]]
        self.assertTrue(kept, "a described row with no order number was dropped")

    def test_pallets_are_still_never_totalled(self):
        out = going_out(self.rows(), day=date(2026, 11, 6), as_of=AS_OF)
        self.assertIsNone(out["pallet_total"])
