"""The app portal (/app/) in the we.are.sdi look, as the estimating pages and the wall (D-754).

9 Nov 2026, James: "can we also ensure that the look and feel of the web app portal page falls
also in line with the we are sdi style of fonts etc", pointing at the estimating page and the
operations wall. The site's look on the dark ground: the lower-case wordmark with its two dots
in SDI yellow, a geometric sans for headings (Outfit, for the licensed Sofia Pro), an elegant
serif for the tagline (Fraunces light, for Juana), pill buttons, the halftone circle, and the
short yellow line over each panel. Amber stays the warning colour, so a warning never reads as
brand.
"""
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "appportal"
PAGE = (APP / "index.html").read_text(encoding="utf-8")
ROOT = PAGE[PAGE.index(":root{"):]
ROOT = ROOT[:ROOT.index("}")]


class TheAppPortalIsWeAreSdiTests(unittest.TestCase):
    def test_the_wordmark_with_its_two_yellow_dots(self):
        m = re.search(r'<svg class="sdi-word" viewBox="0 0 950 169" role="img" '
                      r'aria-label="we\.are\.sdi" fill="currentColor">(.*?)</svg>', PAGE, re.S)
        self.assertTrue(m, "no we.are.sdi wordmark in the header")
        self.assertEqual(m.group(1).count('<path class="d"'), 2)
        self.assertIn(".sdi-word .d{fill:var(--brand)}", PAGE)
        self.assertNotIn('<div class="mark"><b>S</b></div>', PAGE)          # the old lettered square

    def test_sdi_yellow_is_the_brand_and_amber_the_warning(self):
        self.assertIn("--brand:#F6D946", ROOT)
        warn = re.search(r"--warn:(#[0-9a-fA-F]{6})", ROOT).group(1)
        self.assertNotEqual(warn.upper(), "#F6D946")
        self.assertNotIn("#ffd400", PAGE.lower())                             # the old yellow, gone

    def test_the_sites_kind_of_type(self):
        self.assertIn("family=Outfit", PAGE)
        self.assertIn("family=Fraunces", PAGE)
        self.assertIn("--disp:'Outfit'", ROOT)
        self.assertIn(".tagline{font-family:var(--serif-disp)", PAGE)
        for old in ("Archivo", "Hanken"):
            self.assertNotIn(old, PAGE)

    def test_pill_buttons_the_halftone_circle_and_the_yellow_line(self):
        self.assertRegex(PAGE, r"\.card \.go,\.btn\{[^}]*border-radius:999px")
        self.assertIn('class="sdi-dots"', PAGE)
        self.assertRegex(PAGE, r"\.card::before,\.note::before\{[^}]*background:var\(--brand\)")

    def test_what_the_page_does_is_unchanged(self):
        """A restyle only: the catalogue, sign-in, search, detail and the office-only note as before."""
        for kept in ("fetch('../api/services?surface=app'", "location.href='/auth/login?next='",
                     "$('q').addEventListener('input'", "function renderDetail(s)",
                     "if(s.link && s.link!==s.app_url)", "didn't open from here",
                     "navigator.serviceWorker.register('sw.js')"):
            self.assertIn(kept, PAGE)
        for el in ('id="q"', 'id="who"', 'id="list"', 'id="detail"', 'id="banner"', 'id="foot"', 'id="back"'):
            self.assertIn(el, PAGE)


class EveryAppPageReachesTheServerTests(unittest.TestCase):
    def test_every_app_portal_page_is_on_the_deploy(self):
        """SCRUM-195, 9 Nov 2026: three pages were on no deploy list, so a restyle of them would have said
        "all ok" and never reached the server (as sameday_proxy.py had, 8 Nov)."""
        deploy = (APP.parent / "deploy" / "Deploy-AMCRM.ps1").read_text(encoding="utf-8")
        listed = deploy.split("$Files = @(", 1)[1].split("\n)", 1)[0]
        for page in sorted(APP.glob("*.html")):
            with self.subTest(page=page.name):
                self.assertIn(f'"appportal/{page.name}"', listed)


class TheTestWalkthroughsAreOnThePortalTests(unittest.TestCase):
    """10 Nov 2026 (James: "put it on the app portal .. i don't like stray web pages"). The walkthroughs for every app
    and the ten SDI Live scenes are a page of the portal, behind the same sign-in, opened from its own tile."""
    PAGE = (APP / "guide-testing.html").read_text(encoding="utf-8")

    def test_a_tile_opens_it_and_it_leads_back(self):
        import json
        svc = [s for s in json.loads((APP.parent / "services.json").read_text(encoding="utf-8"))["services"]
               if s["id"] == "testing"]
        self.assertEqual(len(svc), 1)
        self.assertEqual((svc[0]["app_url"], svc[0]["surface"]), ("guide-testing.html", "app"))
        self.assertIn('href="./"', self.PAGE)
        self.assertNotIn("claude.ai", self.PAGE)                              # nothing pointing at a stray copy

    def test_every_app_and_the_ten_scenes_are_there(self):
        for app in ("App portal", "SDI Live", "AM CRM", "TTI Despatch", "HRInventry", "Estimating in your pocket",
                    "Remote Control", "Private Assistant", "Brief to Book", "Ten scenes to talk through"):
            with self.subTest(app=app):
                self.assertIn(f'name:"{app}"', self.PAGE)
        scenes = self.PAGE.split('id:"scenes"', 1)[1].split("pass:", 1)[0]
        self.assertEqual(scenes.count('["'), 10)

    def test_in_the_portals_look(self):
        self.assertEqual(self.PAGE.count('<path class="d"'), 2)               # the wordmark, its two yellow dots
        self.assertIn("--brand:#F6D946", self.PAGE)
        self.assertIn("family=Outfit", self.PAGE)
        self.assertIn("color-scheme:dark", self.PAGE)


if __name__ == "__main__":
    unittest.main()
