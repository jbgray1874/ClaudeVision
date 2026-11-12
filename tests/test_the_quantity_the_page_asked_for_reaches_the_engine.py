r"""Four books at one off, on a job that asked for fifty, and nothing anywhere said so.

11908-21 was queued for 50 off. Four consecutive runs came back with D6 = 1 — set-ups
amortised over one unit, every labour line divided by one, a unit cost nobody could compare
with anything. The page said 50. The claim said 50. The workbook said 1.

AN ABSENT FLAG LEAVES NO TRACE. A cell reading 1 looks identical whether the engine was
told one or told nothing, so there was no symptom to chase — only a number that seemed a
little high, four times, while we looked for defects in the costing.

This is the same failure the file already records for `--quantity-breaks`, in its own
words: "the page sends them, the request models accept them, Run stores them, the runner
passes them to main.py — and THIS dictionary did not, so the runner read None every time
and the flag never once reached the engine". And for `--llm-only` before that, where a full
four-reader estimate came back wearing an LLM-only label. Three flags, one shape.

The difference is what each one costs. A missing break makes a run INCOMPLETE — four
variant workbooks that are simply not there. A missing QUANTITY makes it WRONG, and wrong
in a way that reads as ordinary: set-up over the wrong batch touches every line on the
sheet at once.

The runner echoes the command it is about to run, and that echo is the ground truth about
what the engine was told. So it is asked — and said, not stopped, because the run may still
be wanted and killing it would lose the hour.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "sdi-intelligence-backend"))
os.environ.setdefault("SDI_OFFLINE", "1")

import pytest  # noqa: E402

estimate_routes = pytest.importorskip("estimate_routes")


class _Run:
    """The fields the guard reads, and a log it can write to."""

    def __init__(self, units=50, breaks=(), llm_only=False, fresh_read=False):
        self.units = units
        self.quantity_breaks = list(breaks)
        self.llm_only = llm_only
        self.fresh_read = fresh_read
        self.breaks_warned = False
        self.qty_warned = False
        self.instruction_refused = False
        self.log = []

    def line(self, text):
        self.log.append(text)

    def said(self):
        return " ".join(self.log)


def _told(run, cmd):
    estimate_routes._check_the_engine_was_told(run, cmd)
    return run.said()


_ECHO = "$ python main.py --job K:\\...\\11908-21 --generate-ai-spreadsheet"


# ── the quantity, which is the estimate ──────────────────────────────────────────────

def test_a_run_asked_for_fifty_and_told_nothing_says_so():
    run = _Run(units=50)
    said = _told(run, _ECHO)
    assert "WARNING" in said and "50 off" in said
    assert "NOT told the quantity" in said


def test_it_says_what_goes_wrong_rather_than_only_that_something_did():
    """"The quantity is missing" is a fact about a flag. "Every set-up is amortised over
    one instead of fifty" is what it does to the sheet."""
    run = _Run(units=50)
    said = _told(run, _ECHO)
    assert "set-up" in said and "amortised" in said
    assert "look ordinary and be wrong" in said


def test_it_names_the_usual_cause_because_the_remedy_follows_from_it():
    run = _Run(units=50)
    said = _told(run, _ECHO)
    assert "git pull does not reload it" in said


def test_a_quantity_that_disagrees_is_caught_as_well_as_a_missing_one():
    """Told 3 when the page asked for 50 is not a smaller version of being told nothing —
    it is two numbers amortising the same set-ups over different batches."""
    run = _Run(units=50)
    said = _told(run, _ECHO + " --order-qty 3")
    assert "DIFFERENT quantity" in said
    assert "--order-qty 50" in said


def test_the_right_quantity_passes_in_silence():
    run = _Run(units=50)
    assert _told(run, _ECHO + " --order-qty 50") == ""


def test_a_one_off_is_not_warned_about():
    """One off is the ordinary case and needs no flag. A warning that fires on every small
    job is read on none of them."""
    run = _Run(units=1)
    assert _told(run, _ECHO) == ""


def test_it_is_said_once_and_not_on_every_log_line():
    run = _Run(units=50)
    _told(run, _ECHO)
    _told(run, _ECHO)
    assert len([ln for ln in run.log if "NOT told the quantity" in ln]) == 1


def test_it_does_not_stop_the_run():
    """The run may still be wanted, and killing it loses the hour. A guard that refuses is
    a guard people switch off."""
    run = _Run(units=50)
    _told(run, _ECHO)
    assert run.instruction_refused is False


# ── and the guards that were already there still work ───────────────────────────────

def test_the_missing_breaks_warning_is_unchanged():
    run = _Run(units=1, breaks=(50, 100))
    said = _told(run, _ECHO)
    assert "50, 100" in said and "variant workbooks" in said


def test_nothing_is_said_about_a_line_that_is_not_the_command_echo():
    """`$ ` is the runner's own convention for the echo. Prose on the same log — including
    this guard's own words — must not be mistaken for it."""
    run = _Run(units=50)
    assert _told(run, "WARNING — this run asked for 50 off and main.py was not told") == ""
