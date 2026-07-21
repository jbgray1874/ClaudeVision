r"""READ-ONLY (calls real functions, writes nothing live). Before writing the BOM fix, DRY-RUN the
reconciliation against 12120's real data:
  For each dual-path row that's a fastener (FIXING/THUM/STD PART etc.), convert it to a bought-in
  candidate with source='non_sdi_bom_row' (rank 4), then use the ACTUAL _bought_in_token_set /
  _bought_in_same_item to test whether it MATCHES the placeholder part_estimate (BI-SELFCLINCHNUT
  etc., rank 3) and which would WIN. This proves the fix will work (dual-path rank 4 beats
  placeholder rank 3 on a real token match) BEFORE touching live code.
No edits."""
import sys, os, json, glob
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)
import estimator as E

hits=glob.glob(r"C:\ClaudeVision\output\json\*12120*.json")
S=json.load(open(hits[0],encoding="utf-8"))
dp_rows=(S.get("document_analysis") or {}).get("bom_rows") or []
parts=S.get("estimate_summary",{}).get("part_estimates") or []

# placeholder bought-in parts (the ones on the sheet at qty 1)
placeholders=[p for p in parts if str(p.get("part_number","")).upper().startswith("BI-")
              or "SELFCLINCH" in str(p.get("part_number","")).upper()]
print("="*70); print("placeholder part_estimates (bought-in, on sheet):"); print("="*70)
for p in placeholders:
    toks=E._bought_in_token_set(p)
    print(f"  {p.get('part_number'):<22} qty={p.get('quantity')} desc='{p.get('description','')[:30]}' tokens={toks}")

# dual-path fastener rows -> candidate bought-in parts
def is_fastener_row(r):
    d=(str(r.get('description') or '')+' '+str(r.get('part_code') or r.get('code') or r.get('part_number') or '')).upper()
    return any(k in d for k in ('CLINCH','NUT','KNURL','KNOB','THUMB','SCREW','PEM','STUD','RIVET','THUM','FIXING','WASHER','BOLT'))

print("\n"+"="*70); print("dual-path fastener rows -> do they MATCH a placeholder? who WINS?"); print("="*70)
for r in dp_rows:
    if not is_fastener_row(r): continue
    code=r.get('part_code') or r.get('code') or r.get('part_number') or ''
    qty=r.get('qty') or r.get('quantity') or r.get('qty_per_unit')
    desc=r.get('description') or ''
    # build a candidate part as the fix would
    cand={"part_number":code,"description":desc,"quantity":qty,"source":"non_sdi_bom_row",
          "page_roles":["bought_in"]}
    ctoks=E._bought_in_token_set(cand)
    print(f"\n  DUAL-PATH: {str(code):<16} qty={qty} desc='{desc[:34]}' tokens={ctoks}")
    matched=False
    for p in placeholders:
        ptoks=E._bought_in_token_set(p)
        if ctoks and ptoks and E._bought_in_same_item(ctoks, ptoks):
            rank_dp=E._BOUGHT_IN_SOURCE_RANK.get("non_sdi_bom_row",0)
            rank_ph=E._BOUGHT_IN_SOURCE_RANK.get(str(p.get("source") or ""),0)
            winner="DUAL-PATH" if rank_dp>rank_ph else "placeholder"
            print(f"    -> MATCHES {p.get('part_number')} (qty {p.get('quantity')}) | "
                  f"dp_rank={rank_dp} ph_rank={rank_ph} | WINNER={winner} "
                  f"{'=> qty becomes '+str(qty) if winner=='DUAL-PATH' else ''}")
            matched=True
    if not matched:
        print(f"    -> NO placeholder match (would be ADDED as new bought-in row, qty {qty})")

print("\n"+"="*70); print("VERDICT"); print("="*70)
print("  If dual-path fasteners MATCH placeholders and WIN (rank 4>3) -> the fix is: add dual-path")
print("  fastener rows to `parts` as source='non_sdi_bom_row' BEFORE _reconcile_bought_in, and it")
print("  reconciles correctly (qty 4 wins). If they DON'T match on tokens -> need to align the")
print("  matching (description) first. This dry-run tells us which, with zero live changes.")
