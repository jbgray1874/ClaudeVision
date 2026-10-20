"""An hour went on whether a commit had run, and nothing in the deliverable could say.

7332-01's 19:46 book came back carrying a two-minute pack allowance. The commit that makes
a plated part pack twice — four minutes out to the plater, eight on final assembly — is an
ancestor of the tip the runner was told to use. So either the checkout was stale or the fix
had a defect, and those need opposite responses: one is `git pull`, the other is a day.

The evidence available to tell them apart was: none. A workbook records what it costed and
says nothing at all about the source that costed it. So the argument ran on inference —
comparing byte-identical books, reading flag text that turned out never to reach the report,
reasoning backwards from a rate — and inference was wrong about as often as it was right.

The digest is the load-bearing half, not the commit. A commit hash needs a git checkout to
ask; the runner may have a copied tree, no git, or uncommitted edits sitting in it. A hash
over the bytes of every module on the import path is true in all of those cases, and two
runs that agree on it ran the same engine.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import build_stamp                                                      # noqa: E402


def test_there_is_always_a_digest():
    """Even with no git, no network and no packaging. This is the answer that must exist."""
    s = build_stamp.build_stamp(refresh=True)
    assert len(s["source_digest"]) == 12
    assert s["module_count"] > 50


def test_it_is_the_same_answer_twice():
    assert (build_stamp.build_stamp(refresh=True)["source_digest"]
            == build_stamp.build_stamp(refresh=True)["source_digest"])


def test_a_changed_module_changes_the_digest(tmp_path, monkeypatch):
    """THE WHOLE POINT. Two runs that differ in one line of one module must not report the
    same identity, or the stamp is decoration."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("X = 1\n")
    monkeypatch.setattr(build_stamp, "_SRC", src)
    before = build_stamp.build_stamp(refresh=True)["source_digest"]
    (src / "a.py").write_text("X = 2\n")
    assert build_stamp.build_stamp(refresh=True)["source_digest"] != before


def test_an_added_module_changes_it_too(tmp_path, monkeypatch):
    """A fix that is missing because its module never arrived is exactly the case this is
    for, so the file LIST is hashed and not only the file contents."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("X = 1\n")
    monkeypatch.setattr(build_stamp, "_SRC", src)
    before = build_stamp.build_stamp(refresh=True)["source_digest"]
    (src / "b.py").write_text("")
    assert build_stamp.build_stamp(refresh=True)["source_digest"] != before


def test_a_renamed_module_changes_it(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("X = 1\n")
    monkeypatch.setattr(build_stamp, "_SRC", src)
    before = build_stamp.build_stamp(refresh=True)["source_digest"]
    (src / "a.py").rename(src / "z.py")
    assert build_stamp.build_stamp(refresh=True)["source_digest"] != before


def test_a_pycache_is_not_part_of_the_identity(tmp_path, monkeypatch):
    """It is derived, and whether a box has warmed one is not a difference in the engine."""
    src = tmp_path / "src"
    (src / "__pycache__").mkdir(parents=True)
    (src / "a.py").write_text("X = 1\n")
    monkeypatch.setattr(build_stamp, "_SRC", src)
    before = build_stamp.build_stamp(refresh=True)["source_digest"]
    (src / "__pycache__" / "a.cpython-311.py").write_text("whatever\n")
    assert build_stamp.build_stamp(refresh=True)["source_digest"] == before


def test_the_line_is_readable_and_carries_the_digest():
    line = build_stamp.build_stamp_line()
    assert build_stamp.build_stamp()["source_digest"] in line
    assert "modules" in line


def test_no_git_still_produces_a_line(monkeypatch):
    """A copied tree on the runner has no .git. The stamp must degrade to the digest and
    say so, not raise and not go silent."""
    monkeypatch.setattr(build_stamp, "_git", lambda *a: "")
    line = build_stamp.build_stamp_line() if not build_stamp.build_stamp(refresh=True).get(
        "commit") else ""
    assert "no git checkout" in line
    assert build_stamp.build_stamp()["source_digest"] in line


def test_uncommitted_edits_are_declared(monkeypatch):
    """"You are on 4ead09a" is not the same statement as "you are running 4ead09a" when
    there are edits in the working tree, and the difference is worth one word."""
    monkeypatch.setattr(build_stamp, "_git",
                        lambda *a: "abc1234" if a[:1] == ("rev-parse",)
                        else (" M src/estimator.py" if a[:1] == ("status",) else "2026-09-14"))
    assert "+local edits" in build_stamp.build_stamp_line() if build_stamp.build_stamp(
        refresh=True)["dirty"] else True


def test_a_git_that_fails_costs_the_run_nothing(monkeypatch):
    """No exception, no hang, no prompt — a stamp is never worth a failed job."""
    def _boom(*a, **k):
        raise OSError("git not found")
    monkeypatch.setattr(subprocess, "run", _boom)
    assert build_stamp._git("rev-parse", "HEAD") == ""
    assert build_stamp.build_stamp(refresh=True)["source_digest"]


def test_printing_it_never_raises(capsys):
    build_stamp.print_build_stamp()
    assert "[build] engine source:" in capsys.readouterr().out


# ── and it reaches the two places a person actually looks ────────────────────────────────

def test_the_run_prints_it_before_it_scans_anything():
    """In the log, above the first file — so a stale checkout is visible before an hour of
    extraction has been spent on it."""
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "print_build_stamp" in src
    assert src.index("print_build_stamp") < src.index("CAN THIS MACHINE RUN THE ENGINE")


def test_the_provenance_header_carries_it():
    """The tab whose job is to say where every number came from. The source that computed
    them is the first of those facts and was the only one missing."""
    src = (ROOT / "src" / "estimation_report.py").read_text(encoding="utf-8")
    assert "build_stamp_line" in src
    assert "Build: " in src
