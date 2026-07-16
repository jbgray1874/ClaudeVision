"""READ-ONLY. Finds the module + line where the TEMPLATE labour-row Part Description is
written, so we patch the RIGHT writer. The sheet is produced by wb_populate (template path),
NOT xlsx_output.py (which was patched but had no effect). This locates wb_populate's labour
writer.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _find_wb_labour_writer.py
"""
import os, re

SRC = r"C:\ClaudeVision\src"

# 1) find the file that prints "Populated template saved"
print("=== File(s) that print 'Populated template saved' (= the template writer) ===")
writer_files = []
for root, _, files in os.walk(SRC):
    for fn in files:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(root, fn)
        try:
            txt = open(p, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        if "Populated template saved" in txt:
            writer_files.append(p)
            print("  ", p)

# 2) in those files, find where labour rows / part descriptions get written
print("\n=== In the template writer(s): lines writing labour Operation/description ===")
for p in writer_files:
    lines = open(p, encoding="utf-8", errors="ignore").read().splitlines()
    for i, l in enumerate(lines):
        if re.search(r'operation|labour|_op_name|process_estimate|description|desc', l, re.I) \
           and re.search(r'\.value|write|cell|set_cell|\.cell|row', l, re.I):
            print(f"  {os.path.basename(p)}:{i+1}: {l.strip()[:90]}")

# 3) also locate the labour section header write so we can find the loop
print("\n=== Labour section anchors (to find the row-writing loop) ===")
for p in writer_files:
    lines = open(p, encoding="utf-8", errors="ignore").read().splitlines()
    for i, l in enumerate(lines):
        if re.search(r'labour|operation.*part|_estimate_part_labour|for .* in .*operations', l, re.I):
            print(f"  {os.path.basename(p)}:{i+1}: {l.strip()[:90]}")

print("\nNEXT: whichever file+line writes the labour Part Description is the one to patch")
print("(NOT xlsx_output.py). Paste the wb_populate labour-writer lines back.")
