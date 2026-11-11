#!/usr/bin/env python3
"""Do the prices already saved belong to their runs? Read only (reviewer, 11 Nov 2026).

"Audit existing saved results too: correcting future reads must not leave wrong historical
prices in Self-Running, TTI ledgers or tracker cells. Report mismatches before changing them."

Every saved run (the service's run history, <state>/runs/<run_id>.json) is checked against the
record pinned to its own workbook (own_record): the price at one off, and at every quantity.
Every TTI ledger entry is checked against the run it names.

    python src/price_audit.py                      the service's saved runs
    python src/price_audit.py --runs <folder>      another runs folder (a second service's)
    python src/price_audit.py --ledger <file> ...  TTI batch ledgers as well
    python src/price_audit.py --json out.json      the full result

Nothing is changed. A run whose files cannot be reached is reported "not checked", never "ok".
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import own_record as orc  # noqa: E402

UNIT_COST_KEYS = (
    ("final_estimate", "totals", "unit_gbp"),
    ("workbook_equivalent_pricing", "m105_total_unit_cost_gbp"),
    ("headline_cost_price", "workbook_equivalent_total_unit_cost_gbp"),
    ("headline_cost_price", "total_unit_cost_gbp"),
    ("totals", "unit_cost_gbp"),
)


def unit_cost_from(summary: Any) -> Optional[float]:
    if not isinstance(summary, dict):
        return None
    for path in UNIT_COST_KEYS:
        node: Any = summary
        for step in path[:-1]:
            node = node.get(step) if isinstance(node, dict) else None
        if isinstance(node, dict):
            try:
                value = float(node.get(path[-1]))
            except (TypeError, ValueError):
                continue
            if value > 0:
                return round(value, 2)
    return None


def quantity_prices_from(summary: Any) -> Dict[int, float]:
    rows = ((summary or {}).get("quantity_sweep") or {}).get("rows") if isinstance(summary, dict) else None
    out: Dict[int, float] = {}
    for r in rows or []:
        try:
            q, unit = int(r.get("quantity")), float(r.get("unit"))
        except (AttributeError, TypeError, ValueError):
            continue
        if q >= 1 and unit > 0:
            out[q] = round(unit, 2)
    return out


def check_run(run: Dict[str, Any]) -> Dict[str, Any]:
    """One saved run against its own pinned record."""
    out: Dict[str, Any] = {"run_id": run.get("run_id"), "drawing": run.get("drawing_number"),
                           "client": run.get("client"), "source": run.get("source") or "",
                           "shown": run.get("engine_price_gbp"),
                           "shown_by_quantity": {int(q["quantity"]): q.get("unit_gbp")
                                                 for q in (run.get("quantity_prices") or [])
                                                 if isinstance(q, dict) and q.get("quantity")}}
    if run.get("status") != "done":
        return dict(out, verdict="not a finished run")
    files = [d for d in (run.get("deliverables") or []) if isinstance(d, dict)]
    item, why = orc.own_record(files, str(run.get("drawing_number") or ""),
                               float(run.get("started_at") or 0.0))
    out["record_rule"] = why
    out["other_jobs_files"] = orc.other_jobs_files(files, str(run.get("drawing_number") or ""),
                                                   float(run.get("started_at") or 0.0))
    if not item:
        return dict(out, verdict="not checked", why=why)
    try:
        record = json.loads(Path(str(item.get("path"))).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return dict(out, verdict="not checked", why=f"{item.get('name')} could not be read: {exc}")
    own, own_q = unit_cost_from(record), quantity_prices_from(record)
    out.update(record=item.get("name"), own=own, own_by_quantity=own_q)
    wrong = []
    if out["shown"] is not None and own is not None and abs(float(out["shown"]) - own) > 0.005:
        wrong.append(f"shows {out['shown']} at one off, its record says {own}")
    if out["shown"] is None and own is not None:
        wrong.append(f"shows no price, its record says {own}")
    for q, shown in sorted(out["shown_by_quantity"].items()):
        if q in own_q and shown is not None and abs(float(shown) - own_q[q]) > 0.005:
            wrong.append(f"shows {shown} at {q} off, its record says {own_q[q]}")
    if out["shown_by_quantity"] and own_q and set(out["shown_by_quantity"]) != set(own_q):
        wrong.append(f"shows quantities {sorted(out['shown_by_quantity'])}, its record priced {sorted(own_q)}")
    if own is None:
        return dict(out, verdict="not checked", why=f"{item.get('name')} holds no unit cost")
    return dict(out, verdict="MISMATCH" if wrong else "ok", why="; ".join(wrong))


def check_runs(folder: Path) -> List[Dict[str, Any]]:
    rows = []
    for path in sorted(folder.glob("*.json")):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows.append({"run_id": path.stem, "verdict": "not checked", "why": "saved run could not be read"})
            continue
        if isinstance(run, dict):
            rows.append(check_run(run))
    return rows


def check_ledger(path: Path, by_run: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every ledger entry that carries a cost, against the run it names."""
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [{"ledger": str(path), "verdict": "not checked", "why": str(exc)}]
    rows = []
    for key, entry in sorted((ledger or {}).items()):
        if not isinstance(entry, dict) or entry.get("unit_cost") is None:
            continue
        row = {"ledger": path.name, "row": key, "run_id": entry.get("run_id"),
               "ledger_cost": entry.get("unit_cost"), "written": entry.get("written")}
        run = by_run.get(str(entry.get("run_id") or ""))
        if not run or run.get("verdict") in (None, "not checked", "not a finished run"):
            rows.append(dict(row, verdict="not checked",
                             why="its run is not in the saved runs" if not run else run.get("why", "")))
            continue
        qty = None
        try:
            qty = int(str(key).split("|")[2])
        except (IndexError, ValueError):
            pass
        own = (run.get("own_by_quantity") or {}).get(qty) if qty and qty > 1 else None
        own = own if own is not None else run.get("own")
        bad = own is not None and abs(float(entry["unit_cost"]) - float(own)) > 0.005
        rows.append(dict(row, own=own, verdict="MISMATCH" if bad else "ok",
                         why=(f"ledger holds {entry['unit_cost']}, the run's own record says {own}"
                              + ("; this cost was WRITTEN to the tracker" if entry.get("written") else ""))
                         if bad else ""))
    return rows


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default="", help="the saved runs folder (default: this service's)")
    ap.add_argument("--ledger", action="append", default=[], help="a TTI batch ledger; may repeat")
    ap.add_argument("--json", default="")
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.runs:
        folder = Path(a.runs)
    else:
        sys.path.insert(0, str(HERE.parent / "sdi-intelligence-backend"))
        import estimate_history  # noqa: PLC0415
        folder = estimate_history.store_dir()
    runs = check_runs(folder)
    print(f"Saved runs: {folder}  ({len(runs)})")
    tally: Dict[str, int] = {}
    for r in runs:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    print("  " + ", ".join(f"{v}: {n}" for v, n in sorted(tally.items())))
    for r in runs:
        if r["verdict"] == "MISMATCH":
            print(f"  MISMATCH {r.get('drawing')} run {r.get('run_id')} [{r.get('source') or 'page'}]: {r['why']}")
        if r.get("other_jobs_files"):
            print(f"  FILED WITH ANOTHER JOB'S FILES {r.get('drawing')} run {r.get('run_id')}: "
                  + ", ".join(r["other_jobs_files"][:6]))
    for r in runs:
        if r["verdict"] == "not checked":
            print(f"  not checked {r.get('drawing')} run {r.get('run_id')}: {r.get('why')}")
    by_run = {str(r.get("run_id")): r for r in runs}
    led: List[Dict[str, Any]] = []
    for lp in a.ledger:
        rows = check_ledger(Path(lp), by_run)
        led.extend(rows)
        print(f"Ledger: {lp}  ({len(rows)} costed row(s))")
        for r in rows:
            if r["verdict"] != "ok":
                print(f"  {r['verdict']} {r.get('row')} run {r.get('run_id')}: {r.get('why')}")
    if a.json:
        Path(a.json).write_text(json.dumps({"runs": runs, "ledgers": led}, indent=1, default=str), encoding="utf-8")
        print(f"full result: {a.json}")
    return 1 if any(r["verdict"] == "MISMATCH" for r in runs + led) else 0


if __name__ == "__main__":
    raise SystemExit(main())
