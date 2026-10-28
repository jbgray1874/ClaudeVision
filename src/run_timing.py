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

# ── A PARTNER RUN ONLY (D-529) ───────────────────────────────────────────────────────────
#
# Muhammad's endpoint (POST /api/estimate/llm) needs to show where a run is and, once it has
# finished, where its time went down to the model call — the estimating portal does not, and
# its runs must not change. So all of this is off unless main.py finds the partner marker the
# endpoint files beside the drawings (PARTNER_API_RUN.json): with it off, stage() and count()
# do nothing and print nothing, and the [timing] table is exactly what it was.
_detail = False
_last_stage = ""

# ── WHERE THE TIME WENT, KEPT (D-553) ───────────────────────────────────────────────────
# The table was printed into the run log and nowhere else, so "which phase do we work on
# next" could be answered one job at a time, by reading logs. Making re-runs faster starts
# with the same question asked across every job. So the end of each run leaves
#   <stem>_timing.json in the logs folder (the runner copies that folder to the job's output),
#   one row per phase appended to output/timing_history.csv beside the engine (the machine's
#   record, not the job's: it is never copied),
# and a reuse count per store — answers a cache gave back against answers it had to work
# out — because a cache that never hits looks exactly like one that works.
_identity: Dict[str, object] = {}
_reuse: Dict[str, Dict[str, int]] = {}      # store -> {"reused": n, "computed": n}
HISTORY_COLUMNS = ("finished_at", "stem", "product", "customer", "units", "breaks", "build",
                   "kind", "name", "seconds", "reused", "computed", "total_seconds")


def identify(**fields: object) -> None:
    """Name the run the timing belongs to (stem, product, customer, units, breaks, build)."""
    for k, v in fields.items():
        if v is not None and str(v) != "":
            _identity[k] = v


def reuse(store: str, hit: bool) -> None:
    """One answer from a store: given back as held (hit) or worked out and kept (miss)."""
    if not store:
        return
    r = _reuse.setdefault(str(store), {"reused": 0, "computed": 0})
    r["reused" if hit else "computed"] += 1


def reuse_counts() -> Dict[str, Dict[str, int]]:
    return {k: dict(v) for k, v in _reuse.items()}


def record() -> Dict[str, object]:
    """The run's timing as data: identity, phases (slowest first, unfinished marked), the
    wall clock, the unmeasured remainder and the reuse counts."""
    now = time.time()
    phases = [{"phase": n, "seconds": round(s, 1)} for n, s in sorted(_done, key=lambda kv: -kv[1])]
    phases += [{"phase": n, "seconds": round(now - b, 1), "unfinished": True}
               for n, b in _open.items()]
    total = round(now - _run_started, 1) if _run_started is not None else None
    measured = round(_union_seconds(_spans), 1)
    return {"schema": "run_timing.v1", "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            **{k: _identity.get(k) for k in ("stem", "product", "customer", "units", "breaks",
                                              "build")},
            "total_seconds": total,
            "unmeasured_seconds": (round(total - measured, 1) if total is not None else None),
            "phases": phases, "reuse": reuse_counts()}


def write(logs_dir: object, history_csv: object) -> Dict[str, object]:
    """Leave the record beside the run's log and one row per phase on the history. Never
    raises: a run that finished is not undone by its bookkeeping. Returns what was written."""
    import csv
    import json
    import os
    out: Dict[str, object] = {"json": None, "history": None}
    rec = record()
    if not rec["phases"] and not rec["reuse"]:
        return out
    stem = str(_identity.get("stem") or "run")
    try:
        os.makedirs(str(logs_dir), exist_ok=True)
        path = os.path.join(str(logs_dir), f"{stem}_timing.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=1)
        out["json"] = path
    except Exception:                                        # noqa: BLE001
        pass
    try:
        path = str(history_csv)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        new = not os.path.exists(path)
        base = {k: rec.get(k) for k in ("finished_at", "stem", "product", "customer", "units",
                                         "breaks", "build", "total_seconds")}
        with open(path, "a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(HISTORY_COLUMNS))
            if new:
                w.writeheader()
            for ph in rec["phases"]:
                w.writerow({**base, "kind": "phase", "name": ph["phase"],
                            "seconds": ph["seconds"], "reused": "", "computed": ""})
            for store, c in sorted(rec["reuse"].items()):
                w.writerow({**base, "kind": "reuse", "name": store, "seconds": "",
                            "reused": c["reused"], "computed": c["computed"]})
        out["history"] = path
    except Exception:                                        # noqa: BLE001
        pass
    return out
# name -> {"calls", "seconds", "cache_hits", "failed"}
_counters: Dict[str, Dict[str, float]] = {}
# The phases file_scan and main already bracket, as the stage a partner page shows.
STAGE_OF = {"extract_pdf_summary": "reading", "estimate_document": "pricing",
            "job_level_pricing_and_rewrite": "pricing", "populate_workbook": "workbook",
            "invariants": "checking the workbook", "deliverables": "filing"}


def enable_detail() -> None:
    global _detail, _run_started
    _detail = True
    if _run_started is None:
        _run_started = time.time()


def detail_on() -> bool:
    return _detail


def stage(name: str) -> None:
    """Say which stage a partner run has reached, once per change, with its elapsed time."""
    _say_stage(name)


def _say_stage(name: str) -> None:
    global _last_stage
    if not _detail or not name or name == _last_stage:
        return
    _last_stage = name
    began = _run_started if _run_started is not None else time.time()
    print(f"[api-stage] {name} +{time.time() - began:.0f}s", flush=True)


def count(name: str, seconds: float = 0.0, *, cache_hit: bool = False,
          failed: bool = False) -> None:
    """One model call (or one answer from the cache) on a partner run — nothing otherwise."""
    if not _detail:
        return
    c = _counters.setdefault(name, {"calls": 0, "seconds": 0.0, "cache_hits": 0, "failed": 0})
    if cache_hit:
        c["cache_hits"] += 1
    else:
        c["calls"] += 1
        c["seconds"] = round(c["seconds"] + float(seconds or 0.0), 2)
        if failed:
            c["failed"] += 1


def report_json() -> Dict[str, object]:
    """The timing table and the call counters as data, for the partner summary."""
    now = time.time()
    phases = [{"phase": n, "seconds": round(s, 1)} for n, s in sorted(_done, key=lambda kv: -kv[1])]
    phases += [{"phase": n, "seconds": round(now - b, 1), "unfinished": True}
               for n, b in _open.items()]
    total = round(now - _run_started, 1) if _run_started is not None else None
    return {"total_seconds": total, "phases": phases,
            "model_calls": {k: dict(v) for k, v in _counters.items()}}


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
    global _run_started, _detail, _last_stage
    _open.clear()
    _done.clear()
    _spans.clear()
    _counters.clear()
    _identity.clear()
    _reuse.clear()
    _detail, _last_stage = False, ""
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
        if _detail and text[6:].strip() in STAGE_OF:
            _say_stage(STAGE_OF[text[6:].strip()])
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
