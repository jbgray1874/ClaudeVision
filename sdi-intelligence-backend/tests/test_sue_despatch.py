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
        self.assertIn("No confirmed matches for", self.PAGE)
        self.assertIn("cannot be ruled out", self.PAGE)

    def test_a_found_answer_is_qualified_too(self):
        self.assertIn("so this may not", self.PAGE)

    def test_the_flat_sentence_survives_only_when_nothing_is_unreadable(self):
        said = self.PAGE.split("const unread =", 1)[1].split("renderUnused", 1)[0]
        flat = said.index('"Nothing in the plan is set to leave on "')
        guard = said.index(": unread")
        self.assertLess(guard, flat, "the unreadable case must be handled first")
