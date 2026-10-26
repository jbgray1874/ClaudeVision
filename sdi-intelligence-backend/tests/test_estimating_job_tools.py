"""Focused, offline checks for the mobile estimating additions."""
import json
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
