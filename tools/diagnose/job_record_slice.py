"""Cut a job record down to the parts under question, for sending instead of the whole file.

A job's <stem>.json runs to megabytes — every page's text, every reading, every line. A
question about two parts needs their records, the parts-table rows that touch them, the route
decisions made about them, their weld-symbol reads and their costed lines, and nothing else.
This writes that slice to one small JSON, with long strings trimmed, so it can be sent.

    python tools/diagnose/job_record_slice.py output/json/<stem>.json \
        --parts 07M,03M,401 --pages 11,7 \
        --timing output/logs/<stem>_timing.json --out output/deliverables/<stem>_slice.json

--parts   part numbers or their suffixes (07M matches 401918-01-07M); case-insensitive.
--pages   sheet numbers whose own parts-table rows are wanted (as the record numbers them).
--timing  the run's timing record, copied whole (it is small).
Nothing here is job-specific: the parts and pages are arguments.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List

TRIM = 1500          # longest string kept
LIST_CAP = 60        # longest list kept, except lists of numbers


def _trim(o: Any, depth: int = 0) -> Any:
    if isinstance(o, str):
        return o if len(o) <= TRIM else o[:TRIM] + f"… [{len(o)} chars]"
    if isinstance(o, dict):
        return {str(k): _trim(v, depth + 1) for k, v in o.items()}
    if isinstance(o, list):
        if all(isinstance(x, (int, float)) for x in o):
            return o
        if len(o) > LIST_CAP:
            return [_trim(x, depth + 1) for x in o[:LIST_CAP]] + [f"… [{len(o)} items]"]
        return [_trim(x, depth + 1) for x in o]
    return o


def _wanted(value: Any, keys: List[str]) -> bool:
    v = str(value or "").strip().upper()
    if not v:
        return False
    return any(v == k or v.endswith("-" + k) or v.endswith(k) and len(k) >= 3 for k in keys)


def _row_touches(row: Dict[str, Any], keys: List[str], pages: List[int]) -> bool:
    for k in ("part_ref", "part_number", "parent", "parent_part", "grouped_under", "belongs_to",
              "parent_ref", "assembly", "under"):
        if _wanted(row.get(k), keys):
            return True
    for k in ("page", "page_number", "read_from_page", "source_page"):
        try:
            if int(row.get(k)) in pages:
                return True
        except (TypeError, ValueError):
            pass
    return False


def slice_record(d: Dict[str, Any], keys: List[str], pages: List[int]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"schema": "sdi.job_record_slice.v1", "parts_asked": keys, "pages_asked": pages,
                           "job_output_stem": d.get("job_output_stem"), "processed_at": d.get("processed_at"),
                           "environment": _trim(d.get("environment"))}
    # The part records, from both places the record keeps them.
    for pool in ("parts", ("manufacturing_writeup", "parts")):
        recs = d.get(pool) if isinstance(pool, str) else (d.get(pool[0]) or {}).get(pool[1])
        name = pool if isinstance(pool, str) else ".".join(pool)
        out[name] = [_trim(p) for p in (recs or []) if isinstance(p, dict) and _wanted(p.get("part_number"), keys)]
    # Parts-table rows that touch them, from the document analysis and the pages asked for.
    rows = (d.get("document_analysis") or {}).get("bom_rows") or []
    out["document_analysis.bom_rows"] = [_trim(r) for r in rows if isinstance(r, dict) and _row_touches(r, keys, pages)]
    page_rows: Dict[str, Any] = {}
    for i, pg in enumerate(d.get("pages") or []):
        if not isinstance(pg, dict):
            continue
        num = pg.get("page_number") or pg.get("page") or (i + 1)
        try:
            if int(num) not in pages:
                continue
        except (TypeError, ValueError):
            continue
        pa = pg.get("page_analysis") or {}
        page_rows[str(num)] = {"bom_rows": _trim(pa.get("bom_rows")),
                               "region_text.bom": _trim((pg.get("region_text") or {}).get("bom")),
                               "page_roles": _trim(pa.get("page_roles") or pg.get("page_roles")),
                               "title_block": _trim(pa.get("title_block") or pg.get("title_block"))}
    out["pages"] = page_rows
    # Route decisions about them.
    decs = ((d.get("estimate_summary") or {}).get("canonical_route_shadow") or {}).get("decisions") or []
    out["route_decisions"] = [_trim(x) for x in decs if isinstance(x, dict)
                              and (_wanted(x.get("target_id"), keys)
                                   or any(_wanted(p, keys) for p in (x.get("part_numbers") or x.get("parts") or [])))]
    # Weld-symbol reads and costed lines.
    ws = d.get("weld_symbols_by_part") or {}
    out["weld_symbols_by_part"] = {k: _trim(v) for k, v in ws.items() if _wanted(k, keys)}
    lines = (d.get("costed_job") or {}).get("lines") or []
    out["costed_job.lines"] = [_trim(l) for l in lines if isinstance(l, dict)
                               and (_wanted(l.get("part_number"), keys)
                                    or any(_wanted(p, keys) for p in (l.get("part_numbers") or [])))]
    inv = d.get("invariants")
    out["invariants"] = _trim(inv)
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("record", help="the job's <stem>.json")
    ap.add_argument("--parts", required=True, help="comma-separated part numbers or suffixes")
    ap.add_argument("--pages", default="", help="comma-separated sheet numbers")
    ap.add_argument("--timing", default="", help="the run's timing record, copied whole")
    ap.add_argument("--out", default="", help="where to write (default: beside the record, _slice.json)")
    a = ap.parse_args(argv)
    keys = [k.strip().upper() for k in a.parts.split(",") if k.strip()]
    pages = [int(x) for x in re.findall(r"\d+", a.pages)]
    with open(a.record, encoding="utf-8") as f:
        d = json.load(f)
    out = slice_record(d, keys, pages)
    if a.timing and os.path.exists(a.timing):
        with open(a.timing, encoding="utf-8") as f:
            out["timing"] = json.load(f)
    path = a.out or re.sub(r"\.json$", "", a.record) + "_slice.json"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"wrote {path} ({os.path.getsize(path) / 1024:.0f} KB) — parts {len(out['parts'])}, "
          f"rows {len(out['document_analysis.bom_rows'])}, decisions {len(out['route_decisions'])}, "
          f"lines {len(out['costed_job.lines'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
