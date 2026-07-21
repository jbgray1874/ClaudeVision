r"""READ-ONLY. Before wiring --deliverables, confirm the exact call signatures + a manual-path
builder to reuse. Show:
  1) client_quote_html.generate_quote_files signature (args, defaults).
  2) parity_report_html.generate_report_files signature (the convenience API for the HTML).
  3) estimate_full_parity_report.generate_and_write signature (the bundle builder — needs summary
     json + manual workbook; produces the bundle the HTML reads).
  4) Any existing manual-workbook path convention/builder in the codebase (UNC to Manual Estimates)
     so I reuse it instead of hardcoding — search for the share path + customer/year/jobfolder logic.
No edits — confirm signatures + manual-lookup."""
import os, re, inspect, importlib, sys
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)

def sig(mod, fn):
    try:
        m=importlib.import_module(mod); f=getattr(m,fn,None)
        if f is None: return f"  {mod}.{fn} -> NOT FOUND"
        return f"  {mod}.{fn}{inspect.signature(f)}"
    except Exception as e:
        return f"  {mod}.{fn} -> import err: {type(e).__name__}: {str(e)[:60]}"

print("="*66); print("1-3 — generator signatures"); print("="*66)
print(sig("client_quote_html","generate_quote_files"))
print(sig("parity_report_html","generate_report_files"))
print(sig("estimate_full_parity_report","generate_and_write"))
# also the bundle->html path: what does generate_and_write return / write?
try:
    m=importlib.import_module("estimate_full_parity_report")
    src=inspect.getsource(getattr(m,"generate_and_write"))
    print("\n  generate_and_write body (first 30 lines):")
    for ln in src.splitlines()[:30]:
        print("    ", ln[:96])
except Exception as e:
    print("  (couldn't read generate_and_write:", e, ")")

print("\n"+"="*66); print("4 — manual-workbook path convention (UNC to Manual Estimates)"); print("="*66)
found=False
for fn in os.listdir(SRC):
    if not fn.endswith(".py") or re.search(r"\.(bak|backup)|\.\d+\.py$", fn): continue
    p=os.path.join(SRC,fn)
    try: L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    except: continue
    for i,ln in enumerate(L):
        if re.search(r"(Manual Estimate|Completed.*Manual|shareddata.*Manual|def .*manual.*path|find_manual|manual_workbook_path)", ln, re.I):
            print(f"  {fn}:{i+1}: {ln.strip()[:96]}"); found=True
if not found:
    print("  No manual-path builder found -> orchestration constructs the UNC path from")
    print("  config (share root) + customer + year + job folder, and skips on FileNotFoundError.")
    # is the share root in config?
    cfgp=os.path.join(SRC,"config.py")
    if os.path.exists(cfgp):
        for i,ln in enumerate(open(cfgp,encoding="utf-8",errors="replace").read().splitlines()):
            if re.search(r"(shareddata|Manual Estimate|MANUAL_|sdi-dc01|Completed)", ln, re.I):
                print(f"    config.py:{i+1}: {ln.strip()[:90]}")
