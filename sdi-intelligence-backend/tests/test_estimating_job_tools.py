"""Focused, offline checks for the mobile estimating additions."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import estimating_job_tools as tools


class CompletedBriefsTests(unittest.TestCase):
    def test_browse_only_the_fixed_root_and_return_folder_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / "Harrods" / "9439-07-04"
            job.mkdir(parents=True)
            (job / "GA.pdf").write_bytes(b"%PDF-test")
            (job / "private.env").write_text("not public")
            with patch.object(tools, "BRIEFS_ROOT", root):
                top = tools.browse_briefs()
                self.assertTrue(top["entries"][0]["is_dir"])
                self.assertFalse(top["can_select"])
                self.assertFalse(tools.browse_briefs("Harrods")["can_select"])
                result = tools.browse_briefs("Harrods/9439-07-04")
                self.assertEqual(result["folder_path"], str(job.resolve()))
                self.assertEqual(result["parent"], "Harrods")
                self.assertEqual([entry["name"] for entry in result["entries"]], ["GA.pdf"])
                self.assertFalse(result["entries"][0]["is_dir"])
                self.assertTrue(result["can_select"])
                self.assertEqual(result["drawing_count"], 1)

    def test_traversal_and_absolute_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(tools, "BRIEFS_ROOT", Path(directory)):
                for path in ("../outside", "a/../outside", "C:/Windows", "a\\b", "//server"):
                    with self.subTest(path=path), self.assertRaises(ValueError):
                        tools.browse_briefs(path)

    def test_symlink_to_outside_is_not_listed(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            try:
                (root / "escape").symlink_to(Path(outside), target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            with patch.object(tools, "BRIEFS_ROOT", root):
                self.assertEqual(tools.browse_briefs()["entries"], [])
                with self.assertRaises(ValueError):
                    tools.browse_briefs("escape")


class SavedRecordQuestionTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "final_estimate": {"totals": {"unit_gbp": 30, "material_gbp": 10,
                                          "labour_gbp": 15, "other_gbp": 5,
                                          "unit_cell": "Estimate!M225"}},
            "costed_job": {"lines": [{"part_number": "A-101", "description": "bracket",
                                       "qty_per_unit": 2, "material_label": "steel",
                                       "charged_ext_gbp": 8, "charged_cell": "Estimate!M14",
                                       "route_operations": ["Saw", "Weld"]}],
                           "release": {"status": "provisional", "reasons": ["TIG rate open"]}},
        }

    def test_costs_bom_routes_and_release_cite_saved_fields(self):
        cases = (("What does A-101 cost?", "Estimate!M14"),
                 ("Which parts are in the BOM?", "A-101 ×2"),
                 ("What routes were recorded?", "proposed or uncharged"),
                 ("Why is release held?", "TIG rate open"))
        for question, expected in cases:
            with self.subTest(question=question):
                result = tools.answer_saved_record(self.record, question)
                self.assertIn(expected, result["answer"])
                self.assertTrue(result["sources"])

    def test_unknown_question_admits_the_limit(self):
        result = tools.answer_saved_record(self.record, "What did the client say on page two?")
        self.assertFalse(result["complete"])
        self.assertIn("cannot establish", result["answer"])

    def test_missing_total_never_becomes_zero_price(self):
        result = tools.answer_saved_record({"final_estimate": {}}, "What is the total?")
        self.assertFalse(result["complete"])
        self.assertIn("No calculated total", result["answer"])


if __name__ == "__main__":
    unittest.main()


class WhyZeroItemsTests(unittest.TestCase):
    """"0 items" meant three different things and looked like one.

    26 October 2026: a job folder under Harrods showed "0 items". Empty, full
    of spreadsheets, or full of files the service account cannot open all read
    the same on screen - and they need three different people to fix them.
    """

    def test_a_file_of_an_unlisted_type_is_counted_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / "Harrods" / "9439-01-04"
            job.mkdir(parents=True)
            (job / "brief.zip").write_bytes(b"zip")
            (job / "notes.unknown").write_text("x")
            with patch.object(tools, "BRIEFS_ROOT", root):
                result = tools.browse_briefs("Harrods/9439-01-04")
            self.assertEqual(result["entries"], [])
            self.assertEqual(result["other_types"], 2)
            self.assertEqual(result["unreadable"], 0)

    def test_the_spreadsheets_and_emails_that_come_with_a_brief_are_shown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / "Harrods" / "9439-01-04"
            job.mkdir(parents=True)
            for name in ("costing.xlsx", "enquiry.msg", "spec.docx",
                         "photo.jpg", "GA.pdf"):
                (job / name).write_bytes(b"x")
            with patch.object(tools, "BRIEFS_ROOT", root):
                result = tools.browse_briefs("Harrods/9439-01-04")
            self.assertEqual(len(result["entries"]), 5)
            self.assertEqual(result["other_types"], 0)
            # Only the PDF counts as something to estimate FROM.
            self.assertEqual(result["drawing_count"], 1)
            self.assertTrue(result["can_select"])

    def test_an_empty_folder_reports_nothing_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Harrods" / "9439-01-04").mkdir(parents=True)
            with patch.object(tools, "BRIEFS_ROOT", root):
                result = tools.browse_briefs("Harrods/9439-01-04")
            self.assertEqual(result["entries"], [])
            self.assertEqual((result["other_types"], result["unreadable"]), (0, 0))

    def test_a_child_that_cannot_be_read_is_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / "Harrods" / "9439-01-04"
            job.mkdir(parents=True)
            try:
                (job / "gone.pdf").symlink_to(job / "never-existed.pdf")
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            with patch.object(tools, "BRIEFS_ROOT", root):
                result = tools.browse_briefs("Harrods/9439-01-04")
            self.assertEqual(result["entries"], [])
            self.assertEqual(result["unreadable"], 1)

    def test_the_page_says_which_of_the_three_it_is(self):
        page = (Path(__file__).resolve().parent.parent
                / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")
        self.assertIn("This folder is empty.", page)
        self.assertIn("a type this scanner does not list", page)
        self.assertIn("this service cannot read", page)


class ACompletedBriefFolderTests(unittest.TestCase):
    """What is actually in one, taken from Harrods/9439-07-04-GA on 26 Oct 2026.

    Eleven files, none of them a drawing: the saved record, the report, the
    client quotation, the BOM and routes, the extraction evidence and the
    covering email. The scanner recognised ONE of them and the folder read as
    empty.
    """

    REAL = ("9439-07-04_20261025_103002.xlsx",
            "9439-07-04_20261025_103002_covering_email.html",
            "9439-07-04_20261025_103002_covering_email.txt",
            "9439-07-04_20261025_103002_record.json",
            "9439-07-04_boms_and_routes.html",
            "9439-07-04_boms_and_routes.xlsx",
            "9439-07-04_llm_extract.json",
            "9439-07-04_quote_PORTAL.html",
            "9439-07-04_report.html",
            "9439-07-04_source_drawing_data.html",
            "9439-07-04_source_drawing_data.xlsx")

    def test_every_file_in_a_real_completed_folder_is_listed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / "Harrods" / "9439-07-04-GA"
            job.mkdir(parents=True)
            for name in self.REAL:
                (job / name).write_bytes(b"x")
            with patch.object(tools, "BRIEFS_ROOT", root):
                result = tools.browse_briefs("Harrods/9439-07-04-GA")
        self.assertEqual(len(result["entries"]), len(self.REAL))
        self.assertEqual(result["other_types"], 0)

    def test_a_folder_of_outputs_cannot_be_added_to_drawings(self):
        """There is nothing here to estimate FROM, and the button says so
        rather than staging eleven files that are not drawings."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / "Harrods" / "9439-07-04-GA"
            job.mkdir(parents=True)
            for name in self.REAL:
                (job / name).write_bytes(b"x")
            with patch.object(tools, "BRIEFS_ROOT", root):
                result = tools.browse_briefs("Harrods/9439-07-04-GA")
        self.assertEqual(result["drawing_count"], 0)
        self.assertFalse(result["can_select"])


class TwoAreasTests(unittest.TestCase):
    """"it's the area where estimators look for results. I think it's a good
    idea to be able to see the drawings through another button also at
    K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry" - James Gray,
    26 October 2026.

    Two questions, two folders. One scanner over one root could only answer
    one of them, and answered the other with an empty folder.
    """

    def test_the_three_areas_are_offered_and_nothing_else_is(self):
        """The third, 30 October 2026: "we should be able to read all the
        directories with the live enquiry drawing packs and the estimates"."""
        self.assertEqual(sorted(tools.areas()), ["briefs", "enquiries", "estimates"])

    def test_the_estimates_area_is_where_runs_file_them(self):
        """One setting, one default, three places that read it. If they ever
        disagreed, the phone would browse a folder no run writes to."""
        import public_surface
        routes = (Path(tools.__file__).with_name("estimate_routes.py")
                  .read_text(encoding="utf-8"))
        default = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\AISheets"
        self.assertIn(default, routes)
        self.assertEqual(public_surface.ESTIMATES_DEFAULT, default)
        if not os.getenv("SDI_ESTIMATE_OUTPUT_ROOT"):
            self.assertEqual(str(tools.ESTIMATES_ROOT), default)
        self.assertIn(default, public_surface.approved_roots()
                      if not os.getenv("SDI_ESTIMATE_OUTPUT_ROOT") else (default,))

    def test_an_unknown_area_is_refused_rather_than_quietly_substituted(self):
        """A name nobody recognises must not resolve to a real folder."""
        for made_up in ("payroll", "..", "BRIEFS/../..", "enquiries ", "Briefs"):
            with self.subTest(area=made_up):
                with self.assertRaises(ValueError):
                    tools.area_root(made_up)

    def test_asking_for_nothing_means_the_completed_estimates(self):
        """What every existing caller passes, and what the route defaults to."""
        for quiet in ("", None):
            with self.subTest(area=quiet):
                self.assertEqual(tools.area_root(quiet), tools.BRIEFS_ROOT)

    def test_the_live_enquiry_default_is_the_folder_james_named(self):
        self.assertEqual(
            str(tools.LIVE_ENQUIRY_ROOT),
            r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry")

    def test_each_area_browses_its_own_tree_only(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            briefs, enquiries = Path(a), Path(b)
            (briefs / "Harrods" / "9439-07-04-GA").mkdir(parents=True)
            (enquiries / "Boots" / "1234-01").mkdir(parents=True)
            with patch.object(tools, "BRIEFS_ROOT", briefs), \
                 patch.object(tools, "LIVE_ENQUIRY_ROOT", enquiries):
                self.assertEqual([e["name"] for e in
                                  tools.browse_briefs("", "briefs")["entries"]], ["Harrods"])
                self.assertEqual([e["name"] for e in
                                  tools.browse_briefs("", "enquiries")["entries"]], ["Boots"])
                # And the area travels back, so the page cannot mislabel the list.
                self.assertEqual(tools.browse_briefs("", "enquiries")["area"], "enquiries")

    def test_one_areas_relative_path_cannot_reach_the_other(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            briefs, enquiries = Path(a), Path(b)
            (enquiries / "Boots").mkdir(parents=True)
            with patch.object(tools, "BRIEFS_ROOT", briefs), \
                 patch.object(tools, "LIVE_ENQUIRY_ROOT", enquiries):
                with self.assertRaises(ValueError):
                    tools.browse_briefs("Boots", "briefs")


class FilesCanBeOpenedTests(unittest.TestCase):
    """Listing the report and the quotation and then disabling them is half a
    feature in the folder estimators go to for results."""

    PAGE = (Path(__file__).resolve().parent.parent
            / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")

    def test_a_file_is_a_link_not_a_dead_button(self):
        self.assertNotIn("button.disabled = !item.is_dir", self.PAGE)
        self.assertIn('link.href = "/api/file?path="', self.PAGE)
        self.assertIn('link.rel = "noopener noreferrer"', self.PAGE)

    def test_the_path_comes_from_the_server_not_from_the_browser(self):
        """j.folder_path is what the server just reported for this folder. A
        path typed in the page would be a file browser with no boundary."""
        rendering = self.PAGE.split("for(const item of j.entries", 1)[1][:1200]
        self.assertIn("j.folder_path", rendering)
        self.assertIn("encodeURIComponent", rendering)

    def test_the_folder_path_is_still_reported_for_the_link_to_use(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / "Harrods" / "9439-07-04-GA"
            job.mkdir(parents=True)
            (job / "9439-07-04_report.html").write_bytes(b"x")
            with patch.object(tools, "BRIEFS_ROOT", root):
                result = tools.browse_briefs("Harrods/9439-07-04-GA")
        self.assertEqual(result["folder_path"], str(job.resolve()))
        self.assertEqual([e["name"] for e in result["entries"]],
                         ["9439-07-04_report.html"])
