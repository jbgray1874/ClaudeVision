"""Every app portal square that offers a user guide has one, and the app links to it.

A "User guide" button that opens a 404 is worse than no button.
"""
import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
APP_DIR = BACKEND / "appportal"


def _services():
    return json.loads((BACKEND / "services.json").read_text(encoding="utf-8"))["services"]


def test_every_guide_named_on_a_square_exists():
    guides = [s["guide_url"] for s in _services() if s.get("guide_url")]
    assert guides, "no app offers a guide"
    for g in guides:
        assert "/" not in g and (APP_DIR / g).is_file(), g


def test_hrinventry_anywhere_offers_its_guide_and_links_to_it():
    (svc,) = [s for s in _services() if s["id"] == "hr-inventry"]
    assert svc["guide_url"] == "guide-hr-inventry.html"
    app = (APP_DIR / svc["app_url"]).read_text(encoding="utf-8")
    assert 'href="guide-hr-inventry.html"' in app
    guide = (APP_DIR / svc["guide_url"]).read_text(encoding="utf-8")
    assert 'href="hr-inventry.html"' in guide                        # and back again


def test_the_guide_covers_every_tab_and_button():
    guide = (APP_DIR / "guide-hr-inventry.html").read_text(encoding="utf-8")
    app = (APP_DIR / "hr-inventry.html").read_text(encoding="utf-8")
    tabs = re.findall(r'class="tab[^"]*" data-v="\w+">([^<]+)<', app)
    assert tabs, "no tabs found in the app"
    for name in tabs + ["Check who's clocked in", "Update InVentry", "Start a new roll call",
                        "Run the data check"]:
        assert name.replace("'", "&#39;") in guide or name in guide, name
