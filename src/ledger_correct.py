#!/usr/bin/env python3
"""Put the Self-Running ledger's prices back to each run's own. Shows the changes first (JG, 12 Nov 2026).

The Self-Running list on the page showed 12674-01-GA and 6364-01 at the same price at every
quantity, 6364-02 at "17 off" (another job's quantity), and two more such pairs. The saved runs
were corrected that morning (price_correct.py); the list is read from the Live Enquiry ledger,
which that correction never touched. "yes, build the ledger correction and show the changes
first."

What it proposes, for every attempt in the ledger that names a run:
  the price at one off and at each quantity   from that run's saved run file, and only where
                                               price_audit finds the saved run "ok" against
                                               the record pinned to its own workbook

What it never does: change a saved run, a workbook, a record or an e-mail; change a run's
status, files or anything but its two price fields; touch an attempt whose run was not checked
or does not agree with its record (those are listed, unchanged); re-send anything.

    python src/ledger_correct.py                 the proposal, nothing changed
    python src/ledger_correct.py --apply         apply it; the ledger is copied first to
                                                 <ledger folder>/corrections/ledger.<time>.before.json
    python src/ledger_correct.py --only <run_id> one run (may repeat)

Apply it with Self-Running switched off and nothing running: the watcher rewrites the ledger
as it works.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import price_audit as pa  # noqa: E402

LEDGER_SCHEMA = "live_enquiry_ledger.v1"


def _prices(q: Any) -> List[Tuple[int, float]]:
    out = []
    for x in q or []:
        if isinstance(x, dict) and x.get("quantity") is not None and x.get("unit_gbp") is not None:
            try:
                out.append((int(x["quantity"]), round(float(x["unit_gbp"]), 2)))
            except (TypeError, ValueError):
                continue
    return out


def _money(v: Any) -> Optional[float]:
    try:
        return None if v is None else round(float(v), 2)
    except (TypeError, ValueError):
        return None


def proposals(ledger: Dict[str, Any], saved: Dict[str, Dict[str, Any]],
              verdicts: Dict[str, Dict[str, Any]], only: Iterable[str] = ()
              ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(changes to make, attempts left alone and why). Nothing is written."""
    only = set(only)
    change: List[Dict[str, Any]] = []
    left: List[Dict[str, Any]] = []
    for key, job in sorted((ledger.get("jobs") or {}).items()):
        for i, attempt in enumerate(job.get("attempts") or []):
            rid = str(attempt.get("run_id") or "")
            if not rid or attempt.get("status") != "done" or (only and rid not in only):
                continue
            who = {"job": key, "drawing": job.get("drawing"), "customer": job.get("customer"),
                   "attempt": i, "run_id": rid}
            run = saved.get(rid)
            if run is None:
                left.append(dict(who, why="no saved run of that id on this service"))
                continue
            verdict = str((verdicts.get(rid) or {}).get("verdict") or "not checked")
            if verdict != "ok":
                left.append(dict(who, why=f"its saved run is '{verdict}' against its own record: "
                                          f"{(verdicts.get(rid) or {}).get('why') or 'see price_audit'}"))
                continue
            if str(run.get("drawing_number") or "").upper() != str(job.get("drawing") or "").upper():
                left.append(dict(who, why=f"the saved run is for {run.get('drawing_number')}, not this job"))
                continue
            was = (_money(attempt.get("engine_price_gbp")), _prices(attempt.get("quantity_prices")))
            now = (_money(run.get("engine_price_gbp")), _prices(run.get("quantity_prices")))
            if was != now:
                change.append(dict(who, **{
                    "from": {"engine_price_gbp": attempt.get("engine_price_gbp"),
                             "quantity_prices": attempt.get("quantity_prices") or []},
                    "to": {"engine_price_gbp": run.get("engine_price_gbp"),
                           "quantity_prices": run.get("quantity_prices") or []}}))
    return change, left


def shared_prices(ledger: Dict[str, Any]) -> List[str]:
    """Different jobs whose finished attempts carry the same price at every quantity."""
    seen: Dict[Tuple, List[str]] = {}
    for job in (ledger.get("jobs") or {}).values():
        for attempt in job.get("attempts") or []:
            p = tuple(_prices(attempt.get("quantity_prices")))
            if attempt.get("status") == "done" and len(p) >= 2:
                seen.setdefault(p, [])
                if job.get("drawing") not in seen[p]:
                    seen[p].append(job.get("drawing"))
    return [f"{' and '.join(map(str, d))}: {', '.join(f'{q} off {v:.2f}' for q, v in p)}"
            for p, d in seen.items() if len(d) > 1]


def apply(ledger: Dict[str, Any], change: List[Dict[str, Any]], when: str) -> int:
    done = 0
    for c in change:
        attempt = ledger["jobs"][c["job"]]["attempts"][c["attempt"]]
        if str(attempt.get("run_id")) != c["run_id"]:
            continue                                    # the ledger moved under us: leave it
        attempt["engine_price_gbp"] = c["to"]["engine_price_gbp"]
        attempt["quantity_prices"] = c["to"]["quantity_prices"]
        attempt["price_corrected"] = {"at": when, "from": c["from"], "by": "ledger_correct.py"}
        done += 1
    return done


def unfinished(ledger: Dict[str, Any], verdicts: Dict[str, Dict[str, Any]],
               only: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """Attempts showing a price although their run did not finish. Nothing is written.

    Reviewer, 12 Nov 2026: "For unfinished runs, show 'failed/incomplete, no validated
    price'." Only a run the audit positively found unfinished is listed; one whose files
    could not be reached is "not checked" and is left alone.
    """
    import live_enquiry_runner as ler  # noqa: PLC0415
    only = set(only or ())
    out: List[Dict[str, Any]] = []
    for job in (ledger.get("jobs") or {}).values():
        for attempt in job.get("attempts") or []:
            rid = str(attempt.get("run_id") or "")
            if only and rid not in only:
                continue
            shows = attempt.get("engine_price_gbp") not in (None, "") or bool(attempt.get("quantity_prices"))
            if not shows:
                continue
            verdict = str((verdicts.get(rid) or {}).get("verdict") or "")
            failed = attempt.get("status") == "error" or ler.stopped_by_hand(attempt)
            if verdict != "not a finished run" and not failed:
                continue
            earlier = ler.last_completed(job, before=attempt)
            out.append({"customer": job.get("customer"), "drawing": job.get("drawing"), "run_id": rid,
                        "why": "its run did not finish" if verdict == "not a finished run"
                               else "the attempt failed or was stopped",
                        "shows": {"engine_price_gbp": attempt.get("engine_price_gbp"),
                                  "quantity_prices": attempt.get("quantity_prices") or []},
                        "earlier_completed": earlier, "_attempt": attempt})
    return out


def hold(found: List[Dict[str, Any]], when: str) -> int:
    """Move each listed attempt's unproved figure aside; the figure is kept, not deleted."""
    import live_enquiry_runner as ler  # noqa: PLC0415
    n = 0
    for f in found:
        attempt = f["_attempt"]
        attempt["unvalidated_price_gbp"] = attempt.get("engine_price_gbp")
        attempt["unvalidated_quantity_prices"] = attempt.get("quantity_prices") or []
        attempt["engine_price_gbp"] = None
        attempt["quantity_prices"] = []
        attempt["price_validated"] = False
        attempt["price_note"] = ler.NO_VALIDATED_PRICE
        attempt["price_held"] = {"at": when, "by": "ledger_correct.py", "why": f["why"]}
        n += 1
    return n


def _show(q: Any) -> str:
    return ", ".join(f"{a} off {b:.2f}" for a, b in _prices(q)) or "none"


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", default="")
    ap.add_argument("--runs", default="")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", default="")
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.ledger:
        path = Path(a.ledger)
    else:
        import config  # noqa: PLC0415
        path = Path(config.LIVE_ENQUIRY_LEDGER)
    if a.runs:
        folder = Path(a.runs)
    else:
        sys.path.insert(0, str(HERE.parent / "sdi-intelligence-backend"))
        import estimate_history  # noqa: PLC0415
        folder = estimate_history.store_dir()
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"The ledger could not be read: {path} ({exc}). Nothing changed.")
        return 2
    if not isinstance(ledger, dict) or ledger.get("schema") != LEDGER_SCHEMA:
        print(f"{path} is not a Live Enquiry ledger ({LEDGER_SCHEMA}). Nothing changed.")
        return 2
    saved: Dict[str, Dict[str, Any]] = {}
    for p in sorted(folder.glob("*.json")):
        try:
            run = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(run, dict):
            saved[str(run.get("run_id") or p.stem)] = run
    verdicts = {str(r.get("run_id")): r for r in pa.check_runs(folder)}
    print(f"ledger  {path}\nruns    {folder}")
    before = shared_prices(ledger)
    if before:
        print("\nDifferent jobs showing the same prices now:")
        for line in before:
            print(f"  {line}")
    change, left = proposals(ledger, saved, verdicts, a.only)
    for c in change:
        print(f"\n{c['drawing']}  ({c['customer']})  run {c['run_id']}"
              f"\n  price at 1 off      {c['from']['engine_price_gbp']}  ->  {c['to']['engine_price_gbp']}"
              f"\n  price by quantity   {_show(c['from']['quantity_prices'])}"
              f"\n                  ->  {_show(c['to']['quantity_prices'])}")
    if left:
        print("\nLeft exactly as they are:")
        for x in left:
            print(f"  {x['drawing']}  run {x['run_id']}: {x['why']}")
    held = unfinished(ledger, verdicts, a.only)
    if held:
        print("\nShowing a price although the run did not finish. Each would show "
              "'failed/incomplete, no validated price':")
        for h in held:
            e = h["earlier_completed"]
            print(f"  {h['drawing']}  ({h['customer']})  run {h['run_id']}: {h['why']}; shows "
                  f"{h['shows']['engine_price_gbp']}"
                  + (f"\n      earlier completed estimate kept separately: £{e['unit_gbp']:,.2f} "
                     f"finished {e['finished_at']} (run {e['run_id']})" if e else
                     "\n      no earlier completed estimate for this job"))
    after = json.loads(json.dumps(ledger))
    apply(after, change, "preview")
    still = shared_prices(after)
    print(f"\n{len(change)} attempt(s) to correct; {len(left)} left alone.")
    print("After the correction, different jobs still showing the same prices: "
          + ("none" if not still else ""))
    for line in still:
        print(f"  {line}")
    if a.json:
        Path(a.json).write_text(json.dumps({"ledger": str(path), "changes": change, "left": left,
                                            "unfinished": [{k: v for k, v in h.items() if k != "_attempt"}
                                                           for h in held],
                                            "shared_before": before, "shared_after": still},
                                           indent=1, default=str), encoding="utf-8")
    if not a.apply:
        print("\nNothing was changed. Run again with --apply to make these changes.")
        return 0
    if not change and not held:
        print("\nNothing to change.")
        return 0
    when = time.strftime("%Y-%m-%d %H:%M:%S")
    keep = path.parent / "corrections"
    keep.mkdir(parents=True, exist_ok=True)
    backup = keep / f"{path.stem}.{time.strftime('%Y%m%d_%H%M%S')}.before.json"
    shutil.copy2(path, backup)
    n = apply(ledger, change, when)
    m = hold(held, when)
    for h in held:
        h.pop("_attempt", None)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)
    print(f"\n{n} attempt(s) corrected; {m} unfinished attempt(s) now show no validated "
          f"price. The ledger as it was: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
