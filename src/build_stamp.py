"""Which build made this book.

FOUR TIMES NOW A FIX HAS BEEN WRITTEN, TESTED, PUSHED, AND THEN ARGUED ABOUT.

The argument is always the same shape. A sheet comes back with the old number on it. One
side says the fix cannot be running; the other says it is. Neither can prove anything,
because a workbook records what it costed and says nothing whatever about the source that
costed it. So the next hour goes on inference — reading flag text that turned out never to
reach the report, comparing byte-identical books, reasoning backwards from a rate — and the
inference is wrong about as often as it is right.

7332-01's 19:46 book is the case that paid for this module. Two ops changed in commits that
are ancestors of the tip the runner was told to use, and the book carries neither. That is
either a stale checkout or a defect, and those need opposite responses: one is `git pull`,
the other is a day's work. Nothing in the deliverable could tell them apart.

So the run states its own identity, and it is on the sheet:

    Build: 4ead09a · src 9f3a1c2e40b1

The commit is the useful half when there is a git checkout to ask. The DIGEST is the
load-bearing half — a hash over the bytes of every module actually on the import path,
which is true whether or not git is installed, whether or not the runner copied the tree
by hand, and whether or not somebody edited a file without committing it. A digest that
differs from the one this session computed is a different engine, full stop, and no further
argument is needed.

Deliberately not a version number. Nobody bumps a version number reliably and a stale one
is worse than none: it asserts something false with the same confidence as the truth.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

_SRC = Path(__file__).resolve().parent
_CACHE: Optional[Dict[str, Any]] = None


def _git(*args: str) -> str:
    """One git question, or "" — never an exception and never a hang.

    The runner may have no git, no .git directory (a copied tree), or a git that prompts.
    Any of those must cost the run nothing at all: the digest below does not need git and
    is the answer that actually settles arguments."""
    try:
        out = subprocess.run(("git", "-C", str(_SRC.parent)) + args,
                             capture_output=True, text=True, timeout=5,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        return (out.stdout or "").strip() if out.returncode == 0 else ""
    except Exception:                                                # noqa: BLE001
        return ""


def _source_digest() -> Dict[str, Any]:
    """A hash over the bytes of the modules on the import path.

    Path AND content, sorted, so a file added or removed moves the digest as surely as a
    file edited does — a fix that is missing because its module never arrived is exactly
    the case this has to catch.

    __pycache__ is skipped: it is derived, it is not what Python reads when a .py is newer,
    and its presence or absence is not a difference in the engine.
    """
    h = hashlib.sha256()
    n = 0
    for p in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            data = p.read_bytes()
        except Exception:                                            # noqa: BLE001
            continue
        h.update(p.relative_to(_SRC).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(data)
        n += 1
    return {"source_digest": h.hexdigest()[:12], "module_count": n}


def build_stamp(refresh: bool = False) -> Dict[str, Any]:
    """The identity of the source this process is running, computed once."""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    stamp: Dict[str, Any] = {"commit": "", "commit_date": "", "dirty": None,
                             "untracked_files": 0, "source_digest": "", "module_count": 0}
    stamp.update(_source_digest())
    commit = _git("rev-parse", "--short=7", "HEAD")
    if commit:
        stamp["commit"] = commit
        stamp["commit_date"] = _git("log", "-1", "--format=%cI")
        # A tree with uncommitted edits is NOT the commit it claims to be, and saying so
        # is the difference between "your fix is in" and "your fix is in, plus whatever
        # else is sitting in the working tree".
        #
        # TRACKED CHANGES ONLY — the same lesson engine_build.py already paid for, missed
        # here. Plain `git status --porcelain` lists untracked files as `??`, so a drawing
        # pack, the workbook a run just wrote or an answers file placed beside the drawings
        # branded every estimate "+local edits" — a claim about the ENGINE, made from files
        # the engine never imported. A stamp that cries wolf on every real machine goes
        # unread on the day the tree genuinely is modified.
        #
        # Narrowing this loses nothing: an untracked .py dropped into src/ cannot hide,
        # because the SOURCE DIGEST above hashes every module on the import path whether
        # git has ever heard of it or not. Loose files are still counted and reported —
        # as loose files, which is what they are.
        stamp["dirty"] = bool(_git("status", "--porcelain", "--untracked-files=no"))
        stamp["untracked_files"] = len([ln for ln in _git("status", "--porcelain").splitlines()
                                        if ln.startswith("??")])
    _CACHE = stamp
    return stamp


def build_stamp_line() -> str:
    """One line, for a log banner or a header cell.

    The digest is always present; the commit only where a git checkout could answer. Read
    it as an identity to COMPARE, not as a number to interpret."""
    s = build_stamp()
    head = f"{s['commit']}{' +local edits' if s.get('dirty') else ''}" if s.get("commit") \
        else "no git checkout"
    line = f"{head} · src {s.get('source_digest') or '?'} ({s.get('module_count', 0)} modules)"
    if s.get("commit") and not s.get("dirty") and s.get("untracked_files"):
        # Worth saying, and deliberately a different sentence from "+local edits": loose
        # material in the folder is not a modified engine.
        line += f" · {s['untracked_files']} loose file(s) in the tree, none of them the engine"
    return line


def print_build_stamp() -> None:
    try:
        print(f"   [build] engine source: {build_stamp_line()}", flush=True)
    except Exception:                                                # noqa: BLE001
        pass
