"""PRE-FLIGHT: will the next run charge a bend on every tube it bends?

Answers, in seconds and without running the estimate, the question that costs a morning to
answer the slow way: does the route compiler raise a REQUIRED bending operation for every part
whose stock form is a tube?

The failure this exists to catch is a real one. 7332-01's leg was correctly told it cannot go
through a press brake (a tube has no flat blank), and the flat-sheet 'folding' claim was ruled
not_applicable — but nothing raised the operation that IS possible, so under the canonical
cutover, where a labour row exists only where a REQUIRED decision does, the bend left the sheet
entirely and the leg was bent for free. £8.70 of Tubebend, gone between two runs, silently.

Usage (from the engine root):
    python tools\\preflight_tube_bend.py                       # newest job JSON in output/json
    python tools\\preflight_tube_bend.py path\\to\\7332-01.json

Exit code 0 = every tube keeps a bend (or there are no tubes). 1 = a tube would be bent free.
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

BEND_OPS = {"fold", "folding", "linebend", "line_bend", "tubebend", "tube_bending"}


def _newest_job_json() -> str:
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    hits = []
    for pat in ("output/json/*.json", "output/estimates/*.json", "output/*.json"):
        hits.extend(glob.glob(os.path.join(here, pat)))
    if not hits:
        sys.exit("no job JSON found under output/ — pass one as an argument")
    return max(hits, key=os.path.getmtime)


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else _newest_job_json()
    print(f"job JSON : {path}")
    with open(path, encoding="utf-8") as fh:
        summary = json.load(fh)

    parts = (summary.get("parts")
             or (summary.get("scan") or {}).get("parts")
             or summary.get("part_records") or [])
    if not parts:
        sys.exit("no parts in that JSON — is it a scan/final_estimate document?")

    import estimator as e
    import route_compiler as rc

    # Cost each part so the section/tube branch stamps stock_form onto the record, exactly as a
    # real run does before the compiler reads it.
    for p in parts:
        if isinstance(p, dict):
            try:
                e.estimate_part(p, job_quantity=int(summary.get("assumed_job_quantity") or 1))
            except Exception as exc:                                   # noqa: BLE001
                print(f"  ! {p.get('part_number')}: estimate_part skipped ({exc})")

    tubes = [p for p in parts
             if isinstance(p, dict) and str(p.get("stock_form") or "").lower() == "tube"]
    if not tubes:
        print("\nno tube parts on this job — nothing to check.")
        return 0

    graph = rc.compile_job_route(parts, summary.get("llm_full_extract") or {})
    by_part: dict = {}
    for d in graph.get("decisions") or []:
        by_part.setdefault(str(d.get("target_id")), []).append(d)

    print(f"\ntube parts: {len(tubes)}")
    free_bends = []
    for p in tubes:
        pn = str(p.get("part_number"))
        decs = by_part.get(pn) or []
        bends = [d for d in decs if str(d.get("operation")).lower() in BEND_OPS]
        required = [d for d in bends if d.get("status") == "required"]
        print(f"\n  {pn}  ({p.get('description') or ''})")
        for d in bends:
            print(f"      {str(d.get('operation')):14s} {str(d.get('status')):16s} "
                  f"{str(d.get('reason') or '')[:64]}")
        if bends and not required:
            free_bends.append(pn)
            print("      ^^ RULED OUT WITH NOTHING IN ITS PLACE — this tube is bent for FREE")
        elif required:
            print(f"      -> charged as: {', '.join(str(d.get('operation')) for d in required)}")
        else:
            print("      (no bending claimed on this part — nothing to charge)")

    if free_bends:
        print(f"\nFAIL: {len(free_bends)} tube(s) would be bent for free: {', '.join(free_bends)}")
        return 1
    print("\nPASS: every tube that states a bend carries a required bending operation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
