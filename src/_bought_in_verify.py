# -*- coding: utf-8 -*-
r"""Verify what each bought-in item priced to after Fix C1, reading the engine's
own JSON output. Read-only. Shows per-item applied unit cost + source/provenance
so we can confirm the loom is ~£24.15 (not £0.42, not doubled) and nothing is wild.

  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _bought_in_verify.py
"""
import json, os, glob

# Find the most recent 1282 JSON output
candidates = glob.glob(r"C:\ClaudeVision\output\json\*1282*.json")
if not candidates:
    candidates = glob.glob(r"C:\ClaudeVision\output\json\*.json")
if not candidates:
    print("No JSON output found in C:\\ClaudeVision\\output\\json")
    raise SystemExit(0)

path = max(candidates, key=os.path.getmtime)
print(f"Reading: {path}\n")
data = json.load(open(path, encoding="utf-8"))

def walk_parts(d):
    """Yield part dicts wherever they live in the JSON."""
    if isinstance(d, dict):
        # a 'parts' or 'part_estimates' list
        for key in ("parts", "part_estimates", "estimates", "line_items"):
            v = d.get(key)
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        yield it
        for v in d.values():
            yield from walk_parts(v)
    elif isinstance(d, list):
        for it in d:
            yield from walk_parts(it)

seen = set()
print(f"{'qty':>3}  {'unit':>9}  {'ext':>9}  desc  [role/source]")
print("-" * 80)
for p in walk_parts(data):
    desc = str(p.get("description") or p.get("part_number") or "")
    roles = p.get("page_roles") or p.get("roles") or []
    role_blob = ",".join(roles) if isinstance(roles, list) else str(roles)
    # only bought-in-ish lines
    is_bi = "bought_in" in role_blob or any(
        k in desc.upper() for k in ("LOOM","FIXING","RIVET","CABLE","FOAM","NUTSERT","GLIDE","ELECTRIC","STRAP","JUNCTION")
    )
    if not is_bi:
        continue
    unit = p.get("unit_total_cost_gbp", p.get("unit_estimate"))
    ext = p.get("extended_total_cost_gbp", p.get("extended_estimate"))
    key = (desc, str(unit), str(ext))
    if key in seen:
        desc += "   <-- DUPLICATE"
    seen.add(key)
    # find any provenance
    prov = ""
    res = p.get("system_cost", {}) or p.get("system_cost_result", {})
    if isinstance(res, dict):
        sel = (res.get("result", {}) or {}).get("selected", {}) if "result" in res else res.get("selected", {})
        if isinstance(sel, dict):
            prov = f"{sel.get('source','')}: {str(sel.get('provenance',''))[:40]}"
    try:
        print(f"{p.get('quantity','?'):>3}  {float(unit or 0):>9.2f}  {float(ext or 0):>9.2f}  {desc[:42]}  [{role_blob}] {prov}")
    except Exception:
        print(f"  {desc[:42]}  unit={unit} ext={ext}  [{role_blob}]")
