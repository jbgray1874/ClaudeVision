"""
Read-only. Reads an .xlsx WITHOUT openpyxl (xlsx = zipped XML) and prints the
formulas / values behind the two 'Total Material Cost' cells so we can see whether
166.11 and 99.99 are two scopes or a double-count.

Pure stdlib: zipfile + xml. Nothing to install.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _xlsx_formula_probe.py
"""
import zipfile
import re
import sys
from xml.etree import ElementTree as ET

PATH = r"C:\ClaudeVision\output\estimates\1282_-_Milwaukee_Wall_Bay_json_20260701_211234.xlsx"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

def col_letter(cell_ref):
    return re.match(r"([A-Z]+)", cell_ref).group(1)

def main(path):
    z = zipfile.ZipFile(path)

    # shared strings (so we can resolve text cells)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))

    # map sheet name -> file
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {r.get("Id"): r.get("Target") for r in rels}
    sheets = []
    for s in wb.find("m:sheets", NS).findall("m:sheet", NS):
        rid = s.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        tgt = rid_to_target.get(rid, "")
        if not tgt.startswith("xl/"):
            tgt = "xl/" + tgt
        sheets.append((s.get("name"), tgt))

    TERMS = ["166", "99.99", "Total Material", "M59", "M103", "M105", "166.11"]

    for name, tgt in sheets:
        try:
            root = ET.fromstring(z.read(tgt))
        except KeyError:
            continue
        for c in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
            ref = c.get("r")
            t = c.get("t")  # 's' = shared string, 'str' = formula string
            f = c.find("m:f", NS)   # formula
            v = c.find("m:v", NS)   # cached value
            formula = f.text if f is not None else None
            value = v.text if v is not None else None
            disp = value
            if t == "s" and value is not None:
                try:
                    disp = shared[int(value)]
                except (ValueError, IndexError):
                    pass
            blob = f"{formula or ''} {disp or ''}"
            if any(term in blob for term in TERMS):
                print(f"{name}!{ref}")
                if formula:
                    print(f"    FORMULA: ={formula}")
                print(f"    VALUE  : {disp}")
                print()

    print("="*70)
    print("Look for: does the M59 formula SUM a different range than the 166.11 cell?")
    print("If M59 references the cost-model rows and 166.11 sums the BOM sheet rows,")
    print("they are two scopes (labelling issue). If they sum overlapping ranges,")
    print("it's a double-count (real bug).")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else PATH)
