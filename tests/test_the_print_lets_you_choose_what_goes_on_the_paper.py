"""Print must send the files the estimator chose, not everything in the panel.

    body: JSON.stringify({paths: drawings.map(d => d.path), ...})

Print sent the WHOLE Drawings list. The only way to leave a file out was the × beside it — which
also removed it from the estimate run. One list was doing two jobs that are not the same: you want
every file in the run, and a chosen few on the paper.

On 10575-02 that meant pressing Print sent the GA, the manual estimate, both engine-written
workbooks, the quote and the job report. James pressed it and got a hundred and ten pages, most of
them the AI's own estimate rendered back into paper, and reasonably asked what was going on.

So there is a picker. It opens on the click, ticks what belongs on paper, and says WHY anything is
unticked — a tick box with no reason is a decision somebody has to make twice.

WHY THE DEFAULTS LIVE IN THE PAGE AND NOT ON THE SERVER. The dialog has to open inside the click,
because a window.open() after a network round-trip is not a user gesture any more and the browser
blocks it. Asking the server first would cost that. The server stays the authority on what
actually converts; the page only decides where the ticks start, and being wrong there costs a
tick rather than a wrong print.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PAGE = (_ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
    encoding="utf-8")


def test_the_request_sends_the_chosen_paths_not_the_whole_list():
    """The fault itself. `drawings.map` here means the picker is decorative."""
    at = _PAGE.index("/api/estimate/drawings/print")
    body = _PAGE[at:at + 400]
    assert "paths: paths" in body, "the request must carry the selection"
    assert "drawings.map" not in body, "it is still sending everything in the panel"


def test_the_picker_opens_from_the_print_button():
    """The window is generous on purpose. This asserted against the first 220 characters and
    broke the moment the handler grew a try/catch — while the thing it protects, that the click
    reaches the picker, was still true. A test that fails on a guard being added is noise."""
    at = _PAGE.index('$("printDrawings").onclick')
    handler = _PAGE[at:at + 900]
    assert "openPrintPicker" in handler


def test_the_dialog_exists_with_the_controls_it_needs():
    assert 'id="printPick"' in _PAGE
    for control in ("ppList", "ppGo", "ppAll", "ppNone", "ppClose", "ppHelp"):
        assert f'id="{control}"' in _PAGE, f"the picker has no {control}"


def test_the_tab_still_opens_inside_the_gesture():
    """A window.open() after an await is blocked, and the button appears to do nothing — the one
    failure mode that gets a feature abandoned. runPrint must be called straight from the click,
    with the open before the await."""
    at = _PAGE.index("async function runPrint")
    body = _PAGE[at:at + 1200]
    assert body.index('window.open("", "_blank")') < body.index("await api("), \
        "the tab is opened after the round trip, which the browser will block"
    assert 'runPrint([...printPicked])' in _PAGE, "runPrint must be called from the button itself"


def test_nothing_is_printed_when_nothing_is_ticked():
    assert 'printPicked.size === 0' in _PAGE, "Print selected must be disabled on an empty choice"


def test_the_page_knows_which_files_the_engine_wrote():
    """Mirrors drawings_print.ENGINE_OUTPUT_PATTERNS. Two copies of a rule is a cost, and it is
    paid deliberately — see the module docstring — so this at least pins that they agree on the
    shapes that matter."""
    for shape in ("_quote", "_report", "_parity", "_sw_native_extract"):
        assert shape in _PAGE, f"the picker cannot recognise {shape}"
    assert r"_\d{8}_\d{6}" in _PAGE, "the timestamped workbook shape is missing"


def test_an_unticked_file_says_why():
    """A tick box with no reason beside it is a decision somebody has to make twice."""
    at = _PAGE.index("function printDefault")
    body = _PAGE[at:at + 900]
    assert "the engine wrote this" in body
    assert "not a format that can be turned into pages" in body


def test_the_picker_does_not_touch_the_run_list():
    """The whole point. Choosing what to print must not remove a drawing from the estimate."""
    at = _PAGE.index("function openPrintPicker")
    body = _PAGE[at:_PAGE.index('$("ppClose").onclick')]
    assert "drawings.splice" not in body
    assert "drawings =" not in body
    assert "renderFiles" not in body, "it is re-rendering the run list, so it is changing it"


# ── a click must never do nothing ──────────────────────────────────────────────
#
# The old handler opened a tab on the click itself, so even a failure was visible. Routing
# through a dialog put a silent path in the middle: anything thrown inside openPrintPicker — a
# missing element, a bad row, a browser that will not showModal — left the button looking dead.
# A dead-looking button is indistinguishable from a broken service, and is how a feature gets
# abandoned. It happened, on the first real use.

def test_the_click_is_wrapped_so_a_failure_is_visible():
    at = _PAGE.index('$("printDrawings").onclick')
    body = _PAGE[at:at + 900]
    assert "try{" in body and "catch" in body, "the click can still fail silently"
    assert "printNote" in body, "a failure must be said on the page"


def test_a_failed_chooser_still_prints():
    """Falling back to the old behaviour — print everything — beats doing nothing. The estimator
    gets paper and a sentence explaining why they did not get to choose."""
    at = _PAGE.index('$("printDrawings").onclick')
    body = _PAGE[at:at + 900]
    assert "runPrint(drawings.map(d => d.path))" in body, "no fallback: the click does nothing"


def test_a_browser_without_dialog_support_is_detected_rather_than_assumed():
    at = _PAGE.index('$("printDrawings").onclick')
    body = _PAGE[at:at + 900]
    assert "showModal" in body, "it must check the browser can open a dialog before relying on it"


def test_one_bad_row_does_not_cost_the_whole_dialog():
    """Every file in the list gets described. One that cannot be must not take the other eleven
    with it — it is offered ticked, and the server decides whether it converts."""
    at = _PAGE.index("function openPrintPicker")
    body = _PAGE[at:at + 900]
    assert "try { def = printDefault(d); } catch" in body
