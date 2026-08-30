"""
Read-only. Prints the FULL labour block formula structure so we can fix the #DIV/0!
correctly. Shows row 62 (headers), rows 63-64 (every column: formula or input), and
the dept rate table columns. Run:
  C:\ClaudeVision\.venv\Scripts\python.exe _labour_formulas.py
"""
import zipfile, re
from xml.etree import ElementTree as ET

P = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\AISheets\Blank Estimate Sheet  WB 2026.xlsx"
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

z = zipfile.ZipFile(P)
sh = []
if "xl/sharedStrings.xml" in z.namelist():
    r0 = ET.fromstring(z.read("xl/sharedStrings.xml"))
    for si in r0.findall(M+"si"):
        sh.append("".join(t.text or "" for t in si.iter(M+"t")))
wb = ET.fromstring(z.read("xl/workbook.xml"))
rl = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
tg = {x.get("Id"): x.get("Target") for x in rl}
s = [s for s in wb.find(M+"sheets").findall(M+"sheet") if s.get("name") == "Estimate"][0]
p = tg[s.get(R+"id")]; p = p if p.startswith("xl/") else "xl/"+p
rt = ET.fromstring(z.read(p))

def val(c):
    v = c.find(M+"v")
    if v is None: return None
    if c.get("t") == "s":
        try: return sh[int(v.text)]
        except: return v.text
    return v.text

def rn(ref):
    m = re.search(r"(\d+)", ref); return int(m.group(1)) if m else 0

print("=== LABOUR HEADER (row 62) ===")
for c in rt.iter(M+"c"):
    if rn(c.get("r")) == 62:
        print(f"  {c.get('r')}: {val(c)!r}")

print("\n=== ROWS 63-64: each column formula or INPUT ===")
for c in rt.iter(M+"c"):
    if rn(c.get("r")) in (63, 64):
        f = c.find(M+"f")
        if f is not None:
            print(f"  {c.get('r')} = ={f.text}")
        else:
            print(f"  {c.get('r')} = INPUT {val(c)!r}")

print("\n=== DEPT RATE TABLE header (row 114) + P/C sample rows ===")
for c in rt.iter(M+"c"):
    r = rn(c.get("r"))
    if r == 114 or (115 <= r <= 120):
        col = re.match(r"([A-Z]+)", c.get("r")).group(1)
        if col in ("G","H","I","J","K"):
            print(f"  {c.get('r')} = {val(c)!r}")

print("\n>>> KEY QUESTION: does column I (row 63) have a FORMULA or is it INPUT/blank?")
print(">>> And does the dept table have a column the WB expects I to LOOKUP from?")
