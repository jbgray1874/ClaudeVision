"""Two saved timing snapshots of a job, compared whole (D-581).

The timing history (run_timing, D-553) keeps one row per phase per run. A phase's seconds
are inclusive — post_scan_enrichment brackets the stages inside it — so adding stage
deltas up as a wall-time saving double counts; the comparison reports the run's own
total_seconds and the per-stage deltas beside it, with that caveat written into the
result. Two runs compare only on the same job, product, customer, units and breaks; a
snapshot with a missing or impossible total is refused rather than read. Nothing here
prices, invalidates a read or decides a release; a matching identity is necessary, not
proof that the drawings or the store's warmth were the same. From the Codex "Programme
Robust" package of 22 Oct 2026, merged; CLI at tools/diagnose/compare_timing_history.py.
"""
import csv
import math
from collections import defaultdict


def runs_from_history(path, stem):
    groups = defaultdict(list)
    with open(path, encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("stem") == stem:
                groups[(row["finished_at"], row.get("build", ""))].append(row)
    runs = []
    for (finished, build), rows in sorted(groups.items()):
        totals = {float(r["total_seconds"]) for r in rows}
        if len(totals) != 1 or not all(math.isfinite(t) and t > 0 for t in totals):
            raise ValueError("Inconsistent or invalid snapshot wall time: " + finished)
        identity = {(r.get("stem"), r.get("product"), r.get("customer"),
                     r.get("units"), r.get("breaks")) for r in rows}
        if len(identity) != 1:
            raise ValueError("Mixed run identity: " + finished)
        phases = defaultdict(float)
        for row in rows:
            if row.get("kind") == "phase":
                value = float(row["seconds"])
                if not math.isfinite(value) or value < 0:
                    raise ValueError("Invalid stage duration")
                phases[row["name"]] += value
        runs.append(dict(finished_at=finished, build=build,
                         identity=list(next(iter(identity))),
                         total_seconds=next(iter(totals)), phases=dict(phases)))
    return runs


def compare(before, after):
    if before["identity"] != after["identity"]:
        raise ValueError("Different job, customer or quantity basis; not a comparable pair")
    old, new = before["total_seconds"], after["total_seconds"]
    return {
        "before": before["finished_at"], "after": after["finished_at"],
        "before_seconds": old, "after_seconds": new,
        "seconds_saved": round(old-new, 3),
        "percent_saved": round(100*(old-new)/old, 3),
        "stage_deltas_seconds": {
            k: round(after["phases"].get(k, 0)-before["phases"].get(k, 0), 3)
            for k in sorted(before["phases"].keys() | after["phases"].keys())},
        "limits": ["Stage deltas are inclusive: never sum them as wall time.",
                   "File hashes and cache warmth are not held in this history; this is an observational comparison, not a benchmark.",
                   "Use saved snapshots on both sides, not a console total printed earlier."]}
