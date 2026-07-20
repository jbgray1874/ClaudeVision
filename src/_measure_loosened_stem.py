r"""READ-ONLY MEASUREMENT. Find the SAFE loosening rule to catch 1449-PEGPANEL<->1449-01C
without wrong pairs. Compare several stem definitions and, for each, show which manual<->ai
pairs it would produce and whether any are WRONG (different parts sharing a numeric prefix).

Stem candidates tested:
  S1 = first '-' segment                     (current: 1449-PEGPANEL -> 1449)
  S2 = drawing-number stem (digits + optional -NN + optional letter):
         1449-01C -> 1449-01 ; 1449-PEGPANEL -> 1449 ; 3886-02-FOOTBASE -> 3886-02
  S3 = leading pure digit-run                (1449-01C -> 1449 ; 3886-02 -> 3886)

For each: pair manual<->ai where stems match, and MANUALLY flag pairs whose descriptions look
inconsistent (a crude wrong-pair detector using difflib as a *warning only*, not a matcher).
No edits — this sizes the risk of each loosening before patching."""
import re, json, difflib
import xlrd

# Tim codes + descriptions
MANUAL=r"K:\Estimating\Completed\Manual Estimates\2026\TTI\1282- MILWAUKEE RED 50cm PEG\1282-MILWAUKEE 50CM PEG WALL BAY(ISS 7)-.xls"
bk=xlrd.open_workbook(MANUAL); sh=bk.sheet_by_name("Estimate")
def cell(r,c):
    try: return sh.cell_value(r-1,c-1)
    except IndexError: return None
code_re=re.compile(r"^[A-Z0-9][A-Z0-9 ./_-]{1,30}$", re.IGNORECASE)
skip=("TOTAL","SUBTOTAL","DESCRIPTION","ITEM","QTY","SHEET STEEL","BILL OF MATERIALS",
      "PART CODE","SUPPLIER","STANDARD MATERIALS","QUANTITY","MATERIAL","LABOUR","OVERHEAD","MARGIN","SELL")
def norm(raw):
    s=str(raw or "").strip().upper(); s=re.sub(r"\s+","",s); s=re.sub(r"-+$","",s); return s
def has_alpha(s): return any(c.isalpha() for c in s)

tim={}   # norm_code -> desc(from same cell)
for row in range(8,61):
    raw=None
    for col in range(1,7):
        v=cell(row,col)
        if v is None: continue
        t=str(v).strip()
        if not t: continue
        if any(sw in t.upper() for sw in skip): raw=None; break
        if raw is None and code_re.match(t) and any(c.isdigit() for c in t): raw=t; break
    if raw:
        nc=norm(raw)
        if len(nc)>=3 and has_alpha(nc): tim[nc]=raw.upper()

# Engine codes + descriptions
S=json.load(open(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json",encoding="utf-8"))
eng={}
for p in (S.get("estimate_summary",{}).get("part_estimates") or []):
    c=p.get("part_number")
    if c: eng[norm(c)]=(p.get("description") or "").upper()

def S1(c): return c.split("-",1)[0]
def S2(c):
    m=re.match(r"^(\d+(?:-\d+)?)", c)   # 1449, 1449-01, 3886-02
    return m.group(1) if m else c.split("-",1)[0]
def S3(c):
    m=re.match(r"^(\d+)", c); return m.group(1) if m else ""

from collections import Counter
def pairs_for(stemfn, name):
    print("\n"+"="*64); print(f"{name}: stem = {stemfn.__name__}"); print("="*64)
    ms={c:stemfn(c) for c in tim}; es={c:stemfn(c) for c in eng}
    mc=Counter(ms.values()); ec=Counter(es.values())
    # unique-both
    m_uni={s:c for c,s in ms.items() if mc[s]==1 and s}
    e_uni={s:c for c,s in es.items() if ec[s]==1 and s}
    npair=0; risky=0
    for s,mcode in sorted(m_uni.items()):
        acode=e_uni.get(s)
        if not acode: continue
        npair+=1
        dm=tim[mcode]; de=eng[acode]
        r=difflib.SequenceMatcher(None,dm,de).ratio()
        warn = "  <-- CHECK (desc mismatch)" if r<0.30 else ""
        if warn: risky+=1
        print(f"  {mcode:<26} == {acode:<12} stem={s:<8} descsim={r:.2f}{warn}")
    print(f"  -> {npair} pairs, {risky} flagged for description mismatch")

pairs_for(S1,"S1 first-dash")
pairs_for(S2,"S2 drawing-number")
pairs_for(S3,"S3 digit-run")
