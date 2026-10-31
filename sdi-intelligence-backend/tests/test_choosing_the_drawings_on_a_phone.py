"""Choosing which drawings go into a run, on a phone.

"open the live enquiry folder in the estimate screen on my phone, add drawings
and run the estimating process" - James Gray, 31 October 2026.

Starting from a folder prices EVERY drawing in it. Saving a revision from an
email puts it beside the old one ("GA.pdf" and "GA (2).pdf"), so a folder run
would have priced both. The Start card now lists the drawings, ticked; all
ticked sends the folder exactly as before, and anything changed sends the
ticked files by name - what the desk's "Select drawing files" sends.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

POCKET = (BACKEND / "appportal" / "estimating-pocket.html").read_text(encoding="utf-8")


class TheListingGivesEachFileItsPathTests(unittest.TestCase):
    def test_every_file_carries_the_path_the_server_resolved(self):
        try:
            import estimate_routes
        except Exception as exc:                                   # noqa: BLE001
            self.skipTest(f"estimating cannot be imported here: {exc}")
        folder = r"\\sdi-dc01\x\Live Enquiry\Boots\12552"
        fake = {"area": "enquiries", "relative": "Boots/12552", "folder_path": folder,
                "entries": [{"name": "GA.pdf", "is_dir": False},
                            {"name": "frame.sldprt", "is_dir": False},
                            {"name": "old", "is_dir": True}]}
        with patch.object(estimate_routes, "_check_key", lambda key: ""), \
             patch.object(estimate_routes, "_within_a_root", lambda p: Path(p)), \
             patch.object(estimate_routes, "browse_briefs", lambda rel, area: fake), \
             patch.object(estimate_routes.config, "ALLOWED_EXTENSIONS", {".pdf"}):
            out = estimate_routes.completed_briefs("Boots/12552", "enquiries", None)
        files = [e for e in out["entries"] if not e["is_dir"]]
        self.assertTrue(all(e["path"].endswith(e["name"]) for e in files))
        self.assertTrue(all(e["path"].startswith(folder) for e in files))
        self.assertNotIn("path", next(e for e in out["entries"] if e["is_dir"]))


class ThePageSendsWhatWasTickedTests(unittest.TestCase):
    def test_the_types_match_staging(self):
        try:
            import staging
        except Exception as exc:                                   # noqa: BLE001
            self.skipTest(f"staging cannot be imported here: {exc}")
        for name, values in (("DRAWING_TYPES", staging.DRAWING_SUFFIXES),
                             ("PICTURE_TYPES", staging.IMAGE_SUFFIXES)):
            listed = POCKET.split(f"const {name} = [", 1)[1].split("]", 1)[0]
            self.assertEqual(tuple(s.strip().strip('"') for s in listed.split(",")), values)

    def test_untouched_ticks_send_the_folder_as_before(self):
        body = POCKET.split("function packSources(start){", 1)[1].split("\n}", 1)[0]
        self.assertIn("asListed ? {job_folder: start.folder_path}", body)
        self.assertIn("{files: ticked.map(p => p.path)}", body)

    def test_nothing_ticked_starts_nothing(self):
        self.assertIn('if(!sources){ say("start-state", "Tick at least one drawing."', POCKET)

    def test_a_picture_is_offered_unticked(self):
        self.assertIn("box.checked = drawing;", POCKET)


if __name__ == "__main__":
    unittest.main()
