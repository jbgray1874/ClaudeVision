"""
Read-only. Dump the ACTUAL formulas in the WB labour block (rows 62-70) so we see
exactly which columns are inputs vs formulas, and where TIME comes from. Settles
whether writing operation+qty is enough, or whether the WB needs hours as input.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _labour_formula_probe.py "K:\Estimating\Completed\Manual Estimates\Blank Estimate Sheet  WB 2026.xlsx"
"""
import zipfile, sys
from xml.etree import ElementTree as ET

P = sys.argv[1] if len(sys.argv) > 1 else r"K:\Estimating\Completed\Manual Estimates\Blank Estimate Sheet  WB 2026.xlsx"
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
z = zipfile.ZipFile(P)
wb = ET.fromstring(z.read("xl/workbook.xml"))
rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
tgt = {r.get("Id"): r.get("Target") for r in rels}
# find Estimate sheet
for s in wb.find(M+"sheets").findall(M+"sheet"):
    if s.get("name") == "Estimate":
        p = tgt[s.get(R+"id")]
        if not p.startswith("xl/"): p = "xl/"+p
        root = ET.fromstring(z.read(p))
        break

print("LABOUR BLOCK — rows 62-70, every cell: is it a formula (=...) or a blank input?")
for c in root.iter(M+"c"):
    ref = c.get("r"); 
    import re
    m = re.search(r"(\d+)", ref); rn = int(m.group(1)) if m else 0
    if 62 <= rn <= 70:
        f = c.find(M+"f"); v = c.find(M+"v")
        col = re.match(r"([A-Z]+)", ref).group(1)
        if f is not None:
            print(f"  {ref:<5} FORMULA: ={f.text}")
        elif v is not None:
            # could be a header label (shared string) — show it
            print(f"  {ref:<5} value: {v.text}")
        # cells with neither f nor v that are in-range and blank = INPUT cells
print("\nKEY: columns with FORMULAS are computed. Columns in the data rows (63+) with")
print("NO formula are INPUT cells the estimator/engine fills. Find where TIME/HOURS is input.")
