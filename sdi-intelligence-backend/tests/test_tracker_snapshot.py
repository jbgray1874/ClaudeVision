import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from tracker_snapshot import load_schedule_snapshot


class SnapshotReaderTests(unittest.TestCase):
    def test_reads_header_below_title_and_preserves_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "TTI plan"
            sheet.append(["TTI Despatch Plan"])
            sheet.append(["DUE DATE", "SDI ORDER NO", "PART CODE", "LORRY FROM SDI", "PALLETS"])
            sheet.append(["2026-11-05", "12345", "P-01", "Thurs 5th Nov TBC", 2])
            book.save(path)
            digest, rows = load_schedule_snapshot(path)
        self.assertEqual(len(digest), 64)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].cite(), "TTI plan!row 3")
        self.assertEqual(rows[0].cells["SDI ORDER NO"], "12345")

    def test_rejects_unrecognised_workbook(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "other.xlsx"
            book = Workbook()
            book.active.append(["Name", "Cost"])
            book.save(path)
            with self.assertRaisesRegex(ValueError, "No TTI schedule rows"):
                load_schedule_snapshot(path)
