"""An estimate has to say which book of rates it came out of.

EVERY NUMBER THIS ENGINE PRODUCES IS A UK NUMBER. UDEF plain stock, UK labour rates, UK
finishing. The button that produced it said "SDI Intelligence Estimator", which was true while
there was only one book. Work placed in China is a different set of numbers end to end, and
the moment a second book exists an unlabelled button becomes a trap: two estimates that look
identical on the page, told apart only by remembering which button somebody pressed.

SO THE UK BUTTON NAMES ITSELF, AND THE CHINA BUTTON EXISTS WITH NOTHING BEHIND IT. That second
part is deliberate and it is the part worth guarding. There is no China endpoint, no China rate
set, no China route. A control that quietly did nothing when pressed would be read as a run
that produced no file — the most expensive kind of silence this page can offer, because the
estimator waits for it. It is disabled, and it says why in words.

THE RENAME LIVES IN TWO PLACES, WHICH IS THE ORDINARY WAY A RENAME HALF-LANDS. The markup
carries the label, and `refresh()` overwrites it on every state change — so a page renamed only
in the markup shows the new name until the first keystroke and the old name for the rest of the
session.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
    encoding="utf-8")
SCRIPT = PAGE[PAGE.index("<script>"):PAGE.index("</script>")]
MARKUP = PAGE[:PAGE.index("<script>")]


def _button(el_id: str) -> str:
    """The one tag, from `<button` to `</button>` — so an attribute test cannot be satisfied
    by a word sitting in the comment above it or in the button next door."""
    at = re.search(r"<button[^>]*\bid=\"%s\"" % re.escape(el_id), PAGE)
    assert at, "no button with id=%r on the page" % el_id
    start = at.start()
    return PAGE[start:PAGE.index("</button>", start)]


# ── the UK button names its book ─────────────────────────────────────────────────────

def test_the_running_estimator_says_it_is_the_uk_one():
    assert "SDI (UK) Intelligence Estimator" in _button("run")


def test_the_old_unqualified_name_survives_nowhere():
    """Not in the markup, not in a title, not in the label `refresh()` writes back. Two books
    and one of them unnamed is worse than one book unnamed."""
    assert "SDI Intelligence Estimator" not in PAGE


def test_the_label_refresh_writes_back_is_the_new_one():
    """THE HALF-LANDED RENAME. `refresh()` runs on every keystroke and after every run, and it
    sets `textContent` from a literal of its own. Renaming the markup alone gives a button that
    is correct until the user types one character into the client box."""
    writes = re.findall(r"runBtn\.textContent\s*=\s*(.+)", SCRIPT)
    assert writes, "refresh() no longer sets the label — this guard is looking at nothing"
    for w in writes:
        assert "SDI (UK) Intelligence Estimator" in w, (
            "a label is written back that does not name the UK book: " + w.strip())


# ── the China button is present and inert ────────────────────────────────────────────

def test_the_china_estimator_is_offered_on_the_page():
    assert "SDI (China) Intelligence Estimator" in _button("runChina")


def test_the_china_estimator_cannot_be_pressed():
    """The bare `disabled` attribute, not `aria-disabled` — only the first stops a browser
    dispatching the click. A mutant that dropped `disabled` and kept `aria-disabled="true"`
    passed a substring test, leaving a pressable button that announces itself as unpressable."""
    tag = _button("runChina")
    assert re.search(r"(?<![-\w])disabled(?![-\w])", tag), "the button is pressable"
    assert 'aria-disabled="true"' in tag, "a screen reader is not told what the eye is told"


def test_nothing_in_the_script_can_reach_the_china_button():
    """NO ENDPOINT BEHIND IT — and the way that promise breaks is not somebody writing an
    `onclick`, it is somebody widening `refresh()` to enable "the run buttons". If the script
    cannot name the element, it cannot start a run that has nowhere to go."""
    assert "runChina" not in SCRIPT
    assert "runChina" in MARKUP, "the guard is passing because the button is gone"


def test_the_china_button_says_why_it_is_dead_rather_than_only_looking_dead():
    """A greyed-out button with no explanation is read as a page that has not finished loading,
    or as a run that failed. It has to state that there is nothing behind it yet."""
    note = PAGE[PAGE.index('id="chinaNote"'):]
    note = note[:note.index("</p>")]
    assert "Not connected yet" in note
    assert "hidden" not in PAGE[PAGE.index("<p class=\"note\" id=\"chinaNote\""):
                                PAGE.index("<p class=\"note\" id=\"chinaNote\"") + 40], (
        "the explanation for the dead button is itself hidden")


def test_the_two_estimators_are_the_same_kind_of_control():
    """Both are `btn-run`. If the China one were styled as something else — a link, a note —
    it would stop reading as the second half of a choice, which is the whole point of putting
    it there before it works."""
    assert "btn-run" in _button("run")
    assert "btn-run" in _button("runChina")


def test_stopping_still_belongs_to_the_run_that_can_start():
    """The stop control sits between the two buttons now. It must still be the UK run's, not
    something the layout change quietly re-pointed."""
    assert PAGE.index('id="run"') < PAGE.index('id="stop"') < PAGE.index('id="runChina"')
    assert "stopBtn.hidden = !running" in SCRIPT
