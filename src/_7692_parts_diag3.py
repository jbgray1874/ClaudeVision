#!/usr/bin/env python3
r"""
_7692_parts_diag3.py   (READ-ONLY — writes nothing, patches nothing)

Correct call against the real signature:
    scan_folder_job(job_folder: Path, pdf_paths: Sequence[Path], *, auto_discover_dxf: bool)

Steps:
  1. glob the folder for *.pdf
  2. scan_folder_job(Path(folder), pdf_paths, auto_discover_dxf=True) -> (doc, paths)
  3. estimate_document(doc) if needed to get costed parts
  4. recursively find the parts list and dump each, flagging the phantom + junk rows.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _7692_parts_diag3.py
"""
from __future__ import annotations
import os, sys, inspect
from pathlib import Path

FOLDER = r"K:\Estimating\Completed\AI Estimating\Live Enquiry\7692-01-GA Single-Sided Impulse Unit (Rev B)"

def _g(d, *keys, default=""):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default

def _find_parts(obj, depth=0, path="root"):
    if depth > 5:
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
    if isinstance(obj, (list, tuple)):
        for idx, v in enumerate(obj):
            found, p = _find_parts(v, depth + 1, f"{path}[{idx}]")
            if found is not None:
                return found, p
    return None, None

def _dump(parts, where):
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
        src  = _g(p, "source", "source_file", "origin", "provenance", "source_pdf", "page", default="")
        flags = ""
        if pn == "(NONE)" or not str(pn).strip():
            flags += " <<NO-PN"
        if not (bl and bw):
            flags += " <<NO-GEO"
        if str(mat).upper() in ("ACRYLIC","PERSPEX","PMMA","POLYCARBONATE","HIGH IMPACT ACRYLIC"):
            flags += " <<ACRYLIC-ROUTE"
        if "BASE BODY" in str(desc).upper() and pn == "(NONE)":
            flags += " <<JUNK-ROW?"
        if any(t in str(desc).upper() for t in ("CUSTOMER SUPPLY","FREE ISSUE","FREE-ISSUE","BY CUSTOMER","CUST SUPPLY","VINYL","DISPLAY BOARD","GRAPHIC","TICKET")):
            flags += " <<GRAPHIC/CUST?"
        print(f"[{i:2}] PN={pn!r} desc={desc!r}")
        print(f"     mat={mat!r} thk={thk} blank={bl}x{bw} stock_form={sf!r} roles={roles!r} parent={par} src={src!r}{flags}")
    print("=" * 104)

def main():
    try:
        import file_scan
    except Exception as e:
        sys.exit(f"could not import file_scan: {e}")

    folder = Path(FOLDER)
    pdfs = sorted(folder.glob("*.pdf")) + sorted(folder.glob("*.PDF"))
    # de-dup case-insensitive
    seen = set(); pdf_paths = []
    for p in pdfs:
        key = str(p).lower()
        if key not in seen:
            seen.add(key); pdf_paths.append(p)
    print(f"Found {len(pdf_paths)} PDF(s):")
    for p in pdf_paths:
        print("   ", p.name)

    sfj = file_scan.scan_folder_job
    try:
        res = sfj(folder, pdf_paths, auto_discover_dxf=True)
        print("scan_folder_job returned:", type(res).__name__,
              f"(tuple len {len(res)})" if isinstance(res, tuple) else "")
    except Exception as e:
        import traceback; traceback.print_exc()
        sys.exit(f"scan_folder_job failed: {e}")

    # res is (doc, paths_tuple)
    doc = res[0] if isinstance(res, tuple) else res

    parts, where = _find_parts(doc)
    if parts is None and hasattr(file_scan, "estimate_document"):
        ed = file_scan.estimate_document
        print("estimate_document signature:", str(inspect.signature(ed)))
        # try common call shapes
        for call in (
            lambda: ed(doc),
            lambda: ed(doc, pdf_paths),
            lambda: ed(folder, doc),
        ):
            try:
                out = call()
                parts, where = _find_parts(out)
                if parts is not None:
                    print("estimate_document produced parts.")
                    break
            except Exception as e:
                print(f"  estimate_document variant failed: {e}")

    if parts is None:
        print("\nCould not auto-locate parts. doc structure:")
        if isinstance(doc, dict):
            for k, v in doc.items():
                print(f"  {k}: {type(v).__name__}" + (f" (len {len(v)})" if hasattr(v,'__len__') else ""))
        sys.exit("Paste this and I'll target the key directly.")

    _dump(parts, where)
    print("\nWatch for: NO-PN + ACRYLIC-ROUTE (the phantom), the BASE BODY junk row,")
    print("and any GRAPHIC/CUST row — does it carry 'customer supply' text or was it")
    print("turned into a priced VINYL/DISPLAY BOARD part? Paste it all back.")

if __name__ == "__main__":
    main()
