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


def test_tti_despatch_offers_its_guide_and_links_to_it():
    (svc,) = [s for s in _services() if s["id"] == "tti-despatch"]
    assert svc["guide_url"] == "guide-tti.html"
    page = (APP_DIR / "tti-despatch.html").read_text(encoding="utf-8")
    assert 'href="/app/guide-tti.html"' in page
    guide = (APP_DIR / "guide-tti.html").read_text(encoding="utf-8")
    assert 'href="/api/tti/despatch"' in guide


def test_the_tti_guide_names_every_tab_and_every_chase_heading():
    import sys
    sys.path.insert(0, str(BACKEND))
    import tti_search
    guide = (APP_DIR / "guide-tti.html").read_text(encoding="utf-8")
    page = (APP_DIR / "tti-despatch.html").read_text(encoding="utf-8")
    for tab in re.findall(r'^  label: "([^"]+)"', page, re.M):
        assert tab in guide, tab
    for heading in tti_search._HEADINGS.values():
        assert heading in guide, heading


def test_the_tti_guide_lists_every_column_the_code_reads():
    guide = (APP_DIR / "guide-tti.html").read_text(encoding="utf-8")
    for column in ("LORRY FROM SDI", "DUE DATE", "SDI ORDER NO", "CUSTOMER PO", "PART CODE",
                   "DESCRIPTION", "TTI ACCOUNT", "QTY", "PALLETS", "COMMENTS",
                   "BOOKED IN WITH TTI", "LABEL + Batch DONE", "INVOICE NUMBER",
                   "PROOF OF EXPORT", "DEL ADD", "WHO PAYING", "VALUE", "TRAILER"):
        assert column in guide, column


def test_am_crm_offers_its_guide_and_links_to_it():
    (svc,) = [s for s in _services() if s["id"] == "voice-crm"]
    assert svc["guide_url"] == "guide-am-crm.html"
    app = (APP_DIR / svc["app_url"]).read_text(encoding="utf-8")
    assert 'href="guide-am-crm.html"' in app
    guide = (APP_DIR / svc["guide_url"]).read_text(encoding="utf-8")
    assert 'href="voice-crm.html"' in guide                          # and back again


def test_the_am_crm_guide_names_every_button_the_app_shows():
    """A button nobody explained is a button nobody presses."""
    guide = (APP_DIR / "guide-am-crm.html").read_text(encoding="utf-8")
    app = (APP_DIR / "voice-crm.html").read_text(encoding="utf-8")
    buttons = {re.sub(r"\s+", " ", b).strip()
               for b in re.findall(r"<button[^>]*>([^<]{3,40})</button>", app)}
    # The mic and Drive carry an emoji in the app; the guide names them in words.
    for name in sorted(buttons):
        plain = re.sub(r"&#\d+;\s*", "", name).strip()
        if not plain:
            continue
        assert plain in guide, f"the guide does not mention the {plain!r} button"


def test_the_am_crm_guide_explains_the_refusals_a_person_can_hit():
    """The messages worth explaining are the ones that stop somebody working,
    and each of these is a sentence the code can actually produce."""
    guide = (APP_DIR / "guide-am-crm.html").read_text(encoding="utf-8")
    for phrase in ("Updates in this pilot are limited to named people",
                   "updates aren't switched on for this pilot yet",
                   "Someone changed that record while we were talking",
                   "changes can't be saved"):
        assert phrase in guide, phrase
    source = (BACKEND / "voicecrm.py").read_text(encoding="utf-8")
    excel = (BACKEND / "voicecrm_excel.py").read_text(encoding="utf-8")
    for phrase in ("Updates in this pilot are limited to named people",
                   "updates aren't switched on for this pilot yet",
                   "Someone changed that record while we were talking"):
        assert phrase in source, f"the guide quotes a message the app no longer says: {phrase}"
    assert "changes can't be saved" in excel


def test_the_am_crm_guide_does_not_promise_what_the_app_refuses():
    """It says a calculated cell is never typed over and the owner column
    cannot change. Both have to stay true of the code."""
    guide = (APP_DIR / "guide-am-crm.html").read_text(encoding="utf-8")
    source = (BACKEND / "voicecrm.py").read_text(encoding="utf-8")
    assert "calculated cell" in guide
    assert "is_formula" in source
    assert "owner column" in guide
    assert "_is_owner_field" in source or "OWNER_FIELD" in source


def test_sameday_has_its_square_its_guide_and_a_way_back():
    """3 November 2026: "add the SameDay tile to the app portal, along with the
    other apps. anyone can use". Its own app on its own port; the square opens
    it, and the guide opens it too and returns to the portal."""
    (svc,) = [s for s in _services() if s["id"] == "sameday"]
    assert svc["surface"] in ("app", "both") and svc["app_category"] == "Apps"
    # 4 November: "the app needs to work on the phone" - carried by SDI Intelligence (sameday_proxy.py)
    assert svc["app_url"] == "/sameday/"
    assert svc["guide_url"] == "guide-sameday.html"
    guide = (APP_DIR / svc["guide_url"]).read_text(encoding="utf-8")
    assert 'href="/sameday/"' in guide
    assert 'href="./"' in guide                                       # back to all apps


def test_sameday_says_what_the_office_address_cannot_do_yet():
    """Plain http: the browser will not give it the microphone. Said on the
    square and in the guide, so nobody presses Talk live and decides it is broken.
    4 November: on a phone it now works from anywhere, signed in, mic and all."""
    (svc,) = [s for s in _services() if s["id"] == "sameday"]
    assert "microphone" in svc["requires"] and "http" in svc["requires"] and "phone" in svc["requires"]
    guide = (APP_DIR / "guide-sameday.html").read_text(encoding="utf-8")
    assert "On your phone, from anywhere." in guide
    assert "won't give it the microphone" in guide
    assert "no team code" in guide



def test_sameday_is_in_both_portals_with_one_open_button_each():
    """3 November: "integrate into SDI Intelligence portal off the left menu in
    the main intranet portal as well as in the app section". `both` puts it in
    the intranet's AI Services menu (which shows every entry not marked `app`)
    and in the app portal; the intranet opens it by `link`, the app portal by
    `app_url`, and the app portal does not show the same address twice."""
    (svc,) = [s for s in _services() if s["id"] == "sameday"]
    assert svc["surface"] == "both"
    assert svc["link"] == svc["app_url"]
    intranet = (BACKEND / "sdi-intelligence-portal.html").read_text(encoding="utf-8")
    assert "filter(s=>s.surface!=='app')" in intranet
    portal = (APP_DIR / "index.html").read_text(encoding="utf-8")
    assert "if(s.link && s.link!==s.app_url)" in portal
    assert any("/app/guide-sameday.html" in x["body"] for x in svc["sections"])


def test_no_section_repeats_the_heading_the_intranet_already_gives_it():
    """The intranet's detail page opens every service with its own "What it
    does" (from `detail`); a section with the same title printed it twice -
    seen on SameDay's page, 4 November."""
    for svc in _services():
        if svc.get("surface") == "app":
            continue
        for sec in svc.get("sections", []):
            assert sec["title"].strip().lower() != "what it does", svc["id"]
