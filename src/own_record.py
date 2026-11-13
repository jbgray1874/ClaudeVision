#!/usr/bin/env python3
"""Which record is THIS run's, among the files filed with it (reviewer, 11 Nov 2026).

"Each displayed price must match that run's ID, drawing, quantity, pinned record and workbook,
not merely the newest filename."

A run writes one workbook, <job>_<YYYYMMDD>_<HHMMSS>.xlsx, and pins its record beside it as
<job>_<YYYYMMDD>_<HHMMSS>_record.json (main.py, D-598d). The record is the run's because it is
named after the run's workbook, and the workbook is the run's because it is named for the run's
drawing and was written after the run began. Nothing here falls back to another job's file: when
the files filed with a run name several jobs and none is the run's drawing, the answer is "no
record", and the run shows no price rather than somebody else's.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_BOOK = re.compile(r"^(?P<job>.+)_(?P<d>\d{8})_(?P<t>\d{6})\.xlsx$", re.IGNORECASE)
_RECORD = re.compile(r"^(?P<job>.+)_(?P<d>\d{8})_(?P<t>\d{6})_record\.json$", re.IGNORECASE)


def _key(text: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def _stamp(d: str, t: str) -> float:
    try:
        return datetime.strptime(d + t, "%Y%m%d%H%M%S").timestamp()
    except ValueError:
        return 0.0


def books(deliverables: List[Dict[str, Any]]) -> List[Tuple[str, float, str]]:
    """(job, written, file name) for every run workbook among the files."""
    out = []
    for item in deliverables or []:
        name = str((item or {}).get("name") or "")
        m = _BOOK.match(name)
        if m and not name.startswith("~$"):
            out.append((m.group("job"), _stamp(m.group("d"), m.group("t")), name))
    return out


def own_book(deliverables: List[Dict[str, Any]], drawing_number: str = "",
             started_at: float = 0.0) -> Tuple[Optional[str], str]:
    """(workbook file name or None, why). The run's workbook: named for its drawing where the
    drawing is known, written after the run began, the latest of those."""
    found = books(deliverables)
    if not found:
        return None, "no run workbook among the files"
    if started_at:
        # a minute's grace: the name's stamp is local wall time to the second
        fresh = [b for b in found if b[1] == 0.0 or b[1] + 60.0 >= started_at]
        if not fresh:
            return None, "every workbook among the files was written before this run began"
        found = fresh
    jobs = {_key(b[0]) for b in found}
    want = _key(drawing_number)
    if want and want in jobs:
        found = [b for b in found if _key(b[0]) == want]
    elif len(jobs) > 1:
        return None, ("the files name several jobs (" + ", ".join(sorted({b[0] for b in found}))
                      + ") and none is this run's drawing " + (drawing_number or "(not given)"))
    elif want:
        # one job among the files, named differently from the drawing asked for: a page job
        # whose workbook is named from the job number. It is the only run here.
        pass
    best = max(found, key=lambda b: b[1])
    return best[2], "named for the run's drawing" if want and _key(best[0]) == want \
        else "the only job among the files"


def own_record(deliverables: List[Dict[str, Any]], drawing_number: str = "",
               started_at: float = 0.0) -> Tuple[Optional[Dict[str, Any]], str]:
    """(the deliverable that is this run's pinned record, or None; why)."""
    book, why = own_book(deliverables, drawing_number, started_at)
    if not book:
        return None, why
    wanted = (book[:-len(".xlsx")] + "_record.json").lower()
    for item in deliverables or []:
        if str((item or {}).get("name") or "").lower() == wanted:
            return item, f"{item.get('name')} beside {book} ({why})"
    return None, f"{book} has no pinned record among the files"


def other_jobs_files(deliverables: List[Dict[str, Any]], drawing_number: str = "",
                     started_at: float = 0.0) -> List[str]:
    """File names among these that carry ANOTHER job's workbook name: a previous run's files
    written late into the same checkout. Empty unless the run's own workbook is identified."""
    book, _why = own_book(deliverables, drawing_number, started_at)
    if not book:
        return []
    mine = _key(_BOOK.match(book).group("job"))
    others = {b[0] for b in books(deliverables) if _key(b[0]) != mine}
    out = []
    for item in deliverables or []:
        name = str((item or {}).get("name") or "")
        if any(name.upper().startswith(o.upper() + "_") or name.upper().startswith(o.upper() + ".")
               for o in others):
            out.append(name)
    return sorted(out)


# How long after its workbook a run's unstamped files (the report, the quote) are still its own.
_BESIDE_WINDOW_S = 15 * 60.0


def beside_the_book(book_path: Any, started_at: float = 0.0) -> List[Path]:
    """THE FILES WRITTEN BESIDE A RUN'S WORKBOOK ARE THE RUN'S, WHEREVER THE WORKBOOK IS
    (12 Nov 2026). The second runner's engine wrote its first files under its own checkout and
    its workbook, record, covering note, walkthrough and report into the main checkout's
    estimates folder. The collector looked only in its own tree and took the workbook because
    the engine declared it: three finished estimates went out as a list of files headed "not
    reported/unit", with their notes and records sitting on disk beside their workbooks.

    Named for the workbook, "<job>_<date>_<time>_...", they are this run's without question.
    Named for the job only ("<job>_report.html", "<job>_quote_PORTAL.html"), they are this
    run's when written after the run began and within a quarter hour of its workbook: a later
    run of the same job overwrites them, and an earlier run's are older than this one's start.
    Never another run's stamped files, and never another job's."""
    book = Path(str(book_path))
    m = _BOOK.match(book.name)
    if not m:
        return []
    stem, job = book.name[:-len(".xlsx")], m.group("job")
    written = _stamp(m.group("d"), m.group("t"))
    try:
        entries = sorted(p for p in book.parent.iterdir() if p.is_file())
    except OSError:
        return []
    out: List[Path] = []
    for p in entries:
        name = p.name
        if p == book or name.startswith("~$"):
            continue
        if name.lower().startswith(stem.lower() + "_"):
            out.append(p)
            continue
        if not (name.lower().startswith(job.lower() + "_") or name.lower().startswith(job.lower() + ".")):
            continue
        rest = name[len(job):]
        if re.match(r"^_\d{8}_\d{6}(?:[_.]|$)", rest):
            continue                                  # another run of this job
        if re.match(r"^[-A-Za-z0-9]", rest[1:2] or "") and rest[:1] == "-":
            continue                                  # "<job>-02..." is another drawing
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if started_at and mtime + 1.0 < started_at:
            continue
        if written and not (written - 60.0 <= mtime <= written + _BESIDE_WINDOW_S):
            continue
        out.append(p)
    return out
