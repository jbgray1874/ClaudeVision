r"""READ-ONLY. The fix must: correct qty on matches (self-clinch 1->4, knob 1->2), NOT double-add
THUM620 (already a part_estimate), and correctly ADD the genuinely-missing pem stud. Verify:
  1) Is THUM620 already a part_estimate (so code-match prevents double-add)? What's its current qty?
  2) The dual-path 'STD PART' / 'FIXING' / 'FIXINGTBC' codes are ugly — if we ADD a row with
     code='STD PART' it'd show literally on the sheet. What SHOULD the added pem stud's code be?
     (Tim's is FIXING2908; dual-path gives 'STD PART'. Better to use a clean derived code or the
     description.) Check how added bought-in rows render their part_number on the sheet.
  3) List ALL current part_estimates by code+qty so I see the full picture of what's already there
     vs what dual-path would add.
No edits — confirm the add-path is safe (no dup THUM620, no ugly 'STD PART' code on sheet)."""
import sys, os, json, glob
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)
hits=glob.glob(r"C:\ClaudeVision\output\json\*12120*.json")
S=json.load(open(hits[0],encoding="utf-8"))
parts=S.get("estimate_summary",{}).get("part_estimates") or []

print("="*66); print("1 — is THUM620 already a part_estimate?"); print("="*66)
for p in parts:
    if "THUM" in str(p.get("part_number","")).upper():
        print(f"  FOUND: {p.get('part_number')} qty={p.get('quantity')} src={p.get('source')} "
              f"cost_method={(p.get('material_estimate') or {}).get('cost_method')}")
print("  -> if present, matching dual-path THUM620 by CODE prevents a double-add")

print("\n"+"="*66); print("2 — full part_estimates list (code | qty | is-bought-in)"); print("="*66)
for p in parts:
    pn=str(p.get("part_number") or "")
    roles=p.get("page_roles") or []
    bi="BI" if ("bought_in" in roles or pn.upper().startswith("BI-")) else "fab"
    print(f"  {pn:<24} qty={p.get('quantity'):<3} [{bi}] {str(p.get('description',''))[:30]}")

print("\n"+"="*66); print("3 — the dual-path rows we'd ADD (missing) vs MATCH (correct qty)"); print("="*66)
dp=(S.get("document_analysis") or {}).get("bom_rows") or []
existing_codes={str(p.get("part_number","")).upper() for p in parts}
for r in dp:
    code=str(r.get('part_code') or r.get('code') or r.get('part_number') or '')
    d=(str(r.get('description') or '')).upper()
    if any(k in d for k in ('CLINCH','NUT','KNURL','KNOB','THUMB','SCREW','PEM','STUD','RIVET','THUM','WASHER','BOLT')):
        by_code = code.upper() in existing_codes
        print(f"  dual-path {code:<14} qty={r.get('qty') or r.get('quantity')} "
              f"code-in-parts={by_code} desc='{r.get('description','')[:30]}'")
print("\n  -> 'STD PART','FIXING','FIXINGTBC' are placeholder-ish codes. For ADDED rows the sheet")
print("     part_number should be clean (derive from description, or map to a proper BI- code).")
