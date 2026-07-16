"""
READ-ONLY. Probe the Labour sheet in the POPULATED output file to understand
what row 101 contains and how the dept-hours table (C117:D149) flows from it.
Run from src:
  C:\ClaudeVision\.venv\Scripts\python.exe _labour_sheet_probe2.py
"""
import zipfile, re, os, glob
from xml.etree import ElementTree as ET

# Use the most recent populated output
OUTPUT_DIR = r"C:\ClaudeVision\output\estimates"
files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "1282*.xlsx")), key=os.path.getmtime)
P = files[-1] if files else None
if not P:
    print("No output file found"); raise SystemExit
print(f"Reading: {P}\n")

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

def get_sheet(name):
    for s in wb.find(M+"sheets").findall(M+"sheet"):
        if s.get("name") == name:
            p = tg[s.get(R+"id")]
            p = p if p.startswith("xl/") else "xl/"+p
            return ET.fromstring(z.read(p))
    return None

def val(c):
    v = c.find(M+"v")
    if v is None: return None
    if c.get("t") == "s":
        try: return sh[int(v.text)]
        except: return v.text
    return v.text

def rn(ref): m = re.search(r"(\d+)", ref); return int(m.group(1)) if m else 0
def cl(ref): return re.match(r"([A-Z]+)", ref).group(1)

print("=== Sheets in this workbook ===")
for s in wb.find(M+"sheets").findall(M+"sheet"):
    print(f"  {s.get('name')!r}")

lab = get_sheet("Labour")
if not lab:
    print("\nNo Labour sheet found"); raise SystemExit

dim = lab.find(M+"dimension")
print(f"\nLabour sheet dimension: {dim.get('ref') if dim is not None else '?'}")

print("\n=== Labour sheet row 100 (headers?) ===")
for c in lab.iter(M+"c"):
    if rn(c.get("r")) == 100:
        f = c.find(M+"f")
        v = val(c)
        print(f"  {c.get('r')}: {'='+f.text if f is not None else repr(v)}")

print("\n=== Labour sheet row 101 (the dept-hours source) ===")
row101 = [(c.get("r"), c) for c in lab.iter(M+"c") if rn(c.get("r")) == 101]
if not row101:
    print("  (empty — no cells in row 101)")
else:
    for ref, c in row101:
        f = c.find(M+"f")
        v = val(c)
        print(f"  {ref}: {'='+f.text if f is not None else repr(v)}")

print("\n=== Estimate sheet: dept-hours table rows 117-120 (C,D cols) ===")
est = get_sheet("Estimate")
for c in est.iter(M+"c"):
    if 117 <= rn(c.get("r")) <= 122 and cl(c.get("r")) in ("C","D"):
        f = c.find(M+"f")
        v = val(c)
        print(f"  {c.get('r')}: {'='+f.text if f is not None else repr(v)}")
