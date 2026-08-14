"""An estimate has to say which book of rates it came out of.

EVERY NUMBER THIS ENGINE PRODUCES IS A UK NUMBER. UDEF plain stock, UK labour rates, UK
finishing. The buttons that produced it said "SDI Intelligence Estimator" and "Estimate every
drawing", which was true while there was only one book. The moment a second one exists an
unlabelled button becomes a trap: two estimates that look identical on the page and in the
filed spreadsheet, told apart only by remembering which button somebody pressed.

THE ENQUIRY BUTTON IS THE ONE THAT WOULD HURT MOST. A hundred estimates arrive at once, filed
into a hundred folders, and nothing downstream would say which set of rates they were read
against.

SO EACH CARD OFFERS THE SAME PAIR: a UK button that runs, and a China button that exists with
nothing behind it. That second part is deliberate and it is the part worth guarding. There is
no China endpoint, no China rate set, no China route. A control that quietly did nothing when
pressed would be read as a run that produced no file — the most expensive kind of silence this
page can offer, because the estimator waits for it. It is disabled, and it says why in words.

THIS IS ONE RULE OVER EVERY CARD, not a check per button. A third card gets it by being listed,
and a card that grows a China button without the note or with the script able to reach it fails
here without anybody writing a new test.

THE RENAME LIVES IN TWO PLACES ON THE JOB CARD, which is the ordinary way a rename half-lands.
The markup carries the label and `refresh()` overwrites it on every state change — so a page
renamed only in the markup shows the new name until the first keystroke and the old name for
the rest of the session.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
    encoding="utf-8")
SCRIPT = PAGE[PAGE.index("<script>"):PAGE.index("</script>")]
MARKUP = PAGE[:PAGE.index("<script>")]

# Every card that starts work. `stop` is the control that ends the UK run on that card; it sits
# between the two so the live pair reads together and the dead one sits under them both.
CARDS = [
    pytest.param("run", "stop", "runChina", "chinaNote",
                 "SDI (UK) Intelligence Estimator",
                 "SDI (China) Intelligence Estimator", id="job"),
    pytest.param("bRun", "bStop", "bRunChina", "bChinaNote",
                 "SDI (UK) Intelligence — Estimate every drawing",
                 "SDI (China) Intelligence — Estimate every drawing", id="enquiry"),
]


def _button(el_id: str) -> str:
    """The one tag, from `<button` to `</button>` — so an attribute test cannot be satisfied by
    a word sitting in the comment above it or in the button next door."""
    at = re.search(r"<button[^>]*\bid=\"%s\"" % re.escape(el_id), PAGE)
    assert at, "no button with id=%r on the page" % el_id
    return PAGE[at.start():PAGE.index("</button>", at.start())]


# ── the UK button on each card names its book ────────────────────────────────────────

@pytest.mark.parametrize("uk,stop,cn,note,uk_label,cn_label", CARDS)
def test_the_button_that_runs_says_it_is_the_uk_one(uk, stop, cn, note, uk_label, cn_label):
    assert uk_label in _button(uk)


def test_no_unqualified_name_survives_anywhere():
    """Not in the markup, not in a title, not in a label written back by script. Two books and
    one of them unnamed is worse than one book unnamed."""
    assert "SDI Intelligence Estimator" not in PAGE
    assert ">Estimate every drawing<" not in PAGE


def test_every_label_written_back_by_script_names_its_book():
    """THE HALF-LANDED RENAME. `refresh()` runs on every keystroke and after every run and sets
    `textContent` from a literal of its own. Renaming the markup alone gives a button that is
    correct until the user types one character into the client box.

    Stated over every run button rather than the one that has a writeback today, so the trap
    cannot be re-entered by a later card learning to relabel itself."""
    seen = 0
    for var in ("runBtn", "bRun", "$(\"run\")", "$(\"bRun\")"):
        for w in re.findall(re.escape(var) + r"\.textContent\s*=\s*(.+)", SCRIPT):
            seen += 1
            assert "SDI (UK) Intelligence" in w, (
                "a label is written back that does not name the UK book: " + w.strip())
    assert seen, "no run button relabels itself any more — this guard is looking at nothing"


# ── the China button on each card is present and inert ───────────────────────────────

@pytest.mark.parametrize("uk,stop,cn,note,uk_label,cn_label", CARDS)
def test_the_china_estimator_is_offered(uk, stop, cn, note, uk_label, cn_label):
    assert cn_label in _button(cn)


@pytest.mark.parametrize("uk,stop,cn,note,uk_label,cn_label", CARDS)
def test_the_china_estimator_cannot_be_pressed(uk, stop, cn, note, uk_label, cn_label):
    """The bare `disabled` attribute, not `aria-disabled` — only the first stops a browser
    dispatching the click. A mutant that dropped `disabled` and kept `aria-disabled="true"`
    passed a substring test, leaving a pressable button that announces itself unpressable."""
    tag = _button(cn)
    assert re.search(r"(?<![-\w])disabled(?![-\w])", tag), "the button is pressable"
    assert 'aria-disabled="true"' in tag, "a screen reader is not told what the eye is told"


@pytest.mark.parametrize("uk,stop,cn,note,uk_label,cn_label", CARDS)
def test_nothing_in_the_script_can_reach_the_china_button(uk, stop, cn, note, uk_label,
                                                          cn_label):
    """NO ENDPOINT BEHIND IT — and the way that promise breaks is not somebody writing an
    `onclick`, it is somebody widening the card's refresh to enable "the run buttons". If the
    script cannot name the element, it cannot start a run that has nowhere to go."""
    assert cn not in SCRIPT
    assert cn in MARKUP, "the guard is passing because the button is gone"


@pytest.mark.parametrize("uk,stop,cn,note,uk_label,cn_label", CARDS)
def test_the_china_button_says_why_it_is_dead(uk, stop, cn, note, uk_label, cn_label):
    """A greyed-out button with no explanation reads as a page that has not finished loading,
    or as a run that failed. It has to state that there is nothing behind it yet — and the
    statement has to be visible, which is the failure a `hidden` would introduce silently."""
    at = PAGE.index('id="%s"' % note)
    tag_start = PAGE.rindex("<p", 0, at)
    para = PAGE[tag_start:PAGE.index("</p>", at)]
    assert "Not connected yet" in para
    assert not re.search(r"(?<![-\w])hidden(?![-\w])", para[:para.index(">")]), (
        "the explanation for the dead button is itself hidden")


@pytest.mark.parametrize("uk,stop,cn,note,uk_label,cn_label", CARDS)
def test_the_two_estimators_are_the_same_kind_of_control(uk, stop, cn, note, uk_label,
                                                         cn_label):
    """Both are `btn-run`. Styled as anything else — a link, a note — the China one would stop
    reading as the second half of a choice, which is the whole point of showing it before it
    works."""
    assert "btn-run" in _button(uk)
    assert "btn-run" in _button(cn)


@pytest.mark.parametrize("uk,stop,cn,note,uk_label,cn_label", CARDS)
def test_stopping_belongs_to_the_run_that_can_start(uk, stop, cn, note, uk_label, cn_label):
    """Stop sits under the button whose work it ends and above the one that has no work. Both
    cards read the same way, so neither card's stop can be mistaken for the other's."""
    assert PAGE.index('id="%s"' % uk) < PAGE.index('id="%s"' % stop) < PAGE.index('id="%s"' % cn)


def test_the_enquiry_stop_is_still_wired_after_the_relayout():
    """Moving the run buttons onto their own rows moved the stop with them. It has to still be
    the control the script binds, not a look-alike left behind in the old row."""
    assert 'id="bStop"' in MARKUP
    assert MARKUP.count('id="bStop"') == 1, "two stop buttons is one too many"
    assert '$("bStop").onclick' in SCRIPT
