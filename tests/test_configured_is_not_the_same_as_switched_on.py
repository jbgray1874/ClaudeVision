"""Having the settings and having a host that answers are two different things, and the page said
only the first one.

WHAT HAPPENED. The Document Manager settings were copied into the backend's .env, the service was
restarted, and `/api/estimate/dm/health` reported:

    {"configured": true, "reachable": false, "com_available": null,
     "reason": "The Document Manager at http://DESKTOP-4F3TLJN:8000 could not be reached
                (ConnectTimeout). Its host must be online."}

`configured: true` is real progress and the page should reflect it — Extract DesignDrawingPack
stops falling back to the share browser and opens its own panel. But `reachable: false` means the
desktop hosting the API is off, and the page had no way of knowing that, because NOTHING EVER
CALLED /dm/health. The route's own docstring says it is "asked before the button is offered rather
than after it is pressed"; it was written, deployed, and then never asked. `checkDm()` called
/dm/status only, which is a pure settings check.

So the sequence was: press Extract, get a panel that looks ready, type a project number, press
Extract again, wait, and receive a ConnectTimeout — a network fault delivered as though it were a
failed extract. The fix a person needs ("switch that desktop on") was three screens away from where
they were told something had gone wrong.

TWO PLACES, ON PURPOSE, AND NEITHER OF THEM BLOCKS ANYTHING.

  * On load, under the list, quietly — the estimator learns the state of the world before they
    have invested anything in the form.
  * On opening the panel, again — because a desktop that was off when this page loaded can be on
    by now. A health reading taken minutes ago is not evidence about a press happening now, and
    disabling a button on a stale reading would be a worse fault than the one being fixed: it
    would refuse work the host could perfectly well do.

The button is never disabled by either. They report; the extract itself is still the authority.

AND THE OUTPUT-ROOT NAG IS GONE WHEN THE API WORKS. `SDI_DM_OUTPUT_ROOT` is our name for a share
the Document Manager's own author had never heard of — callers omit `outputDir` and read
`result.outputDir` back from the finished job. Telling somebody with a working API that they are
missing that setting sent them hunting for it. It cost an afternoon, and it is now only mentioned
when there is no API at all to do the job better.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PAGE = (_ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
    encoding="utf-8")


# ── the route existed and nobody asked it ──────────────────────────────────────

def test_the_page_actually_asks_whether_the_host_is_up():
    """THE FAULT IN ONE LINE. /dm/health was written to be asked before the button is offered,
    and the page only ever asked /dm/status."""
    assert "/api/estimate/dm/health" in _PAGE, (
        "the page never asks whether the Document Manager host is reachable")


def test_it_is_asked_on_load_and_again_on_opening_the_panel():
    """Once is not enough in either direction: on load it is too early to be sure and by the
    press it is too late to be useful."""
    assert _PAGE.count("/api/estimate/dm/health") >= 2


def test_opening_the_panel_checks_before_the_project_number_is_typed():
    at = _PAGE.index('$("addFolder").onclick')
    body = _PAGE[at:_PAGE.index('$("dmCancel").onclick')]
    assert "/api/estimate/dm/health" in body, (
        "the panel opens without checking, so a dead host is discovered after the form is filled")


# ── what it must NOT do ────────────────────────────────────────────────────────

def test_a_health_reading_never_disables_the_button():
    """A stale 'unreachable' would refuse an extract the host could run. The health call informs;
    the extract remains the authority on whether it can be done."""
    at = _PAGE.index('$("addFolder").onclick')
    body = _PAGE[at:_PAGE.index('$("dmCancel").onclick')]
    assert "addFolder.disabled" not in body
    handler = body.split("/api/estimate/dm/health")[1].split("}).catch")[0]
    assert "disabled" not in handler, "the health result gates the form instead of reporting on it"
    assert "hidden = true" not in handler, "an unreachable host closes the panel it just opened"


def test_the_note_is_never_left_waiting_on_a_timeout():
    """Filled from the settings immediately, corrected when health returns. A ten-second blank
    line reads as a broken page."""
    at = _PAGE.index("if(dmNote){")
    body = _PAGE[at:at + 1400]
    assert body.index("dmNote.textContent =") < body.index("/api/estimate/dm/health"), \
        "the note waits for the health call before saying anything"
    assert "await api(\"/api/estimate/dm/health\")" not in body, \
        "awaiting it holds the page for the health timeout"


def test_a_failed_health_call_costs_nothing():
    """Not being able to ask is not the same as a bad answer, and must not blank the note or
    throw into the console."""
    at = _PAGE.index("if(dmNote){")
    body = _PAGE[at:at + 1400]
    assert ".catch(" in body


# ── the sentences a person has to act on ───────────────────────────────────────

def test_the_reason_from_the_service_reaches_the_screen():
    """'Its host must be online' is the whole fix. Replacing it with our own wording would lose
    the address and the exception name, which are what identify the machine to switch on."""
    at = _PAGE.index('$("addFolder").onclick')
    body = _PAGE[at:_PAGE.index('$("dmCancel").onclick')]
    assert "h.reason" in body
    assert "h.reason" in _PAGE[_PAGE.index("if(dmNote){"):_PAGE.index("if(dmNote){") + 1400]


def test_a_host_that_is_up_says_so_rather_than_nothing():
    """Silence after pressing a button is indistinguishable from a button that does nothing."""
    at = _PAGE.index('$("addFolder").onclick')
    body = _PAGE[at:_PAGE.index('$("dmCancel").onclick')]
    assert "is up at" in body


def test_a_cad_failure_is_not_dressed_as_a_network_failure():
    """comAvailable false means the host answered. It is somebody else's CAD problem, may clear
    on its own, and must not be styled as this service failing."""
    at = _PAGE.index('$("addFolder").onclick')
    body = _PAGE[at:_PAGE.index('$("dmCancel").onclick')]
    assert "com_available !== false" in body
    assert 'h.reachable ? "w" : "e"' in body, "a reachable host with bad COM must not read as down"


# ── the setting that should never have been asked for ──────────────────────────

def test_the_output_root_is_not_demanded_of_somebody_who_has_the_api():
    """SDI_DM_OUTPUT_ROOT is our name for a share the API's own author had never heard of.
    Callers omit outputDir and read result.outputDir back."""
    at = _PAGE.index("const gaps = [];")
    body = _PAGE[at:at + 700]
    root_at = body.index("SDI_DM_OUTPUT_ROOT")
    guard = body.rfind("if(", 0, root_at)
    assert "!dmApiReady" in body[:root_at], "the output root is mentioned regardless of the API"
    assert "j.configured" in body[guard:root_at], "the nag is not conditional at all"


def test_the_settings_are_still_named_when_there_are_none():
    """The names its owner gave them — the whole point of the previous commit."""
    at = _PAGE.index("const gaps = [];")
    body = _PAGE[at:at + 700]
    assert "DOCMGR_BASE_URL" in body and "DOCMGR_ACCESS_SECRET" in body


def test_nothing_is_said_when_there_is_nothing_wrong():
    at = _PAGE.index("const gaps = [];")
    body = _PAGE[at:at + 900]
    assert 'gaps.length ?' in body, "the note must be empty when the gaps list is"
