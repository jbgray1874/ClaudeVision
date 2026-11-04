"""An app on the office network says why it won't open from a phone, instead of hanging.

4 November 2026, James on his phone: "Open SameDay doesn't do anything, it is there. I can open the guide but it just
hangs." The portal reaches the phone through App Proxy; SameDay is still only http://10.0.0.5:5020, an address that
exists only inside the office, so the browser waited for ever. Now it is tried, and after 10 seconds the wait is
stopped and the reason given. (Checked in Chromium with the address made to hang: "Opening SameDay..." at once, the
reason at 10 s, and a reachable address opens as before.)
"""
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "appportal"
PAGES = {name: (APP / name).read_text(encoding="utf-8") for name in ("index.html", "guide-sameday.html")}


def office_rule(page):
    js = re.search(r"const OFFICE=/(.+?)/i;", page).group(1).replace("\\/", "/")
    return re.compile(js, re.I)


class EveryPageWithASameDayLinkTests(unittest.TestCase):
    def test_both_pages_carry_it(self):
        for name, page in PAGES.items():
            with self.subTest(page=name):
                self.assertIn("didn't open from here", page)
                self.assertIn("window.stop()", page)
                self.assertIn("},10000);", page)
                self.assertIn("window.addEventListener('pagehide',()=>clearTimeout(t),{once:true});", page)

    def test_it_names_the_vpn_and_the_secure_address(self):
        for name, page in PAGES.items():
            with self.subTest(page=name):
                self.assertIn("office network or the VPN", page)
                self.assertIn("secure address", page)

    def test_only_office_addresses_are_held(self):
        rule = office_rule(PAGES["index.html"])
        for url in ("http://10.0.0.5:5020/", "http://192.168.1.20/", "http://172.20.0.4:8080/"):
            with self.subTest(url=url):
                self.assertTrue(rule.match(url))
        for url in ("https://sdi.example.com/app/", "http://100.64.0.1/", "http://172.32.0.1/", "https://10.0.0.5/",
                    "guide-sameday.html"):
            with self.subTest(url=url):
                self.assertIsNone(rule.match(url))

    def test_a_new_tab_link_is_left_alone(self):
        for page in PAGES.values():
            self.assertIn("a.target==='_blank'", page)

    def test_sameday_is_still_linked_by_its_office_address(self):
        self.assertIn('href="http://10.0.0.5:5020/"', PAGES["guide-sameday.html"])


if __name__ == "__main__":
    unittest.main()
