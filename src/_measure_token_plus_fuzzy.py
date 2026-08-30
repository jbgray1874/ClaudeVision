r"""READ-ONLY MEASUREMENT. Design + measure the two-stage matcher before patching:
  Stage 1: better leading-token extractor (split on '-', keep first segment).
  Stage 2: description fuzzy-match for lines with no code match (difflib ratio).
Show for each Tim line: token result, exact-token match, and best fuzzy candidate + score.
Goal: see how many token matches we get, and whether the fuzzy matches are trustworthy
(high score, obviously-right) or dangerous (low score, wrong). No stdlib beyond difflib.
No edits."""
import re, json, difflib
import xlrd

# --- Tim lines: code + DESCRIPTION (need the full text now, not just code) ---
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

def better_token(code):
    # split on first '-', keep first segment; that's the part-code stem
    seg=code.split("-")[0]
    return seg if seg else code

tim=[]  # (norm_code, better_token, raw_desc_text)
for row in range(8,61):
    raw_full=None
    for col in range(1,7):
        v=cell(row,col)
        if v is None: continue
        t=str(v).strip()
        if not t: continue
        if any(sw in t.upper() for sw in skip): raw_full=None; break
        if raw_full is None and code_re.match(t) and any(c.isdigit() for c in t):
            raw_full=t; break
    if raw_full:
        nc=norm(raw_full)
        if len(nc)>=3:
            tim.append((nc, better_token(nc), raw_full.upper()))

# --- Engine: code + description ---
S=json.load(open(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json",encoding="utf-8"))
eng=[]  # (norm_code, token, desc)
for p in (S.get("estimate_summary",{}).get("part_estimates") or []):
    c=p.get("part_number"); d=(p.get("description") or "")
    if c: eng.append((norm(c), better_token(norm(c)), d.upper()))
for p in (S.get("bay_estimate",{}).get("lines") or []):
    c=p.get("code"); d=(p.get("description") or "")
    if c: 
        nc=norm(c)
        if nc not in {e[0] for e in eng}: eng.append((nc, better_token(nc), d.upper()))

eng_tok={e[1]:e[0] for e in eng}

print("="*66); print("STAGE 1 — better token match"); print("="*66)
tok_matched=[]; unmatched=[]
for nc, tk, desc in tim:
    if tk in eng_tok:
        tok_matched.append((nc, tk, eng_tok[tk]))
        print(f"  MATCH {nc:<26} tok={tk:<10} == engine {eng_tok[tk]}")
    else:
        unmatched.append((nc, tk, desc))
print(f"\n  token-matched: {len(tok_matched)}  (exact was 0)")

print("\n"+"="*66); print("STAGE 2 — description fuzzy for the unmatched"); print("="*66)
print("  (score = difflib ratio; >0.6 plausible, <0.5 weak — human vetoes)\n")
for nc, tk, desc in unmatched:
    best=(0.0,None,None)
    for enc, etk, edesc in eng:
        if not edesc: continue
        r=difflib.SequenceMatcher(None, desc, edesc).ratio()
        # also try token-in-desc containment boost
        if tk and tk in edesc.replace(" ",""): r=max(r,0.7)
        if r>best[0]: best=(r, enc, edesc)
    flag = "STRONG" if best[0]>=0.6 else ("weak" if best[0]>=0.45 else "NONE")
    print(f"  {nc:<26} -> best {best[0]:.2f} [{flag}] eng={best[1]}  ({str(best[2])[:34]})")
