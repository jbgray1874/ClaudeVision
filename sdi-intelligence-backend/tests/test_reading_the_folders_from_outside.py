"""The drawing packs and the estimates, read from a phone.

"we should be able to read all the directories with the live enquiry drawing
packs and the estimates etc .. If we can open up a drawing / drawing pack in a
folder and run an estimate" - James Gray, 30 October 2026.

Three things were missing. The filed estimates (AISheets) could not be reached
from outside at all. Every file the phone listed was greyed out - seen, never
opened. And a pack found while looking could not be estimated from where it
was found.

Pinned here: the boundary moved by exactly one folder and no further; a file
is offered as a link only when the file route will serve it, with an address
the server built; and a pack link lands on the Start screen at that pack.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import public_surface  # noqa: E402

POCKET = (BACKEND / "appportal" / "estimating-pocket.html").read_text(encoding="utf-8")
APP = (BACKEND / "app.py").read_text(encoding="utf-8")

AISHEETS = public_surface.ESTIMATES_DEFAULT


class TheBoundaryMovedByOneFolderTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict("os.environ", {"SDI_ESTIMATE_OUTPUT_ROOT": "",
                                        "SDI_LIVE_ENQUIRY_ROOT": "",
                                        "SDI_COMPLETED_AI_BRIEFS_ROOT": ""})
        env.start()
        self.addCleanup(env.stop)

    def test_a_filed_estimate_can_be_opened(self):
        self.assertTrue(public_surface.under_the_briefs(
            AISHEETS + r"\Boots\12552\2026-10-29_1407_1off\12552 quote.html"))

    def test_the_folders_beside_it_still_cannot(self):
        shared = r"\\sdi-dc01\shareddata$\Shared"
        for elsewhere in (AISHEETS + " backup\\x.pdf",
                          shared + r"\Estimating\Completed\AI Estimating\Pricing\x.xlsx",
                          shared + r"\HR\payroll.xlsx",
                          AISHEETS + r"\..\..\..\HR\payroll.xlsx"):
            with self.subTest(path=elsewhere):
                self.assertFalse(public_surface.under_the_briefs(elsewhere))

    def test_it_is_three_folders_and_no_more(self):
        self.assertEqual(len(public_surface.approved_roots()), 3)

    def test_the_refusal_names_all_three(self):
        self.assertIn("the filed estimates (AISheets)", APP)


class EachFileSaysWhetherItOpensTests(unittest.TestCase):
    def listing(self, names, allowed=(".pdf", ".html", ".xlsx")):
        try:
            import estimate_routes
        except Exception as exc:                                   # noqa: BLE001
            self.skipTest(f"estimating cannot be imported here: {exc}")
        folder = AISHEETS + r"\Boots\12552"
        fake = {"area": "estimates", "relative": "Boots/12552", "folder_path": folder,
                "entries": [{"name": n, "is_dir": False} for n in names]
                           + [{"name": "drawings", "is_dir": True}]}
        with patch.object(estimate_routes, "_check_key", lambda key: ""), \
             patch.object(estimate_routes, "_within_a_root", lambda p: Path(p)), \
             patch.object(estimate_routes, "browse_briefs", lambda rel, area: fake), \
             patch.object(estimate_routes.config, "ALLOWED_EXTENSIONS", set(allowed)):
            return estimate_routes.completed_briefs("Boots/12552", "estimates", None)

    def test_what_the_file_route_serves_gets_an_address(self):
        out = self.listing(["12552 quote.html", "12552.pdf", "12552 estimate.xlsx"])
        for entry in out["entries"]:
            if not entry["is_dir"]:
                with self.subTest(name=entry["name"]):
                    self.assertTrue(entry["open_url"].startswith("/api/file?path="))

    def test_a_model_the_file_route_would_refuse_is_not_offered(self):
        out = self.listing(["frame.sldprt", "base.dxf"])
        self.assertEqual([e for e in out["entries"] if e.get("open_url")], [])

    def test_a_folder_is_never_a_link(self):
        out = self.listing(["a.pdf"])
        folder = next(e for e in out["entries"] if e["is_dir"])
        self.assertNotIn("open_url", folder)

    def test_the_address_is_built_by_the_server_from_the_folder_it_resolved(self):
        out = self.listing(["12552.pdf"])
        url = next(e for e in out["entries"] if e.get("open_url"))["open_url"]
        self.assertIn("Boots", url)
        self.assertNotIn(" ", url, "the path must be quoted")

    def test_the_page_never_builds_a_path_itself(self):
        self.assertIn("a.href = entry.open_url", POCKET)
        self.assertNotIn("folder_path + ", POCKET)


class APackIsOneTapFromAnEstimateTests(unittest.TestCase):
    def test_the_folders_screen_offers_all_three(self):
        for area in ('data-area="enquiries"', 'data-area="estimates"', 'data-area="briefs"'):
            self.assertIn(area, POCKET)

    def test_a_pack_found_while_reading_can_be_estimated(self):
        offer = POCKET.split("A pack in Live Enquiry, found while reading", 1)[1][:500]
        self.assertIn('AREA.files === "enquiries" && data.can_select', offer)
        self.assertIn("goToPack(data.relative)", offer)

    def test_a_pack_link_opens_the_start_screen_at_that_pack(self):
        self.assertIn('new URLSearchParams(location.search).get("pack")', POCKET)
        body = POCKET.split("function goToPack(relative){", 1)[1][:200]
        for step in ('setHow("pack")', 'show("start")', 'browse("start", relative)'):
            self.assertIn(step, body)

    def test_the_door_carries_the_pack_to_a_phone(self):
        """/estimating sends a phone to the pocket page. Dropping ?pack= there
        would land the private assistant's link on the Ask screen."""
        door = APP.split('def estimating_page(', 1)[1][:2200]
        self.assertIn('request.query_params.get("pack", "")', door)
        self.assertIn('"?pack=" + _q(pack[:512], safe="")', door)

    def test_the_client_is_filled_from_the_folder_only_when_empty(self):
        self.assertIn('if(!$("start-client").value.trim())', POCKET)
        self.assertIn('String(data.relative || "").split("/")[0]', POCKET)


if __name__ == "__main__":
    unittest.main()
