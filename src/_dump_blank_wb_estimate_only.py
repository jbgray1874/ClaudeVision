"""
Read-only. Dumps formulas from ONLY the cost-model sheet of the Blank Estimating WB,
and only the rows that carry the estimating intelligence (totals, M-cells, rebate,
overhead, sell price). Keeps output small enough to paste.

Pure stdlib. Run:
  C:\ClaudeVision\.venv\Scripts\python.exe _dump_blank_wb_estimate_only.py "K:\Estimating\Completed\Manual Estimates\Blank Estimate Sheet  WB 2026.xlsx"
"""
import zipfile, sys, re
from xml.etree import ElementTree as ET

PATH = r"K:\Estimating\Completed\Manual Estimates\Blank Estimate Sheet  WB 2026.xlsx"
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# only show formulas/labels whose text or formula mentions these (the cost-model spine)
KEYWORDS = [
    "material", "labour", "labor", "sub-total", "subtotal", "sub total",
    "rebate", "gross", "overhead", "absorption", "unit cost", "sell",
    "margin", "M59", "M103", "M105", "M107", "M109", "L111",
    "total", "cost", "price", "scrap", "quantity break", "qty break",
]

def matches(text):
    t = (text or "").lower()
    return any(k.lower() in t for k in KEYWORDS)

def main(path):
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(M+"si"):
            shared.append("".join(t.text or "" for t in si.iter(M+"t")))

    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    tgt = {r.get("Id"): r.get("Target") for r in rels}

    # find the sheet most likely to be the cost model: name contains 'estimat' or 'cost'
    target_sheets = []
    for s in wb.find(M+"sheets").findall(M+"sheet"):
        nm = (s.get("name") or "").lower()
        if any(w in nm for w in ("estimat", "cost", "summary", "quote", "sheet1")):
            target_sheets.append(s)
    if not target_sheets:  # fallback: first sheet
        target_sheets = wb.find(M+"sheets").findall(M+"sheet")[:1]

    # build row -> label map per sheet, so we can print label + formula on the same logical row
    for s in target_sheets:
        name = s.get("name")
        rid = s.get(R+"id")
        p = tgt.get(rid, "")
        if not p.startswith("xl/"):
            p = "xl/" + p
        try:
            root = ET.fromstring(z.read(p))
        except KeyError:
            continue

        # first pass: collect all cells with (ref, text-or-None, formula-or-None)
        cells = []
        for c in root.iter(M+"c"):
            ref = c.get("r")
            f = c.find(M+"f")
            v = c.find(M+"v")
            formula = f.text if f is not None else None
            txt = None
            if c.get("t") == "s" and v is not None:
                try: txt = shared[int(v.text)]
                except (ValueError, IndexError): pass
            cached = v.text if v is not None else None
            cells.append((ref, txt, formula, cached))

        # row number helper
        def rownum(ref): 
            m = re.search(r"(\d+)", ref); return int(m.group(1)) if m else 0

        # which rows are "interesting" — any row that has a label matching KEYWORDS,
        # OR a cell that has a formula
        interesting_rows = set()
        for ref, txt, formula, cached in cells:
            if (txt and matches(txt)) or formula:
                interesting_rows.add(rownum(ref))

        print("="*80)
        print("SHEET:", name, "  (showing cost-model rows only)")
        print("="*80)
        # print those rows in order, label cells + formula cells together
        for rn in sorted(interesting_rows):
            rowcells = [c for c in cells if rownum(c[0]) == rn]
            # labels first
            labels = [f"{ref}:'{txt}'" for ref, txt, formula, cached in rowcells if txt and txt.strip()]
            formulas = [f"{ref}==={formula} [={cached}]" for ref, txt, formula, cached in rowcells if formula]
            if labels or formulas:
                line = f"row {rn:>3}: "
                if labels:   line += " | ".join(labels)
                if formulas: line += "   >>> " + " ; ".join(formulas)
                print(line)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else PATH)
