#!/usr/bin/env python3
r"""
_probe_parts_routes_counts.py  —  READ-ONLY. Writes nothing.

Systematic audit of a job's PART ROSTER, ROUTES and COUNTS, so we can check the
engine's parts against the drawing/manual instead of assuming. For each part it
reports:
  - part number, description, material, page role (detail / assembly / bought_in)
  - quantity, and whether a bay/GA multiplier changed it (base vs effective)
  - the operation ROUTE (ordered ops), flagging weld/spot ops so routing is visible
  - geometry source (dxf_flat_pattern / pdf) + reliability
  - whether it will land in the WB or be DROPPED by the 15-BOM / 11-steel row caps

Then it summarises:
  - fabricated vs bought-in vs placeholder counts
  - which block each fabricated part routes to (steel / other-sheet / weldment / tube)
  - OVERFLOW check: >15 BOM/tube or >11 steel -> names the parts that overflow
  - a per-operation tally across the job (how many laser vs punch vs fold vs weld...)

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_parts_routes_counts.py ^
      "C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_parts_routes_counts.py ^
      "C:\ClaudeVision\output\json\12532-03RecipeCard.json"
"""
import sys, json, collections

STEEL_FORMS = {"sheet", "sheet_steel", "steel"}
PLACEHOLDERS = {"PACKAGING", "DELIVERY", "CARRIAGE", "HAULAGE"}
WELD_OPS = {"welding", "spot_welding", "resistance_welding", "dress_welds"}

# row caps from wb_populate CELL_MAP
CAP_BOM = 15      # rows 11-25
CAP_STEEL = 11    # rows 38-48
CAP_OTHER = 8     # rows 51-58
CAP_TUBE = 8      # rows 28-35


def g(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default


def find_parts(obj):
    out = []
    def walk(o, p):
        if isinstance(o, dict):
            k = set(o.keys())
            if "part_number" in k and ("page_roles" in k or "material" in k
                                       or "textual_operations" in k or "quantity" in k):
                out.append(o)
            for vv in o.values():
                walk(vv, p)
        elif isinstance(o, list):
            for vv in o:
                walk(vv, p)
    walk(obj, "root")
    # de-dup by id() — same dict can appear under multiple keys
    seen, uniq = set(), []
    for d in out:
        if id(d) not in seen:
            seen.add(id(d)); uniq.append(d)
    return uniq


def role_of(pe):
    roles = pe.get("page_roles") or pe.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    return ",".join(str(r) for r in roles) or "?"


def material_of(pe):
    return str(pe.get("normalized_material") or (pe.get("materials") or [None])[0]
               or pe.get("material") or "?").upper()


def stock_form_of(pe):
    me = pe.get("material_estimate") or {}
    return str(g(me, "stock_form") or pe.get("stock_form") or "").lower()


def ops_of(pe):
    ops = pe.get("textual_operations") or pe.get("operations") or []
    if isinstance(ops, str):
        ops = [ops]
    return [str(o) for o in ops]


def classify_block(pe):
    role = role_of(pe).lower()
    mat = material_of(pe)
    sf = stock_form_of(pe)
    pn = str(pe.get("part_number") or "").upper()
    if any(p in pn for p in PLACEHOLDERS):
        return "placeholder"
    if "bought_in" in role:
        return "bought_in"
    if "tube" in sf or "section" in sf or "erw" in (str(pe.get("description") or "").upper()):
        return "tube"
    if mat in ("ACRYLIC", "HIPS", "PETG", "PET", "MDF", "TIMBER", "FOAMEX") or "acrylic" in sf:
        return "other_sheet"
    if pe.get("reliability_flags") and any("weldment_parent" in str(f) for f in pe.get("reliability_flags")):
        return "weldment"
    if mat in ("MILD_STEEL", "MILD STEEL", "STAINLESS_STEEL", "ZINTEC", "GALVANISED", "ALUMINIUM"):
        return "steel"
    return "other"


def main(jpath):
    data = json.load(open(jpath, "r", encoding="utf-8"))
    parts = find_parts(data)

    print("=" * 92)
    print("PARTS / ROUTES / COUNTS AUDIT (read-only)")
    print(f"job: {data.get('source_file') or jpath}")
    print("=" * 92)
    print(f"{'part':<16}{'role':<10}{'material':<12}{'blk':<11}{'qty':>4} {'geom':<16}{'route'}")
    print("-" * 92)

    blocks = collections.Counter()
    op_tally = collections.Counter()
    block_members = collections.defaultdict(list)

    for pe in parts:
        pn = str(pe.get("part_number") or "?")[:15]
        role = role_of(pe)[:9]
        mat = material_of(pe)[:11]
        blk = classify_block(pe)
        qty = pe.get("quantity") or pe.get("extended_quantity") or 1
        gs = str(pe.get("geometry_source") or "?")[:15]
        ops = ops_of(pe)
        route = ", ".join(ops) if ops else "—"
        weldmark = "  ⚠WELD" if any(o in WELD_OPS for o in ops) else ""
        blocks[blk] += 1
        block_members[blk].append(pn)
        for o in ops:
            op_tally[o] += 1
        print(f"{pn:<16}{role:<10}{mat:<12}{blk:<11}{str(qty):>4} {gs:<16}{route}{weldmark}")

    print("-" * 92)
    print("\nBLOCK COUNTS (how many parts route to each WB block):")
    for blk in ("steel", "other_sheet", "tube", "weldment", "bought_in", "placeholder", "other"):
        n = blocks.get(blk, 0)
        cap = {"steel": CAP_STEEL, "other_sheet": CAP_OTHER, "tube": CAP_TUBE}.get(blk)
        capmsg = ""
        if cap and n > cap:
            capmsg = f"   ⚠ OVERFLOW: {n} > {cap} rows -> {n-cap} DROPPED: {', '.join(block_members[blk][cap:])}"
        elif cap:
            capmsg = f"   (cap {cap}, ok)"
        if n:
            print(f"   {blk:<12}: {n}{capmsg}")

    # BOM block = bought_in + tube share the 15-row BOM block in wb_populate
    bom_like = blocks.get("bought_in", 0) + blocks.get("tube", 0)
    print(f"\n   BOM block (bought_in + tube share 15 rows): {bom_like}"
          + (f"   ⚠ OVERFLOW by {bom_like-CAP_BOM}" if bom_like > CAP_BOM else "   (ok)"))

    print("\nOPERATION TALLY (route audit — how many parts carry each op):")
    for op, n in op_tally.most_common():
        mark = "  ⚠" if op in WELD_OPS else ""
        print(f"   {op:<22}: {n}{mark}")

    print("\nSUMMARY:")
    fab = blocks.get("steel", 0) + blocks.get("other_sheet", 0) + blocks.get("weldment", 0) + blocks.get("tube", 0)
    print(f"   fabricated parts : {fab}")
    print(f"   bought-in        : {blocks.get('bought_in', 0)}")
    print(f"   placeholders     : {blocks.get('placeholder', 0)}")
    print(f"   TOTAL records    : {len(parts)}")
    print(f"   weld-carrying    : {sum(1 for pe in parts if any(o in WELD_OPS for o in ops_of(pe)))}")
    print("=" * 92)
    print("Compare part roster + qty + route above against the drawing BOM / manual sheet.")
    print("Any ⚠ OVERFLOW = parts that won't reach the workbook. Any ⚠WELD = verify it's real.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_parts_routes_counts.py <summary.json>"); sys.exit(1)
    main(sys.argv[1])
