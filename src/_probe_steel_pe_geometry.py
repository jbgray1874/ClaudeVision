#!/usr/bin/env python3
r"""
_probe_steel_pe_geometry.py  —  READ-ONLY. Writes nothing.

The holes/T patch reads:  pe.get("geometry").get("estimated_hole_count")
                          pe.get("geometry").get("estimated_cut_length_mm")
...but S38/T38 came back blank. That means, for the steel part as the WB writer
sees it, geometry is under a DIFFERENT key or nested deeper. This probe dumps the
exact structure so we fix the path precisely (no guessing).

It loads the summary JSON, finds the steel part record (1300-01), and shows:
  - every top-level key on the part
  - the value/location of any key containing 'hole' or 'cut_length' ANYWHERE in
    the part (recursive), with its full path
  - what pe.get("geometry") actually returns

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_steel_pe_geometry.py ^
      "C:\ClaudeVision\output\json\1300-01FlatShelf.json"
"""
import sys, json

TARGET = "1300-01"


def find_parts(obj):
    out = []
    def walk(o, p):
        if isinstance(o, dict):
            k = set(o.keys())
            if "part_number" in k or ("material" in k and ("geometry" in k or "material_estimate" in k)):
                out.append((p, o))
            for kk, vv in o.items():
                walk(vv, f"{p}.{kk}")
        elif isinstance(o, list):
            for i, vv in enumerate(o):
                walk(vv, f"{p}[{i}]")
    walk(obj, "root")
    return out


def find_key_paths(o, needle, path="pe"):
    hits = []
    if isinstance(o, dict):
        for k, v in o.items():
            if needle in k.lower():
                disp = v if not isinstance(v, (dict, list)) else f"<{type(v).__name__}>"
                hits.append((f"{path}.{k}", disp))
            hits += find_key_paths(v, needle, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            hits += find_key_paths(v, needle, f"{path}[{i}]")
    return hits


def main(jpath):
    data = json.load(open(jpath, "r", encoding="utf-8"))
    parts = find_parts(data)
    # pick the steel part: has a part_number containing 1300-01 AND is not a placeholder
    steel = None
    for p, d in parts:
        pn = str(d.get("part_number") or "")
        if TARGET in pn and (d.get("normalized_material") or d.get("material") or "").upper().replace(" ", "_") == "MILD_STEEL":
            steel = (p, d); break
    if not steel:
        for p, d in parts:
            if TARGET in str(d.get("part_number") or ""):
                steel = (p, d); break
    if not steel:
        print("Could not find 1300-01 part."); return

    ppath, pe = steel
    print("=" * 78)
    print("STEEL PART GEOMETRY PATH PROBE (read-only)")
    print("=" * 78)
    print(f"part at: {ppath}")
    print(f"part_number: {pe.get('part_number')}")
    print(f"\ntop-level keys on the part record:")
    for k in pe.keys():
        v = pe[k]
        t = type(v).__name__
        print(f"   {k}  <{t}>")

    print(f"\npe.get('geometry') is: {type(pe.get('geometry')).__name__}")
    g = pe.get("geometry")
    if isinstance(g, dict):
        print(f"   geometry keys: {list(g.keys())}")
        print(f"   geometry.estimated_hole_count      = {g.get('estimated_hole_count')}")
        print(f"   geometry.estimated_cut_length_mm   = {g.get('estimated_cut_length_mm')}")

    print(f"\nALL paths containing 'hole':")
    for path, val in find_key_paths(pe, "hole"):
        print(f"   {path} = {val}")

    print(f"\nALL paths containing 'cut_length':")
    for path, val in find_key_paths(pe, "cut_length"):
        print(f"   {path} = {val}")

    print("\n" + "-" * 78)
    print("FIX: point the patch at whichever path above actually holds the values.")
    print("=" * 78)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_steel_pe_geometry.py <summary.json>"); sys.exit(1)
    main(sys.argv[1])
