r"""READ-ONLY. FINDING: the BOM LLM fires (used_llava/bom_table) but BOM lines come from
prose_recogniser (category guesses -> generic BI-*), not the table. Suspect: the proper BOM path is
gated behind SDI_DUALPATH_BOM, which is OFF, so it falls back to prose recognition. Verify:
  1) Is SDI_DUALPATH_BOM set in the environment / .env? (the gate)
  2) Show the dualpath block (file_scan.py ~1203-1260) — what it does when ON vs the fallback.
  3) When OFF, what builds bom_rows -> confirm it's the prose/synthesize fallback.
No edits — confirm the gate is the cause."""
import os, re

# 1) is the flag set?
print("="*66); print("1 — SDI_DUALPATH_BOM state"); print("="*66)
print(f"  os.environ SDI_DUALPATH_BOM = {os.getenv('SDI_DUALPATH_BOM')!r}")
envp=r"C:\ClaudeVision\.env"
if os.path.exists(envp):
    found=False
    for ln in open(envp,encoding="utf-8",errors="replace"):
        if "DUALPATH" in ln.upper() or "BOM" in ln.upper():
            print(f"  .env: {ln.strip()}"); found=True
    if not found:
        print("  .env: SDI_DUALPATH_BOM NOT present -> defaults to OFF (fallback path used)")

# 2) show the dualpath block
print("\n"+"="*66); print("2 — the dualpath BOM block (file_scan.py ~1195-1265)"); print("="*66)
p=r"C:\ClaudeVision\src\file_scan.py"
L=open(p,encoding="utf-8",errors="replace").read().splitlines()
for i in range(1194, min(len(L),1266)):
    print(f"  {i+1}: {L[i].rstrip()[:100]}")
