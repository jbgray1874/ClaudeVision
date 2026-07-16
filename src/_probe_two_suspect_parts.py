#!/usr/bin/env python3
r"""
_probe_two_suspect_parts.py  —  READ-ONLY.

Two 12532 parts where the VALUE (not just a label) could be wrong, both because they
derive from assembly pages rather than their own detail drawing:

  #3  12532-02-302 'FRONT PANEL 1' — sits in the BOM at £14.50. Is that a REAL price
      (catalogue / historical / recognised bought-in) or a placeholder/stub? It's an
      assembly-ish part; if £14.50 is a stand-in, the sub-parts may be uncosted.

  #10 12532-03-06M 'BACK WALL' — a STEEL part flagged 'assembly_only_part_record'
      (no own detail page; geometry came from an assembly page). Are its dimensions
      (part_length / part_width / blank) plausible, or artefacts of an assembly-page
      read? Compare its geometry source + extents against a normal detail-page steel
      part (e.g. 03-03M SHELF BODY, which has its own page).

Dumps for each: price/cost fields + their source, geometry_source, dimensions, blank,
page(s), page_roles, validation flags. Read-only — decides whether either needs a fix
before the number goes out, or whether both are acceptable-with-a-note.

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_two_suspect_parts.py ^
      "C:\ClaudeVision\output\json\12532-03RecipeCard.json"
"""
import sys, json


def find_part(data, pn):
    best = None
    def walk(o):
        nonlocal best
        if isinstance(o, dict):
            if str(o.get("part_number")) == pn:
                if best is None or len(o.keys()) > len(best.keys()):
                    best = o
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(data)
    return best


def g(pe, *keys):
    for k in keys:
        v = pe.get(k)
        if v not in (None, "", []):
            return v
    return None


def dump_price(pe, pn):
    print(f"\n{'='*84}\n[PRICE] {pn}  {pe.get('description')!r}")
    me = pe.get("material_estimate") or {}
    print(f"  unit_cost_gbp            = {pe.get('unit_cost_gbp')!r}")
    print(f"  unit_material_cost_gbp   = {g(pe,'unit_material_cost_gbp') or me.get('unit_material_cost_gbp')!r}")
    print(f"  extended_estimate/cost   = {g(pe,'extended_estimate','extended_material_cost_gbp')!r}")
    print(f"  unit_estimate            = {g(pe,'unit_estimate')!r}")
    print(f"  source                   = {g(pe,'source')!r}")
    print(f"  cost_source              = {g(pe,'cost_source')!r}")
    print(f"  price_verified           = {pe.get('price_verified')!r}")
    print(f"  supplier                 = {g(pe,'supplier','supplier_name')!r}")
    print(f"  page_roles               = {pe.get('page_roles')!r}")
    print(f"  pages                    = {pe.get('pages')!r}")
    # any review flags mentioning provisional/placeholder/stub?
    rf = pe.get("review_flags") or []
    print(f"  review_flags             = {rf!r}")
    blob = json.dumps(pe).lower()
    for kw in ("provisional", "placeholder", "stub", "estimator_to_price", "udef", "historical", "catalogue"):
        if kw in blob:
            print(f"    contains {kw!r}: yes")


def dump_geom(pe, pn):
    print(f"\n{'='*84}\n[GEOM] {pn}  {pe.get('description')!r}")
    me = pe.get("material_estimate") or {}
    ng = pe.get("normalized_geometry") or {}
    print(f"  geometry_source          = {g(pe,'geometry_source')!r}")
    print(f"  dxf_source_file          = {g(pe,'dxf_source_file')!r}")
    print(f"  flat_pattern_detected    = {pe.get('flat_pattern_detected')!r}")
    print(f"  part_length_mm           = {g(me,'part_length_mm') or g(pe,'part_length_mm') or ng.get('part_length_mm')!r}")
    print(f"  part_width_mm            = {g(me,'part_width_mm') or g(pe,'part_width_mm') or ng.get('part_width_mm')!r}")
    print(f"  blank_length_mm          = {g(me,'blank_length_mm') or ng.get('blank_length_mm')!r}")
    print(f"  blank_width_mm           = {g(me,'blank_width_mm') or ng.get('blank_width_mm')!r}")
    print(f"  normalized_thickness_mm  = {pe.get('normalized_thickness_mm')!r}")
    print(f"  estimated_cut_length_mm  = {ng.get('estimated_cut_length_mm', (pe.get('geometry') or {}).get('estimated_cut_length_mm'))!r}")
    print(f"  page_roles               = {pe.get('page_roles')!r}")
    print(f"  pages                    = {pe.get('pages')!r}")


def main(jpath):
    data = json.load(open(jpath, "r", encoding="utf-8"))

    print("SUSPECT-PART DILIGENCE PROBE (read-only) — verify VALUES before report")

    # #3 price provenance
    p302 = find_part(data, "12532-02-302")
    if p302: dump_price(p302, "12532-02-302")
    else: print("\n12532-02-302 NOT FOUND")

    # #10 geometry of assembly-only steel part vs a normal detail-page steel part
    p0306 = find_part(data, "12532-03-06M")
    p0303 = find_part(data, "12532-03-03M")  # control: has own detail page (18)
    if p0306: dump_geom(p0306, "12532-03-06M  (assembly-only — SUSPECT)")
    else: print("\n12532-03-06M NOT FOUND")
    if p0303: dump_geom(p0303, "12532-03-03M  (own detail page 18 — CONTROL)")
    else: print("\n12532-03-03M NOT FOUND")

    print(f"\n{'='*84}")
    print("READ:")
    print(" #3  02-302 £14.50 — if source is historical/catalogue/udef and price_verified,")
    print("     it's a REAL price -> fine. If 'estimator_to_price'/provisional/stub ->")
    print("     flag as needs-estimator-pricing in the report.")
    print(" #10 03-06M — compare its dims/cut_length to the 03-03M control. If similar")
    print("     order of magnitude and plausible for a BACK WALL, accept with a note.")
    print("     If wildly off (assembly-page extents), flag geometry as low-confidence.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_two_suspect_parts.py <json>"); sys.exit(1)
    main(sys.argv[1])
