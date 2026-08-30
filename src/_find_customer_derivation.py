r"""READ-ONLY. Find where the client quote derives the customer (the '01-GA-' bug) so I can fix it
to: (a) use the manual's folder customer (Tesco) when a manual exists, else (b) a neutral value —
never the drawing-number fragment. Locate:
  1) In client_quote_html.py: where 'customer'/'prepared for' is set — the split that yields '01-GA-'.
  2) Whether the quote generator receives the manual path / customer already (so we can pass Tesco).
  3) The exact string/function to patch."""
import os, re
SRC=r"C:\ClaudeVision\src"
for fn in ("client_quote_html.py",):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p):
        print(f"  {fn} NOT FOUND"); continue
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    print("="*66); print(f"{fn}: customer derivation"); print("="*66)
    for i,ln in enumerate(L):
        if re.search(r"(customer|client|prepared.?for|cust|\.split\(|job_folder|stem|title)", ln, re.I):
            print(f"  {i+1}: {ln.rstrip()[:98]}")
    print("\n"+"="*66); print(f"{fn}: the generate function signature (what it receives)"); print("="*66)
    for i,ln in enumerate(L):
        if re.search(r"def generate|def .*quote", ln):
            for j in range(i, min(len(L),i+12)):
                print(f"  {j+1}: {L[j].rstrip()[:96]}")
            print()
