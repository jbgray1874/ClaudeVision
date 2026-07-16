#!/usr/bin/env python3
r"""
_probe_parts_routes_counts_v2.py  —  READ-ONLY. Writes nothing.

FIX over v1: v1 walked the ENTIRE json tree and matched every part dict wherever
it appeared (roster, bom_tree, bay_rollup, labour, provenance...), so each part
printed 5-8x and every COUNT was inflated (353 records for a ~30-part job).

v2 finds the ONE canonical part list and reports each part exactly once. It:
  - locates the canonical list: the longest list of dicts that (a) all have
    part_number and (b) mostly carry role/material/route (the hydrated roster),
    NOT the shadow copies in trees/rollups.
  - dedupes by part_number (keeps the most-hydrated record if a PN repeats).
  - prints per part: PN, role, material, inferred WB block, qty, geom, route (+WELD flag).
  - correct block counts, overflow check, operation tally, summary.

If the canonical-list detection looks wrong, it PRINTS which json path it chose and
how many candidate lists it saw, so we can see its working (no silent guess).

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_parts_routes_counts_v2.py ^
      "C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
"""
import sys, json, collections

PLACEHOLDERS = {"PACKAGING", "DELIVERY", "CARRIAGE", "HAULAGE"}
WELD_OPS = {"welding", "spot_welding", "resistance_welding", "dress_welds"}
CAP_BOM, CAP_STEEL, CAP_OTHER, CAP_TUBE = 15, 11, 8, 8


def hydration_score(d):
    """How 'real' a part record is: rewards role/material/ops/geometry presence."""
    s = 0
    for k in ("page_roles", "roles"):
        if d.get(k): s += 2
    for k in ("normalized_material", "materials", "material"):
        if d.get(k): s += 1; break
    for k in ("textual_operations", "operations"):
        if d.get(k): s += 2; break
    if d.get("geometry_source"): s += 1
    if d.get("material_estimate"): s += 1
    if d.get("geometry_rollup") or d.get("normalized_geometry"): s += 1
    return s


def all_part_lists(obj):
    """Every list whose items are dicts with part_number. Returns (path, list)."""
    found = []
    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            if o and all(isinstance(x, dict) and "part_number" in x for x in o):
                found.append((path, o))
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
    walk(obj, "root")
    return found


def pick_canonical(lists):
    """
    The canonical roster is the list with the highest TOTAL hydration across its
    members (the fully-built part records), tie-broken by length. Shadow lists in
    trees/rollups have low hydration (just PN + qty).
    """
    best, best_key = None, (-1, -1)
    for path, lst in lists:
        total_hydration = sum(hydration_score(d) for d in lst)
        key = (total_hydration, len(lst))
        if key > best_key:
            best_key, best = key, (path, lst)
    return best


def role_of(pe):
    r = pe.get("page_roles") or pe.get("roles") or []
    if isinstance(r, str): r = [r]
    return ",".join(str(x) for x in r) or "?"


def material_of(pe):
    return str(pe.get("normalized_material") or (pe.get("materials") or [None])[0]
               or pe.get("material") or "?").upper()


def stock_form_of(pe):
    me = pe.get("material_estimate") or {}
    return str(me.get("stock_form") or pe.get("stock_form") or "").lower()


def ops_of(pe):
    o = pe.get("textual_operations") or pe.get("operations") or []
    if isinstance(o, str): o = [o]
    return [str(x) for x in o]


def classify_block(pe):
    role = role_of(pe).lower(); mat = material_of(pe); sf = stock_form_of(pe)
    pn = str(pe.get("part_number") or "").upper()
    desc = str(pe.get("description") or "").upper()
    if any(p in pn for p in PLACEHOLDERS): return "placeholder"
    if "bought_in" in role and mat not in ("MILD_STEEL", "MILD STEEL", "STAINLESS_STEEL",
                                           "ALUMINIUM", "ACRYLIC", "HIPS", "CARD"):
        return "bought_in"
    # a part with a fabrication route is FABRICATED even if role includes bought_in
    fab_ops = {"laser_cutting", "folding", "punch", "powder_coating", "welding", "diamond_polish"}
    is_fab = bool(set(ops_of(pe)) & fab_ops) or pe.get("geometry_source", "").startswith("dxf")
    if "tube" in sf or "section" in sf or "ERW" in desc: return "tube"
    if mat in ("ACRYLIC", "HIPS", "PETG", "PET", "MDF", "TIMBER", "FOAMEX", "CARD") or "acrylic" in sf:
        return "other_sheet"
    if mat in ("MILD_STEEL", "MILD STEEL", "STAINLESS_STEEL", "ZINTEC", "GALVANISED", "ALUMINIUM"):
        return "steel" if is_fab else "steel"
    if "bought_in" in role: return "bought_in"
    return "other"


def main(jpath):
    data = json.load(open(jpath, "r", encoding="utf-8"))
    lists = all_part_lists(data)
    picked = pick_canonical(lists)
    if not picked:
        print("No part list found."); return
    cpath, canonical = picked

    # dedupe by part_number, keep most-hydrated
    by_pn = {}
    for d in canonical:
        pn = str(d.get("part_number") or "?")
        if pn not in by_pn or hydration_score(d) > hydration_score(by_pn[pn]):
            by_pn[pn] = d
    parts = list(by_pn.values())

    print("=" * 92)
    print("PARTS / ROUTES / COUNTS AUDIT v2 (read-only)")
    print(f"job: {data.get('source_file') or jpath}")
    print(f"canonical list: {cpath}  ({len(canonical)} rows -> {len(parts)} unique parts)")
    print(f"(saw {len(lists)} candidate part-lists in the JSON; picked the most-hydrated)")
    print("=" * 92)
    print(f"{'part':<16}{'role':<12}{'material':<11}{'blk':<11}{'qty':>4} {'geom':<15}{'route'}")
    print("-" * 92)

    blocks = collections.Counter()
    op_tally = collections.Counter()
    members = collections.defaultdict(list)

    for pe in sorted(parts, key=lambda p: str(p.get("part_number"))):
        pn = str(pe.get("part_number") or "?")[:15]
        role = role_of(pe)[:11]
        mat = material_of(pe)[:10]
        blk = classify_block(pe)
        qty = pe.get("quantity") or pe.get("extended_quantity") or 1
        gs = str(pe.get("geometry_source") or "?")[:14]
        ops = ops_of(pe)
        route = ", ".join(ops) if ops else "—"
        weld = "  ⚠WELD" if any(o in WELD_OPS for o in ops) else ""
        blocks[blk] += 1
        members[blk].append(pn)
        for o in ops: op_tally[o] += 1
        print(f"{pn:<16}{role:<12}{mat:<11}{blk:<11}{str(qty):>4} {gs:<15}{route}{weld}")

    print("-" * 92)
    print("\nBLOCK COUNTS (parts routed to each WB block, deduped):")
    for blk in ("steel", "other_sheet", "tube", "weldment", "bought_in", "placeholder", "other"):
        n = blocks.get(blk, 0)
        if not n: continue
        cap = {"steel": CAP_STEEL, "other_sheet": CAP_OTHER, "tube": CAP_TUBE}.get(blk)
        msg = ""
        if cap and n > cap:
            msg = f"   ⚠ OVERFLOW {n}>{cap}: drops {', '.join(members[blk][cap:])}"
        elif cap:
            msg = f"   (cap {cap}, ok)"
        print(f"   {blk:<12}: {n}{msg}")

    bom_like = blocks.get("bought_in", 0) + blocks.get("tube", 0)
    print(f"\n   BOM block (bought_in+tube share 15 rows): {bom_like}"
          + (f"   ⚠ OVERFLOW by {bom_like-CAP_BOM}" if bom_like > CAP_BOM else "   (ok)"))

    print("\nOPERATION TALLY (unique parts carrying each op):")
    for op, n in op_tally.most_common():
        print(f"   {op:<20}: {n}{'  ⚠' if op in WELD_OPS else ''}")

    fab = sum(blocks.get(b, 0) for b in ("steel", "other_sheet", "weldment", "tube"))
    print("\nSUMMARY:")
    print(f"   fabricated parts : {fab}")
    print(f"   bought-in        : {blocks.get('bought_in', 0)}")
    print(f"   placeholders     : {blocks.get('placeholder', 0)}")
    print(f"   other/unclassed  : {blocks.get('other', 0)}")
    print(f"   UNIQUE parts     : {len(parts)}")
    print(f"   weld-carrying    : {sum(1 for pe in parts if any(o in WELD_OPS for o in ops_of(pe)))}")
    print("=" * 92)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_parts_routes_counts_v2.py <summary.json>"); sys.exit(1)
    main(sys.argv[1])
