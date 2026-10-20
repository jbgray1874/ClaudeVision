r"""A run that is behind the branch says so, and one bad part does not bin the job.

401912-02, three runs in twenty minutes, all of them ending the same way:

    [build] engine source: 2314342 +local edits
    ...
    KeyError: 'geometry_rollup'
    The engine exited with code 1. Nothing was filed.

TWO SEPARATE FAILURES OF THE ENGINE TO LOOK AFTER ITSELF, and between them they cost an
afternoon.

**It could not tell it was behind.** `main-2026` had moved FOUR commits ahead — one of them
the fix for the very crash ending each run — and the banner said "+local edits" every time,
which is true and is not the problem. The two existing stale checks both compare the PROCESS
against the CHECKOUT, so they are silent when the two agree perfectly, and they agree
perfectly on a runner that simply never pulled. The one question nobody was asking is the
one with the answer in it.

**And one part took the whole job down.** A `KeyError` costing the magnetic tape ended the
process, and the DXF augment, the SolidWorks extract, the SQL price lookups and every other
part went in the bin with it. Forty-nine seconds of work and an estimator holding nothing —
not even the parts that costed perfectly well. The trade is not "hide the error": it is
which failure the estimator is handed. A job with one line marked NOT COSTED can be read,
priced by hand and sent. No job at all cannot be anything.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import build_stamp  # noqa: E402
import estimator  # noqa: E402


# ── behind the branch ────────────────────────────────────────────────────────────────

def _run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo_behind_by(tmp_path, monkeypatch):
    """A real checkout with a real upstream that is really ahead."""
    def _make(commits: int):
        origin = tmp_path / "origin"
        origin.mkdir()
        _run("git", "init", "-q", "-b", "main", cwd=origin)
        (origin / "f.txt").write_text("0")
        _run("git", "add", "-A", cwd=origin)
        _run("git", "commit", "-qm", "base", cwd=origin)
        clone = tmp_path / "clone"
        _run("git", "clone", "-q", str(origin), str(clone), cwd=tmp_path)
        for n in range(commits):
            (origin / "f.txt").write_text(str(n + 1))
            _run("git", "add", "-A", cwd=origin)
            _run("git", "commit", "-qm", f"ahead {n + 1}", cwd=origin)
        _run("git", "fetch", "-q", "origin", cwd=clone)
        monkeypatch.setattr(build_stamp, "_git",
                            lambda *a: _git_in(clone, *a))
        return clone
    return _make


def _git_in(cwd, *args):
    out = subprocess.run(("git", "-C", str(cwd)) + args, capture_output=True, text=True,
                         env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    return (out.stdout or "").strip() if out.returncode == 0 else ""


def test_a_checkout_four_commits_behind_says_how_many(repo_behind_by):
    """The 401912-02 case exactly: four commits on the branch, none of them in the run."""
    repo_behind_by(4)
    said = build_stamp.behind_origin_warning()
    assert said and "4 commit(s) behind" in said


def test_it_names_the_branch_and_the_tip_it_is_missing(repo_behind_by):
    """'Behind' with no name is not actionable. The remedy needs to be in the message."""
    repo_behind_by(2)
    said = build_stamp.behind_origin_warning()
    assert "origin/main" in said
    assert "ahead 2" in said, "the tip commit's subject is what tells you what you are missing"
    assert "git pull" in said and "restart" in said


def test_an_up_to_date_checkout_is_told_nothing(repo_behind_by):
    """A banner that fires on every run is a banner nobody reads — the lesson three other
    flags in this engine have already paid for."""
    repo_behind_by(0)
    assert build_stamp.behind_origin_warning() is None


def test_a_checkout_with_no_upstream_says_nothing(tmp_path, monkeypatch):
    """A copied tree, or a branch never pushed. Silence is the honest answer, not a guess."""
    solo = tmp_path / "solo"
    solo.mkdir()
    _run("git", "init", "-q", "-b", "main", cwd=solo)
    (solo / "f.txt").write_text("0")
    _run("git", "add", "-A", cwd=solo)
    _run("git", "commit", "-qm", "only", cwd=solo)
    monkeypatch.setattr(build_stamp, "_git", lambda *a: _git_in(solo, *a))
    assert build_stamp.behind_origin_warning() is None


def test_no_git_at_all_costs_the_run_nothing(monkeypatch):
    monkeypatch.setattr(build_stamp, "_git", lambda *a: "")
    assert build_stamp.behind_origin_warning() is None


def test_the_louder_fault_wins_the_banner(monkeypatch, capsys):
    """A process out of step with its own checkout is worse than a checkout out of step with
    its branch, and two banners competing for one reader's attention gets both ignored."""
    monkeypatch.setattr(build_stamp, "stale_process_warning", lambda: "STALE ENGINE — x")
    monkeypatch.setattr(build_stamp, "behind_origin_warning",
                        lambda: pytest.fail("asked when the louder fault was already known"))
    build_stamp.print_build_stamp()
    assert "STALE ENGINE" in capsys.readouterr().out


def test_the_behind_warning_reaches_the_banner(monkeypatch, capsys):
    monkeypatch.setattr(build_stamp, "stale_process_warning", lambda: None)
    monkeypatch.setattr(build_stamp, "behind_origin_warning", lambda: "BEHIND THE BRANCH — x")
    build_stamp.print_build_stamp()
    assert "BEHIND THE BRANCH" in capsys.readouterr().out


# ── one bad part does not bin the job ────────────────────────────────────────────────

_GOOD = {"part_number": "401912-02-01M", "normalized_material": "MILD_STEEL",
         "normalized_thickness_mm": 2.0, "blank_length_mm": 460.0,
         "blank_width_mm": 356.61, "quantity": 1, "geometry_source": "dxf_flat_pattern",
         "geometry_rollup": {"confidence": {"geometry_reliability": 0.9}}}


_TAPE = dict(_GOOD, part_number="MAGNET45",
             description="25.4mm ADHESIVE MAGNETIC TAPE, L: 450mm")


@pytest.fixture
def tape_throws(monkeypatch):
    """The real failure: `estimate_part` raised part-way through costing the tape. Raised
    HERE rather than from a contrived dict, because a dict that throws on `.get` also breaks
    the estimable-parts filter and would be testing a different line."""
    _real = estimator.estimate_part

    def _maybe(part, *a, **k):
        if part.get("part_number") == "MAGNET45":
            raise KeyError("geometry_rollup")
        return _real(part, *a, **k)
    monkeypatch.setattr(estimator, "estimate_part", _maybe)


def test_the_job_still_costs_when_one_part_throws(tape_throws, capsys):
    """Forty-nine seconds of DXF, model extract and SQL lookups must not be thrown away
    because one purchased line has no geometry."""
    summary = {}
    out = estimator.estimate_document([dict(_GOOD), dict(_TAPE)], summary=summary)
    assert out, "the job produced nothing"
    costed = [p.get("part_number") for p in out.get("part_estimates", [])]
    assert "401912-02-01M" in costed


def test_the_part_that_failed_is_impossible_to_miss(tape_throws):
    """A line dropped from the costed record is a hole in the total. It goes where an
    estimator looks before sending, not only into a log line that scrolls away."""
    summary = {}
    estimator.estimate_document([dict(_GOOD), dict(_TAPE)], summary=summary)
    said = " ".join(str(f) for f in summary.get("review_flags", []))
    assert "NOT COSTED" in said
    assert "MAGNET45" in said
    assert "MISSING FROM THE TOTAL" in said


def test_the_failure_is_kept_in_full_for_diagnosis(tape_throws):
    summary = {}
    estimator.estimate_document([dict(_GOOD), dict(_TAPE)], summary=summary)
    failed = summary.get("parts_that_failed_to_cost") or []
    assert len(failed) == 1
    assert failed[0]["part_number"] == "MAGNET45"
    assert "KeyError" in failed[0]["error"]
    assert "Traceback" in failed[0]["traceback"]


def test_nothing_half_costed_reaches_the_record(tape_throws):
    """A partially built part estimate is how a £0 gets into a total. The line is dropped
    whole, and its absence is announced — it is never patched up and quietly included."""
    summary = {}
    out = estimator.estimate_document([dict(_GOOD), dict(_TAPE)], summary=summary)
    assert all(p.get("part_number") != "MAGNET45"
               for p in out.get("part_estimates", []))


def test_an_ordinary_job_is_told_nothing_about_failures():
    """The control. No failure, no flag, no key."""
    summary = {}
    estimator.estimate_document([dict(_GOOD)], summary=summary)
    assert "parts_that_failed_to_cost" not in summary
    assert not any("NOT COSTED" in str(f) for f in summary.get("review_flags", []))
