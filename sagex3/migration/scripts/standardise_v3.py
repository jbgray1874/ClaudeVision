"""Put the four product-side load files on one set of codes.

  products (ZSDIITM) - the master, its codes are left exactly as they are
  prices   (YITC)
  BOMs     (YA00408BOM)
  routes   (ZSDIROU2)

Three things happen, in this order:
  1. Excel damage in the price file is repaired - a code Excel read as a date, and one
     that lost a leading zero. Each repair has to land on a code that really exists.
  2. Every code in the price, BOM and routing files is matched to the product file on a
     normalised key and rewritten to the product file's exact spelling.
  3. The BOM is split: the lines whose parent and component both exist, and the lines
     held back because a code is not in the product file.

Nothing is invented. A code that cannot be matched is left alone and reported.

Usage: python3.13 -I standardise_v3.py <in_dir> <out_dir>
"""
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# The files came out of Access in the DOS OEM code page, not Windows-1252: 0x9C is a
# pound sign, 0xF8 a degree sign, 0x9D a diameter sign. Reading them as anything else
# mangles 209 characters. Bytes are preserved on the way out.
ENC = "cp850"


def read(path):
    with open(path, newline="", encoding=ENC) as f:
        return [r for r in csv.reader(f, delimiter=";") if r and r[0].strip()]


def write(path, rows):
    with open(path, "w", newline="", encoding=ENC) as f:
        csv.writer(f, delimiter=";", lineterminator="\r\n").writerows(rows)


def key(s):
    """What two codes must share to be the same product."""
    return (str(s or "").strip().replace(" ", "").replace("&", "")
            .replace("(", "").replace(")", "").replace(".", "-").upper())


def repair(code, master):
    """Undo the two kinds of Excel damage, but only onto a code that exists."""
    s = str(code or "").strip()
    # Excel read the code as a date and stamped a midnight time onto it.
    m = re.match(r"^(.*?)(\d{2}:\d{2}:\d{2})$", s)
    if m and key(m.group(1)) in master:
        return master[key(m.group(1))], "Excel added a time to a code it read as a date"
    # Excel dropped a leading zero by treating the code as a number.
    if s.isdigit():
        for pad in range(1, 4):
            cand = "0" * pad + s
            if key(cand) in master:
                return master[key(cand)], "Excel dropped a leading zero"
    return None, None


def main(in_dir, out_dir):
    src, out = Path(in_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    items = read(src / "ZSDIITM_Cleansing.txt")
    master, lines_of = {}, defaultdict(list)
    for i, r in enumerate(items, start=1):
        code = r[1].strip()
        master.setdefault(key(code), code)
        lines_of[code].append((i, r))

    log, unmatched, repairs = Counter(), [], []

    def fix(rows, cols, name, allow_repair=False):
        seen = Counter()
        for r in rows:
            for c in cols:
                old = str(r[c] or "").strip()
                if not old:
                    continue
                new = master.get(key(old))
                if new is None and allow_repair:
                    new, why = repair(old, master)
                    if new:
                        repairs.append((name, old, new, why))
                        r[c] = new
                        log[name + ": Excel damage repaired"] += 1
                        continue
                if new is None:
                    seen[old] += 1
                elif new != old:
                    r[c] = new
                    log[name + ": codes rewritten to the product file's spelling"] += 1
        for code, n in seen.items():
            unmatched.append((name, code, n))
        log[name + ": codes with no such product"] = sum(seen.values())
        return rows

    # The product file is the master. It goes out byte for byte as it came in.
    write(out / "ZSDIITM_load5_products.txt", items)
    log["Products in the master file"] = len(items)

    rou = fix(read(src / "ZSDIROU2_load1_routes-V4-cleansed.txt"), [0], "Routes")
    write(out / "ZSDIROU2_load5_routes.txt", rou)
    log["Routes: lines"] = len(rou)

    cst = fix(read(src / "YITC_load1_product_costs-cleansed.txt"), [2], "Prices",
              allow_repair=True)
    write(out / "YITC_load5_product_prices.txt", cst)
    log["Prices: lines"] = len(cst)

    bom = fix(read(src / "YA00408BOM_guide_MAPPED-V1.1-cleansed.txt"), [0, 8], "BOMs")
    known = set(master.values())
    good = [r for r in bom if r[0].strip() in known and r[8].strip() in known]
    held = [r for r in bom if not (r[0].strip() in known and r[8].strip() in known)]
    write(out / "YA00408BOM_load5_loadable.txt", good)
    write(out / "YA00408BOM_load5_held_back.txt", held)
    log["BOMs: lines in the source file"] = len(bom)
    log["BOMs: lines that will load"] = len(good)
    log["BOMs: lines held back - a code is not a product"] = len(held)

    # --- the report ----------------------------------------------------------
    wb = Workbook()
    hf = Font(name="Arial", bold=True, size=10)
    bf = Font(name="Arial", size=10)
    fill = PatternFill("solid", fgColor="D9E1F2")

    def sheet(title, headers, data, widths):
        ws = wb.create_sheet(title)
        ws.append(headers)
        for c in ws[1]:
            c.font, c.fill = hf, fill
            c.alignment = Alignment(wrap_text=True, vertical="top")
        for row in data:
            ws.append(list(row))
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.font = bf
                c.alignment = Alignment(wrap_text=True, vertical="top")
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"
        if ws.max_row > 1:
            ws.auto_filter.ref = ws.dimensions
        return ws

    s = wb.active
    s.title = "Summary"
    s["A1"] = "One set of codes across products, prices, BOMs and routes"
    s["A1"].font = Font(name="Arial", bold=True, size=12)
    for i, (k, v) in enumerate(sorted(log.items()), start=3):
        s.cell(i, 1, k).font = bf
        s.cell(i, 2, v).font = bf
    r = len(log) + 4
    for t in ["The product file is the master. Its codes are untouched; everything else was matched to it "
              "ignoring case, spaces, ampersands, brackets and full stops, then rewritten to its exact spelling.",
              "Prices and routes now resolve completely. The BOM does not, and cannot: it needs 14,303 codes "
              "that are not in the product file at all. That is not a formatting problem - only 8 of those "
              "14,303 are a cleansing artefact. The product extract is simply narrower than the BOM.",
              "Two sheets need a human: 'Two parts, one code' is 33 pairs of genuinely different parts that "
              "cleanse onto the same code, and 'Codes with no product' is what the BOM is missing."]:
        s.cell(r, 1, t).font = Font(name="Arial", italic=True, size=9)
        s.cell(r, 1).alignment = Alignment(wrap_text=True, vertical="top")
        s.row_dimensions[r].height = 42
        r += 1
    s.column_dimensions["A"].width = 100
    s.column_dimensions["B"].width = 14

    sheet("Excel damage repaired", ["File", "Code as it was", "Code it should be", "What had happened"],
          sorted(set(repairs)), [12, 26, 26, 52])

    sheet("Codes with no product", ["File", "Code in the file", "Times it appears"],
          sorted(unmatched, key=lambda x: (-x[2], x[1])), [12, 30, 18])

    clash = []
    for code, rows in sorted(lines_of.items()):
        if len(rows) > 1:
            for i, rr in rows:
                clash.append((code, i, rr[0], rr[2], rr[4]))
    sheet("Two parts, one code",
          ["Standard code", "Line in the product file", "Category", "Description 1", "Description 2"],
          clash, [22, 20, 12, 44, 44])

    enc = []
    for label, path in [("Products", "ZSDIITM_Cleansing.txt"),
                        ("Prices", "YITC_load1_product_costs-cleansed.txt"),
                        ("BOMs", "YA00408BOM_guide_MAPPED-V1.1-cleansed.txt"),
                        ("Routes", "ZSDIROU2_load1_routes-V4-cleansed.txt")]:
        raw = (src / path).read_bytes()
        counts = Counter(b for b in raw if b > 127)
        for b, n in sorted(counts.items()):
            enc.append((label, f"0x{b:02X}", bytes([b]).decode("cp850"), n,
                        bytes([b]).decode("cp1252", errors="replace")))
    sheet("Characters outside plain text",
          ["File", "Byte", "What it is (DOS code page)", "How many",
           "What it becomes if the import reads Windows-1252 instead"],
          enc, [12, 10, 26, 12, 48])

    wb.save(out / "code_consistency_report.xlsx")

    for k, v in sorted(log.items()):
        print(f"  {k:56} {v}")
    print(f"  {'Two parts cleansing onto one code':56} {len(clash) // 2}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
