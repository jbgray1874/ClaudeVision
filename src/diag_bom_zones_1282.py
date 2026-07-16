#!/usr/bin/env python3
"""
diag_bom_zones_1282.py  --  scope the §5 CAPTURE pattern against real text.

READ-ONLY. The first diagnostic proved 14/15 bought-in lines are never
produced. This one shows WHY, by dumping the raw input the extractor saw:

  1) what document_analysis.bom_rows actually parsed (so we know absent vs
     filtered),
  2) the region_text zones per page (esp. 'bom' and 'notes'), and
  3) for each missed Tim token, the exact line(s) it appears on in the raw
     text — so we can see if it's a table row (item# + qty columns) or a
     free-text NOTES entry, and design the capture accordingly.

Run:
    python diag_bom_zones_1282.py --job "C:\\ClaudeVision\\output\\json\\1282 - Milwaukee Wall Bay.json"

Paste the output back into the chat.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, List


# Tokens for the 14 missing lines (from diagnostic #1). Edit if a job differs.
MISSED_TOKENS = [
    "ELECTRICS", "LOOM",
    "FIXING125", "FIXING2", "FIXING49", "FIXING51", "FIXING1101",
    "SLOTTEDTUBE", "SLOTTED TUBE",
    "SUBPLAS72", "SUBPLAS",
    "VINYL03", "VINYL76", "VINYL",
    "BOX82",
    "PALLET", "PACKAGING",
    "DELIVERY", "SWADLINCOTE",
]


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def doc_analysis(doc: Dict[str, Any]) -> Dict[str, Any]:
    return (doc or {}).get("document_analysis") or {}


def page_text_blob(page: Dict[str, Any]) -> str:
    """Everything textual on a page, joined, for token grep."""
    chunks: List[str] = []
    rt = page.get("region_text") or {}
    if isinstance(rt, dict):
        for v in rt.values():
            if v:
                chunks.append(str(v))
    for key in ("pdfplumber_text", "normalized_text", "pypdf_text", "text", "text_preview"):
        v = page.get(key)
        if v:
            chunks.append(str(v))
    ps = page.get("pattern_summary") or {}
    if isinstance(ps, dict) and ps.get("raw_text"):
        chunks.append(str(ps["raw_text"]))
    return "\n".join(chunks)


def truncate(s: str, n: int = 1800) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + f"\n    ...[+{len(s)-n} chars truncated]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--zonechars", type=int, default=1800,
                    help="max chars to print per zone (default 1800)")
    args = ap.parse_args()

    try:
        doc = load_json(args.job)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR loading job JSON: {exc}", file=sys.stderr)
        return 2

    bar = "=" * 78
    da = doc_analysis(doc)
    bom_rows = da.get("bom_rows") or []

    # --- 1) what parsed -----------------------------------------------------
    print(bar)
    print(f" BOM ZONE DIAGNOSTIC — {doc.get('source_file', args.job)}")
    print(bar)
    print(f" document_analysis.bom_rows parsed: {len(bom_rows)}")
    for r in bom_rows:
        print(f"   item={str(r.get('item_number')):<4} pn={str(r.get('part_number')):<24} "
              f"qty={str(r.get('quantity')):<4} desc={str(r.get('description') or '')[:48]}")
    print()

    pages = doc.get("pages", []) or []
    print(f" pages: {len(pages)}")
    for p in pages:
        rt = p.get("region_text") or {}
        keys = list(rt.keys()) if isinstance(rt, dict) else []
        pn = p.get("page_number")
        role = (p.get("page_role") or {}).get("primary_role")
        print(f"   page {pn} role={role} region_text keys={keys}")
    print()

    # --- 2) the bom / notes zones, verbatim --------------------------------
    for zone in ("bom", "notes"):
        print("-" * 78)
        print(f" region_text['{zone}'] per page")
        print("-" * 78)
        found_any = False
        for p in pages:
            rt = p.get("region_text") or {}
            if isinstance(rt, dict) and rt.get(zone):
                found_any = True
                print(f" --- page {p.get('page_number')} [{zone}] ---")
                print(truncate(str(rt[zone]), args.zonechars))
                print()
        if not found_any:
            print(f"  (no '{zone}' zone present on any page)")
        print()

    # --- 3) where each missed token actually lives -------------------------
    print("-" * 78)
    print(" MISSED-TOKEN GREP — exact line context for each missing item")
    print("-" * 78)
    # Build a per-page line index once.
    page_lines: List[tuple] = []  # (page_number, line)
    for p in pages:
        for ln in page_text_blob(p).splitlines():
            ln = ln.rstrip()
            if ln.strip():
                page_lines.append((p.get("page_number"), ln))

    for tok in MISSED_TOKENS:
        rx = re.compile(re.escape(tok), re.IGNORECASE)
        hits = [(pgn, ln) for pgn, ln in page_lines if rx.search(ln)]
        if not hits:
            # token may be inside a collapsed (newline-free) blob — windowed search
            windows = []
            for p in pages:
                blob = page_text_blob(p)
                for m in rx.finditer(blob):
                    a, b = max(0, m.start() - 55), min(len(blob), m.end() + 55)
                    windows.append((p.get("page_number"), "…" + blob[a:b].replace("\n", " ") + "…"))
            hits = windows[:3]
        print(f"\n  '{tok}': {len(hits)} hit(s)")
        for pgn, ln in hits[:4]:
            print(f"      p{pgn}: {ln[:150]}")
    print()
    print(bar)
    print(" Paste this whole output back. Key questions it answers:")
    print("  • Are the missed items in a 'bom' zone (table) or 'notes' (free text)?")
    print("  • Do their lines carry an item number AND a trailing qty (table cols)?")
    print("  • Do their codes have NO internal hyphen (why QTY_TABLE_ROW_PATTERN skips)?")
    print(bar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
