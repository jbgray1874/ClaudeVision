"""Which build of the engine this is — asked once, answered the same way everywhere.

WHY THIS EXISTS. 11650-04's handed side panels inherited material on one hand and not the
other, and no thickness at all, from a loop that writes both through one resolver in one pass.
That is not a possible outcome of that loop, so the real question was whether the loop had run
on the build that produced the sheet. Nothing on the record, the console or the spreadsheet
answered it, and a round of diagnosis went into a question a commit hash settles.

A FIX THAT IS NOT DEPLOYED AND A FIX THAT DOES NOT WORK PRODUCE THE SAME SPREADSHEET. The only
way to tell them apart after the fact is for the run to say what it was.

STAMPED AT WRITE TIME, NOT READ TIME. A diagnostic that reports the build of the checkout it is
reading FROM answers a different question — the estimate may be days old and the checkout
pulled since. The engine stamps this into the document it writes, so the answer stays attached
to the run that produced it.

DIRTY IS PART OF THE ANSWER. A checkout with uncommitted changes is not the commit it names,
and a run from one cannot be reproduced from the hash. Reporting the hash without reporting
that is worse than reporting nothing.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CACHE: Optional[Dict[str, Any]] = None


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", _REPO_ROOT, *args],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def describe(refresh: bool = False) -> Dict[str, Any]:
    """The build, as a record that can be written into a document and read back.

    NEVER RAISES. A deployment with no git, no history or no .git directory still has to
    produce an estimate; it just cannot say which build produced it, and says THAT instead of
    a hash it made up.

    Cached, because this is stamped once per document and shelling out per part would be
    absurd. `refresh` exists for the tests, which need to see it recomputed.
    """
    global _CACHE
    if _CACHE is not None and not refresh:
        return dict(_CACHE)
    commit = _git("rev-parse", "--short", "HEAD")
    if not commit:
        _CACHE = {"commit": None, "branch": None, "dirty": None, "subject": None,
                  "known": False,
                  "note": "This engine cannot identify its own build: not a git checkout, or "
                          "git is unavailable. Any question about which fix was live in this "
                          "run has to be answered another way."}
    else:
        # TRACKED CHANGES ONLY, AND THAT IS THE WHOLE QUESTION THIS FIELD ANSWERS.
        #
        # `git status --porcelain` lists untracked files as `??`, so a scratch script, a PDF
        # dropped in the folder or a notes file made every run report "not reproducible from
        # the commit". A file git has never tracked cannot change the checkout this engine
        # imported — the code that ran is exactly the commit — so saying otherwise is a false
        # alarm, and a warning that cries wolf on a clean checkout is a warning nobody reads
        # on the day the tree really is modified.
        #
        # Untracked files are still COUNTED and reported, because "there is loose material in
        # the working tree" is worth knowing; it is simply not the same claim as "this run
        # cannot be reproduced from this commit".
        dirty_out = _git("status", "--porcelain", "--untracked-files=no")
        all_out = _git("status", "--porcelain")
        _untracked = len([ln for ln in (all_out or "").splitlines()
                          if ln.startswith("??")]) if all_out is not None else None
        _CACHE = {
            "commit": commit,
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            # None, not False, when git could not be asked -- "clean" is a claim.
            "dirty": (bool(dirty_out) if dirty_out is not None else None),
            "untracked_files": _untracked,
            "subject": _git("log", "-1", "--format=%s"),
            "known": True,
        }
    return dict(_CACHE)


def one_line(build: Optional[Dict[str, Any]] = None) -> str:
    """The same record as a line a person reads, so the console, the report and the
    diagnostic cannot describe one build three ways."""
    b = build if isinstance(build, dict) else describe()
    if not b.get("known"):
        return "engine build: UNKNOWN (this run could not identify itself)"
    state = ""
    if b.get("dirty"):
        state = " + UNCOMMITTED CHANGES (this run is not reproducible from the commit)"
    elif b.get("dirty") is None:
        state = " (could not tell whether the checkout was clean)"
    elif b.get("untracked_files"):
        # Worth saying, and deliberately not the same sentence. Nothing untracked reached the
        # import path, so the run IS reproducible from this commit.
        state = (f" (clean; {b['untracked_files']} untracked file(s) in the tree, none of "
                 f"which the engine imported)")
    return f"engine build: {b.get('commit')} on {b.get('branch') or '?'}{state}"
