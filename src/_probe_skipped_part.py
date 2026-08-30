#!/usr/bin/env python3
r"""
_probe_skipped_part.py  —  READ-ONLY.

12532 skipped 12532-04-01G: "unclassifiable (stock_form='', role=[], unit=None,
ext=0.42, blankL=2106.0) — skipped." With NO manual sheet to compare, a silent drop
on this job is the worst case. This probe determines whether the skipped part is:

  (A) a GENUINE fabricated part wrongly dropped (real bug — cost missing), or
  (B) a GA / assembly-rollup node correctly excluded because its cost is carried by
      its children (correct behaviour, just poorly worded as 'unclassifiable').

It dumps, for the skipped part(s) and their likely children:
  - full identity: part_number, description, role, page_roles, material, stock_form
  - is it an assembly/GA node? (part number ends -G / -GA / has assembly role /
    has children referencing it)
  - its geometry (does it have real dimensions/DXF -> looks fabricated, or empty ->
    looks like a rollup)
  - its cost fields (unit/extended) and whether children exist that would carry it
  - the classify path: WHY wb_populate couldn't place it (stock_form/role/material all
    empty -> falls through every block test)

Also lists ALL parts whose block would be 'other'/unclassifiable, so we see if 04-01G
is alone or part of a pattern (e.g. all -G GA nodes).

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_skipped_part.py ^
      "C:\ClaudeVision\output\json\12532-03RecipeCard.json"
"""
import sys, json

TARGETS = ("12532-04-01G",)  # extend if more skipped


def find_parts(obj):
    out, seen = [], set()
    def walk(o):
        if isinstance(o, dict):
            if "part_number" in o:
                if id(o) not in seen:
                    seen.add(id(o)); out.append(o)
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(obj)
    best = {}
    for d in out:
        pn = str(d.get("part_number"))
        if pn not in best or len(d.keys()) > len(best[pn].keys()):
            best[pn] = d
    return best  # dict pn->part


def geom_summary(pe):
    for key in ("geometry_rollup", "normalized_geometry", "dxf_raw_geometry"):
        g = pe.get(key)
        if isinstance(g, dict):
            cl = g.get("estimated_cut_length_mm") or g.get("cut_length_mm")
            if cl:
                return f"{key}: cut_len={cl}, holes={g.get('estimated_hole_count') or g.get('hole_count')}"
    return "no real geometry (no cut length) — looks non-fabricated"


def looks_like_ga(pn, pe):
    reasons = []
    if pn.upper().endswith(("-G", "-GA", "-GA-")) or "-GA" in pn.upper():
        reasons.append("part number has GA/-G suffix")
    roles = [str(r).lower() for r in (pe.get("page_roles") or pe.get("roles") or [])]
    if "assembly" in roles:
        reasons.append("has 'assembly' page role")
    if pe.get("assembly_candidate"):
        reasons.append("assembly_candidate=True")
    return reasons


def main(jpath):
    parts = find_parts(json.load(open(jpath, "r", encoding="utf-8")))

    print("=" * 92)
    print("SKIPPED-PART PROBE (read-only) — is it a real drop or a GA node?")
    print("=" * 92)

    for tpn in TARGETS:
        pe = parts.get(tpn)
        if not pe:
            print(f"\n{tpn}: NOT FOUND in parts — deeper issue (part vanished before roster).")
            continue
        print(f"\n── {tpn} ──")
        print(f"  description : {pe.get('description')!r}")
        print(f"  page_roles  : {pe.get('page_roles') or pe.get('roles')}")
        print(f"  material    : {pe.get('normalized_material')!r}")
        print(f"  stock_form  : {(pe.get('material_estimate') or {}).get('stock_form')!r}")
        print(f"  quantity    : {pe.get('quantity')}  ext_qty: {pe.get('extended_quantity')}")
        print(f"  unit_cost   : {pe.get('unit_cost_gbp')}  extended: {pe.get('extended_cost_gbp')}")
        print(f"  ops         : {pe.get('textual_operations')}")
        print(f"  geometry    : {geom_summary(pe)}")
        ga = looks_like_ga(tpn, pe)
        print(f"  GA node?    : {'YES — ' + '; '.join(ga) if ga else 'no GA markers'}")

        # do children reference it? find parts whose number is a longer form / assembly ref
        base = tpn.rsplit("-", 1)[0]  # e.g. 12532-04
        children = [p for p in parts if p != tpn and p.startswith(base) and p != tpn]
        print(f"  possible children (share {base}): {children}")
        if children:
            tot = 0.0
            for c in children:
                ec = parts[c].get("extended_cost_gbp") or parts[c].get("unit_cost_gbp") or 0
                try: tot += float(ec)
                except: pass
            print(f"    -> children carry ~£{tot:.2f} of cost (if this is a GA node, its cost IS here)")

        # verdict
        print("  VERDICT:")
        if ga and geom_summary(pe).startswith("no real"):
            print("    (B) Looks like a GA/assembly NODE (GA markers + no fabrication geometry).")
            print("        Skipping is CORRECT behaviour but the message should say 'assembly")
            print("        rollup excluded — carried by children', not 'unclassifiable'.")
        elif not ga and not geom_summary(pe).startswith("no real"):
            print("    (A) Looks like a REAL FABRICATED part (has geometry, no GA markers).")
            print("        This is a GENUINE DROP — cost is missing. Needs a classification fix.")
        else:
            print("    AMBIGUOUS — has some fabrication signal but empty classification fields.")
            print("        Inspect above: geometry present -> lean real drop; empty -> lean GA node.")

    # pattern check: any other parts that would be unclassifiable (empty stock_form+role+material)
    print("\n" + "-" * 92)
    print("PATTERN CHECK — other parts with empty stock_form AND empty role AND no material:")
    n = 0
    for pn, pe in parts.items():
        sf = (pe.get("material_estimate") or {}).get("stock_form")
        roles = pe.get("page_roles") or pe.get("roles")
        mat = pe.get("normalized_material")
        if not sf and not roles and not mat:
            print(f"  {pn}: desc={pe.get('description')!r} ops={pe.get('textual_operations')}")
            n += 1
    if n == 0:
        print("  none — 12532-04-01G is the only one (isolated case, not a pattern).")
    print("=" * 92)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_skipped_part.py <summary.json>"); sys.exit(1)
    main(sys.argv[1])
