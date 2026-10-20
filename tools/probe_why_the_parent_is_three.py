"""Ask the record — not a fixture — where a parent node's per-unit quantity comes from.

WHY THIS EXISTS. 12349-02's module -69-100 is costed at 3 per quoted unit while its own
corrected BOM row says 1. Four separate fixtures were built to reproduce that in
build_part_graph and every one produced the correct answer of 1, so the code path is not
known — and four earlier fixes on this defect were "proven" against fixtures whose shape was
chosen rather than observed. This reads the real record and prints the five facts that decide
it, so the next change is aimed at something seen rather than something assumed.

    python tools\\probe_why_the_parent_is_three.py C:\\ClaudeVision\\output\\json\\12349-02.json 12349-02-69-100

Prints, for the code given:

  1. whether it is in manufacturing_writeup.parts at all, and its quantity + source there
     — the collection the install-context correction writes into. If it is absent, that
       correction never saw it and said nothing, which looks identical to it being refused.
  2. whether a part_estimate carries it, and that record's quantity
  3. the canonical-route node: qty_per_unit, qty_own, qty_own_source, qty_note, parents
  4. every edge in the graph that names it as a child, with the quantity on that edge
     — an edge is what the cascade multiplies, and it is built from a record's quantity in
       one place and from a BOM row in another
  5. every BOM row for it, with quantity, quantity_as_printed and the parent named

Read-only. Writes nothing, changes nothing, needs no re-run.
"""
from __future__ import annotations

import json
import sys


def _nodes(doc):
    for key in ("canonical_route_shadow", "canonical_route"):
        for holder in (doc, doc.get("estimate_summary") or {}):
            if isinstance(holder, dict) and isinstance(holder.get(key), dict):
                payload = holder[key]
                if payload.get("nodes"):
                    return payload.get("nodes") or [], key
    return [], ""


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    path, code = sys.argv[1], sys.argv[2].strip().upper()
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        doc = json.load(fh)

    def _same(value) -> bool:
        return str(value or "").strip().upper().replace(" ", "") == code.replace(" ", "")

    print(f"\n=== {code} in {path}\n")

    print("1. manufacturing_writeup.parts — the list the install-context correction writes into")
    _parts = ((doc.get("manufacturing_writeup") or {}).get("parts") or [])
    _hit = [p for p in _parts if isinstance(p, dict) and _same(p.get("part_number"))]
    if not _hit:
        print(f"   NOT PRESENT among {len(_parts)} part(s). The correction loops this list, so it "
              f"never saw this code and printed nothing — indistinguishable from a refusal.")
    for p in _hit:
        print(f"   quantity={p.get('quantity')!r}  quantity_source={p.get('quantity_source')!r}")
        print(f"   displaced={((p.get('_displaced') or {}).get('quantity'))!r}")
        print(f"   corroboration={((p.get('_corroboration') or {}).get('quantity'))!r}")

    print("\n2. part_estimates")
    _pes = ((doc.get("estimate_summary") or {}).get("part_estimates")
            or doc.get("part_estimates") or [])
    for p in _pes:
        if isinstance(p, dict) and _same(p.get("part_number")):
            print(f"   quantity={p.get('quantity')!r}  quantity_own={p.get('quantity_own')!r}  "
                  f"source={p.get('quantity_own_source')!r}")
            break
    else:
        print(f"   NOT PRESENT among {len(_pes)} estimate(s)")

    nodes, which = _nodes(doc)
    print(f"\n3. {which or 'canonical route'} node — what the workbook's Qty Per Unit reads")
    for n in nodes:
        if isinstance(n, dict) and _same(n.get("part_number")):
            print(f"   qty_per_unit={n.get('qty_per_unit')!r}  qty_own={n.get('qty_own')!r}  "
                  f"qty_own_source={n.get('qty_own_source')!r}")
            print(f"   parents={n.get('parents')!r}")
            print(f"   qty_note={str(n.get('qty_note') or '')[:200]!r}")
            break
    else:
        print(f"   NOT PRESENT among {len(nodes)} node(s)")

    print("\n4. edges naming it as a CHILD — this is what the cascade multiplies")
    _found = False
    for n in nodes:
        if not isinstance(n, dict):
            continue
        for ch in (n.get("children") or []):
            if isinstance(ch, dict) and _same(ch.get("part_number")):
                print(f"   {n.get('part_number')} -> {code}  qty on the edge = {ch.get('qty')!r} "
                      f"(parent's own qty_per_unit = {n.get('qty_per_unit')!r})")
                _found = True
    if not _found:
        print("   NO EDGE names it as a child. It is a root or disconnected, so its figure came "
              "from its own record rather than from any cascade.")

    print("\n5. BOM rows")
    for row in ((doc.get("document_analysis") or {}).get("bom_rows") or []):
        if isinstance(row, dict) and _same(row.get("part_number")):
            print(f"   quantity={row.get('quantity')!r}  as_printed={row.get('quantity_as_printed')!r}"
                  f"  parent={row.get('bom_parent')!r}  source_pdf={row.get('source_pdf')!r}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
