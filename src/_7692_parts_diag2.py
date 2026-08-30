#!/usr/bin/env python3
r"""
_7692_parts_diag2.py   (READ-ONLY — writes nothing, patches nothing)

Uses the real file_scan entry points to build 7692's parts and dump each, so we can see the
origin of the '2.5mm ACRYLIC' phantom (no part number, invents diamond_polish/manual_labour)
and the 'None BASE BODY 1 2' junk Other-Sheet row.

It tries, in order:
  1. scan_folder_job(FOLDER)            — the folder scanner
  2. estimate_document(<result>)         — if step 1 returns a doc/summary, cost it
It then locates the parts list in whatever comes back and prints, per part:
  part_number, description, material, thickness, blank LxW, stock_form, roles,
  is_assembly_parent, source — flagging phantom-shaped rows.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _7692_parts_diag2.py
"""
from __future__ import annotations
import os, sys, inspect, json

FOLDER = r"K:\Estimating\Completed\AI Estimating\Live Enquiry\7692-01-GA Single-Sided Impulse Unit (Rev B)"

def _g(d, *keys, default=""):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default

def _find_parts(obj, depth=0, path="root"):
    """Recursively hunt for a list of dicts that look like parts (have part_number or material)."""
    if depth > 4:
        return None, None
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys = set()
        for it in obj[:5]:
            if isinstance(it, dict):
                keys |= set(it.keys())
        if keys & {"part_number", "normalized_material", "material", "material_estimate", "blank_length_mm"}:
            return obj, path
    if isinstance(obj, dict):
        for k, v in obj.items():
            found, p = _find_parts(v, depth + 1, f"{path}.{k}")
            if found is not None:
                return found, p
    return None, None

def _call(fn, *args):
    """Call fn trying a couple of signatures."""
    try:
        return fn(*args)
    except TypeError:
        # try with keyword as_job / folder_as_job
        try:
            return fn(args[0], as_job=True)
        except Exception:
            try:
                return fn(args[0], True)
            except Exception as e:
                raise e

def main():
    try:
        import file_scan
    except Exception as e:
        sys.exit(f"could not import file_scan: {e}")

    # Step 1: scan_folder_job
    if not hasattr(file_scan, "scan_folder_job"):
        sys.exit("file_scan has no scan_folder_job — tell me and I'll adjust.")
    sfj = file_scan.scan_folder_job
    print("scan_folder_job signature:", str(inspect.signature(sfj)))
    try:
        res = _call(sfj, FOLDER)
        print("scan_folder_job returned:", type(res).__name__)
    except Exception as e:
        sys.exit(f"scan_folder_job failed: {e}")

    parts, where = _find_parts(res)

    # Step 2: if no parts yet, try estimate_document on the scan result
    if parts is None and hasattr(file_scan, "estimate_document"):
        ed = file_scan.estimate_document
        print("estimate_document signature:", str(inspect.signature(ed)))
        try:
            doc = _call(ed, res)
            print("estimate_document returned:", type(doc).__name__)
            parts, where = _find_parts(doc)
        except Exception as e:
            print(f"estimate_document failed: {e}")

    if parts is None:
        print("\nCould not auto-locate a parts list. Top-level structure:")
        if isinstance(res, dict):
            for k, v in res.items():
                print(f"  {k}: {type(v).__name__}" + (f" (len {len(v)})" if hasattr(v, '__len__') else ""))
        else:
            print("  ", type(res).__name__)
        sys.exit("Paste this structure and I'll point the dumper at the right key.")

    print(f"\nFound {len(parts)} parts at: {where}\n")
    print("=" * 104)
    for i, p in enumerate(parts):
        pn   = _g(p, "part_number", default="(NONE)")
        desc = _g(p, "description", default="(none)")
        mat  = _g(p, "normalized_material", "material", default="(none)")
        thk  = _g(p, "normalized_thickness_mm", "thickness_mm", default="")
        me   = p.get("material_estimate") or {}
        ng   = p.get("normalized_geometry") or {}
        bl   = _g(me, "blank_length_mm", default=_g(ng, "blank_length_mm", default=_g(p, "blank_length_mm", default="")))
        bw   = _g(me, "blank_width_mm", default=_g(ng, "blank_width_mm", default=_g(p, "blank_width_mm", default="")))
        sf   = _g(p, "stock_form", default="")
        roles= _g(p, "page_roles", "page_role", "roles", default="")
        par  = p.get("is_assembly_parent", False)
        src  = _g(p, "source", "source_file", "origin", "provenance", "source_pdf", default="")
        flags = ""
        if pn == "(NONE)" or not str(pn).strip():
            flags += " <<NO-PN"
        if not (bl and bw):
            flags += " <<NO-GEO"
        if str(mat).upper() in ("ACRYLIC","PERSPEX","PMMA","POLYCARBONATE","HIGH IMPACT ACRYLIC"):
            flags += " <<ACRYLIC-ROUTE"
        if "BASE BODY" in str(desc).upper() and str(pn) == "(NONE)":
            flags += " <<JUNK-ROW?"
        print(f"[{i:2}] PN={pn!r} desc={desc!r}")
        print(f"     mat={mat!r} thk={thk} blank={bl}x{bw} stock_form={sf!r} roles={roles!r} parent={par} src={src!r}{flags}")
    print("=" * 104)
    print("\nWatch for: a row with NO-PN + ACRYLIC-ROUTE (the phantom that invents")
    print("diamond_polish/manual_labour), and the BASE BODY junk row. Paste it all back.")

if __name__ == "__main__":
    main()
