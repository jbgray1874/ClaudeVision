#!/usr/bin/env python3
r"""Every estimate ever filed, from AISheets, for the control panel's history (D-744).

    python src\run_history.py [--json] [--cache <file>] [--months 18]

JG, 7 Nov 2026: "the control panel should have the entire stats / history of runs and parity
runs, etc. and we can build vizuals around that and details."

The service remembers thirty days of runs. AISheets remembers every one: each run files its
workbook and summary as <AISheets>\<client>\<drawing>\<date time> (<units> off). So the whole
history is read from there, the same way parity finds an AI run (parity_job: the engine's own
workbook, and the summary filed beside it, never another run's). Each run's unit cost is read
from its own summary, by the same keys, in the same order, as the runner reads it when the
run finishes. A run folder without both is not counted as an estimate, and is counted apart.

A summary is read once: what was read is kept in a cache file beside the service's state,
keyed by the summary's path, size and modified time, so each later read of the share opens
only what is new or changed.

What it answers: every filed estimate with its date, client, drawing, quantity and unit cost;
counts by month and by client; and the drawings estimated more than once, with each run's
unit cost at the quantity it was priced at. A price at 1 off is never set against one at 50
off: a drawing's runs are compared only at the same quantity.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import parity_job  # noqa: E402  (its AISheets rules: the run folder, workbook and summary)

# The runner's own order (tools/runner/sdi_estimate_runner.py _UNIT_COST_KEYS): the figure
# Excel calculated first, then the engine's own arithmetic.
UNIT_COST_KEYS = (
    ("final_estimate", "totals", "unit_gbp"),
    ("workbook_equivalent_pricing", "m105_total_unit_cost_gbp"),
    ("headline_cost_price", "workbook_equivalent_total_unit_cost_gbp"),
    ("headline_cost_price", "total_unit_cost_gbp"),
    ("totals", "unit_cost_gbp"),
)
CACHE_SCHEMA = "sdi_run_history_cache.v1"


def unit_cost_from(summary: Any) -> Optional[float]:
    if not isinstance(summary, dict):
        return None
    for path in UNIT_COST_KEYS:
        node: Any = summary
        for step in path[:-1]:
            node = node.get(step) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            continue
        try:
            value = float(node.get(path[-1]))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return round(value, 2)
    return None


def _read_cache(path: Optional[Path]) -> Dict[str, Any]:
    if not path:
        return {}
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        return body.get("entries", {}) if body.get("schema") == CACHE_SCHEMA else {}
    except (OSError, ValueError):
        return {}


def _write_cache(path: Optional[Path], entries: Dict[str, Any]) -> None:
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"schema": CACHE_SCHEMA, "entries": entries}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def filed_runs(root: Path, cache_path: Optional[Path] = None) -> Dict[str, Any]:
    """Every run folder under AISheets: the estimates (workbook and own summary), and a count
    of the folders that are not one."""
    if not root.is_dir():
        raise parity_job.ParityJobError(f"AISheets is not reachable: {root}")
    cache = _read_cache(cache_path)
    fresh: Dict[str, Any] = {}
    runs: List[Dict[str, Any]] = []
    incomplete = 0
    for cdir, ddir in parity_job._drawing_dirs(root):
        try:
            folders = sorted(p for p in ddir.iterdir() if p.is_dir())
        except OSError:
            continue
        for rdir in folders:
            m = parity_job._RUN_FOLDER.match(rdir.name)
            if not m:
                continue
            book = parity_job._engine_workbook(rdir, ddir.name)
            summary = parity_job._summary_for(book) if book else None
            if not book or not summary:
                incomplete += 1
                continue
            try:
                st = summary.stat()
                key = f"{summary}|{st.st_size}|{int(st.st_mtime)}"
            except OSError:
                incomplete += 1
                continue
            entry = cache.get(key)
            if entry is None:
                try:
                    body = json.loads(summary.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    body = {}
                entry = {"unit_gbp": unit_cost_from(body)}
            fresh[key] = entry
            runs.append({"client": cdir.name, "drawing": ddir.name, "stamp": rdir.name[:19],
                         "day": m.group(1), "units": int(m.group(5)),
                         "unit_gbp": entry.get("unit_gbp"), "folder": str(rdir),
                         "workbook": str(book)})
    _write_cache(cache_path, fresh)
    runs.sort(key=lambda r: r["stamp"], reverse=True)
    return {"runs": runs, "incomplete": incomplete}


def _months(today: date, n: int) -> List[str]:
    out, y, mth = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y:04d}-{mth:02d}")
        mth -= 1
        if mth == 0:
            y, mth = y - 1, 12
    return list(reversed(out))


def summary(found: Dict[str, Any], now: Optional[float] = None, months: int = 18,
            recent: int = 300, repeat_limit: int = 40) -> Dict[str, Any]:
    """Totals, by month, by client, the drawings estimated more than once with each run's
    price at its own quantity, and the newest runs."""
    runs = found["runs"]
    today = (datetime.fromtimestamp(now) if now else datetime.now()).date()
    by_month = {k: {"month": k, "estimates": 0, "drawings": set(), "clients": set()}
                for k in _months(today, months)}
    clients: Dict[str, Dict[str, Any]] = {}
    drawings: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in runs:
        mk = r["day"][:7]
        if mk in by_month:
            b = by_month[mk]
            b["estimates"] += 1
            b["drawings"].add((r["client"].lower(), r["drawing"].lower()))
            b["clients"].add(r["client"].lower())
        c = clients.setdefault(r["client"], {"client": r["client"], "estimates": 0,
                                            "drawings": set(), "first": r["day"], "last": r["day"]})
        c["estimates"] += 1
        c["drawings"].add(r["drawing"].lower())
        c["first"], c["last"] = min(c["first"], r["day"]), max(c["last"], r["day"])
        drawings.setdefault((r["client"], r["drawing"]), []).append(r)
    repeats = []
    for (client, drawing), rs in drawings.items():
        if len(rs) < 2:
            continue
        rs = sorted(rs, key=lambda r: r["stamp"])
        latest = rs[-1]
        same = [r for r in rs if r["units"] == latest["units"] and r["unit_gbp"]]
        first = same[0] if same else None
        change = (round(latest["unit_gbp"] - first["unit_gbp"], 2)
                  if first and latest["unit_gbp"] and first is not latest else None)
        repeats.append({"client": client, "drawing": drawing, "runs": len(rs),
                        "units": latest["units"], "first_stamp": rs[0]["stamp"],
                        "last_stamp": latest["stamp"], "last_unit_gbp": latest["unit_gbp"],
                        "first_unit_gbp": first["unit_gbp"] if first else None,
                        "change_gbp": change,
                        "change_pct": (round(100.0 * change / first["unit_gbp"], 1)
                                       if change is not None and first["unit_gbp"] else None),
                        "points": [[r["stamp"], r["unit_gbp"]] for r in same][-30:],
                        "other_quantities": sum(1 for r in rs if r["units"] != latest["units"]),
                        "not_priced": sum(1 for r in rs if r["units"] == latest["units"]
                                          and not r["unit_gbp"])})
    repeats.sort(key=lambda r: r["last_stamp"], reverse=True)
    prices = [r["unit_gbp"] for r in runs if r["unit_gbp"]]
    out_months = [{"month": b["month"], "estimates": b["estimates"],
                   "drawings": len(b["drawings"]), "clients": len(b["clients"])}
                  for b in by_month.values()]
    out_clients = sorted(({"client": c["client"], "estimates": c["estimates"],
                           "drawings": len(c["drawings"]), "first": c["first"], "last": c["last"]}
                          for c in clients.values()), key=lambda c: (-c["estimates"], c["client"]))
    return {"schema": "sdi_run_history.v1",
            "as_of": datetime.fromtimestamp(now or time.time()).strftime("%Y-%m-%d %H:%M:%S"),
            "totals": {"estimates": len(runs), "drawings": len(drawings),
                       "clients": len(clients), "re_estimated": len(repeats),
                       "priced": len(prices), "not_priced": len(runs) - len(prices),
                       "incomplete_folders": found.get("incomplete", 0),
                       "first_day": runs[-1]["day"] if runs else None,
                       "last_day": runs[0]["day"] if runs else None,
                       "median_unit_gbp": (round(statistics.median(prices), 2) if prices else None)},
            "months": out_months, "clients": out_clients[:40],
            "clients_left_out": max(0, len(out_clients) - 40),
            "repeats": repeats[:repeat_limit], "repeats_left_out": max(0, len(repeats) - repeat_limit),
            "recent": [{k: r[k] for k in ("client", "drawing", "stamp", "units", "unit_gbp",
                                          "folder", "workbook")} for r in runs[:recent]]}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Every estimate filed in AISheets (D-744).")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cache", default="", help="the summaries already read, kept between reads")
    ap.add_argument("--months", type=int, default=18)
    a = ap.parse_args(argv)
    try:
        import config  # noqa: F401  — loads .env, so SDI_ESTIMATE_OUTPUT_ROOT applies
    except Exception:                                                # noqa: BLE001
        pass
    root = parity_job.roots()["aisheets"]
    try:
        out = summary(filed_runs(root, Path(a.cache) if a.cache else None),
                      months=max(1, min(a.months, 60)))
    except parity_job.ParityJobError as exc:
        print(json.dumps({"error": str(exc)}) if a.json else str(exc))
        return 2
    if a.json:
        print(json.dumps(out, default=str))
    else:
        t = out["totals"]
        print(f"{t['estimates']} estimates filed, {t['drawings']} drawings, {t['clients']} "
              f"clients, {t['re_estimated']} drawings estimated more than once.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
