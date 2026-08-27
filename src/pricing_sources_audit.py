"""Which price sources actually price anything? Measured, not assumed.

    python src/pricing_sources_audit.py
    python src/pricing_sources_audit.py --json

WHY THIS EXISTS. The pricing chain has seven steps and `_select_anchor_price_source` really does
walk all of them in order, first hit wins. That much is readable in the source. What is NOT
readable in the source is whether any given step has EVER produced a price on a real job — and a
step that never fires is indistinguishable, in a code review, from one that carries half the
estimate.

The question was asked directly: "do we genuinely do all these lookups, and do we specifically
ever find anything from bought_in_parts, estimating_supplier_catalog_url, or the historical RAG?"
It is a good question and it cannot be answered by reading pricing_service.py, because the answer
lives in the data. A table with no rows can never fire however carefully it is queried. A table
with ten thousand rows and no price column populated can never fire either.

So this asks two things that together settle it:

  SUPPLY  — for each source table: does it exist on this machine, how many rows does it hold, and
            how many of those carry a usable price? A source with zero usable rows is dead
            weight, and saying so is more useful than any amount of reasoning about the query.

  DEMAND  — across every priced estimate ever stored in dbo.drawing_priced_estimate, which source
            actually won each part? The engine records the winning anchor as `price_source` inside
            `priced_json`, so the real distribution is recoverable from what has already run.

WHAT A ZERO IN THE DEMAND COLUMN MEANS, and it is worth being careful here. It means that source
has never won a part in a stored run. It does NOT mean the lookup is broken: a source below UDEF
in the order only ever fires for parts UDEF could not price, so a healthy UDEF legitimately
starves the ones beneath it. The supply column is what separates "never needed" from "never
could".

READ-ONLY. Every statement is a SELECT.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402


# The seven steps of _select_anchor_price_source, in the order it tries them, with the table each
# reads and the column that has to be populated for it to be able to return anything at all.
SOURCES = [
    {"step": 1, "name": "UDEF", "source_key": "udef_parts_table_for_estimating",
     "table": "dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING", "price_col": "[System cost per]",
     "note": "Access Supply Chain contract price. Exact part code, or a supplier reference found "
             "uniquely in a description."},
    {"step": 2, "name": "PMA purchased", "source_key": "pma_tbl",
     "table": "dbo.PMA_TBL", "price_col": "PMA_USAGE_2", "where": "PMA_PROC_CODE = 'P'",
     "note": "Purchased lines from the parts master, matched on description token overlap."},
    {"step": 3, "name": "Bought-in catalogue", "source_key": "bought_in_parts",
     "table": "dbo.bought_in_parts", "price_col": "unit_price_gbp", "where": "is_active = 1",
     "note": "SDI's own curated bought-in list. Exact code, or description of 5+ characters."},
    {"step": 4, "name": "Historical RAG", "source_key": "historical_quote_material_line",
     "table": "dbo.historical_quote_material_line", "price_col": "unit_price_gbp",
     "note": "Every priced line from the ingested historical jobs. Token overlap, newest first, "
             "with a staleness penalty on the confidence."},
    {"step": 5, "name": "Supplier catalogue", "source_key": "estimating_supplier_catalog_url",
     "table": "dbo.estimating_supplier_catalog_url", "price_col": "unit_price_gbp",
     "note": "A HAND-MAINTAINED list of supplier catalogue pages: a material keyword, the URL, "
             "and an indicative price. NOTHING IN THE CODEBASE WRITES TO IT -- there is no "
             "INSERT anywhere -- so it holds whatever was put there by hand and nothing else. "
             "Always flagged 'verify against current supplier quote'."},
    {"step": 6, "name": "Standard commodity", "source_key": "standard_commodity_provisional",
     "table": None, "price_col": None,
     "note": "A config provisional for generically-named standards (PALLET, STD PART). Exists "
             "because those reached the LLM and got a different number every run -- a castor "
             "moved 4.54 to 8.54 between two runs of the same job."},
    {"step": 7, "name": "Web / LLM", "source_key": "web_ai",
     "table": None, "price_col": None,
     "note": "THE ONLY NON-REPRODUCIBLE STEP. Confidence capped, skipped entirely for anything "
             "carrying fabrication evidence."},
]


def _scalar(cur, sql: str) -> Any:
    try:
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else None
    except Exception as exc:                                  # noqa: BLE001
        return f"__error__{str(exc)[:110]}"


def supply(cur) -> List[Dict[str, Any]]:
    """Can each source fire at all? Rows held, and rows carrying a usable price."""
    out = []
    for s in SOURCES:
        rec = dict(s)
        if not s["table"]:
            rec["rows"] = rec["priced_rows"] = None      # config / live lookup, not a table
            out.append(rec)
            continue
        where = f" WHERE {s['where']}" if s.get("where") else ""
        rec["rows"] = _scalar(cur, f"SELECT COUNT(*) FROM {s['table']}{where}")
        priced_where = f"{s['price_col']} IS NOT NULL AND {s['price_col']} > 0"
        rec["priced_rows"] = _scalar(
            cur, f"SELECT COUNT(*) FROM {s['table']} WHERE {priced_where}"
            + (f" AND {s['where']}" if s.get("where") else ""))
        out.append(rec)
    return out


def demand(cur) -> Dict[str, Any]:
    """Which source actually won, across every priced estimate ever stored.

    The engine writes the winning anchor into priced_json as `price_source`, so this is a
    recovery of what really happened rather than a simulation of what would.
    """
    try:
        cur.execute("SELECT priced_json FROM dbo.drawing_priced_estimate")
        rows = cur.fetchall()
    except Exception as exc:                                  # noqa: BLE001
        return {"error": str(exc)[:200], "runs": 0, "parts": 0, "by_source": {}}

    wins: Counter = Counter()
    parts = 0
    unreadable = 0
    for (blob,) in rows:
        try:
            doc = json.loads(blob) if isinstance(blob, str) else blob
        except Exception:                                     # noqa: BLE001
            unreadable += 1
            continue
        for part in _walk_parts(doc):
            src = part.get("price_source")
            if not isinstance(src, dict):
                continue
            parts += 1
            wins[str(src.get("source") or "unknown").lower()] += 1
    return {"runs": len(rows), "parts": parts, "unreadable_runs": unreadable,
            "by_source": dict(wins.most_common())}


def _walk_parts(node: Any):
    """price_source sits on a part, and the shape of the document around it has moved before.
    Walking is cheaper than tracking a path that changes."""
    if isinstance(node, dict):
        if "price_source" in node:
            yield node
        for v in node.values():
            yield from _walk_parts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_parts(v)


def audit() -> Dict[str, Any]:
    try:
        conn = config.get_connection()
    except Exception as exc:                                  # noqa: BLE001
        return {"connected": False, "error": f"{type(exc).__name__}: {exc}"}
    cur = conn.cursor()
    result = {"connected": True, "supply": supply(cur), "demand": demand(cur)}
    try:
        cur.close(); conn.close()
    except Exception:                                         # noqa: BLE001
        pass
    return result


def report(a: Dict[str, Any]) -> str:
    if not a.get("connected"):
        return f"Could not reach SDILive, so nothing was measured.\n  {a.get('error')}"

    d = a["demand"]
    by = d.get("by_source", {})
    lines = ["", "CAN IT FIRE?  (rows in the table, and rows with a usable price)", "=" * 78]
    for s in a["supply"]:
        if s["table"] is None:
            lines.append(f"  {s['step']}. {s['name']:22} (not a table — config / live lookup)")
            continue
        rows, priced = s["rows"], s["priced_rows"]
        if isinstance(rows, str) and rows.startswith("__error__"):
            lines.append(f"  {s['step']}. {s['name']:22} TABLE UNAVAILABLE: {rows[9:]}")
            continue
        verdict = ("cannot fire — no rows" if not rows else
                   "CANNOT FIRE — no row carries a price" if not priced else "")
        lines.append(f"  {s['step']}. {s['name']:22} {rows:>9,} rows  {priced:>9,} priced"
                     + (f"   <-- {verdict}" if verdict else ""))

    lines += ["", "DID IT FIRE?  (winning source across every stored priced estimate)", "=" * 78]
    if d.get("error"):
        lines.append(f"  could not read dbo.drawing_priced_estimate: {d['error']}")
    elif not d.get("parts"):
        lines.append(f"  {d.get('runs', 0)} stored run(s), no part carried a price_source — "
                     f"nothing to count yet.")
    else:
        lines.append(f"  {d['parts']:,} priced parts across {d['runs']:,} stored run(s)")
        lines.append("")
        for s in a["supply"]:
            n = by.get(s["source_key"], 0)
            pct = 100.0 * n / d["parts"] if d["parts"] else 0.0
            lines.append(f"  {s['step']}. {s['name']:22} {n:>7,}  {pct:5.1f}%"
                         + ("   <-- never won a part" if not n else ""))
        others = {k: v for k, v in by.items()
                  if k not in {s["source_key"] for s in a["supply"]}}
        for k, v in others.items():
            lines.append(f"     {k:25} {v:>7,}  (not one of the seven — worth a look)")

    lines += ["", "A ZERO IN THE SECOND TABLE IS NOT AUTOMATICALLY A FAULT.", "-" * 78,
              "  A source below UDEF only ever fires for parts UDEF could not price, so a healthy",
              "  UDEF legitimately starves the ones beneath it. The FIRST table is what separates",
              "  'never needed' from 'never could' — a source with no priced rows is dead weight",
              "  whatever the order says, and one with plenty of rows and no wins is a matching",
              "  problem rather than a data problem.", ""]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Which price sources can fire, and which ever do.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    a = audit()
    print(json.dumps(a, indent=2, default=str) if args.json else report(a))
    return 0 if a.get("connected") else 2


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
