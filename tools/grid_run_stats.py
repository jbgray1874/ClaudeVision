"""Grid run statistics from the service's own run history. Read only.

    python tools/grid_run_stats.py --history "C:\\ProgramData\\SDI Intelligence\\runs" [--days 14] [--csv out.csv]

Answers two questions the wall cannot: how long does each KIND of job really take (so the
wall's "usual" can be set per kind instead of one figure for everything), and how busy is
each runner (so the gain from another runner can be estimated rather than guessed).
Nothing is queued, changed or sent. Hung and stopped runs are reported but kept out of the
baselines, so one 3-hour hang does not become everyone's "usual".
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

HUNG_FACTOR = 4.0           # a run beyond 4x its kind's median is reported as hung, not typical


def kind_of(run: dict) -> str:
    if run.get("job_type"):
        return "pre-run (" + str(run["job_type"]) + ")"
    if run.get("llm_only") or str(run.get("drawing_number") or "").upper().startswith("TTI-C-"):
        return "thumbnail / brief only"
    if float(run.get("sw_turn_at") or 0) > 0:
        return "drawing pack with models"
    return "drawing pack, no models"


def load(history: Path, days: float):
    since = time.time() - days * 86400 if days else 0
    runs = []
    for path in sorted(history.glob("*.json")):
        try:
            r = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(r, dict) or not r.get("run_id"):
            continue
        if float(r.get("queued_at") or 0) < since:
            continue
        runs.append(r)
    return runs


def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def minutes(x):
    return "-" if x is None else f"{x / 60:6.1f}"


def analyse(runs):
    by_kind = defaultdict(list)
    waits = []
    for r in runs:
        st, fin, q = r.get("started_at"), r.get("finished_at"), r.get("queued_at")
        if st and q:
            waits.append(float(st) - float(q))
        if r.get("status") in ("done", "error") and st and fin:
            by_kind[kind_of(r)].append(dict(r, duration=float(fin) - float(st)))
    kinds = {}
    for kind, rs in by_kind.items():
        done = [x for x in rs if x["status"] == "done"]
        durations = [x["duration"] for x in done]
        median = statistics.median(durations) if durations else None
        hung = [x for x in done if median and x["duration"] > HUNG_FACTOR * median]
        typical = [x["duration"] for x in done if not (median and x["duration"] > HUNG_FACTOR * median)]
        kinds[kind] = {
            "runs": len(rs), "done": len(done), "failed": len(rs) - len(done), "hung": len(hung),
            "p25": pct(typical, 0.25), "median": pct(typical, 0.5), "p75": pct(typical, 0.75), "p90": pct(typical, 0.9),
            "slowest_typical": max(typical) if typical else None,
            "hung_examples": [(x.get("drawing_number"), round(x["duration"] / 60)) for x in hung[:5]],
        }
    by_runner = defaultdict(lambda: {"runs": 0, "busy_s": 0.0, "first": None, "last": None})
    for r in runs:
        st, fin = r.get("started_at"), r.get("finished_at")
        if not (st and fin and r.get("runner")):
            continue
        b = by_runner[r["runner"]]
        b["runs"] += 1
        b["busy_s"] += float(fin) - float(st)
        b["first"] = min(b["first"] or st, st)
        b["last"] = max(b["last"] or fin, fin)
    return kinds, by_runner, waits


def report(kinds, by_runner, waits, out=None):
    out = out or sys.stdout
    p = lambda *a: print(*a, file=out)
    p("HOW LONG EACH KIND OF JOB TAKES (minutes; hung and failed runs kept out of the figures)")
    p(f"  {'kind':<28} {'runs':>5} {'done':>5} {'fail':>5} {'hung':>5}  {'p25':>6} {'median':>6} {'p75':>6} {'p90':>6}  {'slowest':>7}")
    for kind, k in sorted(kinds.items()):
        p(f"  {kind:<28} {k['runs']:>5} {k['done']:>5} {k['failed']:>5} {k['hung']:>5}  {minutes(k['p25'])} {minutes(k['median'])} {minutes(k['p75'])} {minutes(k['p90'])}  {minutes(k['slowest_typical'])}")
        for name, mins in k["hung_examples"]:
            p(f"      hung: {name} took {mins} min")
    p("  A fair 'usual' window for the wall is p25 to p75 of the kind; a run past p90 deserves a look.")
    p()
    p("QUEUE WAIT (minutes from queued to started)")
    p(f"  median {minutes(pct(waits, 0.5))}   p90 {minutes(pct(waits, 0.9))}   longest {minutes(max(waits) if waits else None)}")
    p()
    p("HOW BUSY EACH RUNNER WAS (over the span of its own first to last run)")
    for name, b in sorted(by_runner.items()):
        span = (b["last"] - b["first"]) if b["first"] and b["last"] else 0
        util = (b["busy_s"] / span * 100) if span else 0
        p(f"  {name:<40} {b['runs']:>4} runs   busy {b['busy_s'] / 3600:5.1f} h of {span / 3600:5.1f} h   ({util:3.0f}% busy)")
    p()
    p("WHAT ANOTHER RUNNER WOULD GIVE (per kind, if the queue is never empty)")
    for kind, k in sorted(kinds.items()):
        if not k["median"]:
            continue
        per_hour = 3600 / k["median"]
        p(f"  {kind:<28} one runner does about {per_hour:4.1f}/hour; each extra runner adds the same, until the readers or the share become the limit")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", required=True, type=Path, help="the service's runs folder")
    ap.add_argument("--days", type=float, default=14, help="how far back to look (0 = everything)")
    ap.add_argument("--csv", type=Path, help="also write one line per run here")
    a = ap.parse_args(argv)
    runs = load(a.history, a.days)
    if not runs:
        print("no runs found in", a.history)
        return 1
    print(f"{len(runs)} runs read from {a.history} (last {a.days:g} days)\n")
    kinds, by_runner, waits = analyse(runs)
    report(kinds, by_runner, waits)
    if a.csv:
        with a.csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["run_id", "client", "drawing_number", "kind", "status", "runner", "queued_at", "started_at", "finished_at", "wait_min", "duration_min"])
            for r in runs:
                st, fin, q = r.get("started_at"), r.get("finished_at"), r.get("queued_at")
                w.writerow([r.get("run_id"), r.get("client"), r.get("drawing_number"), kind_of(r), r.get("status"), r.get("runner"), q, st, fin,
                            round((float(st) - float(q)) / 60, 1) if st and q else "", round((float(fin) - float(st)) / 60, 1) if st and fin else ""])
        print("\nper-run lines written to", a.csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
