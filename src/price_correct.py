#!/usr/bin/env python3
"""Put a saved run's price and file list back to its own. Shows the changes first (JG, 12 Nov 2026).

"yes, build the correction and show the changes first." The reviewer: "Show the proposed
corrections, preserve the originals, and repair displayed prices and filed results from the
correct existing records. Don't rerun merely to repair filing."

What it proposes, for every saved run price_audit finds wrong:
  the price at one off and at each quantity   from the record pinned to the run's own workbook
  the run's file list                          without the files named for another job

What it never does: delete or move a file, change a workbook, a record or an e-mail, touch a
TTI ledger or a tracker cell, or re-send anything. The other job's files stay where they are on
the share; they are only taken off this run's list and written down under "set_aside_files".

    python src/price_correct.py                  the proposal, nothing changed
    python src/price_correct.py --apply          apply it; each saved run is copied first to
                                                 <runs>/corrections/<run_id>.<time>.before.json
    python src/price_correct.py --only <run_id>  one run (may repeat)

The services read saved runs when they start, so restart them after --apply.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import price_audit as pa  # noqa: E402


def proposal(run: Dict[str, Any], row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The changes for one saved run, or None when it needs none or cannot be proved."""
    if row.get("verdict") not in ("MISMATCH", "ok"):
        return None
    theirs = set(row.get("other_jobs_files") or [])
    own, own_q = row.get("own"), row.get("own_by_quantity") or {}
    changes: List[Dict[str, Any]] = []
    if row.get("verdict") == "MISMATCH" and own is not None:
        if run.get("engine_price_gbp") != own:
            changes.append({"field": "engine_price_gbp", "from": run.get("engine_price_gbp"), "to": own})
        new_q = [{"quantity": q, "unit_gbp": own_q[q]} for q in sorted(own_q)] if len(own_q) > 1 else []
        if (run.get("quantity_prices") or []) != new_q:
            changes.append({"field": "quantity_prices", "from": run.get("quantity_prices") or [], "to": new_q})
    files = [d for d in (run.get("deliverables") or []) if isinstance(d, dict)]
    aside = [d for d in files if str(d.get("name")) in theirs]
    if aside:
        changes.append({"field": "deliverables",
                        "from": f"{len(files)} file(s)", "to": f"{len(files) - len(aside)} file(s)",
                        "set_aside": [str(d.get("name")) for d in aside]})
    if row.get("record_found") and row.get("record_path"):
        if not any(str(d.get("path")) == row["record_path"] for d in files):
            changes.append({"field": "deliverables", "add": Path(row["record_path"]).name,
                            "why": f"the run's own record, {row['record_found']}"})
    if not changes:
        return None
    return {"run_id": run.get("run_id"), "drawing": run.get("drawing_number"),
            "record": row.get("record"), "changes": changes, "email": row.get("email") or {}}


def corrected(run: Dict[str, Any], prop: Dict[str, Any], row: Dict[str, Any], when: str) -> Dict[str, Any]:
    out = dict(run)
    for c in prop["changes"]:
        if c["field"] in ("engine_price_gbp", "quantity_prices"):
            out[c["field"]] = c["to"]
        elif c.get("set_aside"):
            gone = set(c["set_aside"])
            files = [d for d in (run.get("deliverables") or []) if isinstance(d, dict)]
            out["deliverables"] = [d for d in (out.get("deliverables") or files) if str(d.get("name")) not in gone]
            out["set_aside_files"] = list(run.get("set_aside_files") or []) + [
                dict(d, why="named for another job's workbook; filed with this run while both ran at once",
                     at=when) for d in files if str(d.get("name")) in gone]
        elif c.get("add"):
            out["deliverables"] = list(out.get("deliverables") or []) + [
                {"name": c["add"], "path": row["record_path"]}]
    out["log"] = list(run.get("log") or []) + [
        f"[corrected {when}] price and file list put back to this run's own record "
        f"({prop.get('record')}); the saved run as it was is in corrections/."]
    out["corrected_at"] = when
    return out


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default="")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", default="")
    a = ap.parse_args(list(argv) if argv is not None else None)
    if a.runs:
        folder = Path(a.runs)
    else:
        sys.path.insert(0, str(HERE.parent / "sdi-intelligence-backend"))
        import estimate_history  # noqa: PLC0415
        folder = estimate_history.store_dir()
    rows = {str(r.get("run_id")): r for r in pa.check_runs(folder)}
    when = time.strftime("%Y-%m-%d %H:%M:%S")
    props: List[Dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rid = str(run.get("run_id") or path.stem)
        if a.only and rid not in a.only:
            continue
        prop = proposal(run, rows.get(rid) or {})
        if not prop:
            continue
        props.append(prop)
        print(f"\n{prop['drawing']}  run {rid}   own record: {prop.get('record')}")
        for c in prop["changes"]:
            if c["field"] == "engine_price_gbp":
                print(f"  price at 1 off      {c['from']}  ->  {c['to']}")
            elif c["field"] == "quantity_prices":
                was = ", ".join(f"{q.get('quantity')}: {q.get('unit_gbp')}" for q in c["from"]) or "none"
                now = ", ".join(f"{q['quantity']}: {q['unit_gbp']}" for q in c["to"]) or "none"
                print(f"  price by quantity   {was}\n                  ->  {now}")
            elif c.get("set_aside"):
                print(f"  files               {c['from']} -> {c['to']}; taken off this run's list, left on disk:")
                for n in c["set_aside"]:
                    print(f"                        {n}")
            elif c.get("add"):
                print(f"  files               add {c['add']} ({c['why']})")
        e = prop["email"]
        if e.get("sent"):
            print(f"  e-mail (service's record): sent to {e.get('recipients')} recipient(s); message was "
                  f"{e.get('message_note')}"
                  + (" - ANOTHER JOB'S NOTE" if e.get("message_was_another_jobs") else "")
                  + "; attached from another job: "
                  + (", ".join(e.get("attached_from_another_job") or []) or "none"))
            print("    not changed by this tool; nothing is re-sent")
        else:
            print("  e-mail (service's record): none sent for this run")
        if a.apply:
            keep = folder / "corrections"
            keep.mkdir(exist_ok=True)
            shutil.copy2(path, keep / f"{rid}.{when.replace(':', '').replace(' ', '_')}.before.json")
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(corrected(run, prop, rows[rid], when), indent=1, default=str), encoding="utf-8")
            tmp.replace(path)
            print("  APPLIED; the saved run as it was: " + str(keep / f"{rid}.*.before.json"))
    print(f"\n{len(props)} saved run(s) {'corrected' if a.apply else 'would change'}."
          + ("" if a.apply else " Nothing was changed. Add --apply to make these changes.")
          + (" Restart the services so they read the corrected runs." if a.apply and props else ""))
    if a.json:
        Path(a.json).write_text(json.dumps(props, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
