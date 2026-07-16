"""
Read-only. Dumps EVERY formula (and its cell) from the Blank Estimating Workbook,
sheet by sheet, so we can see the real cell relationships (M59, M103, M105, rebate
gross-up, overhead absorption, quantity breaks) the engine is meant to reproduce.

Pure stdlib (zipfile + xml) — nothing to install.

EDIT the PATH below to point at your blank estimating workbook, then run:
  C:\ClaudeVision\.venv\Scripts\python.exe _dump_blank_wb_formulas.py
Or pass the path as an argument:
  C:\ClaudeVision\.venv\Scripts\python.exe _dump_blank_wb_formulas.py "K:\...\Blank Estimating WB.xlsx"
"""
import zipfile, sys
from xml.etree import ElementTree as ET

# <<< EDIT THIS to your blank workbook's path, or pass as arg1 >>>
PATH = r"K:\Estimating\Blank Estimating Workbook.xlsx"

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

def main(path):
    z = zipfile.ZipFile(path)

    # shared strings (to show text labels next to formulas)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(M+"si"):
            shared.append("".join(t.text or "" for t in si.iter(M+"t")))

    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    tgt = {r.get("Id"): r.get("Target") for r in rels}

    for s in wb.find(M+"sheets").findall(M+"sheet"):
        name = s.get("name")
        rid = s.get(R+"id")
        path_in = tgt.get(rid, "")
        if not path_in.startswith("xl/"):
            path_in = "xl/" + path_in
        print("="*80)
        print("SHEET:", name)
        print("="*80)
        try:
            root = ET.fromstring(z.read(path_in))
        except KeyError:
            print("  (could not read)"); continue
        for c in root.iter(M+"c"):
            f = c.find(M+"f")
            if f is None:                 # only cells that HAVE a formula
                continue
            ref = c.get("r")
            v = c.find(M+"v")
            val = v.text if v is not None else ""
            print(f"  {ref:<6} = ={f.text}    [cached: {val}]")
        # also show the LABEL cells (text) so we can map formulas to their meaning
        print("  --- text labels on this sheet ---")
        for c in root.iter(M+"c"):
            if c.get("t") == "s":
                v = c.find(M+"v")
                if v is not None:
                    try:
                        txt = shared[int(v.text)]
                        if txt.strip():
                            print(f"  {c.get('r'):<6} : {txt[:60]}")
                    except (ValueError, IndexError):
                        pass

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else PATH)
