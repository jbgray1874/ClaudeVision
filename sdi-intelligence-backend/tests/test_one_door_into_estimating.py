"""One address for estimating, serving the shape that suits the device.

"I don't want links all over the shop.. they need to be centralised."

There were three ways to the phone-shaped page: a second button on the portal
card, a link in the full screen's subtitle, and the bare URL. Which one you
wanted depended on the device in your hand - which the app can work out for
itself. So /estimating is now the only address, and it decides.

That makes the decision load-bearing in both directions:

  * too generous, and somebody at a desk silently loses the live log, the file
    browser and the release button - the three things the full screen exists
    for, with nothing on screen to say why;
  * too mean, and the phone page nobody can find is the phone page nobody uses.

app.py cannot be imported without FastAPI installed, so the rule lives in
device.py where it can be put to the user-agents of real phones.
"""
import json
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import device                                                      # noqa: E402

APP = (BACKEND / "app.py").read_text(encoding="utf-8")
POCKET = (BACKEND / "appportal" / "estimating-pocket.html").read_text(encoding="utf-8")
FULL = (BACKEND / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")

# Real strings, not invented ones. A regex that passes against something
# plausible and fails against the actual phone is the whole risk here.
PHONES = {
    "iPhone, Safari":
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "iPhone, Chrome":
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) CriOS/126.0.6478.54 Mobile/15E148 Safari/604.1",
    "Android phone, Chrome":
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Mobile Safari/537.36",
    "Samsung phone, Samsung Internet":
        "Mozilla/5.0 (Linux; Android 13; SAMSUNG SM-S918B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36",
}

DESKS = {
    "Windows laptop, Chrome":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36",
    "Windows laptop, Edge":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mac, Safari":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    # ── THE ONE THE REGEX IS MOST LIKELY TO GET WRONG ────────────────────────
    # An Android TABLET sends "Android" with no "Mobile". That absence is the
    # documented way the two are told apart, and a tablet has the room for the
    # full screen - so "android" alone must not match.
    "Android tablet, Chrome":
        "Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36",
    # An iPad reports itself as a Mac. It cannot be distinguished here, and it
    # should not be: it gets the full screen, which is the right answer anyway.
    "iPad, Safari (reports as a Mac)":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
}


class PhonesGetThePocketPageTests(unittest.TestCase):
    def test_every_phone_in_the_building_is_recognised(self):
        for name, ua in PHONES.items():
            with self.subTest(device=name):
                self.assertTrue(device.is_a_phone(ua),
                                f"{name} would be sent to the full screen")

    def test_no_desk_or_tablet_is_mistaken_for_one(self):
        for name, ua in DESKS.items():
            with self.subTest(device=name):
                self.assertFalse(device.is_a_phone(ua),
                                 f"{name} would silently lose the live log, the "
                                 f"file browser and the release button")


class TheBrowserIsBelievedWhenItAnswersTests(unittest.TestCase):
    """Sec-CH-UA-Mobile is the browser describing itself, rather than us
    guessing from a string it made up, so it wins over the user-agent."""

    def test_the_hint_wins_over_a_desk_user_agent(self):
        self.assertTrue(device.is_a_phone(DESKS["Windows laptop, Chrome"], "?1"))

    def test_the_hint_wins_over_a_phone_user_agent(self):
        self.assertFalse(device.is_a_phone(PHONES["Android phone, Chrome"], "?0"))

    def test_a_missing_or_nonsense_hint_falls_back_to_the_user_agent(self):
        for hint in ("", "   ", "1", "true", "?2", "yes"):
            with self.subTest(hint=hint):
                self.assertTrue(device.is_a_phone(PHONES["iPhone, Safari"], hint))
                self.assertFalse(device.is_a_phone(DESKS["Mac, Safari"], hint))


class NotKnowingTakesNothingAwayTests(unittest.TestCase):
    """The full screen is the one that can do everything, so an unreadable
    request gets it. Guessing "phone" would remove the release button from
    somebody who never asked."""

    def test_nothing_at_all_is_a_desk(self):
        self.assertFalse(device.is_a_phone())
        self.assertFalse(device.is_a_phone("", ""))

    def test_rubbish_is_a_desk(self):
        for ua in ("curl/8.4.0", "x" * 500, "Mozilla/5.0", "?", "\x00"):
            with self.subTest(user_agent=ua[:20]):
                self.assertFalse(device.is_a_phone(ua))

    def test_it_decides_from_the_two_headers_and_nothing_else(self):
        """A narrow window on a laptop is still a laptop: somebody who dragged
        a browser half-way across a monitor has not asked for a different app.
        So the decision is made from request headers only.

        Checked by signature rather than by grepping the source - the first
        version of this test looked for the word "screen" and found it in the
        module's own comments, which is a test being wrong about working code.
        """
        import inspect
        taken = list(inspect.signature(device.is_a_phone).parameters)
        self.assertEqual(taken, ["user_agent", "mobile_hint"])

    def test_the_page_does_not_bounce_on_window_width_either(self):
        """The handover is the server's decision, made once. A page that also
        redirected on width would fight it on every resize."""
        for width in ("innerWidth", "matchMedia", "outerWidth", "screen.width"):
            with self.subTest(term=width):
                self.assertNotIn(width, POCKET)


class TheTwoPagesDoNotVolleyTests(unittest.TestCase):
    """── THE TRAP THIS WHOLE ARRANGEMENT SETS ─────────────────────────────
    /estimating sends a phone to the pocket page. The pocket page has a "Full
    screen" link back to /estimating. Without the escape hatch those two bounce
    off each other and the phone never lands anywhere.
    """

    def test_the_route_honours_the_escape_hatch(self):
        handler = APP.split("def estimating_page(", 1)[1].split("\n@app.", 1)[0]
        self.assertIn('query_params.get("full") != "1"', handler)
        self.assertIn("_is_a_phone(request)", handler)

    def test_the_pocket_pages_own_link_back_carries_it(self):
        self.assertIn('href="/estimating?full=1"', POCKET)

    def test_the_redirect_is_not_cached_as_permanent(self):
        """One cached 301 would send a laptop to the phone page for as long as
        the browser kept it - and nothing on screen would explain why."""
        handler = APP.split("def estimating_page(", 1)[1].split("\n@app.", 1)[0]
        self.assertIn("status_code=302", handler)
        self.assertIn("no-store", handler)
        self.assertNotIn("status_code=301", handler)
        self.assertNotIn("status_code=308", handler)

    def test_signing_in_happens_before_the_handover(self):
        """Otherwise a phone is redirected, signs in at the pocket page, and
        the parameter that got it there is lost."""
        handler = APP.split("def estimating_page(", 1)[1].split("\n@app.", 1)[0]
        self.assertLess(handler.index("login_redirect"), handler.index("_is_a_phone"))


class TheFullScreenStillDoesFullRunsTests(unittest.TestCase):
    """── WHAT THE HANDOVER MUST NOT COST ──────────────────────────────────
    "we also DO need to be able to do full runs."

    Sending a phone to the pocket page is only acceptable because the pocket
    page starts the SAME run: /api/estimate with a job_folder, the complete
    engine, drawings and all. If that ever became brief-only, the handover
    would be taking the main job away from whoever is holding a phone.
    """

    def test_the_pocket_page_starts_a_full_drawing_pack_run(self):
        self.assertIn('api("/api/estimate"', POCKET)
        self.assertIn("job_folder:", POCKET)
        self.assertIn("From a drawing pack", POCKET)

    def test_and_a_brief_only_run_as_well(self):
        self.assertIn('api("/api/estimate/brief"', POCKET)
        self.assertIn("From a written brief", POCKET)

    def test_the_full_screen_is_still_reachable_from_a_desk(self):
        self.assertIn('"/estimating"', APP)
        self.assertIn("sdi-estimating-intelligence.html", APP)

    def test_a_desk_can_still_find_the_phone_view_to_check_it(self):
        """Removing every link left it undiscoverable from a laptop, which is
        exactly how "what is the pocket page...." happened."""
        self.assertIn("/app/estimating-pocket.html", FULL)


if __name__ == "__main__":
    unittest.main()
