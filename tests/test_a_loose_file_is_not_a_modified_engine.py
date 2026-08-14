"""An untracked file in the folder does not mean the code that ran was modified.

THE STAMP EXISTS TO ANSWER ONE QUESTION: can this estimate be reproduced from a commit? It
asked `git status --porcelain`, which lists untracked files as `??` — so a scratch script, a
PDF dropped in the working tree or a notes file made every run report

    + UNCOMMITTED CHANGES (this run is not reproducible from the commit)

on a checkout whose tracked files were identical to the commit. A file git has never tracked
was never imported; the code that ran IS the commit.

THAT IS NOT A COSMETIC COMPLAINT. A warning that fires on a clean tree is a warning nobody
reads on the day the tree is genuinely modified — and this stamp is the only thing standing
between "which build wrote this JSON" and another afternoon of arguing about it.

Untracked files are still counted and still reported. "There is loose material in the working
tree" is worth knowing. It is simply a different claim from "this run cannot be reproduced".
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import engine_build  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh():
    engine_build._CACHE = None
    yield
    engine_build._CACHE = None


def _git_returning(answers):
    def fake(*args):
        if args[0] == "rev-parse" and "HEAD" in args and "--short" in args:
            return "abc1234"
        if args[0] == "rev-parse":
            return "a-branch"
        if args[0] == "log":
            return "a subject"
        if args[0] == "status":
            return answers["tracked"] if "--untracked-files=no" in args else answers["all"]
        return ""
    return fake


def _describe(tracked, all_out, monkeypatch):
    monkeypatch.setattr(engine_build, "_git",
                        _git_returning({"tracked": tracked, "all": all_out}))
    return engine_build.describe(refresh=True)


def test_untracked_files_alone_do_not_make_a_run_unreproducible(monkeypatch):
    """THE DEFECT. Three loose files, nothing tracked modified — the code that ran is the
    commit, and the stamp must say so."""
    b = _describe("", "?? notes.md\n?? scratch.py\n?? drawing.pdf", monkeypatch)
    assert b["dirty"] is False
    assert "not reproducible" not in engine_build.one_line(b)


def test_the_loose_files_are_still_counted_and_said_out_loud(monkeypatch):
    """Not silence. "There is loose material in the tree" is worth knowing — it is simply not
    the same claim."""
    b = _describe("", "?? notes.md\n?? scratch.py", monkeypatch)
    assert b["untracked_files"] == 2
    line = engine_build.one_line(b)
    assert "2 untracked file(s)" in line
    assert "clean" in line


def test_a_modified_tracked_file_is_still_reported_as_unreproducible(monkeypatch):
    """The alarm must still work. This is the case the stamp was built for."""
    b = _describe(" M src/estimator.py", " M src/estimator.py\n?? notes.md", monkeypatch)
    assert b["dirty"] is True
    assert "not reproducible" in engine_build.one_line(b)


def test_a_staged_change_counts_as_modified(monkeypatch):
    """Staged is tracked and differs from the commit — `git add` does not make a run
    reproducible from HEAD."""
    b = _describe("M  src/estimator.py", "M  src/estimator.py", monkeypatch)
    assert b["dirty"] is True


def test_a_deleted_tracked_file_counts_as_modified(monkeypatch):
    b = _describe(" D src/estimator.py", " D src/estimator.py", monkeypatch)
    assert b["dirty"] is True


def test_a_wholly_clean_tree_says_nothing_extra(monkeypatch):
    line = engine_build.one_line(_describe("", "", monkeypatch))
    assert "untracked" not in line
    assert "not reproducible" not in line
    assert "abc1234" in line


def test_git_being_unavailable_is_still_not_a_claim_of_cleanliness(monkeypatch):
    """None, not False. "Clean" is a claim, and an engine that cannot ask git has not earned
    it — the one thing this stamp must never do is assert something it did not check."""
    monkeypatch.setattr(engine_build, "_git",
                        lambda *a: "abc1234" if a[0] == "rev-parse" and "--short" in a else None)
    b = engine_build.describe(refresh=True)
    assert b["dirty"] is None
    assert "could not tell" in engine_build.one_line(b)


def test_the_reproducibility_question_is_asked_of_tracked_files_only():
    """Stated against the source, because the whole defect was one missing flag and a mutant
    that drops it produces a stamp that is wrong only on machines with loose files — which is
    every real one, and never the test machine."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "engine_build.py"),
               encoding="utf-8").read()
    assert '"status", "--porcelain", "--untracked-files=no"' in src
