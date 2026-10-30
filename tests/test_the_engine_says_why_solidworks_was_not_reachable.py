"""The engine told an estimator the two causes "look identical from here". They do not.

WHAT IT SAID, on a machine with a paid, licensed, open SolidWorks seat:

    No SolidWorks seat could be attached to... SolidWorks is either not running, or is running
    in a different logon session from this runner. Both look identical from here.

James: "we can't be having these issues with SolidWorks. the company is paying for this
subscription. it needs to work. no bugs. this is NOT an academic exercise."

He is right, and the engine's share of it is precise: that sentence is TRUE of COM and useless
to the person reading it. It names two causes with opposite remedies — start the application,
or move the runner — and declines to say which, leaving somebody to guess on a job that cannot
be costed without the models.

THE TWO CASES ARE ONLY IDENTICAL TO COM. GetActiveObject reads the Running Object Table, which
is partitioned per logon session and per integrity level, so a seat in another session is
invisible to it. Windows is perfectly willing to say whether SLDWORKS.exe is running, as whom,
and in which session, and this process knows its own. Comparing them turns an unactionable
error into one instruction. The engine stopped looking at the exact point where looking was
cheap.

FOUR ANSWERS, FOUR DIFFERENT THINGS TO DO:

    not running anywhere        open SolidWorks in this desktop session
    another session             start the runner in the session that owns it
    same session, same user     it was started as administrator; reopen it normally
    the runner is elevated      start the runner unelevated

AND A FIFTH THAT MUST NOT COLLAPSE INTO THE SECOND: we could not query the machine at all.
Reporting that as "nothing is running" is the same inference-printed-as-observation the whole
function exists to remove.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cad_inputs import attach_failure_reason                            # noqa: E402

ME = {"session": 1, "user": "will.lear"}


def test_a_seat_that_is_not_running_says_so_and_nothing_else():
    txt = attach_failure_reason([], ME, False)
    assert "NOT RUNNING" in txt
    assert "Open SolidWorks" in txt
    assert "logon session" not in txt, (
        "it is still offering the other cause, which is the shrug this replaces")


def test_a_seat_in_another_session_names_the_session_and_the_remedy():
    txt = attach_failure_reason(
        [{"pid": "8123", "user": "will.lear", "session": "2"}], ME, False)
    assert "session 2" in txt and "session 1" in txt
    assert "8123" in txt, "the process it can see is not identified"
    assert "install-runner-task" in txt
    assert "session 0 has no desktop" in txt, (
        "nothing warns that a service or NSSM can never work, which is the wrong fix "
        "somebody reaches for next")


def test_a_seat_in_our_own_session_leaves_exactly_one_cause():
    """Same user, same session, runner unelevated, still invisible. The only remaining
    partition of the Running Object Table is integrity level, so SolidWorks is the elevated
    one — and that is a statement, not a guess."""
    txt = attach_failure_reason(
        [{"pid": "8123", "user": "will.lear", "session": "1"}], ME, False)
    assert "AS ADMINISTRATOR" in txt
    assert "reopen it normally" in txt
    assert "not running" not in txt.lower(), "it is contradicting itself: the seat IS running"


def test_an_elevated_runner_is_answered_before_anything_else():
    """No amount of process detail changes this one: an administrator process cannot see an
    ordinary one however plainly it is on screen."""
    txt = attach_failure_reason(
        [{"pid": "8123", "user": "will.lear", "session": "1"}], ME, True)
    assert "ELEVATED" in txt
    assert "NORMAL PowerShell" in txt


def test_being_unable_to_look_is_not_reported_as_nothing_running():
    """THE ONE THAT WOULD UNDO THE WHOLE THING. If tasklist cannot be run, saying "SolidWorks
    is not running" sends somebody to start an application that is already open — which is the
    exact failure recorded in the comment above the original message, twice."""
    txt = attach_failure_reason(None, ME, False)
    assert "could not query" in txt
    assert "NOT RUNNING" not in txt


@pytest.mark.parametrize("procs", [
    [], None,
    [{"pid": "1", "user": "will.lear", "session": "2"}],
    [{"pid": "1", "user": "will.lear", "session": "1"}],
])
def test_every_answer_ends_in_something_to_do(procs):
    """A diagnosis with no next step is the message this replaces wearing more words."""
    txt = attach_failure_reason(procs, ME, False)
    assert any(w in txt for w in ("Open SolidWorks", "Start the", "start the",
                                  "reopen it normally", "could not query"))
