r"""READ-ONLY test (run AFTER applying the customer fix). Confirm _derive_customer now returns
'Tesco' for 12120 (from the manual folder path), NOT '01-GA-'. Also sanity-check it doesn't crash
and gives a sensible value. Fast — no full run."""
import sys, os, json, glob, importlib
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)
import client_quote_html as CQ
importlib.reload(CQ)

hits=glob.glob(r"C:\ClaudeVision\output\json\*12120*.json")
jsons=[h for h in hits if 'report' not in h.lower() and 'quote' not in h.lower()]
S=json.load(open(max(jsons,key=os.path.getmtime),encoding="utf-8"))
stem=S.get("job_output_stem") or "12120-01-GA- DIGITAL TICKETING BRACKET"

cust=CQ._derive_customer(S, stem)
print(f"_derive_customer -> '{cust}'")
print(f"  expected: 'Tesco' (from manual folder path)")
print(f"  {'PASS' if cust.lower()=='tesco' else 'CHECK: got ' + repr(cust)}")

# also confirm the manual-path helper works standalone
if hasattr(CQ,"_customer_from_manual_path"):
    print(f"\n_customer_from_manual_path -> '{CQ._customer_from_manual_path(S)}'")

# build the header snippet to see what the quote will show
try:
    html=CQ.build_quote_html(S, job_stem=stem)
    import re
    # find the 'Prepared for' block
    m=re.search(r"Prepared for.*?</div>\s*</div>", html, re.S)
    snippet=re.sub(r"<[^>]+>"," ",m.group(0)) if m else "(header not found)"
    print(f"\nquote header 'Prepared for': {re.sub(r'  +',' ',snippet).strip()[:120]}")
    print(f"  -> '01-GA-' present in header? {'YES (BAD)' if '01-GA' in html[:3000] else 'no (good)'}")
except Exception as e:
    print(f"build_quote_html raised: {e}")
