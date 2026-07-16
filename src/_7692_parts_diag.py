#!/usr/bin/env python3
r"""
_7692_parts_diag.py   (READ-ONLY diagnostic — writes nothing, patches nothing)

Dumps every part the engine builds for 7692 so we can see the origin of:
  - the 'None  BASE BODY 1 2' junk row (Other Sheet, 3x2mm, £0)
  - the '2.5mm ACRYLIC' phantom (no part number) that invents diamond_polish +
    manual_labour_acrylic ops

For each part we print: part_number, description, normalized_material, thickness,
blank L/W, stock_form, page_role, is_assembly_parent, a 'source' hint if present,
and whether it has real geometry. That tells us whether the phantom is a duplicated
lens, a BOM/title-block text artifact, or something else — so the fix targets the root.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _7692_parts_diag.py
"""
from __future__ import annotations
import os, sys, json

FOLDER = r"K:\Estimating\Completed\AI Estimating\Live Enquiry\7692-01-GA Single-Sided Impulse Unit (Rev B)"

def _g(d, *keys, default=""):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default

def main():
    # Prefer to reuse the engine's own document build so we see EXACTLY the parts it costed.
    try:
        import file_scan
    except Exception as e:
        sys.exit(f"could not import file_scan: {e}")

    # Find the scan entry point the engine uses. Try common names.
    scan_fn = None
    for name in ("scan_folder_as_job", "scan_job_folder", "build_document", "scan_folder", "load_job"):
        if hasattr(file_scan, name):
            scan_fn = getattr(file_scan, name)
            print(f"using file_scan.{name}()")
            break
    if scan_fn is None:
        print("No known scan entry point in file_scan. Available callables:")
        print("  " + ", ".join(n for n in dir(file_scan) if not n.startswith("_") and callable(getattr(file_scan, n))))
        sys.exit("Tell me which function builds the parts list and I'll adjust.")

    try:
        doc = scan_fn(FOLDER)
    except TypeError:
        # some signatures take (folder, as_job=True) or similar
        try:
            doc = scan_fn(FOLDER, True)
        except Exception as e:
            sys.exit(f"scan call failed: {e}")
    except Exception as e:
        sys.exit(f"scan call failed: {e}")

    # doc may be a dict with 'parts' or a list
    parts = None
    if isinstance(doc, dict):
        for k in ("parts", "components", "part_list", "items"):
            if k in doc and isinstance(doc[k], list):
                parts = doc[k]; break
    elif isinstance(doc, list):
        parts = doc
    if parts is None:
        print("Could not find a parts list on the scan result. Top-level keys:")
        if isinstance(doc, dict):
            print("  " + ", ".join(doc.keys()))
        sys.exit("Tell me the parts key and I'll adjust.")

    print(f"\n{len(parts)} parts built. Dumping each:\n")
    print("=" * 100)
    for i, p in enumerate(parts):
        pn   = _g(p, "part_number", default="(none)")
        desc = _g(p, "description", default="(none)")
        mat  = _g(p, "normalized_material", "material", default="(none)")
        thk  = _g(p, "normalized_thickness_mm", "thickness_mm", default="")
        me   = p.get("material_estimate") or {}
        ng   = p.get("normalized_geometry") or {}
        bl   = _g(me, "blank_length_mm", default=_g(ng, "blank_length_mm", default=""))
        bw   = _g(me, "blank_width_mm", default=_g(ng, "blank_width_mm", default=""))
        sf   = _g(p, "stock_form", default="")
        roles= _g(p, "page_roles", "page_role", "roles", default="")
        par  = p.get("is_assembly_parent", False)
        src  = _g(p, "source", "source_file", "origin", "provenance", default="")
        has_geo = bool(bl and bw)
        flag = ""
        if not pn or pn == "(none)":
            flag += " <<PHANTOM: no part number"
        if not has_geo:
            flag += " <<no geometry"
        if str(mat).upper() in ("ACRYLIC", "PERSPEX", "PMMA", "POLYCARBONATE", "HIGH IMPACT ACRYLIC"):
            flag += " <<acrylic-route-eligible"
        print(f"[{i}] PN={pn!r}  desc={desc!r}")
        print(f"     material={mat!r} thk={thk} blank={bl}x{bw} stock_form={sf!r} roles={roles!r} parent={par} source={src!r}{flag}")
    print("=" * 100)
    print("\nLook for: any row with no PN + acrylic material (the phantom), and the")
    print("'BASE BODY 1 2' row (mangled dims). Their material/source/geometry tell us")
    print("the root. Paste this whole dump back.")

if __name__ == "__main__":
    main()
