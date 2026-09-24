r"""A pull into a running runner changes every file and nothing the process is running.

17 September 2026. James pulls to 3629222, runs 11908-21, and the book comes back with the
old glue charge, the old joinery rates, no edging line and delivery still open. He says,
correctly, "it was ran after all the latest git pulls". Both halves are true: the checkout
IS current, and the run was NOT made by it. The estimating process was already up. It had
imported the engine hours earlier, and a pull changes files on a disk — not modules in a
running interpreter.

Nothing said so. Two full rounds of assessment went on reading a book that could not have
contained the fixes, looking for defects in code that was never executed.

`build_stamp` already held the answer and was only asked afterwards, from a header in the
Provenance tab: "Build: 9299fa5 +local edits" against a checkout at 3629222. That is the
module doing exactly what it was written for, one round trip too late.

SO THE RUN SAYS IT BEFORE IT COSTS ANYTHING, on two independent tells:

    SOURCE NEWER THAN THE PROCESS   a .py on the import path has an mtime later than the
                                    moment this process imported the engine. This is the
                                    pull-into-a-live-runner case exactly, and it needs no
                                    git at all.

    HEAD IS NOT WHAT WE STAMPED     `git rev-parse` now, against the commit this process
                                    recorded. The same fact from the other side, and the
                                    one a person can act on, because it names both.

Either is enough. It does not stop the run — the numbers may still be wanted — and it does
not guess; it states what is true and names the remedy, in the console before the first
figure and on the book that gets forwarded.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import build_stamp  # noqa: E402


# ── quiet when the process is running what is on the disk ────────────────────────────

def test_a_fresh_process_says_nothing():
    """The normal case, and it must stay silent. A warning that fires on every real run is
    read as noise on the day it is true — the same lesson `+local edits` already paid for
    when untracked files were branding every estimate."""
    assert build_stamp.source_changed_since_import() is None
    assert build_stamp.stale_process_warning() is None


def test_the_stamp_still_answers_normally():
    line = build_stamp.build_stamp_line()
    assert "src " in line and "modules" in line


# ── loud when the disk has moved on ──────────────────────────────────────────────────

def test_a_pull_after_import_is_detected(monkeypatch):
    """The 16:25 run in one assertion: the engine on disk is newer than the engine in
    memory."""
    monkeypatch.setattr(build_stamp, "_IMPORTED_AT", time.time() - 3600)
    said = build_stamp.source_changed_since_import()
    assert said, "a pull an hour after import went unnoticed"
    assert ".py" in said
    assert "AFTER this process imported" in said


def test_it_says_how_long_ago_not_merely_that_it_happened():
    """"Somebody is editing" and "you pulled after this process started" are different
    situations with different remedies, and only the WHEN separates them."""
    import re
    _saved = build_stamp._IMPORTED_AT
    try:
        # Anchored to the newest source file, not the clock: "now minus 30 minutes" fails
        # whenever nothing in src/ was edited in the last half hour.
        newest = max(p.stat().st_mtime for p in build_stamp._SRC.rglob("*.py")
                     if "__pycache__" not in p.parts)
        build_stamp._IMPORTED_AT = newest - 1800
        said = build_stamp.source_changed_since_import() or ""
    finally:
        build_stamp._IMPORTED_AT = _saved
    assert re.search(r"\d+ minute\(s\)", said), said


def test_the_warning_names_the_remedy(monkeypatch):
    monkeypatch.setattr(build_stamp, "_IMPORTED_AT", time.time() - 3600)
    warn = build_stamp.stale_process_warning() or ""
    assert "STALE ENGINE" in warn
    assert "Stop the runner and start it again" in warn
    assert "before reading a single number" in warn


def test_a_moved_head_is_caught_on_its_own(monkeypatch):
    """The second tell, independent of mtimes: a runner that imported at one commit while
    the checkout has since moved. It names BOTH commits, because "you are stale" without
    the two numbers is not something anyone can check."""
    monkeypatch.setattr(build_stamp, "build_stamp",
                        lambda *_a, **_k: {"commit": "9299fa5"})
    monkeypatch.setattr(build_stamp, "_git",
                        lambda *_a: "3629222" if _a[:1] == ("rev-parse",) else "")
    warn = build_stamp.stale_process_warning() or ""
    assert "9299fa5" in warn and "3629222" in warn


def test_a_matching_head_raises_nothing(monkeypatch):
    """The control on that half: same commit, no complaint."""
    monkeypatch.setattr(build_stamp, "build_stamp",
                        lambda *_a, **_k: {"commit": "3629222"})
    monkeypatch.setattr(build_stamp, "_git", lambda *_a: "3629222")
    assert build_stamp.stale_process_warning() is None


# ── and it reaches the two places a person is actually looking ───────────────────────

def test_the_console_says_it_above_the_run_not_inside_it(capsys):
    _saved = build_stamp._IMPORTED_AT
    try:
        build_stamp._IMPORTED_AT = time.time() - 3600
        build_stamp.print_build_stamp()
    finally:
        build_stamp._IMPORTED_AT = _saved
    out = capsys.readouterr().out
    assert "STALE ENGINE" in out
    assert "=" * 40 in out, "a line that scrolls past like any other is not a warning"


def test_a_healthy_run_prints_the_stamp_and_no_banner(capsys):
    build_stamp.print_build_stamp()
    out = capsys.readouterr().out
    assert "engine source:" in out
    assert "STALE ENGINE" not in out


def test_the_book_carries_it_too():
    """The console scrolls and the book gets forwarded. A stale book must say so on its
    own face — that is where this was eventually noticed, a day late."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimation_report.py"
           ).read_text(encoding="utf-8")
    assert "from build_stamp import stale_process_warning as _stale" in src
    assert '_build_txt += f"   |   ⚠ {_st}"' in src


def test_it_does_not_stop_the_run():
    """The numbers may still be wanted — for a comparison, or because the fix being missed
    is not the one this job needs. Refusing to run would make the warning something people
    switch off."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "build_stamp.py"
           ).read_text(encoding="utf-8")
    start = src.index("def stale_process_warning(")
    block = src[start:src.index("def print_build_stamp(")]
    for banned in ("raise ", "sys.exit", "SystemExit"):
        assert banned not in block, f"the warning {banned.strip()}s — it must only say so"
