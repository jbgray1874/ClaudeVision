r"""READ-ONLY MEASUREMENT. Prove that leading-token code extraction recovers the matches.
1) Get the ENGINE's BOM codes (from the summary's parts / ai lines).
2) Get TIM's picked codes (from the parser trace — the 18 real ones).
3) Match them THREE ways: (a) current _norm_line_code exact, (b) leading-token extracted,
   and show which engine parts pair with which Tim lines. Measures matches recovered.
No edits — measurement to size the fix before writing it."""
import re, json, os
import xlrd

# --- Tim codes (replicate parser pick) ---
MANUAL = r"K:\Estimating\Completed\Manual Estimates\2026\TTI\1282- MILWAUKEE RED 50cm PEG\1282-MILWAUKEE 50CM PEG WALL BAY(ISS 7)-.xls"
bk=xlrd.open_workbook(MANUAL); sh=bk.sheet_by_name("Estimate")
def cell(r,c):
    try: return sh.cell_value(r-1,c-1)
    except IndexError: return None
code_re=re.compile(r"^[A-Z0-9][A-Z0-9 ./_-]{1,30}$", re.IGNORECASE)
skip=("TOTAL","SUBTOTAL","DESCRIPTION","ITEM","QTY","SHEET STEEL","BILL OF MATERIALS",
      "PART CODE","SUPPLIER","STANDARD MATERIALS","QUANTITY","MATERIAL","LABOUR","OVERHEAD","MARGIN","SELL")
def norm(raw):
    s=str(raw or "").strip().upper(); s=re.sub(r"\s+","",s); s=re.sub(r"-+$","",s); return s
tim=[]
for row in range(8,61):
    cv=None
    for col in range(1,7):
        v=cell(row,col)
        if v is None: continue
        t=str(v).strip()
        if not t: continue
        if any(sw in t.upper() for sw in skip): cv=None; break
        if cv is None and code_re.match(t) and any(c.isdigit() for c in t): cv=t; break
    if cv and len(norm(cv))>=3: tim.append(norm(cv))

# --- Engine codes (from summary) ---
S=json.load(open(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json",encoding="utf-8"))
eng=set()
for p in (S.get("estimate_summary",{}).get("part_estimates") or []):
    c=p.get("part_number")
    if c: eng.add(norm(c))
# also bay/BOM codes
for p in (S.get("bay_estimate",{}).get("lines") or []):
    c=p.get("code")
    if c: eng.add(norm(c))

def token(code):
    # leading part-code token: letters+digits up to first '-' or space-collapsed boundary
    m=re.match(r"^([A-Z]+\d+[A-Z]?(?:-\d+[A-Z]?)?)", code)  # FIXING125, 1448-02, VINYL76
    return m.group(1) if m else code

print("ENGINE codes:", sorted(eng))
print("\nTIM codes:   ", tim)

print("\n"+"="*60); print("(a) EXACT norm match"); print("="*60)
exact=[t for t in tim if t in eng]
print(f"  matched {len(exact)}: {exact}")

print("\n"+"="*60); print("(b) LEADING-TOKEN match"); print("="*60)
eng_tok={token(e):e for e in eng}
rec=[]
for t in tim:
    tt=token(t)
    if tt in eng_tok:
        rec.append((t, tt, eng_tok[tt]))
for t,tt,e in rec:
    print(f"  {t:<28} --tok--> {tt:<12} == engine {e}")
print(f"\n  token-matched {len(rec)} (was {len(exact)} exact) -> recovered {len(rec)-len(exact)}")

print("\n  UNMATCHED Tim lines even with token (fabricated / no engine code):")
matched_t={r[0] for r in rec}
for t in tim:
    if t not in matched_t: print(f"    {t}")
