r"""READ-ONLY. Helper is correct + logic hits 4 files, but the RUN said 'no manual found'. So the
deployed DELIVERABLES BLOCK either passes a wrong scan_label or has a control-flow bug. Show the
ACTUAL deployed deliverables block verbatim + the scan_label in scope, to see what really happens.
Check specifically:
  1) The deployed deliverables block — is the parity branch nested INSIDE the quote's 'if
     _canon_json2 exists' (so if quote ran, parity should too)? Is _find_manual_workbook called
     with scan_label or something else?
  2) What is scan_label at that point — is it the folder name, or was it reassigned to a PDF stem
     (line 447) because the run globbed individual PDFs inside the folder?
  3) Is there an exception being swallowed? The parity branch is in try/except — a DIFFERENT error
     (not 'no manual') would ALSO print... wait, it printed 'no manual estimate found' which is the
     ELSE branch of 'if _manual:'. So _find_manual_workbook RETURNED None at runtime. Why?
No edits — read the deployed block + trace scan_label."""
import re
p=r"C:\ClaudeVision\src\main.py"
src=open(p,encoding="utf-8",errors="replace").read()
L=src.splitlines()

print("="*66); print("1 — deployed DELIVERABLES block (verbatim)"); print("="*66)
# find the deliverables block
start=None
for i,ln in enumerate(L):
    if "getattr(args, \"deliverables\"" in ln or "Deliverables: client quote" in ln:
        start=i; break
if start is not None:
    lo=max(0,start-2)
    for j in range(lo, min(len(L), start+45)):
        print(f"  {j+1}: {L[j].rstrip()[:100]}")
else:
    print("  deliverables block not found")

print("\n"+"="*66); print("2 — where scan_label is SET and whether it's reassigned before deliverables"); print("="*66)
for i,ln in enumerate(L):
    if re.search(r"scan_label\s*=", ln):
        print(f"  {i+1}: {ln.strip()[:96]}")
# is the deliverables block INSIDE a loop over PDFs where scan_label = pdf name?
print("\n  context: is deliverables inside a per-PDF loop (scan_label=PDF) or per-job (folder)?")
if start:
    # walk backwards to find the enclosing 'for' or the folder-as-job branch
    for j in range(start, max(0,start-120), -1):
        s=L[j].strip()
        if re.search(r"^for .* in .*:", s) or "folder_as_job" in s or "--folder-as-job" in s or "args.folder_as_job" in s:
            print(f"    enclosing at {j+1}: {s[:90]}")
            if j < start-1: break

print("\n"+"="*66); print("3 — add a debug: what would scan_label be for the PDF-loop case?"); print("="*66)
print("  If --folder-as-job still LOOPS the PDFs inside and sets scan_label per-PDF (line 447),")
print("  then at deliverables-time scan_label might be e.g.")
print("    '1282 - Milwaukee 500mm Standard Wall Bay ISS7.PDF'  -> split('-')[0].strip()='1282' OK")
print("    OR '1448 - GA Upper Leg Assembly_revA.PDF'  -> job_num='1448' -> NO 1448 manual -> None!")
print("  ^ THAT would explain it: if the LAST processed item was a sub-assembly PDF (1448),")
print("    job_num='1448', no manual exists for 1448 -> 'no manual found'.")
print("  Check the output\\estimates list: there WAS a '1448 - GA Upper Leg Assembly' xlsx at 15:35.")
