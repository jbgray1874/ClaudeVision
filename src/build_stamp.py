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

# WHEN THIS PROCESS READ THE ENGINE OFF THE DISK.
#
# One clock read at import, which is when the modules around it are being imported too. It
# is the only fact that can answer the question the stamp could not: not "is the checkout
# current" — git answers that — but "is the code this process is RUNNING the code that is
# on the disk now". A long-lived runner imports once and then serves runs for hours; a pull
# in the middle changes every file and none of the imported modules, and nothing anywhere
# says so. The workbook's own stamp told us afterwards, which is better than nothing and
# still a round trip too late.
_IMPORTED_AT = __import__("time").time()


def source_changed_since_import() -> Optional[str]:
    """A sentence naming the newest source file edited since this process imported, or None.

    THE STALE-RUNNER CASE, WHICH THE COMMIT ALONE CANNOT SEE. `git rev-parse` reports the
    checkout as it is NOW; the modules in memory are as they were at import. Pull while a
    runner is up and the two disagree silently — every fix in the pull is on the disk, none
    of it is in the process, and the run produces the old numbers with a straight face.

    Compared on MTIME rather than on the digest, because the digest says only THAT the
    source differs and this says WHEN it started differing, which is what distinguishes
    "somebody is editing" from "you pulled after this process started". One stat per module
    at the start of a run.
    """
    newest, newest_at = None, 0.0
    for p in _SRC.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            _m = p.stat().st_mtime
        except OSError:
            continue
        if _m > newest_at:
            newest, newest_at = p, _m
    # A second of slack: a file written in the same moment the process started is this
    # process's own doing, not somebody else's pull.
    if newest is None or newest_at <= _IMPORTED_AT + 1.0:
        return None
    return (f"{newest.name} (and possibly others) changed on disk "
            f"{(newest_at - _IMPORTED_AT) / 60.0:.0f} minute(s) AFTER this process imported "
            f"the engine")


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


def behind_origin_warning() -> Optional[str]:
    """This checkout is costing jobs with code that is not the branch it was told to use.

    THE THIRD THING A STALE RUN CAN BE, AND THE ONLY ONE NOTHING COULD SEE. The two tells
    above both compare the PROCESS against the CHECKOUT, so they are silent when the two
    agree perfectly — and they agree perfectly on a runner that simply never pulled.
    401912-02 ran three times against `2314342 +local edits` while the branch it was
    supposed to be on had moved four commits ahead, including the fix for the very crash
    that was ending each run. The banner said "+local edits" every time, which is true and
    is not the problem, and said nothing at all about the four commits.

    Read from the git tree only — no fetch, no network, no delay on a runner that may have
    neither. That means it reports what the last fetch knew, so it can UNDERSTATE how far
    behind a checkout is and can never overstate it: a warning that appears is always real.
    A checkout that has never fetched says nothing, which is the honest answer.
    """
    try:
        _upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if not _upstream:
            return None
        _behind = _git("rev-list", "--count", "HEAD..@{u}")
        _n = int(_behind) if _behind and _behind.isdigit() else 0
        if _n <= 0:
            return None
        _subject = _git("log", "-1", "--format=%h %s", "@{u}") or _upstream
        return (f"BEHIND THE BRANCH — this checkout is {_n} commit(s) behind {_upstream}, "
                f"whose tip is {_subject}. Those commits are not in this run and anything "
                f"they fixed is still broken here. `git pull` and restart the runner. "
                f"(Read from the last fetch, so the real gap may be larger.)")
    except Exception:                                                # noqa: BLE001
        return None


def stale_process_warning() -> Optional[str]:
    """The run is about to be costed by code older than the checkout it was told to use.

    Two independent tells, either of which is enough:

      the source changed on disk AFTER this process imported it — a pull into a runner that
      was already up, which is the case that cost 11908-21 two rounds of assessment;

      git HEAD is not the commit this process stamped — the same thing seen from the other
      side, and the one a reader can act on, because it names both commits.

    It does not guess and it does not stop the run: it says what is true, in the one place
    somebody is certainly looking, before any number is produced. The remedy is one line and
    it is in the message, because a warning that describes a problem without naming its fix
    gets read as noise.
    """
    bits = []
    try:
        _changed = source_changed_since_import()
    except Exception:                                                # noqa: BLE001
        _changed = None
    if _changed:
        bits.append(_changed)
    try:
        _stamped = (build_stamp() or {}).get("commit") or ""
        _now = _git("rev-parse", "--short=7", "HEAD")
        if _stamped and _now and _stamped != _now:
            bits.append(f"this process stamped {_stamped}; the checkout is now {_now}")
    except Exception:                                                # noqa: BLE001
        pass
    if not bits:
        return None
    return ("STALE ENGINE — this run is being costed by code older than the checkout. "
            + "; ".join(bits)
            + ". Nothing in the pull is in this process. Stop the runner and start it "
              "again, then check this line says the commit you expect before reading a "
              "single number.")


def print_build_stamp() -> None:
    try:
        print(f"   [build] engine source: {build_stamp_line()}", flush=True)
    except Exception:                                                # noqa: BLE001
        pass
    # WHICH RATE CARD PRICED THIS JOB, BESIDE WHICH ENGINE COSTED IT. The department rates
    # decide every labour line on the sheet, and until now a run that read them from the live
    # template and a run that fell back to the defaults in config printed exactly the same
    # thing — nothing. Two machines could produce different money from the same commit with
    # no way to tell from either book which had the newer card. It goes here because this is
    # the banner people already read when a number looks wrong.
    try:
        import config as _cfg_bs
        for _note in (getattr(_cfg_bs, "RATE_CARD_NOTES", None) or []):
            print(f"   [rates] {_note}", flush=True)
    except Exception:                                                # noqa: BLE001
        pass
    try:
        _warn = stale_process_warning()
    except Exception:                                                # noqa: BLE001
        _warn = None
    if not _warn:
        # Only where the process and the checkout agree — otherwise the louder fault is the
        # one to act on first, and two banners compete for the same attention.
        try:
            _warn = behind_origin_warning()
        except Exception:                                            # noqa: BLE001
            _warn = None
    if _warn:
        # Loud, and above the run rather than inside it. A stale engine invalidates every
        # number that follows, so it is not a footnote.
        print("", flush=True)
        print("   " + "=" * 76, flush=True)
        print(f"   [build] {_warn}", flush=True)
        print("   " + "=" * 76, flush=True)
        print("", flush=True)
