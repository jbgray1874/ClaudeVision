r"""READ-ONLY. Find where the AI run finishes populating the spreadsheet, so the parity report
auto-generation hooks in there and writes next to the .xlsx. Locate: (1) where the populated
workbook is saved (the 'Populated template saved' line), (2) the function + its return, (3)
whether a parity bundle is already built in the run or needs building first. No edits."""
import os, re, glob

root=r"C:\ClaudeVision\src"
# which file writes 'Populated template saved'?
print("="*66); print("where is the populated xlsx saved?"); print("="*66)
for p in glob.glob(os.path.join(root,"*.py")):
    if os.path.getsize(p)>2_000_000: continue
    try: txt=open(p,encoding="utf-8",errors="replace").read()
    except: continue
    if "Populated template saved" in txt or "wb_populate" in txt.lower():
        for i,ln in enumerate(txt.splitlines()):
            if re.search(r"Populated template saved|def .*populate|def wb_populate|\.save\(|output.*estimates|present_files|return .*xlsx|saved_path", ln, re.I):
                print(f"  {os.path.basename(p)}:{i+1}: {ln.strip()[:100]}")
        print()

# main.py: where does a job run finish? is a bundle built there?
print("="*66); print("main.py run flow (populate + parity bundle build)"); print("="*66)
mp=os.path.join(root,"main.py")
if os.path.exists(mp):
    for i,ln in enumerate(open(mp,encoding="utf-8",errors="replace").read().splitlines()):
        if re.search(r"populate|parity|bundle|estimate_full_parity|report|\.xlsx|save|def main|folder_as_job|output", ln, re.I):
            print(f"  {i+1}: {ln.strip()[:100]}")
