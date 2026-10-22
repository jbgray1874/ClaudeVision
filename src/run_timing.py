"""Where a run's minutes actually go.

A 12552 estimate takes twenty to forty minutes and nobody has ever measured it. What we
had instead was the runner's "no output for 133s" notices — the absence of printing, read
as if it were a phase — and from those we inferred a PDF scan of six minutes and an Excel
stretch of five, which together do not account for half the wall clock. Optimising on that
basis means guessing which half to work on.

The phase boundaries were already there. file_scan brackets every major step with
`_debug("start …")` / `_debug("done …")`, and those calls do nothing unless the run is in
debug mode. So this records the same boundaries unconditionally — two dictionary writes
per phase, no measurable cost — and prints a table at the end of the job.

DELIBERATELY NOT A PROFILER. It answers one question: which phase should somebody work on
next. A phase is named by the string file_scan already passes; nothing here knows what the
phases are, so a new one starts being timed the moment it is bracketed like the rest.

UNCLOSED PHASES ARE REPORTED, NOT DROPPED. A step that started and never finished is the
most interesting row in the table — that is what a hang looks like — so it is shown with
the time it had consumed when the run ended rather than omitted for being incomplete.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

# stage name -> when it started. Ordered by insertion, which is the order the run ran them.
_open: Dict[str, float] = {}
# (stage, seconds) in completion order.
_done: List[Tuple[str, float]] = []
# (began, finished) for every closed phase, so nested brackets can be merged.
_spans: List[Tuple[float, float]] = []
_run_started: Optional[float] = None


def _union_seconds(spans: List[Tuple[float, float]]) -> float:
    """Total seconds covered by at least one span — overlapping spans count once."""
    total = 0.0
    cur_start = cur_end = None
    for began, finished in sorted(spans):
        if cur_end is None or began > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = began, finished
        elif finished > cur_end:
            cur_end = finished
    if cur_end is not None:
        total += cur_end - cur_start
    return total


def reset() -> None:
    """Begin a fresh run. Safe to call more than once; a job-per-process never needs it."""
    global _run_started
    _open.clear()
    _done.clear()
    _spans.clear()
    _run_started = time.time()


def mark(stage: str) -> None:
    """Record one boundary, given file_scan's own wording ("start X" / "done X").

    Anything that is neither start nor done is ignored rather than guessed at: file_scan
    also passes free-text notes through _debug ("dual-path bom_rows applied: 41 rows"), and
    treating those as phases would fill the table with rows that never close.
    """
    global _run_started
    if _run_started is None:
        _run_started = time.time()
    text = str(stage or "").strip()
    now = time.time()
    if text.startswith("start "):
        _open.setdefault(text[6:].strip(), now)
    elif text.startswith("done "):
        name = text[5:].strip()
        began = _open.pop(name, None)
        if began is not None:
            _done.append((name, now - began))
            _spans.append((began, now))


def report() -> str:
    """The table, slowest first, or "" when nothing was recorded.

    Slowest first because the question is always "what do I fix", and a table in run order
    makes the reader do the sorting. The total is wall clock for the whole job, so the gap
    between it and the sum of the phases is itself informative: it is the work that happens
    outside any bracketed step, and if that gap is the largest number here then the next
    thing to do is bracket more, not optimise anything.
    """
    if not _done and not _open:
        return ""
    rows = sorted(_done, key=lambda kv: -kv[1])
    width = max([len(n) for n, _ in rows] + [len(n) for n in _open] + [12])
    lines = ["   [timing] where this run spent its time:"]
    for name, secs in rows:
        lines.append(f"   [timing]   {name:<{width}}  {secs:8.1f}s")
    now = time.time()
    for name, began in _open.items():
        lines.append(f"   [timing]   {name:<{width}}  {now - began:8.1f}s  "
                     f"STARTED AND NEVER FINISHED")
    if _run_started is not None:
        total = now - _run_started
        # MEASURED IS THE UNION OF THE BRACKETS, NOT THEIR SUM. A coarse phase that
        # contains a finer one ("pre_estimate_passes" around "solidworks_extract") would
        # otherwise count the same seconds twice and push "unmeasured" below zero, so
        # nested brackets were impossible and 2,557 s of 12567-01's 4,351 s stayed
        # outside any phase (D-279). Spans are merged before they are summed.
        measured = _union_seconds(_spans)
        lines.append(f"   [timing]   {'TOTAL (wall clock)':<{width}}  {total:8.1f}s")
        lines.append(f"   [timing]   {'unmeasured':<{width}}  {total - measured:8.1f}s  "
                     f"(outside any timed phase)")
    return "\n".join(lines)
