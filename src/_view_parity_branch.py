r"""READ-ONLY. Show the current --deliverables parity branch verbatim so I write the exact swap:
replace the parity_report_html call with job_report_html.generate_report, passing the bundle when a
manual exists (parity variant) and no bundle when not (new-job variant). Need the exact current
lines to match-or-refuse against. No edits."""
import re
p=r"C:\ClaudeVision\src\main.py"
L=open(p,encoding="utf-8",errors="replace").read().splitlines()
# find the deliverables block
start=None
for i,ln in enumerate(L):
    if "Deliverables: client quote" in ln:
        start=i; break
if start:
    for j in range(start, min(len(L), start+50)):
        print(f"  {j+1}: {L[j].rstrip()[:110]}")
