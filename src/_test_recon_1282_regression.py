r"""READ-ONLY. REGRESSION: the reconcile now runs on 1282 too. 1282's dual-path BOM was clean (22
real-coded rows: 1448-GA, 1449-01C qty3, FIXING5 qty2, ELECTRICS 50cm...). Confirm the reconcile
does NOT spuriously mangle 1282 — it should mostly code-match existing parts (no change) and only
touch genuine fastener placeholders. Report what it WOULD change on 1282 (qty-corrected / added),
and flag if it touches anything it shouldn't (fabricated parts, real SDI-coded parts)."""
import sys, os, json, glob, re
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)
import estimator as E

hits=glob.glob(r"C:\ClaudeVision\output\json\1282*.json")
S=json.load(open(hits[0],encoding="utf-8"))
parts=[dict(p) for p in (S.get("estimate_summary",{}).get("part_estimates") or [])]

from bom_pipeline import reconciled_bom_rows_for_job
folder=S.get("job_folder") or os.path.dirname(S.get("full_path") or "")
dp=reconciled_bom_rows_for_job(folder=folder)
dp_rows=dp.get("rows") or []
print(f"1282: {len(parts)} part_estimates, {len(dp_rows)} dual-path rows\n")

def is_fast(r):
    d=(str(r.get("description") or "")+" "+str(r.get("part_code") or r.get("code") or r.get("part_number") or "")).upper()
    return any(k in d for k in ("CLINCH","NUT","KNURL","KNOB","THUMB","SCREW","PEM","STUD","RIVET","THUM","WASHER","BOLT","GLIDE"))
def dcode(r): return str(r.get("part_code") or r.get("code") or r.get("part_number") or "").strip()
def dqty(r):
    q=r.get("qty") or r.get("quantity") or r.get("qty_per_unit")
    try: return int(float(q)) if q is not None else None
    except: return None
def pcode(p): return str(p.get("part_number") or "").strip().upper()
def clean(desc,fb):
    dU=(desc or "").upper(); fbU=(fb or "").upper().strip()
    if fbU not in ("STD PART","FIXING","FIXINGTBC","TBC","STDPART","") and re.search(r"\d",fbU): return fb
    M=[(r"SELF[\s-]?CLINCH.*NUT|CLINCH.*NUT","BI-SELFCLINCHNUT"),(r"KNURLED.*KNOB","BI-KNURLEDKNOB"),
       (r"THREADED.*PEM.*STUD|PEM.*STUD","BI-PEMSTUD"),(r"KEYHOLE.*PEM","BI-KEYHOLEPEM"),
       (r"MUSHROOM.*THUMB|THUMB.*SCREW","BI-THUMBSCREW"),(r"DOME.*RIVET|RIVET","BI-RIVET"),(r"NUT","BI-NUT")]
    for pat,c in M:
        if re.search(pat,dU): return c
    return fb or "BI-FIXING"

changes=[]
for r in dp_rows:
    if not is_fast(r): continue
    code=dcode(r); qty=dqty(r) or 1; desc=str(r.get("description") or code)
    cm=next((p for p in parts if code and pcode(p)==code.upper()), None)
    if cm is not None:
        if cm.get("quantity")!=qty:
            changes.append(f"QTY: {cm.get('part_number')} {cm.get('quantity')}->{qty} (code-match '{desc[:26]}')")
            cm["quantity"]=qty
        continue
    ct=E._bought_in_token_set({"description":desc}); tm=None
    if ct is not None:
        for p in parts:
            roles=p.get("page_roles") or []
            if not ("bought_in" in roles or pcode(p).startswith("BI-")): continue
            pt=E._bought_in_token_set(p)
            if pt is not None and E._bought_in_same_item(ct,pt): tm=p; break
    if tm is not None:
        if tm.get("quantity")!=qty:
            changes.append(f"QTY: {tm.get('part_number')} {tm.get('quantity')}->{qty} (token-match '{desc[:26]}')")
            tm["quantity"]=qty
        continue
    cc=clean(desc,code)
    if any(pcode(p)==cc.upper() for p in parts): continue
    changes.append(f"ADD: {cc} qty={qty} ('{desc[:30]}')")
    parts.append({"part_number":cc,"description":desc,"quantity":qty,"page_roles":["bought_in"],"source":"non_sdi_bom_row"})

print(f"reconcile would make {len(changes)} change(s) on 1282:")
for c in changes: print(f"  {c}")
print("\nASSESS: are these SENSIBLE (correcting a fastener qty / adding a genuinely missing fastener),")
print("or SPURIOUS (touching a real SDI-coded fabricated part, or adding a dup)?")
# Flag any change touching a fabricated SDI part (NNNN-NN-NN pattern)
fab_touched=[c for c in changes if re.search(r"\d{4}-\d{2}", c) and "ADD" not in c]
if fab_touched:
    print(f"  ⚠ POSSIBLE ISSUE — changes touching SDI-coded parts: {fab_touched}")
else:
    print("  ✓ no SDI-coded fabricated parts touched")
