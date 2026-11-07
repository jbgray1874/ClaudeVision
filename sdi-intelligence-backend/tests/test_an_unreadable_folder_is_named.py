"""A folder the service cannot read is named, with the reason (D-741).

JG, 7 Nov 2026, from the phone's Review screen: "The completed AI briefs share is
unavailable to this service." It said that for every area, and never which folder
or why. A folder that does not exist from the service's machine, one its account
may not read, and a share that did not answer need different people, so the
message names the folder, the setting that chooses it and the reason.
"""
import errno
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

BRIEFS = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Live Enquiries\completed AI briefs"


class AnUnreadableFolderIsNamedTests(unittest.TestCase):
    def setUp(self):
        try:
            import estimate_routes
        except Exception as exc:                                    # noqa: BLE001
            self.skipTest(f"estimating cannot be imported here: {exc}")
        self.er = estimate_routes
        areas = {"briefs": Path(BRIEFS), "enquiries": Path(r"\\s\Live Enquiry"),
                 "estimates": Path(r"\\s\AISheets")}
        p = patch.object(estimate_routes, "areas", lambda: areas)
        p.start()
        self.addCleanup(p.stop)

    def _said(self, area, exc):
        return self.er._area_unreadable(area, exc)

    def test_a_missing_folder_names_it_and_its_setting(self):
        said = self._said("briefs", FileNotFoundError(errno.ENOENT, "not found", BRIEFS))
        self.assertIn("completed AI briefs folder was not found", said)
        self.assertIn(BRIEFS, said)
        self.assertIn("SDI_COMPLETED_AI_BRIEFS_ROOT", said)

    def test_a_folder_the_account_may_not_read_says_permission(self):
        said = self._said("briefs", PermissionError(errno.EACCES, "Access is denied", BRIEFS))
        self.assertIn("may not read", said)
        self.assertIn("permission denied", said)
        self.assertIn(BRIEFS, said)

    def test_any_other_failure_carries_the_systems_own_reason(self):
        said = self._said("enquiries", OSError(errno.EHOSTUNREACH, "No route to host",
                                               r"\\s\Live Enquiry"))
        self.assertIn("Live Enquiry folder could not be read", said)
        self.assertIn("No route to host", said)
        self.assertNotIn("completed AI briefs", said)

    def test_each_area_is_called_by_its_own_name(self):
        said = self._said("estimates", FileNotFoundError(errno.ENOENT, "x", r"\\s\AISheets"))
        self.assertIn("AISheets", said)
        self.assertIn("SDI_ESTIMATE_OUTPUT_ROOT", said)

    def test_the_browse_route_says_it(self):
        def gone(relative, area):
            raise FileNotFoundError(errno.ENOENT, "not found", BRIEFS)
        from fastapi import HTTPException
        with patch.object(self.er, "_check_key", lambda key: ""), \
             patch.object(self.er, "_within_a_root", lambda p: Path(p)), \
             patch.object(self.er, "browse_briefs", gone):
            with self.assertRaises(HTTPException) as caught:
                self.er.completed_briefs(relative="", area="briefs", x_sdi_key="")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn(BRIEFS, caught.exception.detail)

    def test_the_ask_route_says_it(self):
        def gone(relative, area):
            raise PermissionError(errno.EACCES, "Access is denied", BRIEFS)
        from fastapi import HTTPException
        req = self.er.SavedRunQuestion(brief="Client/12552", area="briefs", question="price?")
        with patch.object(self.er, "_check_key", lambda key: ""), \
             patch.object(self.er, "filed_record", gone):
            with self.assertRaises(HTTPException) as caught:
                self.er.ask_saved_run(req, x_sdi_key="")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("permission denied", caught.exception.detail)

    def test_the_old_sentence_is_gone(self):
        source = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
        self.assertNotIn("share is unavailable to this service", source)


if __name__ == "__main__":
    unittest.main()
