r"""READ-ONLY, FAST. Two targeted questions (avoid slow recursive share glob):
  1) Does a 12120 manual estimate exist? Check the LIKELY customer folders directly rather than a
     full recursive glob. 12120 is a Tesco 'Digital Ticketing' job -> check Tesco + a shallow scan.
  2) What's the REAL customer (for the '01-GA-' quote fix)? Read 12120's GA title block / any
     customer field in the JSON.
Shallow + targeted so it returns quickly."""
import sys, os, json, glob
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)

ROOT=r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates"

print("="*66); print("1 — 12120 manual estimate (targeted, shallow)"); print("="*66)
# Only scan 2 years, 1 level of customer dirs, look for a 12120* jobfolder — no deep recursion.
found=None
for yr in ("2026","2025"):
    ydir=os.path.join(ROOT, yr)
    if not os.path.isdir(ydir):
        print(f"  {yr}: (no dir)"); continue
    try:
        customers=[d for d in os.listdir(ydir) if os.path.isdir(os.path.join(ydir,d))]
    except Exception as e:
        print(f"  {yr}: listdir failed {e}"); continue
    print(f"  {yr}: {len(customers)} customer folders")
    for cust in customers:
        cdir=os.path.join(ydir,cust)
        try:
            jobs=os.listdir(cdir)
        except Exception:
            continue
        for j in jobs:
            if j.startswith("12120") or "12120" in j:
                jpath=os.path.join(cdir,j)
                xls=glob.glob(os.path.join(jpath,"*.xls*"))
                print(f"    >>> FOUND under {cust}: {j}  xls={len(xls)}")
                if xls: found=xls[0]
    if found: break
print(f"\n  => 12120 manual: {found or 'NONE FOUND'}")
print(f"  => report variant on full run: {'PARITY' if found else 'NEW-JOB'}")

print("\n"+"="*66); print("2 — the REAL customer (fix '01-GA-')"); print("="*66)
hits=glob.glob(r"C:\ClaudeVision\output\json\*12120*.json")
jsons=[h for h in hits if 'report' not in h.lower() and 'quote' not in h.lower()]
S=json.load(open(max(jsons,key=os.path.getmtime),encoding="utf-8"))
# any explicit customer field?
for k in ("customer","client","customer_name","company","end_customer"):
    if S.get(k): print(f"  S['{k}']: {S.get(k)}")
# title block scan across pages for a customer-ish line
import re
pages=S.get("pages",[]) or []
print(f"  scanning {len(pages)} page title blocks for customer...")
for pg in pages[:4]:
    rt=pg.get("region_text") or {}
    for fld in ("title_block","notes","drawing_info"):
        txt=str(rt.get(fld) or "")
        # look for TESCO or a 'CUSTOMER:' line
        for m in re.finditer(r"(?:CUSTOMER|CLIENT)\s*[:\-]?\s*([A-Z][A-Za-z0-9 &]{2,30})", txt, re.I):
            print(f"    [{fld}] customer-ish: {m.group(1).strip()}")
        if "TESCO" in txt.upper():
            print(f"    [{fld}] contains 'TESCO'")
# folder name breakdown
print(f"\n  job_folder: {S.get('job_folder')}")
print(f"  -> '01-GA-' came from splitting '12120-01-GA- DIGITAL TICKETING BRACKET' on the number.")
print(f"     The real customer isn't in the folder name at all. Fix options:")
print(f"     (a) read customer from GA title block, (b) allow a per-job override, (c) leave customer")
print(f"     blank/generic rather than emitting the drawing-number fragment.")
